"""Log sink for the ACI worker — persists this job's pipeline logs to Cosmos.

The worker is ephemeral (one job, then exit), so its ``event_log`` entries would
vanish when the container stops. To surface them in the admin Pipeline Monitor,
we buffer the job's logs and upsert them as a single TTL'd document into a Cosmos
container (``pipeline_logs``) that the .NET admin API reads.

Document contract (shared with the .NET pipeline-log reader)::

    {
      "id":        "<jobId>",          # one document per job
      "jobId":     "<jobId>",          # partition key  /jobId
      "entries":   [ {<event_log entry>}, ... ],   # oldest -> newest
      "count":     <int>,
      "updatedAt": "<iso8601>",
      "ttl":       <seconds>           # Cosmos TTL (container DefaultTimeToLive must be set)
    }

**One document per job + batched (timer) upserts** keeps RU usage low on the
free-tier **shared-throughput** database — the ``pipeline_logs`` container is
created without its own provisioned throughput, so it draws on the shared
database RU/s budget rather than reserving extra (which would blow the cap).
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone

# Cap entries per job doc as a safety margin against the Cosmos 2MB item limit.
MAX_ENTRIES_PER_JOB = 1000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LogSink(ABC):
    """Where the worker streams its pipeline logs for the dashboard to read."""

    @abstractmethod
    def record(self, entry: dict) -> None:
        """Buffer one log entry (sync, called from the logging hot path)."""

    @abstractmethod
    async def flush(self) -> None:
        """Persist buffered entries now (called once more on shutdown)."""

    async def aclose(self) -> None:
        """Release resources (override if needed)."""


class NullLogSink(LogSink):
    """No-op sink used when Cosmos isn't configured.

    Logs still print to stdout (container logs) and stream over Web PubSub; they
    just aren't persisted for the dashboard.
    """

    def record(self, entry: dict) -> None:
        pass

    async def flush(self) -> None:
        pass


class CosmosLogSink(LogSink):
    """Buffers the job's logs and upserts them as one TTL'd Cosmos document.

    A background timer flushes every ``flush_interval`` seconds while the job
    runs (so the dashboard sees progress as it polls), and ``flush()`` is called
    once more on shutdown to capture the tail. ``azure-cosmos`` is imported
    lazily so local/light runs don't need it.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        key: str,
        database: str,
        container: str,
        job_id: str,
        ttl_seconds: int = 86400,
        flush_interval: float = 5.0,
    ):
        self._endpoint = endpoint
        self._key = key
        self._database = database
        self._container_name = container
        self._job_id = job_id
        self._ttl = ttl_seconds
        self._flush_interval = flush_interval

        self._client = None
        self._container = None
        self._entries: list[dict] = []
        self._dirty = False
        self._closed = False
        self._flusher: asyncio.Task | None = None

    # ── ingest ──────────────────────────────────────────────
    def record(self, entry: dict) -> None:
        self._entries.append(entry)
        if len(self._entries) > MAX_ENTRIES_PER_JOB:
            self._entries = self._entries[-MAX_ENTRIES_PER_JOB:]
        self._dirty = True
        self._ensure_flusher()

    def _ensure_flusher(self) -> None:
        if self._flusher is not None and not self._flusher.done():
            return
        try:
            self._flusher = asyncio.get_running_loop().create_task(self._flush_loop())
        except RuntimeError:
            pass  # no running loop yet — flush() on shutdown still persists

    async def _flush_loop(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(self._flush_interval)
                if self._dirty:
                    await self._upsert()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    # ── persistence ─────────────────────────────────────────
    async def _ensure(self):
        if self._container is not None:
            return
        from azure.cosmos.aio import CosmosClient  # lazy

        self._client = CosmosClient(self._endpoint, credential=self._key)
        db = self._client.get_database_client(self._database)
        self._container = db.get_container_client(self._container_name)

    async def _upsert(self) -> None:
        self._dirty = False
        snapshot = list(self._entries)
        try:
            await self._ensure()
            await self._container.upsert_item(
                {
                    "id": self._job_id,
                    "jobId": self._job_id,
                    "entries": snapshot,
                    "count": len(snapshot),
                    "updatedAt": _now(),
                    "ttl": self._ttl,
                }
            )
        except Exception as e:  # best-effort: retry on the next tick / final flush
            self._dirty = True
            print(f"[CosmosLogSink] upsert failed: {e}", flush=True)

    async def flush(self) -> None:
        if self._entries:
            await self._upsert()

    async def aclose(self) -> None:
        self._closed = True
        if self._flusher is not None:
            self._flusher.cancel()
            try:
                await self._flusher
            except (asyncio.CancelledError, Exception):
                pass
            self._flusher = None
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
            self._container = None


def build_log_sink_from_env(job_id: str) -> LogSink:
    """Cosmos log sink when ``COSMOS_*`` env is present, else a no-op sink."""
    endpoint = os.getenv("COSMOS_ENDPOINT")
    key = os.getenv("COSMOS_KEY")
    if endpoint and key:
        return CosmosLogSink(
            endpoint=endpoint,
            key=key,
            database=os.getenv("COSMOS_DATABASE", "agentdb"),
            container=os.getenv("COSMOS_LOGS_CONTAINER", "pipeline_logs"),
            job_id=job_id,
            ttl_seconds=int(os.getenv("PIPELINE_LOGS_TTL_SECONDS", "86400")),
        )
    return NullLogSink()
