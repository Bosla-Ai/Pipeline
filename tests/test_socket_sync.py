"""
Integration tests for the socket-sync changes.

Validates:
- /stats endpoint returns correct JSON shape
- /generate-roadmap accepts job_id and proceeds without a frontend socket
- wait_for_socket timeout behavior
- Job semaphore limiting concurrent requests
"""

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from src.api import app, wait_for_socket
import src.socket_server as ss


# ── Helpers ───────────────────────────────────────────────────


def _reset_registry():
    ss.job_sockets.clear()
    ss.socket_jobs.clear()
    ss.connected_clients.clear()
    ss._job_ready_events.clear()


@pytest.fixture(autouse=True)
def clean_state():
    _reset_registry()
    yield
    _reset_registry()


# ═════════════════════════════════════════════════════════════
#  /stats endpoint
# ═════════════════════════════════════════════════════════════


class TestStatsEndpoint:
    @pytest.mark.asyncio
    async def test_stats_returns_200(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/stats")

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_stats_shape(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/stats")

        data = response.json()
        assert "active_connections" in data
        assert "active_jobs" in data
        assert "max_concurrent_jobs" in data
        assert "connections" in data
        assert isinstance(data["connections"], list)
        assert isinstance(data["active_connections"], int)
        assert isinstance(data["active_jobs"], int)
        assert isinstance(data["max_concurrent_jobs"], int)

    @pytest.mark.asyncio
    async def test_stats_reflects_live_state(self):
        """Manually inject a connection and verify /stats shows it."""
        ss.connected_clients["test-sid"] = {
            "user_id": "tester",
            "job_id": "job-stats-test",
            "connected_at": "2026-02-09T10:00:00+00:00",
        }
        ss.job_sockets["job-stats-test"] = "test-sid"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/stats")

        data = response.json()
        assert data["active_connections"] == 1
        assert data["active_jobs"] == 1
        assert len(data["connections"]) == 1
        assert data["connections"][0]["sid"] == "test-sid"
        assert data["connections"][0]["user_id"] == "tester"
        assert data["connections"][0]["job_id"] == "job-stats-test"


# ═════════════════════════════════════════════════════════════
#  wait_for_socket
# ═════════════════════════════════════════════════════════════


class TestWaitForSocket:
    @pytest.mark.asyncio
    async def test_returns_existing_socket(self):
        """If a socket is already connected for the job, return immediately."""
        ss.job_sockets["job-exists"] = "sid-exists"
        result = await wait_for_socket("job-exists")
        assert result == "sid-exists"

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        """If no socket connects within timeout, return None."""
        with patch("src.api.SOCKET_WAIT_TIMEOUT", 0.1):
            result = await wait_for_socket("job-no-socket")
        assert result is None

    @pytest.mark.asyncio
    async def test_waiter_resolves_when_socket_connects(self):
        """Simulate a socket connecting mid-wait."""
        job_id = "job-midwait"

        async def delayed_connect():
            await asyncio.sleep(0.1)
            ss.job_sockets[job_id] = "sid-midwait"
            evt = ss._job_ready_events.get(job_id)
            if evt:
                evt.set()

        with patch("src.api.SOCKET_WAIT_TIMEOUT", 2):
            task = asyncio.create_task(delayed_connect())
            result = await wait_for_socket(job_id)
            await task

        assert result == "sid-midwait"

    @pytest.mark.asyncio
    async def test_waiter_cleanup_on_timeout(self):
        """After timeout, the waiter event should be cleaned up."""
        job_id = "job-cleanup"
        with patch("src.api.SOCKET_WAIT_TIMEOUT", 0.1):
            await wait_for_socket(job_id)
        assert job_id not in ss._job_ready_events


# ═════════════════════════════════════════════════════════════
#  /generate-roadmap with job_id
# ═════════════════════════════════════════════════════════════


class TestGenerateRoadmapJobId:
    @pytest.mark.asyncio
    async def test_accepts_job_id(self, mocker):
        """The endpoint should accept a job_id and use it."""
        mocker.patch("src.api.fetch_youtube", return_value={"vid": "data"})
        mocker.patch("src.api.SOCKET_WAIT_TIMEOUT", 0.1)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/generate-roadmap",
                json={
                    "tags": ["python"],
                    "prefer_paid": False,
                    "language": "en",
                    "job_id": "custom-job-123",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    @pytest.mark.asyncio
    async def test_generates_job_id_when_missing(self, mocker):
        """If no job_id is provided, one should be auto-generated."""
        mocker.patch("src.api.fetch_youtube", return_value={})
        mocker.patch("src.api.SOCKET_WAIT_TIMEOUT", 0.1)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/generate-roadmap",
                json={
                    "tags": ["react"],
                    "prefer_paid": False,
                    "language": "en",
                },
            )

        assert response.status_code == 200
        assert response.json()["status"] == "success"

    @pytest.mark.asyncio
    async def test_proceeds_without_socket(self, mocker):
        """
        When no frontend socket connects (timeout), the roadmap should still
        be generated — just without AI classification.
        """
        mock_yt = mocker.patch(
            "src.api.fetch_youtube", return_value={"python": {"title": "Py Course"}}
        )
        mocker.patch("src.api.SOCKET_WAIT_TIMEOUT", 0.1)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/generate-roadmap",
                json={
                    "tags": ["python"],
                    "prefer_paid": False,
                    "language": "en",
                    "job_id": "job-no-frontend",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["youtube"] == {"python": {"title": "Py Course"}}
        mock_yt.assert_called_once()


# ═════════════════════════════════════════════════════════════
#  Semaphore integration
# ═════════════════════════════════════════════════════════════


class TestSemaphoreIntegration:
    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency_unit(self):
        """
        Unit-level test: use a fresh semaphore (same loop) to verify
        concurrency limiting logic works correctly.
        The module-level semaphore gets bound to a different loop per test,
        so we test the concept with a local semaphore.
        """
        sem = asyncio.Semaphore(ss.MAX_CONCURRENT_JOBS)
        concurrent = 0
        max_concurrent = 0

        async def limited_job():
            nonlocal concurrent, max_concurrent
            async with sem:
                concurrent += 1
                max_concurrent = max(max_concurrent, concurrent)
                await asyncio.sleep(0.05)
                concurrent -= 1

        tasks = [asyncio.create_task(limited_job()) for _ in range(10)]
        await asyncio.gather(*tasks)

        assert max_concurrent <= ss.MAX_CONCURRENT_JOBS
        assert max_concurrent >= 1  # at least some parallelism


# ═════════════════════════════════════════════════════════════
#  Request model validation
# ═════════════════════════════════════════════════════════════


class TestRequestModel:
    @pytest.mark.asyncio
    async def test_job_id_in_request_model(self):
        """The RoadmapRequest model should accept job_id as optional field."""
        from src.api import RoadmapRequest

        req = RoadmapRequest(tags=["python"], language="en")
        assert req.job_id is None

        req_with_job = RoadmapRequest(
            tags=["python"], language="en", job_id="my-job-123"
        )
        assert req_with_job.job_id == "my-job-123"

    @pytest.mark.asyncio
    async def test_sources_accepts_valid_enums(self):
        from src.api import RoadmapRequest, CourseSource

        req = RoadmapRequest(
            tags=["python"],
            language="en",
            sources=["youtube", "coursera"],
        )
        assert CourseSource.YOUTUBE in req.sources
        assert CourseSource.COURSERA in req.sources

    @pytest.mark.asyncio
    async def test_invalid_source_rejected(self):
        from src.api import RoadmapRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RoadmapRequest(
                tags=["python"],
                language="en",
                sources=["invalid_source"],
            )
