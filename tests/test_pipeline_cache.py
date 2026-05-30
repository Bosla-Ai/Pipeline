import pytest
from unittest.mock import AsyncMock, patch
from src.cache.pipeline_cache import (
    get_raw_ytdlp_candidates,
    set_raw_ytdlp_candidates,
    get_normalized_candidates,
    set_normalized_candidates,
    get_ranked_candidates,
    set_ranked_candidates,
)


@pytest.mark.asyncio
async def test_pipeline_cache_raw_ytdlp():
    mock_candidates = [{"title": "Course 1", "url": "url1"}]
    with patch(
        "src.utils.cache.cache.connect", new_callable=AsyncMock
    ) as mock_connect, patch(
        "src.utils.cache.cache.get", new_callable=AsyncMock
    ) as mock_get, patch(
        "src.utils.cache.cache.set", new_callable=AsyncMock
    ) as mock_set:

        # Test Get (Cache Hit)
        mock_get.return_value = mock_candidates
        res = await get_raw_ytdlp_candidates("python", "en")
        assert res == mock_candidates
        mock_connect.assert_called_once()
        mock_get.assert_called_once()

        # Test Set
        mock_set.return_value = True
        success = await set_raw_ytdlp_candidates("python", "en", mock_candidates)
        assert success is True
        mock_set.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_cache_normalized():
    mock_candidates = [{"title": "Course 1", "url": "url1"}]
    with patch(
        "src.utils.cache.cache.connect", new_callable=AsyncMock
    ) as mock_connect, patch(
        "src.utils.cache.cache.get", new_callable=AsyncMock
    ) as mock_get, patch(
        "src.utils.cache.cache.set", new_callable=AsyncMock
    ) as mock_set:

        # Test Get (Cache Hit)
        mock_get.return_value = mock_candidates
        res = await get_normalized_candidates("youtube", "rawhash123")
        assert res == mock_candidates
        mock_connect.assert_called_once()
        mock_get.assert_called_once()

        # Test Set
        mock_set.return_value = True
        success = await set_normalized_candidates(
            "youtube", "rawhash123", mock_candidates
        )
        assert success is True
        mock_set.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_cache_ranked():
    mock_candidates = [{"title": "Course 1", "url": "url1"}]
    with patch(
        "src.utils.cache.cache.connect", new_callable=AsyncMock
    ) as mock_connect, patch(
        "src.utils.cache.cache.get", new_callable=AsyncMock
    ) as mock_get, patch(
        "src.utils.cache.cache.set", new_callable=AsyncMock
    ) as mock_set:

        # Test Get (Cache Hit)
        mock_get.return_value = mock_candidates
        res = await get_ranked_candidates("python", "youtube", "candhash123")
        assert res == mock_candidates
        mock_connect.assert_called_once()
        mock_get.assert_called_once()

        # Test Set
        mock_set.return_value = True
        success = await set_ranked_candidates(
            "python", "youtube", "candhash123", mock_candidates
        )
        assert success is True
        mock_set.assert_called_once()
