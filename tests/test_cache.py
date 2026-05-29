from unittest import mock
from src.utils.cache import generate_cache_key


def test_generate_cache_key_default_version():
    # Test default version (v1)
    key = generate_cache_key("udemy", "python programming", "en")
    assert key == "v1:udemy:python_programming:en"


def test_generate_cache_key_custom_version():
    with mock.patch("src.utils.cache.CACHE_VERSION", "v2"):
        key = generate_cache_key("youtube", "react js", "ar")
        assert key == "v2:youtube:react_js:ar"


def test_generate_cache_key_no_version():
    with mock.patch("src.utils.cache.CACHE_VERSION", ""):
        key = generate_cache_key("coursera", "machine learning", "en")
        assert key == "coursera:machine_learning:en"


import asyncio
import pytest
from src.utils.cache import cache

@pytest.mark.asyncio
async def test_cache_stampede_protection():
    # Simple fake Redis client in memory
    store = {}

    async def fake_get(key):
        return store.get(key)

    async def fake_set(key, val, ex=None, nx=False):
        if nx:
            if key in store:
                return False
            store[key] = val
            return True
        store[key] = val
        return True

    async def fake_delete(key):
        if key in store:
            del store[key]
            return True
        return False

    mock_client = mock.MagicMock()
    mock_client.get = mock.AsyncMock(side_effect=fake_get)
    mock_client.set = mock.AsyncMock(side_effect=fake_set)
    mock_client.delete = mock.AsyncMock(side_effect=fake_delete)

    # Temporarily assign mock client to cache
    original_client = cache._client
    cache._client = mock_client

    factory_1_called = 0
    factory_2_called = 0

    async def factory_1():
        nonlocal factory_1_called
        factory_1_called += 1
        await asyncio.sleep(0.4)
        return "data_from_factory_1"

    async def factory_2():
        nonlocal factory_2_called
        factory_2_called += 1
        return "data_from_factory_2"

    try:
        # Run both tasks concurrently
        task1 = cache.get_or_set_with_lock(
            key="test_stampede_key",
            ttl=30,
            factory=factory_1,
            job_id="job1",
            source="test_src",
            tag="test_tag",
            language="en",
        )

        # Start task2 slightly after to ensure task1 acquires the lock first
        async def run_task2():
            await asyncio.sleep(0.1)
            return await cache.get_or_set_with_lock(
                key="test_stampede_key",
                ttl=30,
                factory=factory_2,
                job_id="job2",
                source="test_src",
                tag="test_tag",
                language="en",
            )

        res1, res2 = await asyncio.gather(task1, run_task2())

        assert res1 == "data_from_factory_1"
        assert res2 == "data_from_factory_1"
        assert factory_1_called == 1
        assert factory_2_called == 0
    finally:
        cache._client = original_client
