import asyncio
from datetime import datetime, timezone

import socketio

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=[
        "https://bosla.me",
        "https://front.bosla.almiraj.xyz",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "*",
    ],
)

job_sockets: dict[str, str] = {}
socket_jobs: dict[str, str] = {}
connected_clients: dict[str, dict] = {}

_job_ready_events: dict[str, asyncio.Event] = {}

MAX_CONCURRENT_JOBS = 3
job_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)


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
        print(f"⛔ [SOCKET] Rejected connection {sid} — no jobId in auth")
        await sio.disconnect(sid)
        return False

    job_sockets[job_id] = sid
    socket_jobs[sid] = job_id
    connected_clients[sid] = {
        "user_id": user_id,
        "job_id": job_id,
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }

    print(f"✅ [SOCKET] User {user_id} connected for job {job_id[:8]}… (sid: {sid})")

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
    print(
        f"🔌 [SOCKET] User {user_id} disconnected (job {jid[:8] if len(jid) > 8 else jid})"
    )
