from __future__ import annotations

import asyncio

import src.socket_server as socket_server
from src.engine.models import CourseSource
from src.engine.runtime import runtime_limits, runtime_semaphores
from src.fetchers.videos.udemy_fetcher import UdemyFetcher
from src.utils.cache import cache, generate_cache_key
from src.utils.event_log import event_log
from src.planning.source_planner import SourcePlanner
from src.utils.helpers import classify_via_frontend


class FetchCoordinator:
    def __init__(
        self,
        *,
        sio,
        fetch_youtube,
        fetch_coursera,
        get_global_driver,
    ):
        self.sio = sio
        self.fetch_youtube = fetch_youtube
        self.fetch_coursera = fetch_coursera
        self.get_global_driver = get_global_driver

    async def fetch_resources(
        self,
        *,
        tags: list[str],
        language: str,
        active_sources: list[CourseSource],
        current_sid: str | None,
        job_id: str,
    ) -> dict:
        roadmap_result = {"youtube": {}, "coursera": {}, "udemy": {}}

        if CourseSource.YOUTUBE in active_sources:
            try:
                event_log.log(
                    "info",
                    "fetcher",
                    f"Fetching Free Content (YouTube)... Lang: {language}",
                    job_id=job_id,
                )
                youtube_data = await self._fetch_youtube_with_limit(
                    tags=tags,
                    language=language,
                    current_sid=current_sid,
                    job_id=job_id,
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

            # Refresh sid in case the socket reconnected
            current_sid = socket_server.get_socket_for_job(job_id) or current_sid

            broad_tags, atomic_tags, scope_cache = await SourcePlanner.plan_tag_scopes(
                self.sio, current_sid, tags
            )

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

                    async def fetch_coursera_task():
                        try:
                            coursera_data = await self._fetch_coursera_with_limit(
                                tags=broad_tags,
                                language=language,
                                current_sid=current_sid,
                                job_id=job_id,
                            )
                            roadmap_result["coursera"].update(coursera_data)
                        except Exception as e:
                            event_log.log(
                                "error",
                                "fetcher",
                                f"Coursera task unexpected failure: {e}",
                                job_id=job_id,
                            )

                    fetch_tasks.append(fetch_coursera_task())

                if CourseSource.UDEMY in active_sources:

                    async def fetch_udemy_task():
                        try:
                            udemy_cached = {}
                            udemy_tags_to_fetch = []
                            try:
                                await cache.connect()
                                for tag in broad_tags:
                                    cache_key = generate_cache_key(
                                        "udemy", tag, language
                                    )
                                    try:
                                        cached_result = await cache.get(cache_key)
                                    except Exception as ce:
                                        event_log.log(
                                            "error",
                                            "fetcher",
                                            f"Udemy Cache Get Error for tag '{tag}': {ce}",
                                            job_id=job_id,
                                        )
                                        cached_result = None

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
                            except Exception as ce:
                                event_log.log(
                                    "error",
                                    "fetcher",
                                    f"Udemy Cache Connect/Lookup Error: {ce}",
                                    job_id=job_id,
                                )
                                udemy_tags_to_fetch = list(broad_tags)

                            roadmap_result["udemy"].update(udemy_cached)

                            if not udemy_tags_to_fetch:
                                event_log.log(
                                    "success",
                                    "cache",
                                    "Udemy: All tags cached",
                                    job_id=job_id,
                                )
                            else:
                                try:
                                    udemy_data = await self._fetch_udemy_with_limit(
                                        tags=udemy_tags_to_fetch,
                                        language=language,
                                        current_sid=current_sid,
                                        job_id=job_id,
                                    )
                                    roadmap_result["udemy"].update(udemy_data)
                                except Exception as ue:
                                    event_log.log(
                                        "error",
                                        "fetcher",
                                        f"Udemy limit-fetching unexpected error: {ue}",
                                        job_id=job_id,
                                    )
                        except Exception as e:
                            event_log.log(
                                "error",
                                "fetcher",
                                f"Udemy task overall unexpected failure: {e}",
                                job_id=job_id,
                            )

                    fetch_tasks.append(fetch_udemy_task())

                if fetch_tasks:
                    results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                    for res_item in results:
                        if isinstance(res_item, Exception):
                            event_log.log(
                                "error",
                                "fetcher",
                                f"Provider task failed with exception: {res_item}",
                                job_id=job_id,
                            )

            if atomic_tags:
                # Always fall back to YouTube for atomic tags
                try:
                    event_log.log(
                        "info",
                        "fetcher",
                        f"Fetching YouTube for atomic tags: {atomic_tags}",
                        job_id=job_id,
                    )
                    sid = socket_server.get_socket_for_job(job_id) or current_sid
                    youtube_data = await self._fetch_youtube_with_limit(
                        tags=atomic_tags,
                        language=language,
                        current_sid=sid,
                        job_id=job_id,
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

            # Fallback: if paid sources returned nothing for broad tags, use YouTube
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
                        youtube_fallback = await self._fetch_youtube_with_limit(
                            tags=unmatched_broad,
                            language=language,
                            current_sid=sid,
                            job_id=job_id,
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

        return roadmap_result

    async def _fetch_youtube_with_limit(
        self,
        tags: list[str],
        language: str,
        current_sid: str | None,
        job_id: str,
        scope_cache: dict[str, str] | None = None,
    ) -> dict:
        if not tags:
            return {}
        async with runtime_semaphores.youtube_provider:
            try:
                return await asyncio.wait_for(
                    self.fetch_youtube(
                        self.sio,
                        current_sid,
                        tags,
                        language,
                        scope_cache=scope_cache,
                    ),
                    timeout=runtime_limits.youtube_provider_timeout_seconds,
                )
            except asyncio.TimeoutError:
                event_log.log(
                    "error",
                    "fetcher",
                    f"[fetcher] YouTube provider timed out",
                    job_id=job_id,
                )
                return {}
            except Exception as e:
                event_log.log(
                    "error",
                    "fetcher",
                    f"YouTube Error: {e}",
                    job_id=job_id,
                )
                return {}

    async def _fetch_coursera_with_limit(
        self,
        tags: list[str],
        language: str,
        current_sid: str | None,
        job_id: str,
    ) -> dict:
        if not tags:
            return {}
        async with runtime_semaphores.coursera_provider:
            try:
                return await asyncio.wait_for(
                    self.fetch_coursera(
                        self.sio,
                        current_sid,
                        tags,
                        language,
                        driver=self.get_global_driver(),
                    ),
                    timeout=runtime_limits.coursera_provider_timeout_seconds,
                )
            except asyncio.TimeoutError:
                event_log.log(
                    "error",
                    "fetcher",
                    f"[fetcher] Coursera provider timed out",
                    job_id=job_id,
                )
                return {}
            except Exception as e:
                event_log.log(
                    "error",
                    "fetcher",
                    f"Coursera Error: {e}",
                    job_id=job_id,
                )
                return {}

    async def _fetch_udemy_with_limit(
        self,
        tags: list[str],
        language: str,
        current_sid: str | None,
        job_id: str,
    ) -> dict:
        if not tags:
            return {}
        async with runtime_semaphores.udemy_provider:
            try:
                return await asyncio.wait_for(
                    self._fetch_udemy_impl(tags, language, current_sid, job_id),
                    timeout=runtime_limits.udemy_provider_timeout_seconds,
                )
            except asyncio.TimeoutError:
                event_log.log(
                    "error",
                    "fetcher",
                    f"[fetcher] Udemy provider timed out",
                    job_id=job_id,
                )
                return {}
            except Exception as e:
                event_log.log(
                    "error",
                    "fetcher",
                    f"Udemy Error: {e}",
                    job_id=job_id,
                )
                return {}

    async def _fetch_udemy_impl(
        self,
        tags: list[str],
        language: str,
        current_sid: str | None,
        job_id: str,
    ) -> dict:
        udemy_fetcher = UdemyFetcher(
            tags=tags,
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
        result_map = {}

        from src.engine.models import Candidate, SourceName
        from src.engine.runtime import runtime_limits
        from src.ranking.dedupe import dedupe_candidates
        from src.ranking.cheap_ranker import cheap_rank

        for tag, candidates in udemy_results_map.items():
            if not candidates:
                continue

            pool_candidates = candidates[: runtime_limits.candidate_pool_limit_per_tag]
            candidate_objs = [
                Candidate.from_dict(c, SourceName.UDEMY, tag) for c in pool_candidates
            ]

            deduped_objs = dedupe_candidates(candidate_objs)
            ranked_objs = cheap_rank(deduped_objs, tag)[
                : runtime_limits.cheap_rank_limit_per_tag
            ]

            ranked_dicts = [c.to_dict() for c in ranked_objs]

            if not ranked_dicts:
                continue

            sid = socket_server.get_socket_for_job(job_id) or current_sid
            valid_udemy = await classify_via_frontend(self.sio, sid, tag, ranked_dicts)

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
                result_map[tag] = winner
                cache_key = generate_cache_key("udemy", tag, language)
                try:
                    await cache.connect()
                    await cache.set(cache_key, winner)
                except Exception as ce:
                    event_log.log(
                        "error",
                        "cache",
                        f"Udemy Cache Set Error for tag '{tag}': {ce}",
                        job_id=job_id,
                    )
                event_log.log(
                    "success",
                    "fetcher",
                    f"Udemy Winner: {winner['title'][:50]}...",
                    job_id=job_id,
                )
        return result_map
