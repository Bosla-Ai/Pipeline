from __future__ import annotations

import asyncio
import uuid
from typing import Any, List, Optional

import src.socket_server as socket_server

from src.fetchers.videos.udemy_fetcher import UdemyFetcher
from src.utils.cache import cache, generate_cache_key
from src.utils.learning_path import generate_learning_path
from src.utils.event_log import event_log
from src.engine.runtime import runtime_limits, runtime_semaphores
from src.engine.models import CourseSource


def preprocess_tags(tags: list[str]) -> list[str]:
    """
    Cleans and normalizes tags from the API before passing to fetchers.
    Handles rich descriptive tags like 'Automated Testing with Jest'.
    """
    cleaned = []
    seen = set()
    for tag in tags:
        t = tag.strip()
        if not t:
            continue
        t = " ".join(t.split())
        key = t.lower()
        if key not in seen:
            seen.add(key)
            cleaned.append(t)
    return cleaned


async def wait_for_socket(job_id: str, timeout: float) -> str | None:
    """Block until the frontend connects with this job_id, or timeout."""
    existing = socket_server.get_socket_for_job(job_id)
    if existing:
        return existing

    evt = socket_server.register_job_waiter(job_id)
    try:
        await asyncio.wait_for(evt.wait(), timeout=timeout)
        return socket_server.get_socket_for_job(job_id)
    except asyncio.TimeoutError:
        event_log.log(
            "warn",
            "job",
            f"No frontend socket connected within {timeout}s. Proceeding without AI.",
            job_id=job_id,
        )
        return None
    finally:
        socket_server.cleanup_job_waiter(job_id)


