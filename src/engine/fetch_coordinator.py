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

            try:
                broad_tags, atomic_tags, scope_cache = await SourcePlanner.plan_tag_scopes(
                    self.sio,
                    current_sid,
                    tags,
                    job_id=job_id,
                )
            except TypeError:
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
                                            "cache_hit",
                                            job_id=job_id,
                                            metadata={
                                                "source": "udemy",
                                                "tag": tag,
                                                "language": language,
                                            }
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
                                return

                            import uuid
                            tags_to_scrape = []
                            tags_to_wait = []
                            locked_tokens = {}

                            for tag in udemy_tags_to_fetch:
                                cache_key = generate_cache_key("udemy", tag, language)
                                token = str(uuid.uuid4())
                                acquired = await cache.acquire_lock(cache_key, token, ttl=60)
                                if acquired is True:
                                    locked_tokens[tag] = token
                                    tags_to_scrape.append(tag)
                                    event_log.log(
                                        "info",
                                        "cache",
                                        "cache_miss",
                                        job_id=job_id,
                                        metadata={
                                            "source": "udemy",
                                            "tag": tag,
                                            "language": language,
                                        }
                                    )
                                elif acquired is None:
                                    # Cache unavailable/infra failure: fetch immediately, do not wait
                                    tags_to_scrape.append(tag)
                                else:
                                    # acquired is False: lock held by another worker, wait
                                    tags_to_wait.append(tag)

                            if tags_to_scrape:
                                try:
                                    udemy_data = await self._fetch_udemy_with_limit(
                                        tags=tags_to_scrape,
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
                                finally:
                                    for tag, token in locked_tokens.items():
                                        cache_key = generate_cache_key("udemy", tag, language)
                                        await cache.release_lock(cache_key, token)

                            if tags_to_wait:
                                print(f"    [Cache Stampede Protection] Waiting for Udemy locks on: {tags_to_wait}...")
                                for tag in tags_to_wait:
                                    cache_key = generate_cache_key("udemy", tag, language)
                                    resolved = False
                                    for _ in range(30):  # 15 seconds max wait
                                        await asyncio.sleep(0.5)
                                        try:
                                            cached = await cache.get(cache_key)
                                        except Exception as ce:
                                            print(f"    [Cache Wait] Error reading cached result for {tag}: {ce}")
                                            cached = None
                                        if cached is not None:
                                            print(f"    [Cache Hit via Lock] Udemy: {tag} ({language})")
                                            event_log.log(
                                                "success",
                                                "cache",
                                                "cache_hit",
                                                job_id=job_id,
                                                metadata={
                                                    "source": "udemy",
                                                    "tag": tag,
                                                    "language": language,
                                                    "stampede_protection": True,
                                                }
                                            )
                                            roadmap_result["udemy"][tag] = cached
                                            resolved = True
                                            break
                                    if not resolved:
                                        print(f"    [Cache Wait Timeout] Falling back to fetch Udemy for '{tag}' individually...")
                                        event_log.log(
                                            "info",
                                            "cache",
                                            "cache_miss_fallback",
                                            job_id=job_id,
                                            metadata={
                                                "source": "udemy",
                                                "tag": tag,
                                                "language": language,
                                                "reason": "lock_wait_timeout",
                                            }
                                        )
                                        try:
                                            udemy_data = await self._fetch_udemy_with_limit(
                                                tags=[tag],
                                                language=language,
                                                current_sid=current_sid,
                                                job_id=job_id,
                                            )
                                            roadmap_result["udemy"].update(udemy_data)
                                        except Exception as ue:
                                            event_log.log(
                                                "error",
                                                "fetcher",
                                                f"Udemy limit-fetching fallback error: {ue}",
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
        start_time = asyncio.get_running_loop().time()
        event_log.log(
            "info",
            "provider",
            "provider_fetch_started",
            job_id=job_id,
            metadata={
                "source": "youtube",
                "tags": tags,
            }
        )
        async with runtime_semaphores.youtube_provider:
            try:
                res = await asyncio.wait_for(
                    self.fetch_youtube(
                        self.sio,
                        current_sid,
                        tags,
                        language,
                        scope_cache=scope_cache,
                        job_id=job_id,
                    ),
                    timeout=runtime_limits.youtube_provider_timeout_seconds,
                )
                duration_ms = int((asyncio.get_running_loop().time() - start_time) * 1000)
                event_log.log(
                    "success",
                    "provider",
                    "provider_fetch_completed",
                    job_id=job_id,
                    metadata={
                        "source": "youtube",
                        "duration_ms": duration_ms,
                        "candidate_count": len(res) if isinstance(res, dict) else 0,
                    }
                )
                return res
            except asyncio.TimeoutError:
                duration_ms = int((asyncio.get_running_loop().time() - start_time) * 1000)
                event_log.log(
                    "error",
                    "provider",
                    "provider_fetch_timeout",
                    job_id=job_id,
                    metadata={
                        "source": "youtube",
                        "duration_ms": duration_ms,
                    }
                )
                event_log.log(
                    "error",
                    "fetcher",
                    f"[fetcher] YouTube provider timed out",
                    job_id=job_id,
                )
                return {}
            except Exception as e:
                duration_ms = int((asyncio.get_running_loop().time() - start_time) * 1000)
                event_log.log(
                    "error",
                    "provider",
                    "provider_fetch_failed",
                    job_id=job_id,
                    metadata={
                        "source": "youtube",
                        "duration_ms": duration_ms,
                        "error": str(e),
                    }
                )
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
        start_time = asyncio.get_running_loop().time()
        event_log.log(
            "info",
            "provider",
            "provider_fetch_started",
            job_id=job_id,
            metadata={
                "source": "coursera",
                "tags": tags,
            }
        )
        async with runtime_semaphores.coursera_provider:
            try:
                res = await asyncio.wait_for(
                    self.fetch_coursera(
                        self.sio,
                        current_sid,
                        tags,
                        language,
                        driver=self.get_global_driver(),
                        job_id=job_id,
                    ),
                    timeout=runtime_limits.coursera_provider_timeout_seconds,
                )
                duration_ms = int((asyncio.get_running_loop().time() - start_time) * 1000)
                event_log.log(
                    "success",
                    "provider",
                    "provider_fetch_completed",
                    job_id=job_id,
                    metadata={
                        "source": "coursera",
                        "duration_ms": duration_ms,
                        "candidate_count": len(res) if isinstance(res, dict) else 0,
                    }
                )
                return res
            except asyncio.TimeoutError:
                duration_ms = int((asyncio.get_running_loop().time() - start_time) * 1000)
                event_log.log(
                    "error",
                    "provider",
                    "provider_fetch_timeout",
                    job_id=job_id,
                    metadata={
                        "source": "coursera",
                        "duration_ms": duration_ms,
                    }
                )
                event_log.log(
                    "error",
                    "fetcher",
                    f"[fetcher] Coursera provider timed out",
                    job_id=job_id,
                )
                return {}
            except Exception as e:
                duration_ms = int((asyncio.get_running_loop().time() - start_time) * 1000)
                event_log.log(
                    "error",
                    "provider",
                    "provider_fetch_failed",
                    job_id=job_id,
                    metadata={
                        "source": "coursera",
                        "duration_ms": duration_ms,
                        "error": str(e),
                    }
                )
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
        start_time = asyncio.get_running_loop().time()
        event_log.log(
            "info",
            "provider",
            "provider_fetch_started",
            job_id=job_id,
            metadata={
                "source": "udemy",
                "tags": tags,
            }
        )
        async with runtime_semaphores.udemy_provider:
            try:
                res = await asyncio.wait_for(
                    self._fetch_udemy_impl(tags, language, current_sid, job_id),
                    timeout=runtime_limits.udemy_provider_timeout_seconds,
                )
                duration_ms = int((asyncio.get_running_loop().time() - start_time) * 1000)
                event_log.log(
                    "success",
                    "provider",
                    "provider_fetch_completed",
                    job_id=job_id,
                    metadata={
                        "source": "udemy",
                        "duration_ms": duration_ms,
                        "candidate_count": len(res) if isinstance(res, dict) else 0,
                    }
                )
                return res
            except asyncio.TimeoutError:
                duration_ms = int((asyncio.get_running_loop().time() - start_time) * 1000)
                event_log.log(
                    "error",
                    "provider",
                    "provider_fetch_timeout",
                    job_id=job_id,
                    metadata={
                        "source": "udemy",
                        "duration_ms": duration_ms,
                    }
                )
                event_log.log(
                    "error",
                    "fetcher",
                    f"[fetcher] Udemy provider timed out",
                    job_id=job_id,
                )
                return {}
            except Exception as e:
                duration_ms = int((asyncio.get_running_loop().time() - start_time) * 1000)
                event_log.log(
                    "error",
                    "provider",
                    "provider_fetch_failed",
                    job_id=job_id,
                    metadata={
                        "source": "udemy",
                        "duration_ms": duration_ms,
                        "error": str(e),
                    }
                )
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

            event_log.log(
                "success",
                "job",
                "cheap_rank_completed",
                job_id=job_id,
                metadata={
                    "source": "udemy",
                    "tag": tag,
                    "candidate_pool_size": len(pool_candidates),
                    "ranked_count": len(ranked_dicts),
                }
            )

            if not ranked_dicts:
                continue

            sid = socket_server.get_socket_for_job(job_id) or current_sid
            valid_udemy = await classify_via_frontend(self.sio, sid, tag, ranked_dicts, job_id=job_id)

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
