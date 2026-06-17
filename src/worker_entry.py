"""On-demand ACI worker entry point.

Runs a single roadmap job to completion and exits — the serverless replacement
for the long-lived uvicorn + Socket.IO server. The browser inference loop is
carried over Azure Web PubSub (see :mod:`src.transport.inference_transport`),
and the final roadmap is written to a job sink (Cosmos in prod) that the .NET
backend point-reads.

Activated by ``start.sh`` when ``LIGHT_MODE=true``::

    exec python -m src.worker_entry

Environment:
    JOB_ID                        required
    TAGS                          required, JSON array of strings
    LANGUAGE                      default "en"
    PREFER_PAID                   "true"/"false", default false
    SOURCES                       optional JSON array, e.g. ["youtube"]
    TAG_CHECKPOINTS               optional JSON object
    WEBPUBSUB_CLIENT_ACCESS_URL   required for the live inference loop
    CLIENT_WAIT_TIMEOUT           seconds to wait for the browser, default 30
    COSMOS_ENDPOINT / COSMOS_KEY  enable the Cosmos job sink (else stdout)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, Callable, Optional

from src.worker.job_sink import JobSink, build_job_sink_from_env

log = logging.getLogger("worker_entry")


def _configure_logging() -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


def _parse_sources(raw: Optional[str]):
    if not raw:
        return None
    from src.engine.models import CourseSource

    try:
        values = json.loads(raw)
        sources = []
        for v in values:
            try:
                sources.append(CourseSource(str(v).lower()))
            except ValueError:
                log.warning("Ignoring unknown source: %s", v)
        return sources or None
    except (ValueError, TypeError):
        log.warning("Could not parse SOURCES=%r; defaulting to None", raw)
        return None


def _parse_env() -> dict:
    job_id = os.getenv("JOB_ID")
    if not job_id:
        raise SystemExit("JOB_ID is required")

    tags_raw = os.getenv("TAGS")
    if not tags_raw:
        raise SystemExit("TAGS (JSON array) is required")
    try:
        tags = [str(t) for t in json.loads(tags_raw)]
    except (ValueError, TypeError) as exc:
        raise SystemExit(f"TAGS must be a JSON array: {exc}")

    tag_checkpoints = None
    if os.getenv("TAG_CHECKPOINTS"):
        try:
            tag_checkpoints = json.loads(os.environ["TAG_CHECKPOINTS"])
        except (ValueError, TypeError):
            log.warning("Could not parse TAG_CHECKPOINTS; ignoring")

    return {
        "job_id": job_id,
        "tags": tags,
        "language": os.getenv("LANGUAGE", "en"),
        "prefer_paid": os.getenv("PREFER_PAID", "false").lower() == "true",
        "sources": _parse_sources(os.getenv("SOURCES")),
        "tag_checkpoints": tag_checkpoints,
        "client_wait_timeout": float(os.getenv("CLIENT_WAIT_TIMEOUT", "30")),
        "webpubsub_url": os.getenv("WEBPUBSUB_CLIENT_ACCESS_URL"),
    }


def _default_engine_factory(client_wait_timeout: float):
    # Imported lazily — keeps the module importable for unit tests without the
    # full fetcher/engine dependency chain.
    from src.api import fetch_youtube, fetch_coursera
    from src.socket_server import sio
    from src.engine.roadmap_engine import RoadmapEngine

    return RoadmapEngine(
        sio=sio,
        fetch_youtube=fetch_youtube,
        fetch_coursera=fetch_coursera,
        get_global_driver=lambda: None,
        socket_wait_timeout=client_wait_timeout,
    )


async def run_worker(
    *,
    job_id: str,
    tags: list[str],
    language: str,
    prefer_paid: bool,
    sources: Any,
    tag_checkpoints: Any,
    transport: Any,
    sink: JobSink,
    log_sink: Optional[Any] = None,
    client_wait_timeout: float = 30.0,
    engine_factory: Optional[Callable[[float], Any]] = None,
) -> int:
    """Execute one roadmap job. Returns the process exit code (0 ok, 1 failed)."""
    from src.transport.runtime import set_inference_transport
    from src.utils.event_log import event_log

    # Route the inference loop over the injected (Web PubSub) transport.
    set_inference_transport(transport)

    # Every pipeline log is fanned out two ways from the worker:
    #   • transport.publish(...)  → the job's Web PubSub group (live to the browser)
    #   • log_sink.record(...)    → a TTL'd Cosmos doc the .NET admin API serves,
    #     so the dashboard's Pipeline Monitor shows this ephemeral worker's logs
    #     alongside the existing pipeline logs. Both are best-effort.
    async def _broadcast(entry: dict) -> None:
        if log_sink is not None:
            try:
                log_sink.record(entry)
            except Exception:
                pass
        try:
            await transport.publish(entry.get("job_id") or job_id, "log", entry)
        except Exception:
            pass

    event_log.set_broadcast(_broadcast)

    await sink.set_running(job_id, tags, language)
    log.info("Job %s started (tags=%s, lang=%s)", job_id, tags, language)

    try:
        engine = (engine_factory or _default_engine_factory)(client_wait_timeout)
        # The engine waits for the browser to join the group (via wait_for_socket
        # → transport.wait_for_client) before issuing inference requests.
        result = await engine.generate(
            tags=tags,
            prefer_paid=prefer_paid,
            language=language,
            sources=sources,
            tag_checkpoints=tag_checkpoints,
            job_id=job_id,
        )
        await sink.complete(job_id, result)
        await _safe_publish(transport, job_id, "job_done", {"status": "completed"})
        log.info("Job %s completed", job_id)
        return 0
    except Exception as exc:  # noqa: BLE001 - worker must report, then exit
        message = str(exc) or repr(exc)
        log.exception("Job %s failed: %s", job_id, message)
        await sink.fail(job_id, message)
        await _safe_publish(
            transport, job_id, "job_done", {"status": "failed", "error": message}
        )
        return 1
    finally:
        # Flush the buffered logs to Cosmos before the loop closes, otherwise the
        # tail of this job's logs never lands in the store the dashboard reads.
        if log_sink is not None:
            try:
                await log_sink.flush()
            except Exception:
                pass
        await _safe_aclose(log_sink)
        await _safe_aclose(sink)
        await _safe_aclose(transport)


async def _safe_publish(transport: Any, job_id: str, event: str, data: Any) -> None:
    publish = getattr(transport, "publish", None)
    if publish is None:
        return
    try:
        await publish(job_id, event, data)
    except Exception:
        pass


async def _safe_aclose(obj: Any) -> None:
    aclose = getattr(obj, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception:
        pass


def main() -> None:
    _configure_logging()
    env = _parse_env()

    if not env["webpubsub_url"]:
        raise SystemExit("WEBPUBSUB_CLIENT_ACCESS_URL is required for the worker")

    from src.transport.inference_transport import WebPubSubTransport
    from src.worker.log_sink import build_log_sink_from_env

    transport = WebPubSubTransport(client_access_url=env["webpubsub_url"])
    sink = build_job_sink_from_env()
    log_sink = build_log_sink_from_env(env["job_id"])

    code = asyncio.run(
        run_worker(
            job_id=env["job_id"],
            tags=env["tags"],
            language=env["language"],
            prefer_paid=env["prefer_paid"],
            sources=env["sources"],
            tag_checkpoints=env["tag_checkpoints"],
            log_sink=log_sink,
            transport=transport,
            sink=sink,
            client_wait_timeout=env["client_wait_timeout"],
        )
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
