from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import app
from src.engine.models import Candidate, SourceName
from src.tools.models import SearchResourcesRequest


def _candidate(
    content_id: str,
    *,
    duration: float,
    title: str | None = None,
    url: str | None = None,
) -> Candidate:
    return Candidate(
        source=SourceName.YOUTUBE,
        tag="docker tutorial",
        title=title or f"Docker course {content_id}",
        url=url or f"https://www.youtube.com/watch?v={content_id}",
        content_id=content_id,
        description="must never cross the API boundary",
        channel_or_provider="Bosla Test Channel",
        language="en",
        duration_minutes=duration,
        view_count=10_000,
        published_at="2026-01-01T00:00:00+00:00",
        metadata={"thumbnailUrl": "https://example.test/private.jpg"},
    )


@asynccontextmanager
async def _client_with_candidates(
    monkeypatch: pytest.MonkeyPatch,
    candidates: list[Candidate],
) -> AsyncIterator[AsyncClient]:
    async def fetch_candidates(_request: SearchResourcesRequest) -> list[Candidate]:
        return candidates

    monkeypatch.setattr(
        "src.tools.search_resources.fetch_candidates",
        fetch_candidates,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_search_resources_filters_duration_and_returns_compact_dto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    candidates = [
        _candidate("short", duration=60),
        _candidate("long", duration=240),
    ]

    # When
    async with _client_with_candidates(monkeypatch, candidates) as client:
        response = await client.post(
            "/tools/search_resources",
            json={
                "source": "youtube",
                "query": "docker tutorial",
                "language": "en",
                "limit": 10,
                "duration_max_minutes": 120,
            },
        )

    # Then
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"] == {
        "source": "youtube",
        "query": "docker tutorial",
        "rawCount": 2,
        "filteredCount": 1,
        "shortlistCount": 1,
    }
    assert [item["id"] for item in payload["candidates"]] == ["short"]
    assert set(payload["candidates"][0]) == {
        "id",
        "url",
        "title",
        "durationMinutes",
        "language",
        "channel",
        "viewCount",
        "publishedAt",
        "cheapScore",
        "finalScore",
    }


@pytest.mark.asyncio
async def test_search_resources_dedupes_before_applying_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    candidates = [
        _candidate("same", duration=60),
        _candidate(
            "same-copy",
            duration=60,
            url="https://youtu.be/same",
            title="Docker course same duplicate",
        ),
        _candidate("other", duration=75),
    ]

    # When
    async with _client_with_candidates(monkeypatch, candidates) as client:
        response = await client.post(
            "/tools/search_resources",
            json={
                "source": "youtube",
                "query": "docker tutorial",
                "language": "en",
                "limit": 2,
            },
        )

    # Then
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["candidates"]]
    assert len(ids) == 2
    assert set(ids) == {"same", "other"}


@pytest.mark.asyncio
async def test_search_resources_rejects_limit_above_fifteen() -> None:
    # Given
    transport = ASGITransport(app=app)

    # When
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/tools/search_resources",
            json={
                "source": "youtube",
                "query": "docker tutorial",
                "language": "en",
                "limit": 16,
            },
        )

    # Then
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_resources_does_not_apply_legacy_lexical_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: valid provider evidence whose title does not repeat the query words.
    candidates = [
        _candidate(
            "agent-judges",
            duration=45,
            title="Containers from first principles",
        )
    ]

    # When
    async with _client_with_candidates(monkeypatch, candidates) as client:
        response = await client.post(
            "/tools/search_resources",
            json={
                "source": "youtube",
                "query": "docker tutorial",
                "language": "en",
                "limit": 5,
            },
        )

    # Then
    assert response.status_code == 200
    assert response.json()["candidates"][0]["id"] == "agent-judges"


@pytest.mark.asyncio
async def test_search_resources_defaults_omitted_language_to_english(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    async def fetch_candidates(request: SearchResourcesRequest) -> list[Candidate]:
        captured.append(request.language)
        return [_candidate("default-language", duration=60)]

    monkeypatch.setattr("src.tools.search_resources.fetch_candidates", fetch_candidates)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/tools/search_resources",
            json={"source": "youtube", "query": "docker tutorial"},
        )

    assert response.status_code == 200
    assert captured == ["en"]


@pytest.mark.asyncio
async def test_search_resources_defaults_to_fifteen_and_reserves_unique_arabic_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = [_candidate(f"rank-{index}", duration=60) for index in range(1, 16)]
    candidates[-1].language = "ar"
    async with _client_with_candidates(monkeypatch, candidates) as client:
        response = await client.post(
            "/tools/search_resources",
            json={"source": "youtube", "query": "react"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["candidates"]) == 15
    assert any(candidate["language"] == "ar" for candidate in payload["candidates"])
    assert payload["meta"]["shortlistCount"] == 15
