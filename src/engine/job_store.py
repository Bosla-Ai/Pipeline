"""
Job store module to manage job states (pending, running, completed, failed)
and persist results using Redis or a local in-memory fallback.
"""

import os
import json
import redis.asyncio as redis
from typing import Optional, Any
from datetime import datetime, timezone
from src.engine.runtime import REDIS_HOST, REDIS_PORT

JOB_TTL = int(os.getenv("JOB_TTL", 86400))  # 24 hours in seconds


class RedisJobStore:
    """Singleton Job Store persisting job metadata and status in Redis (or in memory fallback)."""

    _instance: Optional["RedisJobStore"] = None
    _client: Optional[redis.Redis] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        # Prevent re-initializing the fallback dict if the singleton already exists
        if not hasattr(self, "_in_memory_jobs"):
            self._in_memory_jobs: dict[str, dict] = {}

    async def connect(self):
        """Initialize Redis client connection."""
        if self._client is None:
            try:
                self._client = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    decode_responses=True,
                )
                await self._client.ping()
                print(f"[JobStore] Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
            except Exception as e:
                print(
                    f"[JobStore] Redis unavailable: {e}. Falling back to in-memory store."
                )
                self._client = None

    async def create_job(
        self, job_id: str, tags: list[str], language: str, prefer_paid: bool
    ) -> dict:
        """Create a new job entry with status 'pending'."""
        now = datetime.now(timezone.utc).isoformat()
        job = {
            "job_id": job_id,
            "status": "pending",
            "result": None,
            "error": None,
            "tags": tags,
            "language": language,
            "prefer_paid": prefer_paid,
            "created_at": now,
            "updated_at": now,
        }
        if self._client:
            try:
                await self._client.set(f"job:{job_id}", json.dumps(job), ex=JOB_TTL)
            except Exception as e:
                print(f"[JobStore] Set error: {e}")
        self._in_memory_jobs[job_id] = job
        return job

    async def start_job(self, job_id: str) -> Optional[dict]:
        """Mark a job status as 'running'."""
        job = await self.get_job(job_id)
        if not job:
            return None
        job["status"] = "running"
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        if self._client:
            try:
                await self._client.set(f"job:{job_id}", json.dumps(job), ex=JOB_TTL)
            except Exception as e:
                print(f"[JobStore] Set error: {e}")
        self._in_memory_jobs[job_id] = job
        return job

    async def complete_job(self, job_id: str, result: dict) -> Optional[dict]:
        """Mark a job status as 'completed' and store the result."""
        job = await self.get_job(job_id)
        if not job:
            return None
        job["status"] = "completed"
        job["result"] = result
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        if self._client:
            try:
                await self._client.set(f"job:{job_id}", json.dumps(job), ex=JOB_TTL)
            except Exception as e:
                print(f"[JobStore] Set error: {e}")
        self._in_memory_jobs[job_id] = job
        return job

    async def fail_job(self, job_id: str, error: str) -> Optional[dict]:
        """Mark a job status as 'failed' and store the error message."""
        job = await self.get_job(job_id)
        if not job:
            return None
        job["status"] = "failed"
        job["error"] = error
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        if self._client:
            try:
                await self._client.set(f"job:{job_id}", json.dumps(job), ex=JOB_TTL)
            except Exception as e:
                print(f"[JobStore] Set error: {e}")
        self._in_memory_jobs[job_id] = job
        return job

    async def get_job(self, job_id: str) -> Optional[dict]:
        """Retrieve job status, metadata, and results by job ID."""
        if self._client:
            try:
                data = await self._client.get(f"job:{job_id}")
                if data:
                    return json.loads(data)
            except Exception as e:
                print(f"[JobStore] Get error: {e}")
        return self._in_memory_jobs.get(job_id)


job_store = RedisJobStore()
