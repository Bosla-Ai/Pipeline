from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import app
from src.tools.file_cache import JsonValue


EXPECTED_FIELDS = {
    "demandSignals",
    "trendingSkills",
    "decliningSkills",
    "tagTrends",
    "ecosystemNotes",
    "sourcesFailed",
}


@pytest.mark.asyncio
async def test_market_data_is_schema_complete_for_multiple_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    d_cache = Path("D:/BOSLA/.omo/cache/pytest") / uuid4().hex
    monkeypatch.setenv("PIPELINE_CACHE_DIR", str(d_cache))

    async def fetch_tag(tag: str) -> dict[str, JsonValue]:
        return {
            "tag": tag,
            "questionCount": 100 if tag == "docker" else 200,
            "hasSynonyms": True,
            "relatedTags": ["devops", "containers"],
        }

    monkeypatch.setattr("src.tools.market_data.fetch_stackexchange_tag", fetch_tag)
    transport = ASGITransport(app=app)

    # When
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/tools/market_data",
            json={"role": "backend engineer", "tags": ["docker", "kubernetes"]},
        )

    # Then
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == EXPECTED_FIELDS
    assert [row["tag"] for row in payload["tagTrends"]] == ["docker", "kubernetes"]
    assert payload["decliningSkills"] == []
    assert payload["sourcesFailed"] == []


@pytest.mark.asyncio
async def test_market_data_second_call_uses_configured_file_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given
    d_cache = tmp_path / "pipeline-cache" / uuid4().hex
    monkeypatch.setenv("PIPELINE_CACHE_DIR", str(d_cache))
    calls = 0

    async def fetch_tag(tag: str) -> dict[str, JsonValue]:
        nonlocal calls
        calls += 1
        return {
            "tag": tag,
            "questionCount": 42,
            "hasSynonyms": False,
            "relatedTags": [],
        }

    monkeypatch.setattr("src.tools.market_data.fetch_stackexchange_tag", fetch_tag)
    transport = ASGITransport(app=app)

    # When
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/tools/market_data", json={"tags": ["docker"]})
        second = await client.post("/tools/market_data", json={"tags": ["docker"]})

    # Then
    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == 1
    assert list(d_cache.rglob("*.json"))


@pytest.mark.asyncio
async def test_market_data_source_failure_returns_empty_partial_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    d_cache = Path("D:/BOSLA/.omo/cache/pytest") / uuid4().hex
    monkeypatch.setenv("PIPELINE_CACHE_DIR", str(d_cache))

    async def fetch_tag(_tag: str) -> dict[str, JsonValue]:
        raise OSError("network unavailable")

    monkeypatch.setattr("src.tools.market_data.fetch_stackexchange_tag", fetch_tag)
    transport = ASGITransport(app=app)

    # When
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/tools/market_data",
            json={"tags": ["docker", "kubernetes"]},
        )

    # Then
    assert response.status_code == 200
    assert response.json() == {
        "demandSignals": [],
        "trendingSkills": [],
        "decliningSkills": [],
        "tagTrends": [],
        "ecosystemNotes": [],
        "sourcesFailed": ["stackexchange"],
    }
