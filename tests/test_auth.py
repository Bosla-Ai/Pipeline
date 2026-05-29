import importlib

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_generate_roadmap_requires_pipeline_token(monkeypatch):
    monkeypatch.setenv("PIPELINE_SHARED_SECRET", "secret-test-token")
    import src.config.settings as settings
    import src.api as api

    importlib.reload(settings)
    importlib.reload(api)

    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={"tags": ["python"], "prefer_paid": False, "language": "en"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_stats_requires_pipeline_token(monkeypatch):
    monkeypatch.setenv("PIPELINE_SHARED_SECRET", "secret-test-token")
    import src.config.settings as settings
    import src.api as api

    importlib.reload(settings)
    importlib.reload(api)

    transport = ASGITransport(app=api.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/stats")

    assert response.status_code == 401
