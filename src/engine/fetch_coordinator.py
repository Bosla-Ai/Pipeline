from __future__ import annotations

import asyncio

from src.transport.runtime import get_inference_transport
from src.engine.models import CourseSource
from src.engine.runtime import runtime_limits, runtime_semaphores
from src.fetchers.videos.udemy_fetcher import UdemyFetcher
from src.utils.cache import cache, generate_cache_key
from src.utils.event_log import event_log
from src.utils.progress import progress
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
            current_sid = get_inference_transport().target_for_job(job_id) or current_sid

            try:
                broad_tags, atomic_tags, scope_cache = (
                    await SourcePlanner.plan_tag_scopes(
                        self.sio,
                        current_sid,
                        tags,
                        job_id=job_id,
                    )
                )
            except TypeError:
                broad_tags, atomic_tags, scope_cache = (
                    await SourcePlanner.plan_tag_scopes(self.sio, current_sid, tags)
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
                                            },
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
                                acquired = await cache.acquire_lock(
                                    cache_key, token, ttl=60
                                )
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
                                        },
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
                                        cache_key = generate_cache_key(
                                            "udemy", tag, language
                                        )
                                        await cache.release_lock(cache_key, token)

                            if tags_to_wait:
                                print(
                                    f"    [Cache Stampede Protection] Waiting for Udemy locks on: {tags_to_wait}..."
                                )
                                for tag in tags_to_wait:
                                    cache_key = generate_cache_key(
                                        "udemy", tag, language
                                    )
                                    resolved = False
                                    for _ in range(30):  # 15 seconds max wait
                                        await asyncio.sleep(0.5)
                                        try:
                                            cached = await cache.get(cache_key)
                                        except Exception as ce:
                                            print(
                                                f"    [Cache Wait] Error reading cached result for {tag}: {ce}"
                                            )
                                            cached = None
                                        if cached is not None:
                                            print(
                                                f"    [Cache Hit via Lock] Udemy: {tag} ({language})"
                                            )
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
                                                },
                                            )
                                            roadmap_result["udemy"][tag] = cached
                                            resolved = True
                                            break
                                    if not resolved:
                                        print(
                                            f"    [Cache Wait Timeout] Falling back to fetch Udemy for '{tag}' individually..."
                                        )
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
                                            },
                                        )
                                        try:
                                            udemy_data = (
                                                await self._fetch_udemy_with_limit(
                                                    tags=[tag],
                                                    language=language,
                                                    current_sid=current_sid,
                                                    job_id=job_id,
                                                )
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
                    sid = get_inference_transport().target_for_job(job_id) or current_sid
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
                        sid = get_inference_transport().target_for_job(job_id) or current_sid
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

    async def _fetch_youtube_ytdlp_pipeline(
        self,
        tags: list[str],
        language: str,
        current_sid: str | None,
        job_id: str,
    ) -> dict:
        """
        Runs the explicit v2 pipeline for YouTube candidates:
        Plan -> Fetch -> Normalize -> Dedupe -> Rank -> Finalize.
        """
        from src.engine.stages import (
            PreparedTag,
            PlannedSource,
            PlannedQuery,
            CandidateBatch,
            RankedBatch,
        )
        from src.engine.models import TopicScope, SourceName, Candidate
        from src.planning.source_planner import SourcePlanner
        from src.planning.query_planner import QueryPlanner
        from src.providers.ytdlp_provider import YtDlpProvider
        from src.providers.youtube_legacy_adapter import normalize_youtube_candidate
        from src.ranking.dedupe import dedupe_candidates
        from src.ranking.cheap_ranker import cheap_rank_candidate
        from src.ranking.final_ranker import final_rank
        from src.inference.edge_client import EdgeInferenceClient
        from src.inference.schemas import ClassificationRequest
        from src.config.settings import (
            YT_DLP_MAX_RESULTS,
            YT_DLP_QUERY_LIMIT_PER_TAG,
            YT_DLP_HARD_TIMEOUT_SECONDS,
        )
        from src.config import runtime_profile

        provider = YtDlpProvider()
        selected_by_tag = {}

        try:
            broad_tags, atomic_tags, scope_cache = await SourcePlanner.plan_tag_scopes(
                self.sio, current_sid, tags, job_id=job_id
            )
        except TypeError:
            broad_tags, atomic_tags, scope_cache = await SourcePlanner.plan_tag_scopes(
                self.sio, current_sid, tags
            )

        for tag_str in tags:
            await progress.item(job_id, tag_str, "searching")
            raw_scope_str = scope_cache.get(tag_str, "unknown")
            scope_val = raw_scope_str.lower().strip()
            if "broad" in scope_val:
                scope = TopicScope.TECHNOLOGY
            elif "atomic" in scope_val:
                scope = TopicScope.ATOMIC
            elif "debugging" in scope_val or "fix" in scope_val or "error" in scope_val:
                scope = TopicScope.DEBUGGING_QUERY
            elif (
                "comparison" in scope_val or "versus" in scope_val or "vs" in scope_val
            ):
                scope = TopicScope.COMPARISON_QUERY
            elif "project" in scope_val:
                scope = TopicScope.PROJECT_GOAL
            else:
                scope = TopicScope.UNKNOWN

            prep_tag = PreparedTag(
                original=tag_str,
                normalized=QueryPlanner.normalize_search_tag(tag_str),
                language=language,
                scope=scope,
            )

            planned_sources = SourcePlanner.plan_sources_for_scope(
                tag=prep_tag,
                prefer_paid=False,
                requested_sources=[CourseSource.YOUTUBE],
                free_hf_mode=runtime_profile.FREE_HF_MODE,
            )

            planned_queries = QueryPlanner.plan_queries_for_tag(
                tag=prep_tag,
                planned_sources=planned_sources,
                max_results=YT_DLP_MAX_RESULTS,
                query_limit_per_tag=YT_DLP_QUERY_LIMIT_PER_TAG,
            )

            candidates_pool = []
            for pq in planned_queries:
                cands = await provider.fetch(pq)
                for c in cands:
                    raw_dict = c.to_dict() if hasattr(c, "to_dict") else c
                    candidate_obj = normalize_youtube_candidate(raw_dict, tag_str)
                    if candidate_obj:
                        candidates_pool.append(candidate_obj)

            deduped_candidates = dedupe_candidates(candidates_pool)

            if not deduped_candidates:
                await progress.item(job_id, tag_str, "skipped")
                # Omit the tag entirely rather than inserting an empty {}.
                # An empty placeholder looks like a YouTube resource downstream
                # (passes the `is None` guard in the resource audit) but carries
                # no URL, so it gets logged as url=MISSING and renders as a
                # course with a dead/absent link. No candidates == no link.
                event_log.log(
                    "warn",
                    "fetcher",
                    f"No YouTube candidates for '{tag_str}' — omitting from roadmap.",
                    job_id=job_id,
                    details={"source": "youtube", "tag": tag_str},
                )
                continue

            cheap_scores = {}
            for c in deduped_candidates:
                cheap_scores[c.url] = cheap_rank_candidate(
                    c, tag_str, scope=prep_tag.scope
                )

            ai_results = []
            active_sid = get_inference_transport().target_for_job(job_id) or current_sid
            if active_sid:
                await progress.phase(job_id, "classifying", label="Classifying resources")
                candidates_list = []
                for c in deduped_candidates[:5]:
                    c_dict = {}
                    if hasattr(c, "to_dict"):
                        try:
                            c_dict = c.to_dict()
                        except Exception:
                            pass
                    title = c_dict.get("title") or getattr(c, "title", "Candidate")
                    url = c_dict.get("url") or getattr(c, "url", "")
                    candidates_list.append({
                        "title": title,
                        "score": cheap_scores.get(url, 0.0) if url else 0.0,
                        "status": "analyzing",
                    })
                await progress.item(
                    job_id,
                    tag_str,
                    "classifying",
                    candidates=len(deduped_candidates),
                    candidates_list=candidates_list,
                )
                try:
                    req = ClassificationRequest(
                        job_id=job_id,
                        tag=tag_str,
                        candidates=deduped_candidates,
                        labels=["relevant", "irrelevant"],
                    )
                    ai_results = await EdgeInferenceClient.classify(req, timeout=3.0)
                except Exception as ex:
                    event_log.log(
                        "warn",
                        "inference",
                        f"Edge classification failed: {ex}",
                        job_id=job_id,
                    )

            final_ranked = final_rank(
                candidates=deduped_candidates,
                tag=prep_tag,
                cheap_scores=cheap_scores,
                ai_results=ai_results,
            )

            winner = final_ranked[0] if final_ranked else None
            if winner:
                winner_dict = winner.to_dict() if hasattr(winner, "to_dict") else {}
                selected_by_tag[tag_str] = winner_dict
                candidates_list = []
                for idx, c in enumerate(final_ranked[:5]):
                    c_dict = {}
                    if hasattr(c, "to_dict"):
                        try:
                            c_dict = c.to_dict()
                        except Exception:
                            pass
                    title = c_dict.get("title") or getattr(c, "title", "Candidate")
                    score = c_dict.get("score") or getattr(c, "raw_score", 0.0)
                    candidates_list.append({
                        "title": title,
                        "score": score,
                        "status": "winner" if idx == 0 else "rejected",
                    })
                await progress.item(
                    job_id,
                    tag_str,
                    "found",
                    resource={
                        "title": winner_dict.get("title") or getattr(winner, "title", "Candidate"),
                        "url": winner_dict.get("url") or getattr(winner, "url", ""),
                        "source": "youtube",
                        "score": winner_dict.get("score") or getattr(winner, "raw_score", 0.0),
                    },
                    candidates_list=candidates_list,
                )
            else:
                await progress.item(job_id, tag_str, "skipped")
                # No winner survived ranking — omit the tag instead of writing
                # an empty {} placeholder (see note above). The course still
                # appears in the roadmap via the tag list, just without a link.
                event_log.log(
                    "warn",
                    "fetcher",
                    f"No YouTube winner after ranking for '{tag_str}' — omitting from roadmap.",
                    job_id=job_id,
                    details={"source": "youtube", "tag": tag_str},
                )

        return selected_by_tag

    async def _fetch_youtube_with_limit(
        self,
        tags: list[str],
        language: str,
        current_sid: str | None,
        job_id: str,
        scope_cache: dict[str, str] | None = None,
    ) -> dict:
        from src.config import runtime_profile

        if (
            runtime_profile.FREE_HF_MODE
            or runtime_profile.YOUTUBE_FETCH_MODE == "yt_dlp"
        ):
            return await self._fetch_youtube_ytdlp_pipeline(
                tags=tags,
                language=language,
                current_sid=current_sid,
                job_id=job_id,
            )

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
            },
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
                duration_ms = int(
                    (asyncio.get_running_loop().time() - start_time) * 1000
                )
                event_log.log(
                    "success",
                    "provider",
                    "provider_fetch_completed",
                    job_id=job_id,
                    metadata={
                        "source": "youtube",
                        "duration_ms": duration_ms,
                        "candidate_count": len(res) if isinstance(res, dict) else 0,
                    },
                )
                return res
            except asyncio.TimeoutError:
                duration_ms = int(
                    (asyncio.get_running_loop().time() - start_time) * 1000
                )
                event_log.log(
                    "error",
                    "provider",
                    "provider_fetch_timeout",
                    job_id=job_id,
                    metadata={
                        "source": "youtube",
                        "duration_ms": duration_ms,
                    },
                )
                event_log.log(
                    "error",
                    "fetcher",
                    f"[fetcher] YouTube provider timed out",
                    job_id=job_id,
                )
                return {}
            except Exception as e:
                duration_ms = int(
                    (asyncio.get_running_loop().time() - start_time) * 1000
                )
                event_log.log(
                    "error",
                    "provider",
                    "provider_fetch_failed",
                    job_id=job_id,
                    metadata={
                        "source": "youtube",
                        "duration_ms": duration_ms,
                        "error": str(e),
                    },
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
            },
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
                duration_ms = int(
                    (asyncio.get_running_loop().time() - start_time) * 1000
                )
                event_log.log(
                    "success",
                    "provider",
                    "provider_fetch_completed",
                    job_id=job_id,
                    metadata={
                        "source": "coursera",
                        "duration_ms": duration_ms,
                        "candidate_count": len(res) if isinstance(res, dict) else 0,
                    },
                )
                return res
            except asyncio.TimeoutError:
                duration_ms = int(
                    (asyncio.get_running_loop().time() - start_time) * 1000
                )
                event_log.log(
                    "error",
                    "provider",
                    "provider_fetch_timeout",
                    job_id=job_id,
                    metadata={
                        "source": "coursera",
                        "duration_ms": duration_ms,
                    },
                )
                event_log.log(
                    "error",
                    "fetcher",
                    f"[fetcher] Coursera provider timed out",
                    job_id=job_id,
                )
                return {}
            except Exception as e:
                duration_ms = int(
                    (asyncio.get_running_loop().time() - start_time) * 1000
                )
                event_log.log(
                    "error",
                    "provider",
                    "provider_fetch_failed",
                    job_id=job_id,
                    metadata={
                        "source": "coursera",
                        "duration_ms": duration_ms,
                        "error": str(e),
                    },
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
            },
        )
        async with runtime_semaphores.udemy_provider:
            try:
                res = await asyncio.wait_for(
                    self._fetch_udemy_impl(tags, language, current_sid, job_id),
                    timeout=runtime_limits.udemy_provider_timeout_seconds,
                )
                duration_ms = int(
                    (asyncio.get_running_loop().time() - start_time) * 1000
                )
                event_log.log(
                    "success",
                    "provider",
                    "provider_fetch_completed",
                    job_id=job_id,
                    metadata={
                        "source": "udemy",
                        "duration_ms": duration_ms,
                        "candidate_count": len(res) if isinstance(res, dict) else 0,
                    },
                )
                return res
            except asyncio.TimeoutError:
                duration_ms = int(
                    (asyncio.get_running_loop().time() - start_time) * 1000
                )
                event_log.log(
                    "error",
                    "provider",
                    "provider_fetch_timeout",
                    job_id=job_id,
                    metadata={
                        "source": "udemy",
                        "duration_ms": duration_ms,
                    },
                )
                event_log.log(
                    "error",
                    "fetcher",
                    f"[fetcher] Udemy provider timed out",
                    job_id=job_id,
                )
                return {}
            except Exception as e:
                duration_ms = int(
                    (asyncio.get_running_loop().time() - start_time) * 1000
                )
                event_log.log(
                    "error",
                    "provider",
                    "provider_fetch_failed",
                    job_id=job_id,
                    metadata={
                        "source": "udemy",
                        "duration_ms": duration_ms,
                        "error": str(e),
                    },
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
                },
            )

            if not ranked_dicts:
                continue

            sid = get_inference_transport().target_for_job(job_id) or current_sid
            valid_udemy = await classify_via_frontend(
                self.sio, sid, tag, ranked_dicts, job_id=job_id
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
