import pytest
from unittest import mock
import json
import asyncio
from datetime import datetime, timezone, timedelta
from src.utils.event_log import EventLog


@pytest.fixture
def clean_log():
    log = EventLog(max_entries=50)
    log.clear()
    log._redis_client = None
    log._use_redis = False
    return log


@pytest.mark.anyio
async def test_event_log_in_memory(clean_log):
    # Test logging and retrieval in memory
    entry1 = clean_log.log("info", "system", "Test message 1", job_id="job123")
    entry2 = clean_log.log("error", "fetcher", "Test error 1", job_id="job123")

    assert clean_log.count == 2
    assert await clean_log.get_count() == 2

    # Get logs without filter
    logs = await clean_log.get_logs()
    assert len(logs) == 2
    assert logs[0]["message"] == "Test error 1"  # newest first

    # Get logs with filter
    logs_error = await clean_log.get_logs(level="error")
    assert len(logs_error) == 1
    assert logs_error[0]["id"] == entry2["id"]

    logs_job = await clean_log.get_logs(job_id="job123")
    assert len(logs_job) == 2

    logs_category = await clean_log.get_logs(category="system")
    assert len(logs_category) == 1
    assert logs_category[0]["id"] == entry1["id"]


@pytest.mark.anyio
async def test_event_log_redis_backend(clean_log):
    mock_redis = mock.AsyncMock()
    clean_log._redis_client = mock_redis
    clean_log._use_redis = True

    # Prepare mock entries
    mock_entries = [
        {
            "id": "log1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "info",
            "category": "system",
            "message": "Redis log 1",
            "job_id": "job_redis",
        },
        {
            "id": "log2",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "error",
            "category": "fetcher",
            "message": "Redis log 2",
            "job_id": "job_redis",
        },
    ]

    mock_redis.lrange.return_value = [json.dumps(e) for e in mock_entries]
    mock_redis.llen.return_value = 2

    # Test count
    count = await clean_log.get_count()
    assert count == 2
    mock_redis.llen.assert_called_with("logs:global")

    # Test get_logs
    logs = await clean_log.get_logs(job_id="job_redis")
    assert len(logs) == 2
    assert logs[0]["message"] == "Redis log 2"  # reversed from RPUSH chronological
    mock_redis.lrange.assert_called_with("logs:job:job_redis", 0, -1)


@pytest.mark.anyio
async def test_event_log_async_write_queue(clean_log):
    mock_redis = mock.AsyncMock()
    clean_log._redis_client = mock_redis
    clean_log._use_redis = True

    # Log an entry
    clean_log.log("warn", "job", "Queue check", job_id="job_q")

    # Yield control to the event loop so the scheduled background task can run
    await asyncio.sleep(0.01)

    # Verify write was triggered in Redis
    mock_redis.lpush.assert_called_once()
    mock_redis.rpush.assert_called_once()
