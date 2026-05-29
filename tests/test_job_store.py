import pytest
from unittest import mock
import json
from src.engine.job_store import RedisJobStore


@pytest.fixture
def clean_store():
    # Make sure we get a fresh singleton or clean the internal state
    store = RedisJobStore()
    store._in_memory_jobs.clear()
    store._client = None
    return store


@pytest.mark.anyio
async def test_job_store_in_memory_fallback(clean_store):
    # Test job store works in memory when Redis is not connected
    job = await clean_store.create_job(
        job_id="test1", tags=["python"], language="en", prefer_paid=False
    )
    assert job["job_id"] == "test1"
    assert job["status"] == "pending"

    # Start job
    updated = await clean_store.start_job("test1")
    assert updated["status"] == "running"

    # Complete job
    completed = await clean_store.complete_job("test1", {"roadmap": "ok"})
    assert completed["status"] == "completed"
    assert completed["result"] == {"roadmap": "ok"}

    # Get job
    retrieved = await clean_store.get_job("test1")
    assert retrieved == completed


@pytest.mark.anyio
async def test_job_store_fail_job(clean_store):
    # Test job failure tracking
    await clean_store.create_job(
        job_id="test_fail", tags=["js"], language="en", prefer_paid=True
    )
    failed = await clean_store.fail_job("test_fail", "Timeout error")
    assert failed["status"] == "failed"
    assert failed["error"] == "Timeout error"

    retrieved = await clean_store.get_job("test_fail")
    assert retrieved["status"] == "failed"


@pytest.mark.anyio
async def test_job_store_redis_connected(clean_store):
    # Mock Redis client
    mock_redis = mock.AsyncMock()
    clean_store._client = mock_redis

    # Define return value for get
    mock_job = {
        "job_id": "test_redis",
        "status": "completed",
        "result": {"data": 123},
        "error": None,
    }
    mock_redis.get.return_value = json.dumps(mock_job)

    # Test create_job writes to Redis
    await clean_store.create_job(
        job_id="test_redis", tags=["cpp"], language="en", prefer_paid=False
    )
    mock_redis.set.assert_called_once()

    # Test get_job reads from Redis
    retrieved = await clean_store.get_job("test_redis")
    assert retrieved["job_id"] == "test_redis"
    assert retrieved["status"] == "completed"
    mock_redis.get.assert_called_with("job:test_redis")
