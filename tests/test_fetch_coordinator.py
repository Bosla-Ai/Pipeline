import asyncio
import pytest
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

from src.engine.fetch_coordinator import FetchCoordinator
from src.engine.models import CourseSource
from src.engine.runtime import runtime_limits, runtime_semaphores
from src.utils.event_log import event_log


@pytest.mark.asyncio
async def test_fetch_coordinator_free_mode():
    mock_youtube = AsyncMock(
        return_value={
            "react": {"title": "React Video", "url": "https://youtube.com/react"}
        }
    )
    mock_coursera = AsyncMock(return_value={})
    mock_driver = MagicMock()

    coordinator = FetchCoordinator(
        sio=MagicMock(),
        fetch_youtube=mock_youtube,
        fetch_coursera=mock_coursera,
        get_global_driver=lambda: mock_driver,
    )

    res = await coordinator.fetch_resources(
        tags=["react"],
        language="en",
        active_sources=[CourseSource.YOUTUBE],
        current_sid="sid123",
        job_id="job123",
    )

    assert "react" in res["youtube"]
    assert res["youtube"]["react"]["title"] == "React Video"
    assert res["coursera"] == {}
    assert res["udemy"] == {}

    mock_youtube.assert_called_once()
    mock_coursera.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_coordinator_paid_mode_success():
    mock_youtube = AsyncMock(return_value={})
    mock_coursera = AsyncMock(
        return_value={
            "react": {"title": "Coursera React", "url": "https://coursera.org/react"}
        }
    )
    mock_driver = MagicMock()

    coordinator = FetchCoordinator(
        sio=MagicMock(),
        fetch_youtube=mock_youtube,
        fetch_coursera=mock_coursera,
        get_global_driver=lambda: mock_driver,
    )

    # Mock tag scope analysis: "react" is Broad (so it goes to paid), no atomic tags
    async def mock_plan_tag_scopes(sio, sid, tags):
        return ["react"], [], {}

    # Mock UdemyFetcher
    mock_udemy_fetcher = MagicMock()
    mock_udemy_fetcher.scrape = MagicMock()
    mock_udemy_fetcher.blocked_tags = []
    mock_udemy_fetcher.results = {
        "react": [
            {
                "title": "Udemy React",
                "url": "https://udemy.com/react",
                "contentId": "123",
            }
        ]
    }

    # Mock cache lookup and classification via frontend
    mock_classify = AsyncMock(
        return_value=[
            {
                "title": "Udemy React",
                "url": "https://udemy.com/react",
                "contentId": "123",
                "score": 0.9,
            }
        ]
    )

    with patch(
        "src.planning.source_planner.SourcePlanner.plan_tag_scopes",
        side_effect=mock_plan_tag_scopes,
    ), patch(
        "src.engine.fetch_coordinator.UdemyFetcher", return_value=mock_udemy_fetcher
    ), patch(
        "src.engine.fetch_coordinator.classify_via_frontend", new=mock_classify
    ), patch(
        "src.utils.cache.cache.get", new_callable=AsyncMock
    ) as mock_cache_get, patch(
        "src.utils.cache.cache.set", new_callable=AsyncMock
    ) as mock_cache_set:

        mock_cache_get.return_value = None

        res = await coordinator.fetch_resources(
            tags=["react"],
            language="en",
            active_sources=[CourseSource.COURSERA, CourseSource.UDEMY],
            current_sid="sid123",
            job_id="job123",
        )

        assert res["coursera"]["react"]["title"] == "Coursera React"
        assert res["udemy"]["react"]["title"] == "Udemy React"
        assert res["youtube"] == {}


@pytest.mark.asyncio
async def test_fetch_coordinator_atomic_fallback():
    mock_youtube = AsyncMock(
        return_value={
            "hooks": {"title": "React Hooks", "url": "https://youtube.com/hooks"}
        }
    )
    mock_coursera = AsyncMock(return_value={})
    mock_driver = MagicMock()

    coordinator = FetchCoordinator(
        sio=MagicMock(),
        fetch_youtube=mock_youtube,
        fetch_coursera=mock_coursera,
        get_global_driver=lambda: mock_driver,
    )

    # "hooks" is planned as Atomic, no broad tags
    async def mock_plan_tag_scopes(sio, sid, tags):
        return [], ["hooks"], {}

    with patch(
        "src.planning.source_planner.SourcePlanner.plan_tag_scopes",
        side_effect=mock_plan_tag_scopes,
    ):
        res = await coordinator.fetch_resources(
            tags=["hooks"],
            language="en",
            active_sources=[CourseSource.COURSERA, CourseSource.UDEMY],
            current_sid="sid123",
            job_id="job123",
        )

        # Atomic tag fallback automatically requests from YouTube
        assert res["youtube"]["hooks"]["title"] == "React Hooks"
        assert res["coursera"] == {}
        assert res["udemy"] == {}


