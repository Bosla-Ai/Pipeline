from __future__ import annotations

import hashlib
from typing import assert_never
from urllib.parse import urlparse

import anyio

from src.engine.models import Candidate, SourceName, TopicScope
from src.engine.stages import PlannedQuery, PreparedTag
from src.ranking.cheap_ranker import cheap_rank
from src.ranking.dedupe import dedupe_candidates
from src.ranking.final_ranker import final_rank
from src.tools.models import (
    ResourceCandidate,
    SearchMeta,
    SearchResourcesRequest,
    SearchResourcesResponse,
)


async def fetch_candidates(request: SearchResourcesRequest) -> list[Candidate]:
    match request.source:
        case "youtube":
            return await _fetch_youtube(request)
        case "coursera":
            return await _fetch_coursera(request)
        case unreachable:
            assert_never(unreachable)


async def search_resources(request: SearchResourcesRequest) -> SearchResourcesResponse:
    raw = await fetch_candidates(request)
    shaped = [candidate for candidate in raw if _matches_shape(candidate, request)]
    ranked = cheap_rank(shaped, request.query, TopicScope.UNKNOWN)
    deduped = dedupe_candidates(ranked)
    selected = _select_with_diversity(deduped, request.limit)
    cheap_scores = {candidate.url: float(candidate.raw_score) for candidate in selected}
    prepared = PreparedTag(
        original=request.query,
        normalized=request.query,
        language=request.language,
        scope=TopicScope.UNKNOWN,
    )
    final_rank(selected, prepared, cheap_scores, None)
    rows = [
        _to_resource_candidate(candidate, request.language, cheap_scores)
        for candidate in selected
    ]
    return SearchResourcesResponse(
        candidates=rows,
        meta=SearchMeta(
            source=request.source,
            query=request.query,
            rawCount=len(raw),
            filteredCount=len(deduped),
            shortlistCount=len(selected),
        ),
    )


def _select_with_diversity(candidates: list[Candidate], limit: int) -> list[Candidate]:
    """Keep cheap-rank order while reserving one present language/duration bucket.

    Language bucket: normalized candidate language. Duration buckets: short (<30m),
    medium (30-120m), long (>120m). Content type supplies the depth/type bucket.
    """
    if len(candidates) <= limit:
        return list(candidates)
    selected = list(candidates[:limit])
    buckets: dict[tuple[str, str, str], Candidate] = {}
    for candidate in candidates:
        duration = candidate.duration_minutes or 0
        duration_bucket = "short" if duration < 30 else "medium" if duration <= 120 else "long"
        content_bucket = str(candidate.metadata.get("contentType", "video")).lower()
        bucket = ((candidate.language or "unknown").lower(), content_bucket, duration_bucket)
        buckets.setdefault(bucket, candidate)
    for reserve in buckets.values():
        if reserve in selected:
            continue
        selected[-1] = reserve
    order = {candidate.url: index for index, candidate in enumerate(candidates)}
    return sorted(dict.fromkeys(selected), key=lambda candidate: order[candidate.url])[:limit]


def _matches_shape(candidate: Candidate, request: SearchResourcesRequest) -> bool:
    if not candidate.title.strip() or not _is_http_url(candidate.url):
        return False
    duration = candidate.duration_minutes
    if duration is None or duration <= 0:
        return False
    if request.duration_min_minutes is not None and duration < request.duration_min_minutes:
        return False
    if request.duration_max_minutes is not None and duration > request.duration_max_minutes:
        return False
    content_type = str(candidate.metadata.get("contentType", "video")).lower()
    if request.type is not None and request.type not in content_type:
        return False
    if request.embeddable is True and candidate.metadata.get("embeddable") is False:
        return False
    return True


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _to_resource_candidate(
    candidate: Candidate,
    fallback_language: str,
    cheap_scores: dict[str, float],
) -> ResourceCandidate:
    content_id = candidate.content_id or hashlib.sha256(candidate.url.encode()).hexdigest()[:16]
    return ResourceCandidate(
        id=content_id,
        url=candidate.url,
        title=candidate.title,
        durationMinutes=float(candidate.duration_minutes or 0),
        language=candidate.language or fallback_language,
        channel=candidate.channel_or_provider or "",
        viewCount=candidate.view_count or 0,
        publishedAt=candidate.published_at or None,
        cheapScore=cheap_scores.get(candidate.url, 0.0),
        finalScore=float(candidate.raw_score),
    )


async def _fetch_youtube(request: SearchResourcesRequest) -> list[Candidate]:
    from src.cache.pipeline_cache import get_raw_ytdlp_candidates, set_raw_ytdlp_candidates
    from src.fetchers.videos.youtube_scraper import _extract_search_results
    from src.tools.file_cache import read_json_list, write_json_list

    cached = await get_raw_ytdlp_candidates(request.query, request.language)
    disk_key = f"{request.language}:{request.query}"
    if cached is None:
        cached = read_json_list("search-resources", disk_key)
    if cached is None:
        query = f"ytsearch{max(request.limit, 15)}:{request.query}"
        cached = await anyio.to_thread.run_sync(
            _extract_search_results,
            query,
            request.language,
        )
        if cached:
            await set_raw_ytdlp_candidates(request.query, request.language, cached)
            write_json_list("search-resources", disk_key, cached)
    return [
        candidate
        for raw in cached
        if (candidate := _youtube_candidate(raw, request)) is not None
    ]


def _youtube_candidate(
    raw: dict,
    request: SearchResourcesRequest,
) -> Candidate | None:
    title = str(raw.get("title") or "").strip()
    content_id = str(raw.get("id") or "").strip()
    duration_seconds = raw.get("duration")
    if not title or not content_id or not isinstance(duration_seconds, (int, float)):
        return None
    is_playlist = raw.get("_type") == "playlist"
    content_type = "playlist" if is_playlist else "video"
    url = (
        f"https://www.youtube.com/playlist?list={content_id}"
        if is_playlist
        else f"https://www.youtube.com/watch?v={content_id}"
    )
    return Candidate(
        source=SourceName.YOUTUBE,
        tag=request.query,
        title=title,
        url=url,
        content_id=content_id,
        channel_or_provider=str(raw.get("channel") or raw.get("uploader") or ""),
        language=request.language,
        duration_minutes=float(duration_seconds) / 60,
        view_count=int(raw.get("view_count") or 0),
        published_at=str(raw.get("upload_date") or "") or None,
        metadata={
            "contentType": content_type,
            "embeddable": raw.get("availability") not in {"private", "subscriber_only"},
        },
    )


async def _fetch_coursera(request: SearchResourcesRequest) -> list[Candidate]:
    from src.fetchers.videos.coursera_fetcher import scrape_coursera_sync

    result = await anyio.to_thread.run_sync(
        scrape_coursera_sync,
        None,
        [request.query],
        request.language,
        max(request.limit, 15),
        None,
    )
    raw_candidates = result.get(request.query, [])
    return [Candidate.from_dict(raw, SourceName.COURSERA, request.query) for raw in raw_candidates]
