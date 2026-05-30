import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.engine.models import CourseSource
from src.engine.fetch_coordinator import FetchCoordinator


@pytest.mark.asyncio
async def test_ytdlp_mode_uses_provider():
    # Setup fetch coordinator with mocks
    mock_fetch_youtube = AsyncMock()
    mock_fetch_coursera = AsyncMock()
    mock_global_driver = MagicMock()

    fc = FetchCoordinator(
        sio=None,
        fetch_youtube=mock_fetch_youtube,
        fetch_coursera=mock_fetch_coursera,
        get_global_driver=mock_global_driver,
    )

    mock_raw_candidates = [
        {
            "title": "Python Course",
            "url": "https://youtube.com/watch?v=123",
            "duration_minutes": 60,
        }
    ]

    # Mock YtDlpProvider.fetch, SourcePlanner.plan_tag_scopes, EdgeInferenceClient.classify
    with patch(
        "src.providers.ytdlp_provider.YtDlpProvider.fetch", new_callable=AsyncMock
    ) as mock_provider_fetch, patch(
        "src.planning.source_planner.SourcePlanner.plan_tag_scopes",
        new_callable=AsyncMock,
    ) as mock_scopes, patch(
        "src.inference.edge_client.EdgeInferenceClient.classify", new_callable=AsyncMock
    ) as mock_classify, patch(
        "src.config.runtime_profile.FREE_HF_MODE", True
    ):

        mock_scopes.return_value = ([], ["python"], {"python": "atomic"})
        mock_provider_fetch.return_value = mock_raw_candidates
        mock_classify.return_value = []

        result = await fc.fetch_resources(
            tags=["python"],
            language="en",
            active_sources=[CourseSource.YOUTUBE],
            current_sid=None,
            job_id="job-1",
        )

        # Verify provider fetch was called, and old youtube fetcher was NOT called
        mock_provider_fetch.assert_called()
        mock_fetch_youtube.assert_not_called()
        assert "youtube" in result
        assert "python" in result["youtube"]
        assert result["youtube"]["python"]["title"] == "Python Course"


@pytest.mark.asyncio
async def test_api_fetcher_not_called_when_disabled():
    mock_fetch_youtube = AsyncMock()
    fc = FetchCoordinator(
        sio=None,
        fetch_youtube=mock_fetch_youtube,
        fetch_coursera=AsyncMock(),
        get_global_driver=MagicMock(),
    )

    with patch(
        "src.providers.ytdlp_provider.YtDlpProvider.fetch", new_callable=AsyncMock
    ) as mock_provider_fetch, patch(
        "src.planning.source_planner.SourcePlanner.plan_tag_scopes",
        new_callable=AsyncMock,
    ) as mock_scopes, patch(
        "src.config.runtime_profile.FREE_HF_MODE", True
    ):

        mock_scopes.return_value = ([], ["python"], {"python": "atomic"})
        mock_provider_fetch.return_value = []

        await fc.fetch_resources(
            tags=["python"],
            language="en",
            active_sources=[CourseSource.YOUTUBE],
            current_sid=None,
            job_id="job-1",
        )

        mock_fetch_youtube.assert_not_called()


@pytest.mark.asyncio
async def test_free_hf_paid_sources_empty():
    fc = FetchCoordinator(
        sio=None,
        fetch_youtube=AsyncMock(),
        fetch_coursera=AsyncMock(),
        get_global_driver=MagicMock(),
    )

    # Under free HF mode, Udemy and Coursera are planned as disabled in SourcePlanner.
    # Let's test that if we call fetch_resources with paid sources, they don't produce any results.
    with patch("src.config.runtime_profile.FREE_HF_MODE", True), patch(
        "src.providers.ytdlp_provider.YtDlpProvider.fetch", new_callable=AsyncMock
    ) as mock_provider_fetch, patch(
        "src.planning.source_planner.SourcePlanner.plan_tag_scopes",
        new_callable=AsyncMock,
    ) as mock_scopes:

        mock_scopes.return_value = ([], ["python"], {"python": "atomic"})
        mock_provider_fetch.return_value = []

        result = await fc.fetch_resources(
            tags=["python"],
            language="en",
            active_sources=[
                CourseSource.YOUTUBE,
                CourseSource.UDEMY,
                CourseSource.COURSERA,
            ],
            current_sid=None,
            job_id="job-1",
        )

        assert result["coursera"] == {}
        assert result["udemy"] == {}