@pytest.mark.asyncio
async def test_fetch_coordinator_broad_fallback_when_paid_empty():
    mock_youtube = AsyncMock(
        return_value={
            "react": {"title": "React YT Fallback", "url": "https://youtube.com/react"}
        }
    )
    mock_coursera = AsyncMock(return_value={})  # Returns nothing
    mock_driver = MagicMock()

    coordinator = FetchCoordinator(
        sio=MagicMock(),
        fetch_youtube=mock_youtube,
        fetch_coursera=mock_coursera,
        get_global_driver=lambda: mock_driver,
    )

    async def mock_plan_tag_scopes(sio, sid, tags):
        return ["react"], [], {}

    mock_udemy_fetcher = MagicMock()
    mock_udemy_fetcher.scrape = MagicMock()
    mock_udemy_fetcher.blocked_tags = []
    mock_udemy_fetcher.results = {}  # Returns nothing

    with patch(
        "src.planning.source_planner.SourcePlanner.plan_tag_scopes",
        side_effect=mock_plan_tag_scopes,
    ), patch(
        "src.engine.fetch_coordinator.UdemyFetcher", return_value=mock_udemy_fetcher
    ), patch(
        "src.utils.cache.cache.get", new_callable=AsyncMock
    ) as mock_cache_get:

        mock_cache_get.return_value = None

        res = await coordinator.fetch_resources(
            tags=["react"],
            language="en",
            active_sources=[CourseSource.COURSERA, CourseSource.UDEMY],
            current_sid="sid123",
            job_id="job123",
        )

        # Broad tag react is broad, paid returns empty, falls back to YouTube
        assert res["youtube"]["react"]["title"] == "React YT Fallback"


@pytest.mark.asyncio
async def test_fetch_coordinator_timeout_handling():
    # Force YouTube to sleep longer than its timeout
    async def slow_fetch(*args, **kwargs):
        await asyncio.sleep(2.0)
        return {"react": {"title": "React"}}

    mock_youtube = AsyncMock(side_effect=slow_fetch)
    mock_coursera = AsyncMock(return_value={})
    mock_driver = MagicMock()

    coordinator = FetchCoordinator(
        sio=MagicMock(),
        fetch_youtube=mock_youtube,
        fetch_coursera=mock_coursera,
        get_global_driver=lambda: mock_driver,
    )

    # Set timeout low to trigger it
    mock_limits = replace(runtime_limits, youtube_provider_timeout_seconds=0.1)

    # Keep track of logs
    logged_events = []
    original_log = event_log.log

    def mock_log(event_type, channel, msg, *args, **kwargs):
        logged_events.append((event_type, channel, msg))
        return original_log(event_type, channel, msg, *args, **kwargs)

    with patch("src.engine.fetch_coordinator.runtime_limits", mock_limits):
        with patch("src.utils.event_log.event_log.log", side_effect=mock_log):
            res = await coordinator.fetch_resources(
                tags=["react"],
                language="en",
                active_sources=[CourseSource.YOUTUBE],
                current_sid="sid123",
                job_id="job123",
            )

            # Wait_for timeout yields empty results instead of crashing the job
            assert res["youtube"] == {}

            # Check the required log format is present: [fetcher] YouTube provider timed out
            timeout_log_present = any(
                "[fetcher] YouTube provider timed out" in msg
                for et, ch, msg in logged_events
            )
            assert timeout_log_present


