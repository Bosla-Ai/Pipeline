"""
Pipeline Event Log — in-memory structured event store with 24h auto-cleanup.

Usage:
    from src.utils.event_log import event_log

    event_log.log("info", "system", "Driver initialized")
    event_log.log("error", "fetcher", "YouTube timeout", job_id="abc123")
    logs = event_log.get_logs(level="error", limit=50)
"""

import asyncio
import uuid
from collections import deque
from datetime import datetime, timezone, timedelta

LEVELS = {"info", "warn", "error", "success"}
CATEGORIES = {"system", "socket", "job", "fetcher", "cache", "driver"}

MAX_ENTRIES = 2000
CLEANUP_INTERVAL_SECONDS = 3600  # 1 hour
LOG_TTL_HOURS = 24

# Emoji map for console output
_EMOJI = {
    "info": "🔹",
    "warn": "⚠️",
    "error": "❌",
    "success": "✅",
}


class EventLog:
    """Thread-safe (GIL-protected) in-memory event log with TTL cleanup."""

    def __init__(self, max_entries: int = MAX_ENTRIES):
        self._entries: deque[dict] = deque(maxlen=max_entries)
        self._cleanup_task: asyncio.Task | None = None
        self._broadcast_fn = None  # set by socket_server for real-time streaming

    def set_broadcast(self, fn):
        """Register an async callback to broadcast new log entries (e.g. via Socket.IO)."""
        self._broadcast_fn = fn

    # ── Logging ─────────────────────────────────────────────

    def log(
        self,
        level: str,
        category: str,
        message: str,
        *,
        job_id: str | None = None,
        details: dict | None = None,
    ) -> dict:
        """Store an event and print it to stdout."""
        level = level if level in LEVELS else "info"
        category = category if category in CATEGORIES else "system"

        entry = {
            "id": uuid.uuid4().hex[:12],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "category": category,
            "message": message,
            "job_id": job_id,
            "details": details,
        }

        self._entries.append(entry)

        # Broadcast to monitor room if socket is wired up
        if self._broadcast_fn:
            try:
                asyncio.get_event_loop().create_task(self._broadcast_fn(entry))
            except RuntimeError:
                pass  # no running loop yet (startup)

        # Also print for container logs
        emoji = _EMOJI.get(level, "·")
        tag = f"[{category.upper()}]"
        jid = f" [JOB {job_id[:8]}]" if job_id else ""
        print(f"{emoji} {tag}{jid} {message}", flush=True)

        return entry

    # ── Retrieval ───────────────────────────────────────────

    def get_logs(
        self,
        *,
        since: str | None = None,
        level: str | None = None,
        category: str | None = None,
        job_id: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Return logs filtered by optional criteria, newest first."""
        entries = list(self._entries)

        if since:
            try:
                cutoff = datetime.fromisoformat(since)
                entries = [
                    e
                    for e in entries
                    if datetime.fromisoformat(e["timestamp"]) >= cutoff
                ]
            except ValueError:
                pass

        if level and level in LEVELS:
            entries = [e for e in entries if e["level"] == level]

        if category and category in CATEGORIES:
            entries = [e for e in entries if e["category"] == category]

        if job_id:
            entries = [e for e in entries if e.get("job_id") == job_id]

        # Newest first, limited
        return list(reversed(entries))[:limit]

    @property
    def count(self) -> int:
        return len(self._entries)

    def clear(self):
        self._entries.clear()

    # ── Auto-Cleanup ────────────────────────────────────────

    def cleanup_old(self, hours: int = LOG_TTL_HOURS):
        """Remove entries older than `hours`."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        before = len(self._entries)

        # deque doesn't support in-place filtering; rebuild
        fresh = deque(
            (
                e
                for e in self._entries
                if datetime.fromisoformat(e["timestamp"]) >= cutoff
            ),
            maxlen=self._entries.maxlen,
        )
        self._entries = fresh

        removed = before - len(self._entries)
        if removed > 0:
            self.log(
                "info",
                "system",
                f"Cleaned up {removed} log entries older than {hours}h",
            )

    async def _cleanup_loop(self):
        """Background coroutine that purges old entries periodically."""
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            self.cleanup_old()

    def start_cleanup_task(self):
        """Start the background cleanup loop. Call once at app startup."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            self.log(
                "info",
                "system",
                f"Log cleanup task started (every {CLEANUP_INTERVAL_SECONDS}s, TTL {LOG_TTL_HOURS}h)",
            )


# ── Singleton ───────────────────────────────────────────────
event_log = EventLog()
