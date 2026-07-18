from __future__ import annotations

from urllib.parse import quote

import aiohttp

from src.tools.file_cache import read_json, write_json
from src.tools.file_cache import JsonValue
from src.tools.models import (
    DemandSignal,
    MarketDataRequest,
    MarketDataResponse,
    TagTrend,
)


async def market_data(request: MarketDataRequest) -> MarketDataResponse:
    trends: list[TagTrend] = []
    failed = False
    for requested_tag in request.tags:
        normalized = _normalize_tag(requested_tag)
        cached = read_json("market-data", normalized)
        try:
            raw = cached or await fetch_stackexchange_tag(normalized)
        except (OSError, TimeoutError, aiohttp.ClientError):
            failed = True
            continue
        if cached is None:
            write_json("market-data", normalized, raw)
        trends.append(TagTrend.model_validate(raw))

    return MarketDataResponse(
        demandSignals=[
            DemandSignal(tag=row.tag, questionCount=row.questionCount) for row in trends
        ],
        trendingSkills=[row.tag for row in sorted(trends, key=lambda row: -row.questionCount)],
        decliningSkills=[],
        tagTrends=trends,
        ecosystemNotes=[],
        sourcesFailed=["stackexchange"] if failed else [],
    )


async def fetch_stackexchange_tag(tag: str) -> dict[str, JsonValue]:
    encoded = quote(tag, safe="")
    timeout = aiohttp.ClientTimeout(total=10, connect=5)
    headers = {"Accept-Encoding": "gzip", "User-Agent": "Bosla/1.0"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as client:
        info_response = await client.get(
            f"https://api.stackexchange.com/2.3/tags/{encoded}/info",
            params={"site": "stackoverflow"},
        )
        info_response.raise_for_status()
        info_payload = await info_response.json()
        related_response = await client.get(
            f"https://api.stackexchange.com/2.3/tags/{encoded}/related",
            params={"site": "stackoverflow", "pagesize": "5"},
        )
        related_response.raise_for_status()
        related_payload = await related_response.json()

    items = info_payload.get("items", [])
    info = items[0] if items else {}
    related = [
        str(item.get("name"))
        for item in related_payload.get("items", [])
        if item.get("name")
    ]
    return {
        "tag": str(info.get("name") or tag),
        "questionCount": int(info.get("count") or 0),
        "hasSynonyms": bool(info.get("has_synonyms", False)),
        "relatedTags": related,
    }


def _normalize_tag(tag: str) -> str:
    normalized = "-".join(tag.strip().lower().split())
    aliases = {
        "csharp": "c#",
        "cpp": "c++",
        "k8s": "kubernetes",
        "nodejs": "node.js",
        "react": "reactjs",
    }
    return aliases.get(normalized, normalized)
