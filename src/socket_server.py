import asyncio
from datetime import datetime, timezone

import socketio
from src.utils.event_log import event_log

import os
from src.engine.runtime import runtime_limits

ALLOWED_SOCKET_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_SOCKET_ORIGINS",
        "https://bosla.me,https://front.bosla.almiraj.xyz,http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=ALLOWED_SOCKET_ORIGINS,
    logger=False,
    engineio_logger=False,
)


job_sockets: dict[str, str] = {}
socket_jobs: dict[str, str] = {}
connected_clients: dict[str, dict] = {}

_job_ready_events: dict[str, asyncio.Event] = {}

MAX_CONCURRENT_JOBS = runtime_limits.max_concurrent_jobs


def register_job_waiter(job_id: str) -> asyncio.Event:
    """Create an asyncio.Event a pipeline job can await."""
    evt = asyncio.Event()
    _job_ready_events[job_id] = evt
    return evt


def cleanup_job_waiter(job_id: str):
    _job_ready_events.pop(job_id, None)


def get_socket_for_job(job_id: str) -> str | None:
    """Return the sid mapped to a job, or None."""
    return job_sockets.get(job_id)


def get_stats() -> dict:
    """Return a snapshot of the socket registry for the /stats endpoint."""
    return {
        "active_connections": len(connected_clients),
        "active_jobs": len(job_sockets),
        "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
        "connections": [
            {
                "sid": sid,
                "user_id": meta.get("user_id"),
                "job_id": meta.get("job_id"),
                "connected_at": meta.get("connected_at"),
            }
            for sid, meta in connected_clients.items()
        ],
    }


@sio.event
async def connect(sid, environ, auth=None):
    """
    Clients MUST pass auth: { jobId, userId } when connecting.
    Connections without a jobId are rejected to prevent idle sockets.
    """
    auth = auth or {}
    job_id = auth.get("jobId") or auth.get("job_id")
    user_id = auth.get("userId") or auth.get("user_id") or "anonymous"

    if not job_id:
        event_log.log("warn", "socket", f"Rejected connection {sid} — no jobId in auth")
        await sio.disconnect(sid)
        return False

    job_sockets[job_id] = sid
    socket_jobs[sid] = job_id
    connected_clients[sid] = {
        "user_id": user_id,
        "job_id": job_id,
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }

    event_log.log(
        "success",
        "socket",
        f"User {user_id} connected for job {job_id[:8]}… (sid: {sid})",
        job_id=job_id,
    )

    evt = _job_ready_events.get(job_id)
    if evt:
        evt.set()


@sio.event
async def disconnect(sid):
    meta = connected_clients.pop(sid, {})
    job_id = socket_jobs.pop(sid, None)
    if job_id:
        job_sockets.pop(job_id, None)
        cleanup_job_waiter(job_id)

    user_id = meta.get("user_id", "?")
    jid = meta.get("job_id", "?")
    event_log.log(
        "info",
        "socket",
        f"User {user_id} disconnected (job {jid[:8] if len(jid) > 8 else jid})",
        job_id=jid if jid != "?" else None,
    )


# ── Monitor room for real-time log streaming ────────────


@sio.event
async def join_monitor(sid, data=None):
    """Admin dashboards join this room to receive real-time log events."""
    sio.enter_room(sid, "monitor")
    await sio.emit("monitor_joined", {"ok": True}, to=sid)
    event_log.log("info", "socket", f"Monitor joined by {sid}")


@sio.event
async def leave_monitor(sid, data=None):
    sio.leave_room(sid, "monitor")


async def _broadcast_log_entry(entry: dict):
    """Broadcast a new log entry to all sids in the 'monitor' room."""
    await sio.emit("new_log", entry, room="monitor")


# Wire up broadcast at import time
event_log.set_broadcast(_broadcast_log_entry)
