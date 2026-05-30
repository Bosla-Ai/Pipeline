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


@pytest.mark.anyio
async def test_event_log_non_core_categories(clean_log):
    # Test that non-core categories are not normalized to system
    entry1 = clean_log.log("info", "video_search", "Searching Python videos")
    entry2 = clean_log.log("info", "resource_audit", "Auditing resources")
    entry3 = clean_log.log("info", "playlist_proxy", "Proxying playlist")
    entry4 = clean_log.log("info", "unknown_category", "Unknown log")

    assert entry1["category"] == "video_search"
    assert entry2["category"] == "resource_audit"
    assert entry3["category"] == "playlist_proxy"
    assert entry4["category"] == "system"  # Unknown still falls back to system


@pytest.mark.anyio
async def test_event_log_redis_scan_window(clean_log):
    mock_redis = mock.AsyncMock()
    clean_log._redis_client = mock_redis
    clean_log._use_redis = True

    # Generate mock logs and place target log at the end
    mock_entries = [
        {
            "id": f"log{i}",
            "level": "info",
            "category": "system",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for i in range(10)
    ]
    mock_entries.append(
        {
            "id": "log_target",
            "level": "error",
            "category": "fetcher",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )

    mock_redis.lrange.return_value = [json.dumps(e) for e in mock_entries]

    logs = await clean_log.get_logs(level="error", limit=1)
    assert len(logs) == 1
    assert logs[0]["id"] == "log_target"


@pytest.mark.anyio
async def test_event_log_sanitization(clean_log, monkeypatch):
    monkeypatch.setattr(
        "src.config.settings.PIPELINE_SHARED_SECRET",
        "super-secret-pipeline-shared-key-1234",
    )

    entry = clean_log.log(
        "info",
        "system",
        "Using secret super-secret-pipeline-shared-key-1234 for signing",
        details={
            "secret": "my-secret",
            "someToken": "abc-token",
            "password": "123",
            "normal_field": "hello",
        },
    )
    assert "super-secret-pipeline-shared-key-1234" not in entry["message"]
    assert "[MASKED]" in entry["message"]

    details = entry["details"]
    assert details["secret"] == "[MASKED]"
    assert details["someToken"] == "[MASKED]"
    assert details["password"] == "[MASKED]"
    assert details["normal_field"] == "hello"