@pytest.mark.asyncio
async def test_fetch_coordinator_cache_connect_failure():
    mock_youtube = AsyncMock(return_value={})
    mock_coursera = AsyncMock(return_value={})
    mock_driver = MagicMock()

    coordinator = FetchCoordinator(
        sio=MagicMock(),
        fetch_youtube=mock_youtube,
        fetch_coursera=mock_coursera,
        get_global_driver=lambda: mock_driver,
    )

    async def mock_plan_tag_scopes(sio, sid, tags):
        return ["react"], [], {}

    # Mock cache.connect to fail
    with patch(
        "src.planning.source_planner.SourcePlanner.plan_tag_scopes",
        side_effect=mock_plan_tag_scopes,
    ), patch(
        "src.utils.cache.cache.connect",
        side_effect=Exception("Redis connection refused"),
    ), patch(
        "src.engine.fetch_coordinator.UdemyFetcher"
    ) as mock_fetcher_cls:

        # Udemy fetcher should still be called because cache lookup was bypassed/failed
        mock_udemy_fetcher = MagicMock()
        mock_udemy_fetcher.scrape = MagicMock()
        mock_udemy_fetcher.blocked_tags = []
        mock_udemy_fetcher.results = {}
        mock_fetcher_cls.return_value = mock_udemy_fetcher

        res = await coordinator.fetch_resources(
            tags=["react"],
            language="en",
            active_sources=[CourseSource.UDEMY],
            current_sid="sid123",
            job_id="job123",
        )
        # Bypassed cache error and proceeded to run
        assert res["udemy"] == {}
        mock_fetcher_cls.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_coordinator_cache_get_failure():
    mock_youtube = AsyncMock(return_value={})
    mock_coursera = AsyncMock(return_value={})
    mock_driver = MagicMock()

    coordinator = FetchCoordinator(
        sio=MagicMock(),
        fetch_youtube=mock_youtube,
        fetch_coursera=mock_coursera,
        get_global_driver=lambda: mock_driver,
    )

    async def mock_plan_tag_scopes(sio, sid, tags):
        return ["react"], [], {}

    with patch(
        "src.planning.source_planner.SourcePlanner.plan_tag_scopes",
        side_effect=mock_plan_tag_scopes,
    ), patch("src.utils.cache.cache.connect", new_callable=AsyncMock), patch(
        "src.utils.cache.cache.get", side_effect=Exception("Redis GET error")
    ), patch(
        "src.engine.fetch_coordinator.UdemyFetcher"
    ) as mock_fetcher_cls:

        mock_udemy_fetcher = MagicMock()
        mock_udemy_fetcher.scrape = MagicMock()
        mock_udemy_fetcher.blocked_tags = []
        mock_udemy_fetcher.results = {}
        mock_fetcher_cls.return_value = mock_udemy_fetcher

        res = await coordinator.fetch_resources(
            tags=["react"],
            language="en",
            active_sources=[CourseSource.UDEMY],
            current_sid="sid123",
            job_id="job123",
        )
        assert res["udemy"] == {}
        mock_fetcher_cls.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_coordinator_one_provider_task_raises():
    mock_youtube = AsyncMock(return_value={})
    mock_coursera = AsyncMock(side_effect=Exception("Coursera crashed!"))
    mock_driver = MagicMock()

    coordinator = FetchCoordinator(
        sio=MagicMock(),
        fetch_youtube=mock_youtube,
        fetch_coursera=mock_coursera,
        get_global_driver=lambda: mock_driver,
    )

    async def mock_plan_tag_scopes(sio, sid, tags):
        return ["react"], [], {}

    mock_udemy_fetcher = MagicMock()
    mock_udemy_fetcher.scrape = MagicMock()
    mock_udemy_fetcher.blocked_tags = []
    mock_udemy_fetcher.results = {
        "react": [
            {
                "title": "Udemy React",
                "url": "https://udemy.com/react",
                "contentId": "123",
            }
        ]
    }

    mock_classify = AsyncMock(
        return_value=[
            {
                "title": "Udemy React",
                "url": "https://udemy.com/react",
                "contentId": "123",
                "score": 0.9,
            }
        ]
    )

    with patch(
        "src.planning.source_planner.SourcePlanner.plan_tag_scopes",
        side_effect=mock_plan_tag_scopes,
    ), patch(
        "src.engine.fetch_coordinator.UdemyFetcher", return_value=mock_udemy_fetcher
    ), patch(
        "src.engine.fetch_coordinator.classify_via_frontend", new=mock_classify
    ), patch(
        "src.utils.cache.cache.connect", new_callable=AsyncMock
    ), patch(
        "src.utils.cache.cache.get", new_callable=AsyncMock
    ) as mock_cache_get, patch(
        "src.utils.cache.cache.set", new_callable=AsyncMock
    ):

        mock_cache_get.return_value = None

        res = await coordinator.fetch_resources(
            tags=["react"],
            language="en",
            active_sources=[CourseSource.COURSERA, CourseSource.UDEMY],
            current_sid="sid123",
            job_id="job123",
        )

        # Coursera failure did not stop Udemy task from succeeding
        assert res["udemy"]["react"]["title"] == "Udemy React"
        assert res["coursera"] == {}
        assert res["youtube"] == {}


def test_positive_int_env_sanitizes_negative_values():
    import os
    from src.engine.runtime import _positive_int_env

    with patch.dict(
        os.environ, {"YOUTUBE_PROVIDER_CONCURRENCY": "-5", "SOCKET_WAIT_TIMEOUT": "0"}
    ):
        youtube_concurrency = _positive_int_env("YOUTUBE_PROVIDER_CONCURRENCY", 4)
        socket_timeout = _positive_int_env("SOCKET_WAIT_TIMEOUT", 30)

        # Negative and zero values must be sanitized to at least 1
        assert youtube_concurrency == 1
        assert socket_timeout == 1
