import pytest
from unittest.mock import MagicMock, AsyncMock
from src.fetchers.videos.youtube_fetcher import fetch_youtube_data, process_single_tag
from src.utils.key_manager import key_manager


@pytest.fixture(autouse=True)
def setup_dummy_keys():
    """Injects dummy keys for ALL tests in this module to pass CI."""
    original_keys = key_manager.keys
    original_index = key_manager.current_index
    key_manager.keys = ["TEST_KEY_1", "TEST_KEY_2"]
    key_manager.current_index = 0
    yield
    key_manager.keys = original_keys
    key_manager.current_index = original_index


@pytest.fixture
def mock_session():
    # session object itself can be MagicMock because we don't await session itself
    session = MagicMock()

    # session.get(...) returns a context manager, NOT a coroutine
    # So we use MagicMock for .get()
    context_manager = MagicMock()
    response = AsyncMock()

    # Configure context manager to return our response on enter
    context_manager.__aenter__.return_value = response
    context_manager.__aexit__.return_value = None

    session.get.return_value = context_manager
    return session, response


@pytest.mark.asyncio
async def test_fetch_youtube_data_success(mock_session):
    session, response = mock_session

    # Setup successful response
    response.status = 200
    response.json.return_value = {"items": []}

    result = await fetch_youtube_data(session, "http://api.google.com", {})

    assert result == {"items": []}
    assert response.status == 200


@pytest.mark.asyncio
async def test_fetch_youtube_data_quota_rotation():
    # Set predictables
    key_manager.keys = ["KEY_1", "KEY_2"]
    key_manager.current_index = 0

    session = MagicMock()

    # Track params.copy() to capture the state of params at the time session.get is called
    requested_keys = []

    def mock_get(url, params=None):
        if params:
            requested_keys.append(params.get("key"))

        # Determine behavior based on number of calls
        call_num = len(requested_keys)
        context_manager = MagicMock()
        response = AsyncMock()

        if call_num == 1:
            # First call: 403 quotaExceeded
            response.status = 403
            response.text.return_value = "quotaExceeded"
        else:
            # Second call: 200 success
            response.status = 200
            response.json.return_value = {"success": True}

        context_manager.__aenter__.return_value = response
        context_manager.__aexit__.return_value = None
        return context_manager

    session.get.side_effect = mock_get

    result = await fetch_youtube_data(session, "http://api.google.com", {})

    assert result == {"success": True}
    assert session.get.call_count == 2
    assert requested_keys == ["KEY_1", "KEY_2"]
    assert key_manager.current_index == 1


@pytest.mark.asyncio
async def test_key_manager_rotation(mock_session):
    # Simpler test: Just verify specific block logic using a manual call logic or unit test key_manager directly
    current_key_idx = key_manager.current_index
    key_manager.rotate()
    assert key_manager.current_index != current_key_idx


def test_key_manager_duplicate_rotation_prevention():
    # Setup key manager with a predictable list of keys
    key_manager.keys = ["KEY_A", "KEY_B", "KEY_C"]
    key_manager.current_index = 0

    # First rotation from KEY_A should succeed
    res1 = key_manager.rotate("KEY_A")
    assert res1 == "KEY_B"
    assert key_manager.current_index == 1

    # Second rotation from KEY_A (stale/duplicate) should be ignored
    res2 = key_manager.rotate("KEY_A")
    assert res2 == "KEY_B"
    assert key_manager.current_index == 1

    # Rotation from KEY_B should succeed
    res3 = key_manager.rotate("KEY_B")
    assert res3 == "KEY_C"
    assert key_manager.current_index == 2


@pytest.mark.asyncio
async def test_key_manager_concurrency():
    import asyncio

    # Setup key manager
    key_manager.keys = ["KEY_1", "KEY_2", "KEY_3"]
    key_manager.current_index = 0

    # Call rotate concurrently with the same failed key in separate async tasks
    async def task():
        # Yield control to simulate concurrent scheduling
        await asyncio.sleep(0.01)
        return key_manager.rotate("KEY_1")

    results = await asyncio.gather(*(task() for _ in range(10)))

    # They should all resolve to KEY_2, and index should be 1 (rotated only once)
    for res in results:
        assert res == "KEY_2"
    assert key_manager.current_index == 1
