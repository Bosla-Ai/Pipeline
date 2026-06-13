"""Job-state sink for the ACI worker.

The worker is the source of truth for a roadmap job: it writes ``running`` →
``completed``/``failed`` plus the final roadmap document to a store that the
.NET backend point-reads. In production that store is Azure Cosmos DB; locally
(and in tests) a stdout sink prints the same documents so the flow is
observable without any cloud dependency.

The document contract (shared with the .NET ``IRoadmapJobStore``)::

    {
      "id":          "<jobId>",          # Cosmos item id
      "jobId":       "<jobId>",          # partition key  /jobId
      "status":      "running" | "completed" | "failed",
      "tags":        ["..."],
      "language":    "en",
      "result":      { ... } | null,     # final roadmap payload
      "error":       "..."   | null,
      "createdAt":   "<iso8601>",
      "updatedAt":   "<iso8601>",
      "completedAt": "<iso8601>" | null
    }
"""

from __future__ import annotations

import json
import os
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobSink(ABC):
    """Where the worker records job state + the final roadmap."""

    @abstractmethod
    async def set_running(self, job_id: str, tags: list[str], language: str) -> None: ...

    @abstractmethod
    async def complete(self, job_id: str, result: dict) -> None: ...

    @abstractmethod
    async def fail(self, job_id: str, error: str) -> None: ...

    async def aclose(self) -> None:
        """Release resources (override if needed)."""


class StdoutJobSink(JobSink):
    """Prints job documents as JSON lines. Used locally and in ACI logs."""

    def _emit(self, doc: dict) -> None:
        print("JOB_DOC " + json.dumps(doc, default=str), file=sys.stdout, flush=True)

    async def set_running(self, job_id: str, tags: list[str], language: str) -> None:
        self._emit(
            {
                "id": job_id,
                "jobId": job_id,
                "status": STATUS_RUNNING,
                "tags": tags,
                "language": language,
                "result": None,
                "error": None,
                "createdAt": _now(),
                "updatedAt": _now(),
                "completedAt": None,
            }
        )

    async def complete(self, job_id: str, result: dict) -> None:
        self._emit(
            {
                "id": job_id,
                "jobId": job_id,
                "status": STATUS_COMPLETED,
                "result": result,
                "error": None,
                "updatedAt": _now(),
                "completedAt": _now(),
            }
        )

    async def fail(self, job_id: str, error: str) -> None:
        self._emit(
            {
                "id": job_id,
                "jobId": job_id,
                "status": STATUS_FAILED,
                "result": None,
                "error": error,
                "updatedAt": _now(),
                "completedAt": _now(),
            }
        )


class CosmosJobSink(JobSink):
    """Upserts job documents into Azure Cosmos DB (point-read by .NET).

    ``azure-cosmos`` is imported lazily so the LIGHT_MODE image and local runs
    don't need it unless Cosmos is actually configured.
    """

    def __init__(self, *, endpoint: str, key: str, database: str, container: str):
        self._endpoint = endpoint
        self._key = key
        self._database = database
        self._container_name = container
        self._client = None
        self._container = None

    async def _ensure(self):
        if self._container is not None:
            return
        from azure.cosmos.aio import CosmosClient  # lazy

        self._client = CosmosClient(self._endpoint, credential=self._key)
        db = self._client.get_database_client(self._database)
        self._container = db.get_container_client(self._container_name)

    async def _upsert(self, doc: dict) -> None:
        await self._ensure()
        await self._container.upsert_item(doc)

    async def set_running(self, job_id: str, tags: list[str], language: str) -> None:
        await self._upsert(
            {
                "id": job_id,
                "jobId": job_id,
                "status": STATUS_RUNNING,
                "tags": tags,
                "language": language,
                "result": None,
                "error": None,
                "createdAt": _now(),
                "updatedAt": _now(),
                "completedAt": None,
            }
        )

    async def complete(self, job_id: str, result: dict) -> None:
        await self._upsert(
            {
                "id": job_id,
                "jobId": job_id,
                "status": STATUS_COMPLETED,
                "result": result,
                "error": None,
                "updatedAt": _now(),
                "completedAt": _now(),
            }
        )

    async def fail(self, job_id: str, error: str) -> None:
        await self._upsert(
            {
                "id": job_id,
                "jobId": job_id,
                "status": STATUS_FAILED,
                "result": None,
                "error": error,
                "updatedAt": _now(),
                "completedAt": _now(),
            }
        )

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
            self._container = None


def build_job_sink_from_env() -> JobSink:
    """Cosmos sink when ``COSMOS_*`` env is present, else stdout."""
    endpoint = os.getenv("COSMOS_ENDPOINT")
    key = os.getenv("COSMOS_KEY")
    if endpoint and key:
        return CosmosJobSink(
            endpoint=endpoint,
            key=key,
            database=os.getenv("COSMOS_DATABASE", "agentdb"),
            container=os.getenv("COSMOS_JOBS_CONTAINER", "pipeline_jobs"),
        )
    return StdoutJobSink()
