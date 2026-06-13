import os
import importlib
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock

# We need to test the runtime profiles loading dynamically based on environmental variables.


def test_external_scrapers_disabled_profile(monkeypatch):
    """Test that when ENABLE_EXTERNAL_SCRAPERS is false, both Udemy and Coursera are disabled."""
    monkeypatch.setenv("FREE_HF_MODE", "false")
    monkeypatch.setenv("ENABLE_EXTERNAL_SCRAPERS", "false")
    monkeypatch.setenv("ENABLE_UDEMY", "true")
    monkeypatch.setenv("ENABLE_COURSERA", "true")

    import src.config.runtime_profile as rp

    importlib.reload(rp)

    assert rp.ENABLE_EXTERNAL_SCRAPERS is False
    assert rp.ENABLE_UDEMY is False
    assert rp.ENABLE_COURSERA is False
    assert rp.SKIP_GLOBAL_DRIVER_INIT is True


def test_external_scrapers_enabled_profile(monkeypatch):
    """Test that when ENABLE_EXTERNAL_SCRAPERS is true, they load normally from env."""
    monkeypatch.setenv("FREE_HF_MODE", "false")
    monkeypatch.setenv("ENABLE_EXTERNAL_SCRAPERS", "true")
    monkeypatch.setenv("ENABLE_UDEMY", "true")
    monkeypatch.setenv("ENABLE_COURSERA", "true")

    # Mock module checks so they think libraries are installed
    import importlib.util

    class DummySpec:
        pass

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: DummySpec())

    import src.config.runtime_profile as rp

    importlib.reload(rp)

    assert rp.ENABLE_EXTERNAL_SCRAPERS is True
    assert rp.ENABLE_UDEMY is True
    assert rp.ENABLE_COURSERA is True


def test_external_scrapers_missing_deps_degrades_gracefully(monkeypatch):
    """Test that when dependencies are missing, features degrade gracefully to False."""
    monkeypatch.setenv("FREE_HF_MODE", "false")
    monkeypatch.setenv("ENABLE_EXTERNAL_SCRAPERS", "true")
    monkeypatch.setenv("ENABLE_UDEMY", "true")
    monkeypatch.setenv("ENABLE_COURSERA", "true")

    # Simulate missing dependencies (scrapling missing, but undetected_chromedriver present)
    import importlib.util

    class DummySpec:
        pass

    def mock_find_spec(name):
        if name in ("undetected_chromedriver", "selenium"):
            return DummySpec()
        return None

    monkeypatch.setattr(importlib.util, "find_spec", mock_find_spec)

    import src.config.runtime_profile as rp

    importlib.reload(rp)

    assert rp.ENABLE_UDEMY is False
    assert rp.ENABLE_COURSERA is True


@pytest.mark.asyncio
async def test_generate_roadmap_rejects_disabled_scrapers(monkeypatch, mocker):
    """Test that endpoints reject explicit requests for disabled features with HTTP 501, but allow fallback."""
    # Ensure they are disabled
    monkeypatch.setattr("src.config.runtime_profile.ENABLE_EXTERNAL_SCRAPERS", False)
    monkeypatch.setattr("src.config.runtime_profile.ENABLE_UDEMY", False)
    monkeypatch.setattr("src.config.runtime_profile.ENABLE_COURSERA", False)

    # Mock engine generate and job store create
    mock_engine_gen = mocker.patch(
        "src.engine.roadmap_engine.RoadmapEngine.generate",
        new_callable=AsyncMock,
        return_value={"status": "success", "data": {}},
    )
    mocker.patch("src.engine.job_store.job_store.create_job", new_callable=AsyncMock)

    from src.api import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Requesting Udemy explicitly -> HTTP 501
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": False,
                "sources": ["udemy"],
            },
        )
        assert response.status_code == 501
        assert "disabled on this instance" in response.json()["detail"]

        # Requesting Coursera explicitly -> HTTP 501
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": False,
                "sources": ["coursera"],
            },
        )
        assert response.status_code == 501

        # Requesting prefer_paid=True when both are disabled -> HTTP 200 (gracefully falls back to youtube)
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": True,
            },
        )
        assert response.status_code == 200

        # Background endpoint also rejects explicit -> HTTP 501
        response = await ac.post(
            "/jobs/roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": False,
                "sources": ["udemy"],
            },
        )
        assert response.status_code == 501


@pytest.mark.asyncio
async def test_generate_roadmap_allows_enabled_scrapers(monkeypatch, mocker):
    """Test that endpoints allow requests when features are enabled."""
    # Ensure they are enabled
    monkeypatch.setattr("src.config.runtime_profile.ENABLE_EXTERNAL_SCRAPERS", True)
    monkeypatch.setattr("src.config.runtime_profile.ENABLE_UDEMY", True)
    monkeypatch.setattr("src.config.runtime_profile.ENABLE_COURSERA", True)

    # Mock actual runner engine so it doesn't try running browser logic
    mock_engine_gen = mocker.patch(
        "src.engine.roadmap_engine.RoadmapEngine.generate",
        new_callable=AsyncMock,
        return_value={"status": "mocked"},
    )
    mocker.patch("src.engine.job_store.job_store.create_job", new_callable=AsyncMock)

    from src.api import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": False,
                "sources": ["udemy"],
            },
        )
        assert response.status_code == 200
