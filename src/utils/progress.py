"""Live progress emitter for the roadmap pipeline.

Mirrors :data:`src.utils.event_log.event_log` but for a small, *typed* progress
signal the frontend renders as a phase rail + filling roadmap rows. Frames are
published fire-and-forget over the active inference transport's job group
(``WebPubSubTransport.publish``); a transport without ``publish`` (Socket.IO) or
any publish failure degrades silently — progress is best-effort and must never
block or break a job.

Frame contract (``data`` of a ``progress`` group message)::

    {"kind": "phase", "phase": "searching", "label": "Searching sources"}
    {"kind": "item", "tag": "React Hooks", "status": "searching"}
    {"kind": "item", "tag": "React Hooks", "status": "classifying", "candidates": 14}
    {"kind": "item", "tag": "React Hooks", "status": "found",
     "resource": {"title": "...", "url": "...", "source": "youtube", "score": 0.9}}
    {"kind": "item", "tag": "React Hooks", "status": "skipped"}
"""

from __future__ import annotations

from typing import Any, Optional

from src.transport.runtime import get_inference_transport


class Progress:
    """Typed, best-effort progress frames over the job's Web PubSub group."""

    async def phase(self, job_id: str, phase: str, label: Optional[str] = None) -> None:
        await self._emit(job_id, {"kind": "phase", "phase": phase, "label": label})

    async def item(
        self,
        job_id: str,
        tag: str,
        status: str,
        *,
        resource: Optional[dict] = None,
        candidates: Optional[int] = None,
        candidates_list: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        payload: dict[str, Any] = {"kind": "item", "tag": tag, "status": status}
        if resource is not None:
            payload["resource"] = resource
        if candidates is not None:
            payload["candidates"] = candidates
        if candidates_list is not None:
            payload["candidatesList"] = candidates_list
        await self._emit(job_id, payload)

    async def _emit(self, job_id: str, payload: dict) -> None:
        try:
            transport = get_inference_transport()
            publish = getattr(transport, "publish", None)
            if publish is None:
                return
            await publish(job_id, "progress", payload)
        except Exception:
            # Best-effort: progress never breaks a job.
            pass


progress = Progress()
