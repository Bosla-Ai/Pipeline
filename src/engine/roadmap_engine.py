from __future__ import annotations

import asyncio
import uuid
from typing import Any, List, Optional

from src.transport.runtime import get_inference_transport

from src.engine.fetch_coordinator import FetchCoordinator
from src.utils.learning_path import generate_learning_path
from src.utils.event_log import event_log
from src.engine.runtime import runtime_limits, runtime_semaphores
from src.engine.models import CourseSource
from src.planning.source_planner import SourcePlanner


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
    """Block until the browser client attaches for this job_id, or timeout.

    Transport-agnostic: Socket.IO waits on the in-memory job waiter, Web PubSub
    waits for the browser to join the job's group. Returns an opaque target
    (sid or group) when attached, else None.
    """
    transport = get_inference_transport()
    ready = await transport.wait_for_client(job_id, timeout)
    if not ready:
        event_log.log(
            "warn",
            "job",
            f"No frontend client connected within {timeout}s. Proceeding without AI.",
            job_id=job_id,
        )
        return None
    return transport.target_for_job(job_id)


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
        self.fetch_coordinator = FetchCoordinator(
            sio=sio,
            fetch_youtube=fetch_youtube,
            fetch_coursera=fetch_coursera,
            get_global_driver=get_global_driver,
        )

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

        existing = await job_store.get_job(job_id)
        if not existing:
            await job_store.create_job(
                job_id=job_id,
                tags=tags,
                language=language,
                prefer_paid=prefer_paid,
            )
        await job_store.start_job(job_id)
        event_log.log(
            "info",
            "job",
            "job_started",
            job_id=job_id,
            metadata={
                "tags": tags,
                "prefer_paid": prefer_paid,
                "language": language,
            },
        )

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
            event_log.log(
                "success",
                "job",
                "job_completed",
                job_id=job_id,
                metadata={
                    "status": "success",
                },
            )
            return result
        except Exception as e:
            await job_store.fail_job(job_id, str(e))
            event_log.log(
                "error",
                "job",
                "job_failed",
                job_id=job_id,
                metadata={
                    "error": str(e),
                },
            )
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

        from src.config import runtime_profile

        if runtime_profile.FREE_HF_MODE:
            active_sources = [CourseSource.YOUTUBE]
        else:
            active_sources = SourcePlanner.plan_sources(sources, prefer_paid)

        event_log.log("info", "job", f"Active Sources: {active_sources}", job_id=job_id)

        roadmap_result = await self.fetch_coordinator.fetch_resources(
            tags=tags,
            language=language,
            active_sources=active_sources,
            current_sid=current_sid,
            job_id=job_id,
        )

        event_log.log(
            "info", "job", "Generating Learning DNA Sequence...", job_id=job_id
        )
        learning_path = generate_learning_path(
            tags, roadmap_data=roadmap_result, tag_checkpoints=tag_checkpoints
        )
        roadmap_result["learning_path"] = learning_path

        event_log.log(
            "success",
            "job",
            "final_rank_completed",
            job_id=job_id,
            metadata={
                "tag_count": len(tags),
                "phase_count": (
                    len(learning_path.get("phases", []))
                    if isinstance(learning_path, dict)
                    else 0
                ),
            },
        )

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
