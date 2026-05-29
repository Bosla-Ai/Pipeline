import pytest
from httpx import AsyncClient, ASGITransport
from src.api import app
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_prefer_paid_false_defaults_to_youtube(mocker):
    """Test that prefer_paid=False without explicit sources defaults to YouTube."""
    mock_youtube = mocker.patch(
        "src.api.fetch_youtube", new_callable=AsyncMock, return_value={"video": "data"}
    )
    mock_coursera = mocker.patch("src.api.fetch_coursera", new_callable=AsyncMock)
    mock_udemy = mocker.patch("src.fetchers.videos.udemy_fetcher.UdemyFetcher.scrape")
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": False,
                "language": "en",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]

    # YouTube should be called as the default free source
    mock_youtube.assert_called()
    # Paid fetchers should NOT be called
    mock_coursera.assert_not_called()
    mock_udemy.assert_not_called()

    assert "youtube" in data
    assert data["youtube"] == {"video": "data"}


@pytest.mark.asyncio
async def test_explicit_sources_override_prefer_paid(mocker):
    """Test that explicit sources take priority even when prefer_paid=False."""
    mock_youtube = mocker.patch("src.api.fetch_youtube", new_callable=AsyncMock)
    mock_coursera = mocker.patch(
        "src.api.fetch_coursera",
        new_callable=AsyncMock,
        return_value={"python": {"title": "Coursera Python"}},
    )
    mock_udemy = mocker.patch("src.fetchers.videos.udemy_fetcher.UdemyFetcher.scrape")
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": False,
                "language": "en",
                "sources": ["coursera"],
            },
        )

    assert response.status_code == 200

    # Explicit sources should be respected regardless of prefer_paid
    mock_coursera.assert_called()
    # YouTube should NOT be called — it's not in explicit sources
    mock_youtube.assert_not_called()
    mock_udemy.assert_not_called()


@pytest.mark.asyncio
async def test_prefer_paid_strips_youtube_from_sources(mocker):
    """Test that prefer_paid=True strips YouTube from explicit sources."""
    mock_youtube = mocker.patch(
        "src.api.fetch_youtube", new_callable=AsyncMock, return_value={}
    )
    mock_coursera = mocker.patch("src.api.fetch_coursera", new_callable=AsyncMock)
    mock_udemy = mocker.patch("src.fetchers.videos.udemy_fetcher.UdemyFetcher.scrape")
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": True,
                "language": "en",
                "sources": ["youtube", "udemy"],
            },
        )

    assert response.status_code == 200

    # YouTube should be stripped from active sources when prefer_paid=True
    # (YouTube is still used as fallback for atomic/unmatched tags internally)
    mock_udemy.assert_called()
    mock_coursera.assert_not_called()


@pytest.mark.asyncio
async def test_prefer_paid_true_default_sources(mocker):
    """Test default behavior for prefer_paid=True (should be Udemy, then YouTube fallback if empty)."""
    mock_youtube = mocker.patch(
        "src.api.fetch_youtube",
        new_callable=AsyncMock,
        return_value={"python": {"title": "fallback"}},
    )
    mock_coursera = mocker.patch("src.api.fetch_coursera", new_callable=AsyncMock)
    mock_udemy = mocker.patch("src.fetchers.videos.udemy_fetcher.UdemyFetcher.scrape")
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={"tags": ["python"], "prefer_paid": True, "language": "en"},
        )

    assert response.status_code == 200

    # Coursera should NOT be called by default now
    mock_coursera.assert_not_called()

    # Udemy SHOULD be called
    mock_udemy.assert_called()

    # YouTube SHOULD be called as fallback when Udemy returns nothing
    mock_youtube.assert_called()


@pytest.mark.asyncio
async def test_prefer_paid_true_specific_source_coursera(mocker):
    """Test requesting ONLY Coursera — YouTube fallback if Coursera returns nothing for a tag."""
    mock_youtube = mocker.patch(
        "src.api.fetch_youtube",
        new_callable=AsyncMock,
        return_value={"python": {"title": "fallback"}},
    )
    mock_coursera = mocker.patch(
        "src.api.fetch_coursera",
        new_callable=AsyncMock,
        return_value={"python": {"title": "Coursera Python"}},
    )
    mock_udemy = mocker.patch("src.fetchers.videos.udemy_fetcher.UdemyFetcher.scrape")
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": True,
                "language": "en",
                "sources": ["coursera"],
            },
        )

    assert response.status_code == 200

    mock_coursera.assert_called()
    mock_udemy.assert_not_called()
    # When Coursera successfully returns data for the tag, YouTube fallback should NOT be called
    mock_youtube.assert_not_called()


@pytest.mark.asyncio
async def test_prefer_paid_true_specific_source_udemy(mocker):
    """Test requesting ONLY Udemy."""
    mock_coursera = mocker.patch("src.api.fetch_coursera", new_callable=AsyncMock)
    mock_udemy = mocker.patch("src.fetchers.videos.udemy_fetcher.UdemyFetcher.scrape")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": True,
                "language": "en",
                "sources": ["udemy"],
            },
        )

    mock_coursera.assert_not_called()
    mock_udemy.assert_called()


@pytest.mark.asyncio
async def test_mixed_sources(mocker):
    """Test requesting a mix: Udemy + Youtube."""
    mock_youtube = mocker.patch(
        "src.api.fetch_youtube", new_callable=AsyncMock, return_value={"y": "data"}
    )
    mock_coursera = mocker.patch("src.api.fetch_coursera", new_callable=AsyncMock)
    mock_udemy = mocker.patch("src.fetchers.videos.udemy_fetcher.UdemyFetcher.scrape")
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": True,
                "language": "en",
                "sources": ["udemy", "youtube"],
            },
        )

    mock_youtube.assert_called()
    mock_udemy.assert_called()
    mock_coursera.assert_not_called()
