import importlib
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def auth_setup(monkeypatch):
    monkeypatch.setenv("PIPELINE_SHARED_SECRET", "secret-test-token")
    import src.config.settings as settings
    import src.api as api

    importlib.reload(settings)
    importlib.reload(api)
    yield api
    monkeypatch.delenv("PIPELINE_SHARED_SECRET", raising=False)
    importlib.reload(settings)
    importlib.reload(api)


@pytest.mark.asyncio
async def test_auth_validation_on_all_endpoints(auth_setup):
    api = auth_setup
    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/stats")
        assert r.status_code == 401

        r = await ac.get("/logs")
        assert r.status_code == 401

        r = await ac.get("/logs/job/testjob")
        assert r.status_code == 401

        r = await ac.get("/logs/export")
        assert r.status_code == 401

        r = await ac.get("/search-embeddable-video?q=test")
        assert r.status_code == 401

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