class RoadmapEngine:
    def __init__(
        self,
        sio,
        fetch_youtube,
        fetch_coursera,
        get_global_driver,
        socket_wait_timeout: float | None = None,
    ):
        self.sio = sio
        self.fetch_youtube = fetch_youtube
        self.fetch_coursera = fetch_coursera
        self.get_global_driver = get_global_driver
        self.socket_wait_timeout = socket_wait_timeout

    async def generate(
        self,
        tags: List[str],
        prefer_paid: bool,
        language: str,
        sources: Optional[List[CourseSource]] = None,
        tag_checkpoints: Optional[dict] = None,
        job_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if not job_id:
            job_id = uuid.uuid4().hex[:12]

        from src.engine.job_store import job_store

        await job_store.start_job(job_id)

        try:
            async with runtime_semaphores.jobs:
                result = await asyncio.wait_for(
                    self._generate_impl(
                        tags=tags,
                        prefer_paid=prefer_paid,
                        language=language,
                        sources=sources,
                        tag_checkpoints=tag_checkpoints,
                        job_id=job_id,
                    ),
                    timeout=runtime_limits.full_job_timeout_seconds,
                )
            await job_store.complete_job(job_id, result)
            return result
        except Exception as e:
            await job_store.fail_job(job_id, str(e))
            raise

    async def _generate_impl(
        self,
        tags: List[str],
        prefer_paid: bool,
        language: str,
        sources: Optional[List[CourseSource]] = None,
        tag_checkpoints: Optional[dict] = None,
        job_id: Optional[str] = None,
    ) -> dict[str, Any]:
        fetch_youtube = self.fetch_youtube
        fetch_coursera = self.fetch_coursera

        if not job_id:
            job_id = uuid.uuid4().hex[:12]

        tags = preprocess_tags(tags)

        event_log.log(
            "info",
            "job",
            f"Roadmap requested. Tags: {tags}, Lang: {language}",
            job_id=job_id,
        )
        event_log.log("info", "job", "Waiting for frontend socket…", job_id=job_id)

        timeout = (
            self.socket_wait_timeout
            if self.socket_wait_timeout is not None
            else runtime_limits.socket_wait_timeout_seconds
        )
        current_sid = await wait_for_socket(job_id, timeout=timeout)

        if current_sid:
            event_log.log(
                "success",
                "job",
                f"Frontend socket ready (sid: {current_sid})",
                job_id=job_id,
            )
        else:
            event_log.log(
                "warn",
                "job",
                "No frontend socket. AI classification will be skipped.",
                job_id=job_id,
            )

        roadmap_result = {"youtube": {}, "coursera": {}, "udemy": {}}

        if sources:
            active_sources = sources
            if prefer_paid:
                # Strip free sources when user explicitly prefers paid;
                # YouTube is still used as fallback for atomic / unmatched tags later.
                paid_only = [s for s in active_sources if s != CourseSource.YOUTUBE]
                if paid_only:
                    active_sources = paid_only
        elif prefer_paid:
            active_sources = [CourseSource.UDEMY]
        else:
            active_sources = [CourseSource.YOUTUBE]

        event_log.log("info", "job", f"Active Sources: {active_sources}", job_id=job_id)

        if CourseSource.YOUTUBE in active_sources:
            try:
                event_log.log(
                    "info",
                    "fetcher",
                    f"Fetching Free Content (YouTube)... Lang: {language}",
                    job_id=job_id,
                )
                youtube_data = await fetch_youtube(
                    self.sio, current_sid, tags, language
                )
                roadmap_result["youtube"] = youtube_data
            except Exception as e:
                event_log.log(
                    "error", "fetcher", f"YouTube fetcher error: {e}", job_id=job_id
                )

        paid_sources_requested = any(
            s in active_sources for s in [CourseSource.COURSERA, CourseSource.UDEMY]
        )

        if paid_sources_requested:
            event_log.log(
                "info",
                "fetcher",
                f"Fetching Paid Content | Tags: {tags}",
                job_id=job_id,
            )

            from src.utils.helpers import analyze_topic_scope

            # Refresh sid in case the socket reconnected
            current_sid = socket_server.get_socket_for_job(job_id) or current_sid

            broad_tags = []
            atomic_tags = []
            scope_cache = {}

            async def analyze_tag(tag):
                scope = await analyze_topic_scope(self.sio, current_sid, tag)
                return tag, scope

            scope_results = await asyncio.gather(*(analyze_tag(t) for t in tags))
            for tag, scope in scope_results:
                scope_cache[tag] = scope
                if scope == "Broad":
                    broad_tags.append(tag)
                else:
                    atomic_tags.append(tag)

            event_log.log(
                "info",
                "job",
                f"Scope: Broad={broad_tags}, Atomic={atomic_tags}",
                job_id=job_id,
                details={
                    "broad_tags": broad_tags,
                    "atomic_tags": atomic_tags,
                    "method": "heuristic+ai_fallback",
                },
            )

            if broad_tags:
                fetch_tasks = []

                if CourseSource.COURSERA in active_sources:

                    async def fetch_coursera_job():
                        try:
                            data = await fetch_coursera(
                                self.sio,
                                current_sid,
                                broad_tags,
                                language,
                                driver=self.get_global_driver(),
                            )
                            roadmap_result["coursera"] = data
                        except Exception as e:
                            event_log.log(
                                "error",
                                "fetcher",
                                f"Coursera Error: {e}",
                                job_id=job_id,
                            )

                    fetch_tasks.append(fetch_coursera_job())

                if CourseSource.UDEMY in active_sources:

                    async def fetch_udemy_job():
                        try:
                            await cache.connect()
                            udemy_cached = {}
                            udemy_tags_to_fetch = []

                            for tag in broad_tags:
                                cache_key = generate_cache_key("udemy", tag, language)
                                cached_result = await cache.get(cache_key)
                                if cached_result:
                                    event_log.log(
                                        "success",
                                        "cache",
                                        f"Cache Hit - Udemy: {tag}",
                                        job_id=job_id,
                                    )
                                    udemy_cached[tag] = cached_result
                                else:
                                    udemy_tags_to_fetch.append(tag)

                            roadmap_result["udemy"] = udemy_cached

                            if not udemy_tags_to_fetch:
                                event_log.log(
                                    "success",
                                    "cache",
                                    "Udemy: All tags cached",
                                    job_id=job_id,
                                )
                            else:
                                udemy_fetcher = UdemyFetcher(
                                    tags=udemy_tags_to_fetch,
                                    limit=5,
                                    headless=True,
                                )
                                await asyncio.to_thread(udemy_fetcher.scrape)

                                # Log Cloudflare blocks for dashboard visibility
                                if udemy_fetcher.blocked_tags:
                                    event_log.log(
                                        "warn",
                                        "fetcher",
                                        f"Cloudflare blocked Udemy for: {udemy_fetcher.blocked_tags}",
                                        job_id=job_id,
                                        details={
                                            "source": "udemy",
                                            "blocked_tags": udemy_fetcher.blocked_tags,
                                            "reason": "cloudflare_waf",
                                        },
                                    )

                                udemy_results_map = udemy_fetcher.results

                                from src.utils.helpers import classify_via_frontend

                                for tag, candidates in udemy_results_map.items():
                                    if not candidates:
                                        continue

                                    from src.engine.models import Candidate, SourceName
                                    from src.engine.runtime import runtime_limits
                                    from src.ranking.dedupe import dedupe_candidates
                                    from src.ranking.cheap_ranker import cheap_rank

                                    pool_candidates = candidates[
                                        : runtime_limits.candidate_pool_limit_per_tag
                                    ]
                                    candidate_objs = [
                                        Candidate.from_dict(c, SourceName.UDEMY, tag)
                                        for c in pool_candidates
                                    ]

                                    deduped_objs = dedupe_candidates(candidate_objs)
                                    ranked_objs = cheap_rank(deduped_objs, tag)[
                                        : runtime_limits.cheap_rank_limit_per_tag
                                    ]

                                    ranked_dicts = [c.to_dict() for c in ranked_objs]

                                    if not ranked_dicts:
                                        continue

                                    sid = (
                                        socket_server.get_socket_for_job(job_id)
                                        or current_sid
                                    )
                                    valid_udemy = await classify_via_frontend(
                                        self.sio, sid, tag, ranked_dicts
                                    )

                                    if not valid_udemy:
                                        event_log.log(
                                            "warn",
                                            "fetcher",
                                            f"No AI selection for '{tag}', using fallback.",
                                            job_id=job_id,
                                        )
                                        valid_udemy = ranked_dicts

                                    if valid_udemy:
                                        valid_udemy.sort(
                                            key=lambda x: x.get("score", 0),
                                            reverse=True,
                                        )
                                        winner = valid_udemy[0]
                                        roadmap_result["udemy"][tag] = winner
                                        cache_key = generate_cache_key(
                                            "udemy", tag, language
                                        )
                                        await cache.set(cache_key, winner)
                                        event_log.log(
                                            "success",
                                            "fetcher",
                                            f"Udemy Winner: {winner['title'][:50]}...",
                                            job_id=job_id,
                                        )
                        except Exception as e:
                            event_log.log(
                                "error", "fetcher", f"Udemy Error: {e}", job_id=job_id
                            )

                    fetch_tasks.append(fetch_udemy_job())

                if fetch_tasks:
                    await asyncio.gather(*fetch_tasks)

            if atomic_tags:
                # Always fall back to YouTube for atomic tags — even in paid mode,
                # atomic topics (specific concepts) are best served by free videos.
                try:
                    event_log.log(
                        "info",
                        "fetcher",
                        f"Fetching YouTube for atomic tags: {atomic_tags}",
                        job_id=job_id,
                    )
                    sid = socket_server.get_socket_for_job(job_id) or current_sid
                    youtube_data = await fetch_youtube(
                        self.sio,
                        sid,
                        atomic_tags,
                        language,
                        scope_cache=scope_cache,
                    )
                    roadmap_result["youtube"].update(youtube_data)
                except Exception as e:
                    event_log.log(
                        "error",
                        "fetcher",
                        f"YouTube (atomic) Error: {e}",
                        job_id=job_id,
                    )

            # ── Fallback: if paid sources returned nothing for broad tags, use YouTube ──
            if broad_tags:
                unmatched_broad = [
                    t
                    for t in broad_tags
                    if t not in (roadmap_result.get("udemy") or {})
                    and t not in (roadmap_result.get("coursera") or {})
                ]
                if unmatched_broad:
                    event_log.log(
                        "warn",
                        "fetcher",
                        f"Paid sources returned nothing for {unmatched_broad}. Falling back to YouTube.",
                        job_id=job_id,
                        details={
                            "fallback": "youtube",
                            "unmatched_tags": unmatched_broad,
                            "active_sources": [s.value for s in active_sources],
                        },
                    )
                    try:
                        sid = socket_server.get_socket_for_job(job_id) or current_sid
                        youtube_fallback = await fetch_youtube(
                            self.sio,
                            sid,
                            unmatched_broad,
                            language,
                            scope_cache=scope_cache,
                        )
                        roadmap_result["youtube"].update(youtube_fallback)

                        fb_found = [
                            t
                            for t in unmatched_broad
                            if t in youtube_fallback and youtube_fallback[t]
                        ]
                        fb_missed = [t for t in unmatched_broad if t not in fb_found]
                        if fb_found:
                            event_log.log(
                                "success",
                                "fetcher",
                                f"YouTube fallback found resources for: {fb_found}",
                                job_id=job_id,
                                details={
                                    "fallback_found": fb_found,
                                    "fallback_missed": fb_missed,
                                },
                            )
                        if fb_missed:
                            event_log.log(
                                "warn",
                                "fetcher",
                                f"YouTube fallback found nothing for: {fb_missed}",
                                job_id=job_id,
                                details={"fallback_missed": fb_missed},
                            )
                    except Exception as e:
                        event_log.log(
                            "error",
                            "fetcher",
                            f"YouTube fallback Error: {e}",
                            job_id=job_id,
                        )

        event_log.log(
            "info", "job", "Generating Learning DNA Sequence...", job_id=job_id
        )
        learning_path = generate_learning_path(
            tags, roadmap_data=roadmap_result, tag_checkpoints=tag_checkpoints
        )
        roadmap_result["learning_path"] = learning_path

        event_log.log("success", "job", "Roadmap generation complete.", job_id=job_id)

        # ── Resource Audit: log every tag's resource status ───────────────
        _audit_found = 0
        _audit_missing = []
        _audit_no_url = []

        for source_name in ("youtube", "udemy", "coursera"):
            src_map = roadmap_result.get(source_name, {})
            for key, resource in (src_map or {}).items():
                if resource is None:
                    continue
                if not isinstance(resource, dict):
                    continue
                url = resource.get("url", "")
                title = str(resource.get("title", ""))[:60]
                has_url = isinstance(url, str) and url.startswith(
                    ("http://", "https://")
                )
                event_log.log(
                    "info",
                    "resource_audit",
                    f"[{source_name.upper()}] tag='{key}' | title='{title}' | url={'YES' if has_url else 'MISSING'}",
                    job_id=job_id,
                )
                if has_url:
                    _audit_found += 1
                else:
                    _audit_no_url.append(f"{source_name}:{key}")

        # Check which tags from the roadmap have NO resource at all
        lp = roadmap_result.get("learning_path", {})
        for phase in lp.get("phases", []):
            for tag_info in phase.get("tags", []):
                if not tag_info.get("has_resource", False):
                    _audit_missing.append(tag_info.get("tag", "?"))

        if _audit_missing:
            event_log.log(
                "warn",
                "resource_audit",
                f"Tags with NO matching resource ({len(_audit_missing)}): {_audit_missing}",
                job_id=job_id,
            )
        if _audit_no_url:
            event_log.log(
                "warn",
                "resource_audit",
                f"Resources with MISSING url ({len(_audit_no_url)}): {_audit_no_url}",
                job_id=job_id,
            )
        event_log.log(
            "info",
            "resource_audit",
            f"Audit summary: {_audit_found} resources with url, "
            f"{len(_audit_no_url)} without url, {len(_audit_missing)} tags unmatched.",
            job_id=job_id,
        )

        # Safety net: normalize resource objects so `url` is present when possible.
        # This prevents downstream clients from rendering resources without links.
        def _is_http_url(v):
            return isinstance(v, str) and v.startswith(("http://", "https://"))

        def _normalize_source_map(source_name: str, source_map: dict):
            if not isinstance(source_map, dict):
                return

            for key, resource in source_map.items():
                if resource is None:
                    continue

                if not isinstance(resource, dict):
                    # Unexpected shape — don't crash the job; just log for debugging.
                    try:
                        event_log.log(
                            "warn",
                            "job",
                            f"Resource for '{key}' in {source_name} is not an object ({type(resource).__name__}).",
                            job_id=job_id,
                        )
                    except Exception:
                        pass
                    continue

                url = resource.get("url")
                if _is_http_url(url):
                    continue

                # If dict key is actually a URL (some flows key by url)
                if _is_http_url(key):
                    resource["url"] = key
                    continue

                content_id = resource.get("contentId")
                if _is_http_url(content_id):
                    resource["url"] = content_id
                    continue

                # Best-effort YouTube reconstruction
                if (
                    source_name == "youtube"
                    and isinstance(content_id, str)
                    and content_id
                ):
                    ct = str(resource.get("contentType") or "").lower()
                    if ct == "playlist":
                        resource["url"] = (
                            f"https://www.youtube.com/playlist?list={content_id}"
                        )
                    elif ct == "video":
                        resource["url"] = (
                            f"https://www.youtube.com/watch?v={content_id}"
                        )

                # Still no url → log once per item (warn)
                if not _is_http_url(resource.get("url")):
                    try:
                        event_log.log(
                            "warn",
                            "job",
                            f"Missing url for resource '{key}' in {source_name}.",
                            job_id=job_id,
                        )
                    except Exception:
                        pass

        for _src in ("youtube", "udemy", "coursera"):
            _normalize_source_map(_src, roadmap_result.get(_src, {}))

        return {"status": "success", "data": roadmap_result}
