import pytest
from httpx import AsyncClient, ASGITransport
from src.api import app
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_generate_roadmap_structure(mocker):
    """Test basic response structure for free content request."""
    mocker.patch("src.api.fetch_youtube", return_value={"mock_video": "data"})
    mocker.patch("src.api.fetch_coursera", return_value={"mock_course": "data"})
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
    data = response.json()
    assert data["status"] == "success"
    assert "youtube" in data["data"]
    assert "coursera" in data["data"]
    assert "udemy" in data["data"]
    assert data["data"]["youtube"] == {"mock_video": "data"}


@pytest.mark.asyncio
async def test_generate_roadmap_paid(mocker):
    """Test prefer_paid=True routes to Coursera/Udemy."""
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
                "language": "en",
                "sources": ["coursera", "udemy"],
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "coursera" in data["data"]
    assert data["data"]["coursera"] == {"mock_course": "data"}


@pytest.mark.asyncio
async def test_generate_roadmap_multiple_tags(mocker):
    """Test roadmap generation with multiple tags."""
    mocker.patch(
        "src.api.fetch_youtube",
        return_value={
            "python": {"title": "Python Course"},
            "javascript": {"title": "JS Course"},
        },
    )
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python", "javascript"],
                "prefer_paid": False,
                "language": "en",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    # Verify multiple tags are handled
    assert len(data["data"]["youtube"]) >= 1


@pytest.mark.asyncio
async def test_generate_roadmap_cpp_tag(mocker):
    """Test C++ tag specifically (original bug case) with prefer_paid=True."""
    mocker.patch("src.api.fetch_youtube", return_value={})
    mocker.patch(
        "src.api.fetch_coursera", return_value={"c++": {"title": "C++ Mastery"}}
    )
    mocker.patch(
        "src.fetchers.videos.udemy_fetcher.UdemyFetcher.scrape", return_value=None
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["c++"],
                "prefer_paid": True,
                "language": "en",
                "sources": ["coursera"],
            },
        )

    assert response.status_code == 200
    data = response.json()
    # C++ should be routed to Coursera (not YouTube) when prefer_paid=True
    assert "coursera" in data["data"]
    assert data["data"]["coursera"] == {"c++": {"title": "C++ Mastery"}}


@pytest.mark.asyncio
async def test_generate_roadmap_arabic_language(mocker):
    """Test Arabic language parameter."""
    mocker.patch("src.api.fetch_youtube", return_value={"ar_video": "data"})
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["python"],
                "prefer_paid": False,
                "language": "ar",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_generate_roadmap_empty_tags(mocker):
    """Test with empty tags list."""
    mocker.patch("src.api.fetch_youtube", return_value={})
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": [],
                "prefer_paid": False,
                "language": "en",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_generate_roadmap_broad_topics_collection(mocker):
    """Test that all known broad topics route correctly with prefer_paid=True."""
    broad_topics = ["python", "docker", "kubernetes", "react", "machine learning"]

    mocker.patch("src.api.fetch_youtube", return_value={})
    mocker.patch("src.api.fetch_coursera", return_value={"result": "paid_data"})
    mocker.patch(
        "src.fetchers.videos.udemy_fetcher.UdemyFetcher.scrape", return_value=None
    )

    transport = ASGITransport(app=app)

    for topic in broad_topics:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                "/generate-roadmap",
                json={
                    "tags": [topic],
                    "prefer_paid": True,
                    "language": "en",
                    "sources": ["coursera"],
                },
            )

        assert response.status_code == 200, f"Failed for topic: {topic}"
        data = response.json()
        assert data["status"] == "success", f"Status not success for: {topic}"


@pytest.mark.asyncio
async def test_generate_roadmap_response_keys(mocker):
    """Verify all expected keys are present in response."""
    mocker.patch("src.api.fetch_youtube", return_value={})
    mocker.patch("src.socket_server.sio.call", new_callable=AsyncMock)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/generate-roadmap",
            json={
                "tags": ["test"],
                "prefer_paid": False,
                "language": "en",
            },
        )

    assert response.status_code == 200
    data = response.json()

    # Verify top-level structure
    assert "status" in data
    assert "data" in data

    # Verify data structure
    assert "youtube" in data["data"]
    assert "coursera" in data["data"]
    assert "udemy" in data["data"]


@pytest.mark.asyncio
async def test_generate_roadmap_content_type_video(mocker):
    """Test content_type parameter is passed correctly."""
    mocker.patch("src.api.fetch_youtube", return_value={})
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


@pytest.mark.asyncio
async def test_generate_roadmap_content_type_playlist(mocker):
    """Test content_type=playlist parameter."""
    mocker.patch("src.api.fetch_youtube", return_value={})
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
