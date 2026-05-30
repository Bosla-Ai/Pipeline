"""
Pipeline Event Log — in-memory structured event store with 24h auto-cleanup.
Optionally persists logs to Redis if available.

Usage:
    from src.utils.event_log import event_log

    event_log.log("info", "system", "Driver initialized")
    event_log.log("error", "fetcher", "YouTube timeout", job_id="abc123")
    logs = await event_log.get_logs(level="error", limit=50)
"""

import asyncio
import os
import json
import uuid
from collections import deque
from datetime import datetime, timezone, timedelta
import redis.asyncio as redis

LEVELS = {"info", "warn", "error", "success"}
CATEGORIES = {
    "system",
    "socket",
    "job",
    "fetcher",
    "cache",
    "driver",
    "video_search",
    "playlist_proxy",
    "resource_audit",
    "provider",
}

MAX_ENTRIES = 2000
CLEANUP_INTERVAL_SECONDS = 3600  # 1 hour
LOG_TTL_HOURS = 24

from src.engine.runtime import REDIS_HOST, REDIS_PORT

# Level prefixes for console output
_LEVEL_PREFIX = {
    "info": "INFO",
    "warn": "WARN",
    "error": "ERROR",
    "success": "SUCCESS",
}


class EventLog:
    """Thread-safe (GIL-protected) in-memory event log with TTL cleanup, optionally Redis-backed."""

    def __init__(self, max_entries: int = MAX_ENTRIES):
        self._entries: deque[dict] = deque(maxlen=max_entries)
        self._cleanup_task: asyncio.Task | None = None
        self._broadcast_fn = None  # set by socket_server for real-time streaming
        self._redis_client: redis.Redis | None = None
        self._use_redis: bool = False

    async def connect(self):
        """Initialize Redis connection for event logs."""
        if self._redis_client is None:
            try:
                self._redis_client = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    decode_responses=True,
                )
                await self._redis_client.ping()
                self._use_redis = True
                print(f"[EventLog] Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
            except Exception as e:
                print(
                    f"[EventLog] Redis unavailable: {e}. Falling back to in-memory logs."
                )
                self._redis_client = None
                self._use_redis = False

    def set_broadcast(self, fn):
        """Register an async callback to broadcast new log entries (e.g. via Socket.IO)."""
        self._broadcast_fn = fn

    def _sanitize_dict(self, data: dict) -> dict:
        if not isinstance(data, dict):
            return data
        sanitized = {}
        sensitive_keys = {
            "token",
            "sockettoken",
            "socket_token",
            "job_access_token",
            "authorization",
            "x_pipeline_secret",
            "secret",
            "api_key",
            "password",
        }
        for k, v in data.items():
            k_lower = k.lower()
            if any(sk in k_lower for sk in sensitive_keys):
                sanitized[k] = "[MASKED]"
            elif isinstance(v, dict):
                sanitized[k] = self._sanitize_dict(v)
            elif isinstance(v, list):
                sanitized[k] = [
                    self._sanitize_dict(item) if isinstance(item, dict) else item
                    for item in v
                ]
            else:
                sanitized[k] = v
        return sanitized

    # ── Logging ─────────────────────────────────────────────

    def log(
        self,
        level: str,
        category: str,
        message: str,
        *,
        job_id: str | None = None,
        details: dict | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Store an event and print it to stdout."""
        level = level if level in LEVELS else "info"
        category = category if category in CATEGORIES else "system"

        # Mask global pipeline secret in the message text if present
        try:
            from src.config.settings import PIPELINE_SHARED_SECRET

            if PIPELINE_SHARED_SECRET and isinstance(message, str):
                message = message.replace(PIPELINE_SHARED_SECRET, "[MASKED]")
        except Exception:
            pass

        merged_details = {}
        if details:
            merged_details.update(details)
        if metadata:
            merged_details.update(metadata)

        if merged_details:
            merged_details = self._sanitize_dict(merged_details)

        entry = {
            "id": uuid.uuid4().hex[:12],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "category": category,
            "message": message,
            "job_id": job_id,
            "details": merged_details if merged_details else None,
        }

        self._entries.append(entry)

        # Broadcast to monitor room if socket is wired up
        if self._broadcast_fn:
            try:
                asyncio.get_event_loop().create_task(self._broadcast_fn(entry))
            except RuntimeError:
                pass  # no running loop yet (startup)

        # Write asynchronously to Redis if active
        if self._use_redis and self._redis_client:
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(self._write_to_redis(entry))
            except RuntimeError:
                pass

        # Also print for container logs
        prefix = _LEVEL_PREFIX.get(level, "INFO")
        tag = f"[{category.upper()}]"
        jid = f" [JOB {job_id[:8]}]" if job_id else ""
        print(f"[{prefix}] {tag}{jid} {message}", flush=True)

        return entry

    async def _write_to_redis(self, entry: dict):
        if not self._redis_client:
            return
        try:
            entry_str = json.dumps(entry)
            # LPUSH to global logs
            await self._redis_client.lpush("logs:global", entry_str)
            await self._redis_client.ltrim("logs:global", 0, MAX_ENTRIES - 1)
            await self._redis_client.expire("logs:global", LOG_TTL_HOURS * 3600)

            # If job_id is provided, RPUSH to job logs (timeline order)
            if entry.get("job_id"):
                job_key = f"logs:job:{entry['job_id']}"
                await self._redis_client.rpush(job_key, entry_str)
                await self._redis_client.expire(job_key, LOG_TTL_HOURS * 3600)
        except Exception as e:
            # Fall back to standard print to avoid infinite recursion
            print(f"[EventLog] Error writing to Redis: {e}", flush=True)

    # ── Retrieval ───────────────────────────────────────────

    async def get_logs(
        self,
        *,
        since: str | None = None,
        level: str | None = None,
        category: str | None = None,
        job_id: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Return logs filtered by optional criteria, newest first."""
        if self._use_redis and self._redis_client:
            try:
                if job_id:
                    key = f"logs:job:{job_id}"
                    raw_entries = await self._redis_client.lrange(key, 0, -1)
                    # Reverse because RPUSH order is oldest first, but get_logs returns newest first
                    entries = [json.loads(e) for e in reversed(raw_entries)]
                else:
                    scan_limit = min(MAX_ENTRIES, max(limit * 10, 500))
                    raw_entries = await self._redis_client.lrange(
                        "logs:global", 0, scan_limit - 1
                    )
                    entries = [json.loads(e) for e in raw_entries]
            except Exception as e:
                print(f"[EventLog] Error getting logs from Redis: {e}", flush=True)
                entries = [json.loads(json.dumps(e)) for e in reversed(self._entries)]
        else:
            entries = [json.loads(json.dumps(e)) for e in reversed(self._entries)]

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

        if job_id and not (self._use_redis and self._redis_client):
            entries = [e for e in entries if e.get("job_id") == job_id]

        return entries[:limit]

    @property
    def count(self) -> int:
        """In-memory log count fallback."""
        return len(self._entries)

    async def get_count(self) -> int:
        """Get total logs count from Redis if available, or fallback to in-memory."""
        if self._use_redis and self._redis_client:
            try:
                return await self._redis_client.llen("logs:global")
            except Exception as e:
                print(f"[EventLog] Error getting count from Redis: {e}", flush=True)
        return len(self._entries)

    def clear(self):
        self._entries.clear()

    # ── Auto-Cleanup ────────────────────────────────────────

    def cleanup_old(self, hours: int = LOG_TTL_HOURS):
        """Remove entries older than `hours` (in memory)."""
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
