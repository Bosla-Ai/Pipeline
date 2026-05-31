import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from src.api import app, startup_event
from src.engine.job_store import job_store
from src.security.job_tokens import generate_job_access_token


@pytest.mark.asyncio
async def test_post_job_returns_tokens(mocker):
    """Test that POST /jobs/roadmap accepts requests, creates a job, and returns tokens."""
    mocker.patch("src.api.fetch_youtube", return_value={"mock_video": "data"})
    mocker.patch("src.api.fetch_coursera", return_value={})
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)

    # Mock engine.generate so background task finishes immediately
    mocker.patch("src.api.RoadmapEngine.generate", new_callable=AsyncMock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/jobs/roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": False,
                "language": "en",
                "job_id": "job-async-123",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["job_id"] == "job-async-123"
    assert data["status"] == "queued"
    assert "job_access_token" in data
    assert "socket_token" in data

    # Let the background task run/finish
    await asyncio.sleep(0.1)

    # Check that job was created in store
    job = await job_store.get_job("job-async-123")
    assert job is not None
    assert job["job_id"] == "job-async-123"


@pytest.mark.asyncio
async def test_poll_requires_valid_job_token_if_public(mocker):
    """Test token validation for GET /jobs/{job_id}."""
    await job_store.create_job(
        job_id="job-poll-123",
        tags=["python"],
        language="en",
        prefer_paid=False,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Access without any token or secret should fail with 401
        res1 = await ac.get("/jobs/job-poll-123")
        assert res1.status_code == 401

        # 2. Access with invalid token should fail with 403
        res2 = await ac.get("/jobs/job-poll-123?token=invalid_token")
        assert res2.status_code == 403

        # 3. Access with token for a different job should fail with 403
        wrong_token = generate_job_access_token("other-job")
        res3 = await ac.get(f"/jobs/job-poll-123?token={wrong_token}")
        assert res3.status_code == 403

        # 4. Access with valid token should succeed with 200
        valid_token = generate_job_access_token("job-poll-123")
        res4 = await ac.get(f"/jobs/job-poll-123?token={valid_token}")
        assert res4.status_code == 200
        assert res4.json()["job_id"] == "job-poll-123"

        # 5. Access with pipeline secret should succeed (bypass token requirement)
        res5 = await ac.get(
            "/jobs/job-poll-123",
            headers={"X-Pipeline-Secret": "mock-secret-or-unset"},
        )
        # Note: since settings.PIPELINE_SHARED_SECRET might be None in dev, it is bypassed or checked.
        # Let's verify it gets the job metadata:
        assert res5.status_code == 200


@pytest.mark.asyncio
async def test_stale_running_job_marked_failed_on_startup():
    """Test that startup stale cleanup marks running/pending jobs as failed."""
    # Ensure job store is connected
    await job_store.connect()

    # Create one running job and one pending job
    j1 = await job_store.create_job("job-stale-1", ["python"], "en", False)
    await job_store.start_job("job-stale-1")  # sets status to running

    j2 = await job_store.create_job(
        "job-stale-2", ["python"], "en", False
    )  # remains pending

    j3 = await job_store.create_job("job-stale-3", ["python"], "en", False)
    await job_store.complete_job("job-stale-3", {"data": "ok"})  # completed, not stale

    # Trigger startup_event
    with patch("src.utils.event_log.event_log.connect", new_callable=AsyncMock), patch(
        "src.utils.event_log.event_log.start_cleanup_task"
    ), patch("src.api.GLOBAL_DRIVER", None):
        await startup_event()

    # Check status of the jobs
    job1 = await job_store.get_job("job-stale-1")
    assert job1["status"] == "failed"
    assert "restart" in job1["error"]

    job2 = await job_store.get_job("job-stale-2")
    assert job2["status"] == "failed"
    assert "restart" in job2["error"]

    job3 = await job_store.get_job("job-stale-3")
    assert job3["status"] == "completed"


@pytest.mark.asyncio
async def test_background_exception_marks_failed(mocker):
    """Test that background exceptions in the engine correctly mark the job as failed."""
    mocker.patch("src.api.fetch_youtube", return_callable=AsyncMock)
    mocker.patch("src.api.fetch_coursera", return_callable=AsyncMock)
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)

    # Force RoadmapEngine._generate_impl to raise an exception
    mocker.patch(
        "src.engine.roadmap_engine.RoadmapEngine._generate_impl",
        side_effect=Exception("Database connection timed out"),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/jobs/roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": False,
                "language": "en",
                "job_id": "job-failed-bg",
            },
        )
    assert response.status_code == 200

    # Wait for background task to run
    for _ in range(10):
        await asyncio.sleep(0.05)
        job = await job_store.get_job("job-failed-bg")
        if job and job["status"] == "failed":
            break

    job = await job_store.get_job("job-failed-bg")
    assert job["status"] == "failed"
    assert "Database connection timed out" in job["error"]


@pytest.mark.asyncio
async def test_sync_generate_still_works(mocker):
    """Verify that the synchronous /generate-roadmap endpoint still functions as before."""
    mocker.patch("src.api.fetch_youtube", return_value={"video": "data"})
    mocker.patch("src.api.fetch_coursera", return_value={})
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)
    mocker.patch(
        "src.engine.roadmap_engine.RoadmapEngine.generate",
        new_callable=AsyncMock,
        return_value={"sync": "works"},
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": False,
                "language": "en",
                "job_id": "sync-job-123",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"sync": "works"}


@pytest.mark.asyncio
async def test_max_pending_async_jobs(mocker):
    """Test that POST /jobs/roadmap returns 429 when MAX_PENDING_ASYNC_JOBS is exceeded."""
    from src.api import _active_bg_tasks

    # Mock engine.generate so background task doesn't do real work
    mocker.patch("src.api.RoadmapEngine.generate", new_callable=AsyncMock)

    # Fill up the active background tasks to the max (default is 10)
    original_tasks = _active_bg_tasks.copy()
    _active_bg_tasks.clear()

    try:
        # Mock 10 active tasks in the dictionary
        for i in range(10):
            mock_task = MagicMock(spec=asyncio.Task)
            _active_bg_tasks[f"job-{i}"] = mock_task

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/jobs/roadmap",
                json={
                    "tags": ["python"],
                    "prefer_paid": False,
                    "language": "en",
                    "job_id": "job-rejected",
                },
            )

        assert response.status_code == 429
        assert "Too many pending jobs" in response.json()["detail"]
    finally:
        _active_bg_tasks.clear()
        _active_bg_tasks.update(original_tasks)
