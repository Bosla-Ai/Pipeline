"""
Tests for the socket_server module.

Validates the job-scoped socket registry: registration, lookups, cleanup,
stats, waiters, and the semaphore guard.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

import src.socket_server as ss

# ── Helpers ───────────────────────────────────────────────────


def _reset_registry():
    """Clear all mutable state between tests."""
    ss.job_sockets.clear()
    ss.socket_jobs.clear()
    ss.connected_clients.clear()
    ss._job_ready_events.clear()


@pytest.fixture(autouse=True)
def clean_state():
    """Ensure every test starts with a blank registry."""
    _reset_registry()
    yield
    _reset_registry()


# ═════════════════════════════════════════════════════════════
#  get_stats
# ═════════════════════════════════════════════════════════════


class TestGetStats:
    def test_empty_registry(self):
        stats = ss.get_stats()
        assert stats["active_connections"] == 0
        assert stats["active_jobs"] == 0
        assert stats["max_concurrent_jobs"] == ss.MAX_CONCURRENT_JOBS
        assert stats["connections"] == []

    def test_with_one_connection(self):
        ss.connected_clients["sid-1"] = {
            "user_id": "alice",
            "job_id": "job-abc",
            "connected_at": "2026-02-09T00:00:00+00:00",
        }
        ss.job_sockets["job-abc"] = "sid-1"
        ss.socket_jobs["sid-1"] = "job-abc"

        stats = ss.get_stats()
        assert stats["active_connections"] == 1
        assert stats["active_jobs"] == 1
        assert len(stats["connections"]) == 1

        conn = stats["connections"][0]
        assert conn["sid"] == "sid-1"
        assert conn["user_id"] == "alice"
        assert conn["job_id"] == "job-abc"
        assert conn["connected_at"] == "2026-02-09T00:00:00+00:00"

    def test_multiple_connections(self):
        for i in range(5):
            sid = f"sid-{i}"
            jid = f"job-{i}"
            ss.connected_clients[sid] = {
                "user_id": f"user-{i}",
                "job_id": jid,
                "connected_at": "2026-02-09T00:00:00+00:00",
            }
            ss.job_sockets[jid] = sid
            ss.socket_jobs[sid] = jid

        stats = ss.get_stats()
        assert stats["active_connections"] == 5
        assert stats["active_jobs"] == 5
        assert len(stats["connections"]) == 5

    def test_stats_keys(self):
        """Verify the /stats response shape is stable."""
        stats = ss.get_stats()
        required_keys = {
            "active_connections",
            "active_jobs",
            "max_concurrent_jobs",
            "connections",
        }
        assert required_keys.issubset(stats.keys())


# ═════════════════════════════════════════════════════════════
#  get_socket_for_job
# ═════════════════════════════════════════════════════════════


class TestGetSocketForJob:
    def test_existing_job(self):
        ss.job_sockets["job-x"] = "sid-42"
        assert ss.get_socket_for_job("job-x") == "sid-42"

    def test_missing_job(self):
        assert ss.get_socket_for_job("nonexistent") is None


# ═════════════════════════════════════════════════════════════
#  Job waiters
# ═════════════════════════════════════════════════════════════


class TestJobWaiters:
    def test_register_creates_event(self):
        evt = ss.register_job_waiter("job-w")
        assert isinstance(evt, asyncio.Event)
        assert not evt.is_set()
        assert "job-w" in ss._job_ready_events

    def test_cleanup_removes_event(self):
        ss.register_job_waiter("job-w2")
        ss.cleanup_job_waiter("job-w2")
        assert "job-w2" not in ss._job_ready_events

    def test_cleanup_idempotent(self):
        """Cleaning up a non-existent waiter should not raise."""
        ss.cleanup_job_waiter("never-existed")

    @pytest.mark.asyncio
    async def test_waiter_is_set_on_connect(self):
        """When a client connects with a jobId that has a registered waiter, the event fires."""
        evt = ss.register_job_waiter("job-fire")

        # Simulate connect by directly calling the handler logic
        sid = "sid-fire"
        auth = {"jobId": "job-fire", "userId": "tester"}
        job_id = auth["jobId"]
        user_id = auth["userId"]

        ss.job_sockets[job_id] = sid
        ss.socket_jobs[sid] = job_id
        ss.connected_clients[sid] = {
            "user_id": user_id,
            "job_id": job_id,
            "connected_at": "2026-02-09T12:00:00+00:00",
        }

        # Simulate what the connect handler does
        inner_evt = ss._job_ready_events.get(job_id)
        if inner_evt:
            inner_evt.set()

        assert evt.is_set()


# ═════════════════════════════════════════════════════════════
#  connect / disconnect handlers (simulated)
# ═════════════════════════════════════════════════════════════


class TestConnectDisconnect:
    """
    We can't easily call the @sio.event handlers in isolation without
    a full ASGI test client, so we simulate the logic they contain.
    """

    def _simulate_connect(self, sid, auth):
        """Mirror connect handler logic."""
        auth = auth or {}
        job_id = auth.get("jobId") or auth.get("job_id")
        user_id = auth.get("userId") or auth.get("user_id") or "anonymous"

        if not job_id:
            return False  # rejected

        ss.job_sockets[job_id] = sid
        ss.socket_jobs[sid] = job_id
        ss.connected_clients[sid] = {
            "user_id": user_id,
            "job_id": job_id,
            "connected_at": "2026-02-09T00:00:00+00:00",
        }

        evt = ss._job_ready_events.get(job_id)
        if evt:
            evt.set()

        return True

    def _simulate_disconnect(self, sid):
        """Mirror disconnect handler logic."""
        meta = ss.connected_clients.pop(sid, {})
        job_id = ss.socket_jobs.pop(sid, None)
        if job_id:
            ss.job_sockets.pop(job_id, None)
            ss.cleanup_job_waiter(job_id)

    def test_connect_with_valid_auth(self):
        assert self._simulate_connect("sid-ok", {"jobId": "job-ok", "userId": "alice"})
        assert ss.get_socket_for_job("job-ok") == "sid-ok"
        assert ss.connected_clients["sid-ok"]["user_id"] == "alice"

    def test_connect_rejected_without_job_id(self):
        result = self._simulate_connect("sid-bad", {"userId": "bob"})
        assert result is False
        assert "sid-bad" not in ss.connected_clients
        assert len(ss.job_sockets) == 0

    def test_connect_with_snake_case_auth(self):
        """Auth can use job_id / user_id (snake_case) instead of camelCase."""
        assert self._simulate_connect(
            "sid-snake", {"job_id": "job-s", "user_id": "eve"}
        )
        assert ss.get_socket_for_job("job-s") == "sid-snake"

    def test_connect_default_anonymous_user(self):
        self._simulate_connect("sid-anon", {"jobId": "job-anon"})
        assert ss.connected_clients["sid-anon"]["user_id"] == "anonymous"

    def test_disconnect_cleans_up_all_maps(self):
        self._simulate_connect("sid-dc", {"jobId": "job-dc", "userId": "user"})
        assert "sid-dc" in ss.connected_clients
        assert "job-dc" in ss.job_sockets

        self._simulate_disconnect("sid-dc")

        assert "sid-dc" not in ss.connected_clients
        assert "sid-dc" not in ss.socket_jobs
        assert "job-dc" not in ss.job_sockets

    def test_disconnect_cleans_waiter(self):
        ss.register_job_waiter("job-dw")
        self._simulate_connect("sid-dw", {"jobId": "job-dw"})
        self._simulate_disconnect("sid-dw")
        assert "job-dw" not in ss._job_ready_events

    def test_disconnect_unknown_sid_safe(self):
        """Disconnecting an unknown sid should not raise."""
        self._simulate_disconnect("never-connected")

    def test_new_connection_replaces_old_for_same_job(self):
        """If a second socket connects with the same job_id, it replaces the first."""
        self._simulate_connect("sid-old", {"jobId": "job-replace"})
        self._simulate_connect("sid-new", {"jobId": "job-replace"})

        # The job should now point to the new sid
        assert ss.get_socket_for_job("job-replace") == "sid-new"


# ═════════════════════════════════════════════════════════════
#  Semaphore
# ═════════════════════════════════════════════════════════════


class TestSemaphore:
    def test_max_concurrent_jobs_value(self):
        assert ss.MAX_CONCURRENT_JOBS == 3

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """Ensure no more than MAX_CONCURRENT_JOBS run simultaneously."""
        concurrent_count = 0
        max_seen = 0

        async def fake_job(job_id: str):
            nonlocal concurrent_count, max_seen
            async with ss.job_semaphore:
                concurrent_count += 1
                max_seen = max(max_seen, concurrent_count)
                await asyncio.sleep(0.05)
                concurrent_count -= 1

        tasks = [asyncio.create_task(fake_job(f"j-{i}")) for i in range(10)]
        await asyncio.gather(*tasks)

        assert max_seen <= ss.MAX_CONCURRENT_JOBS
