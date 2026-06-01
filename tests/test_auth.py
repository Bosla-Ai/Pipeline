import importlib
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_auth_validation_on_all_endpoints(monkeypatch):
    monkeypatch.setenv("PIPELINE_SHARED_SECRET", "secret-test-token")
    import src.config.settings as settings
    import src.api as api

    importlib.reload(settings)
    importlib.reload(api)

    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. /generate-roadmap
        r = await ac.post(
            "/generate-roadmap",
            json={"tags": ["python"], "prefer_paid": False, "language": "en"},
        )
        assert r.status_code == 401

        # 2. /stats
        r = await ac.get("/stats")
        assert r.status_code == 401

        # 3. /logs
        r = await ac.get("/logs")
        assert r.status_code == 401

        # 4. /logs/job/testjob
        r = await ac.get("/logs/job/testjob")
        assert r.status_code == 401

        # 5. /logs/export
        r = await ac.get("/logs/export")
        assert r.status_code == 401

        # 6. /search-embeddable-video
        r = await ac.get("/search-embeddable-video?q=test")
        assert r.status_code == 401

        # 7. /youtube/playlist-items
        r = await ac.get("/youtube/playlist-items?playlistId=test")
        assert r.status_code == 401

        # Test success with correct header
        headers = {"x-pipeline-secret": "secret-test-token"}

        r = await ac.get("/stats", headers=headers)
        assert r.status_code == 200

        r = await ac.get("/logs", headers=headers)
        assert r.status_code == 200

        r = await ac.get("/logs/job/testjob", headers=headers)
        assert r.status_code == 200

        # Public /health check should return 200 without authentication headers
        r = await ac.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "healthy"}

        # /tokens/socket without secret
        r = await ac.post("/tokens/socket", json={"job_id": "job123"})
        assert r.status_code == 401

        # /tokens/socket with incorrect secret
        r = await ac.post("/tokens/socket", json={"job_id": "job123"}, headers={"x-pipeline-secret": "wrong"})
        assert r.status_code == 401

        # /tokens/socket with correct secret and valid payload
        r = await ac.post("/tokens/socket", json={"job_id": "job123"}, headers=headers)
        assert r.status_code == 200
        res = r.json()
        assert "socket_token" in res
        assert "expires_in" in res
        assert res["expires_in"] == 300

        # /tokens/socket with custom ttl
        r = await ac.post("/tokens/socket", json={"job_id": "job123", "ttl_seconds": 400}, headers=headers)
        assert r.status_code == 200
        assert r.json()["expires_in"] == 400

        # /tokens/socket with clamped ttl (too high)
        r = await ac.post("/tokens/socket", json={"job_id": "job123", "ttl_seconds": 1200}, headers=headers)
        assert r.status_code == 200
        assert r.json()["expires_in"] == 900

        # /tokens/socket with clamped ttl (too low)
        r = await ac.post("/tokens/socket", json={"job_id": "job123", "ttl_seconds": 30}, headers=headers)
        assert r.status_code == 200
        assert r.json()["expires_in"] == 60

        # /tokens/socket with invalid job_id format
        r = await ac.post("/tokens/socket", json={"job_id": "job$123"}, headers=headers)
        assert r.status_code == 422
