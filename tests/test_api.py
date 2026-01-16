import pytest
from httpx import AsyncClient, ASGITransport
from src.api import app
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_generate_roadmap_structure(mocker):
    # Mock external fetchers to prevent real API calls
    mocker.patch("src.api.fetch_youtube", return_value={"mock_video": "data"})
    mocker.patch("src.api.fetch_coursera", return_value={"mock_course": "data"})

    # Mock SocketIO to avoid warnings
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": False,
                "content_type": "video",
                "language": "en",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "youtube" in data["data"]
    assert data["data"]["youtube"] == {"mock_video": "data"}


@pytest.mark.asyncio
async def test_generate_roadmap_paid(mocker):
    mocker.patch("src.api.fetch_youtube", return_value={})
    mocker.patch("src.api.fetch_coursera", return_value={"mock_course": "data"})
    mocker.patch(
        "src.fetchers.videos.udemy_fetcher.UdemyFetcher.scrape", return_value=None
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": True,
                "content_type": "video",
                "language": "en",
            },
        )

    assert response.status_code == 200
    # Logic: Paid prefer -> Coursera + Udemy (Youtube skipped in paid block logic in api.py?)
    # api.py: if not prefer_paid: fetch_youtube; else: fetch_coursera

    data = response.json()
    assert "coursera" in data["data"]
    assert data["data"]["coursera"] == {"mock_course": "data"}
