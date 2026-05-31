import sys
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def test_free_hf_imports_boundary():
    """
    Ensure that importing src.api in FREE_HF_MODE does not trigger
    loading of key_manager, youtube_fetcher, or coursera_fetcher.
    """
    import subprocess
    import sys
    import os

    code = """
import sys
import src.api
assert "src.fetchers.videos.youtube_fetcher" not in sys.modules, "youtube_fetcher was imported"
assert "src.fetchers.videos.coursera_fetcher" not in sys.modules, "coursera_fetcher was imported"
assert "src.utils.key_manager" not in sys.modules, "key_manager was imported"
print("SUCCESS")
"""
    env = os.environ.copy()
    env["FREE_HF_MODE"] = "true"
    env["YOUTUBE_FETCH_MODE"] = "yt_dlp"
    env["SKIP_GLOBAL_DRIVER_INIT"] = "true"
    env["PYTHONPATH"] = "."

    res = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
    )
    assert (
        res.returncode == 0
    ), f"Subprocess failed with error: {res.stderr}\nOutput: {res.stdout}"
    assert "SUCCESS" in res.stdout


@pytest.mark.asyncio
async def test_free_hf_prefer_paid_ignored():
    """
    Regression test: when FREE_HF_MODE is True, requesting prefer_paid=True
    forces active sources to YouTube-only, bypasses paid sources, and returns YouTube results.
    """
    from src.engine.roadmap_engine import RoadmapEngine

    mock_youtube = AsyncMock()
    mock_coursera = AsyncMock()

    engine = RoadmapEngine(
        sio=MagicMock(),
        fetch_youtube=mock_youtube,
        fetch_coursera=mock_coursera,
        get_global_driver=MagicMock,
    )

    # Mock YtDlpProvider.fetch, SourcePlanner.plan_tag_scopes, EdgeInferenceClient.classify
    with patch(
        "src.providers.ytdlp_provider.YtDlpProvider.fetch", new_callable=AsyncMock
    ) as mock_provider_fetch, patch(
        "src.planning.source_planner.SourcePlanner.plan_tag_scopes",
        new_callable=AsyncMock,
    ) as mock_scopes, patch(
        "src.config.runtime_profile.FREE_HF_MODE", True
    ):
        mock_scopes.return_value = ([], ["python"], {"python": "atomic"})
        mock_provider_fetch.return_value = [
            {
                "title": "Python Course",
                "url": "https://youtube.com/watch?v=123",
                "duration_minutes": 60,
            }
        ]

        # Call generate with prefer_paid=True
        result = await engine.generate(
            tags=["python"],
            prefer_paid=True,
            language="en",
            job_id="job-paid-test-1",
        )

        # Verify legacy paid/free fetchers were not invoked
        mock_youtube.assert_not_called()
        mock_coursera.assert_not_called()

        # Verify active sources were forced to YouTube
        assert "youtube" in result["data"]
        assert "python" in result["data"]["youtube"]
        assert result["data"]["coursera"] == {}
        assert result["data"]["udemy"] == {}


@pytest.mark.asyncio
async def test_scrape_youtube_missing_yt_dlp():
    """
    Ensure scrape_youtube_query_candidates returns empty list gracefully when yt_dlp is not installed.
    """
    from src.fetchers.videos.youtube_scraper import scrape_youtube_query_candidates

    with patch.dict("sys.modules", {"yt_dlp": None}):
        result = await scrape_youtube_query_candidates(
            query="test query",
            tag="test",
            language="en",
        )
        assert result == []


@pytest.mark.asyncio
async def test_scrape_youtube_timeout_trips_circuit_breaker():
    """
    Ensure that a timeout in extracting results trips the circuit breaker.
    """
    from src.fetchers.videos import youtube_scraper

    youtube_scraper._scraper_disabled_until = 0.0

    try:
        with patch("src.config.settings.YT_DLP_HARD_TIMEOUT_SECONDS", "0.05"), patch(
            "src.fetchers.videos.youtube_scraper._extract_search_results"
        ) as mock_extract:

            def slow_extract(*args, **kwargs):
                import time

                time.sleep(0.5)
                return []

            mock_extract.side_effect = slow_extract

            mock_yt_dlp = MagicMock()
            with patch.dict("sys.modules", {"yt_dlp": mock_yt_dlp}):
                result = await youtube_scraper.scrape_youtube_query_candidates(
                    query="timeout query",
                    tag="python",
                    language="en",
                )
                assert result == []
                assert youtube_scraper._scraper_circuit_open() is True
    finally:
        youtube_scraper._scraper_disabled_until = 0.0
