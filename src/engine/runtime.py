import asyncio
import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class RuntimeLimits:
    max_concurrent_jobs: int
    youtube_api_concurrency: int
    youtube_scraper_concurrency: int
    udemy_concurrency: int
    coursera_concurrency: int
    frontend_ai_concurrency: int

    socket_wait_timeout_seconds: int
    frontend_ai_timeout_seconds: int
    provider_timeout_seconds: int
    full_job_timeout_seconds: int

    candidate_pool_limit_per_tag: int
    cheap_rank_limit_per_tag: int
    final_result_limit_per_tag: int


def load_runtime_limits() -> RuntimeLimits:
    return RuntimeLimits(
        max_concurrent_jobs=_int_env("MAX_CONCURRENT_JOBS", 3),
        youtube_api_concurrency=_int_env("YOUTUBE_API_CONCURRENCY", 4),
        youtube_scraper_concurrency=_int_env("YOUTUBE_SCRAPER_CONCURRENCY", 1),
        udemy_concurrency=_int_env("UDEMY_CONCURRENCY", 1),
        coursera_concurrency=_int_env("COURSERA_CONCURRENCY", 1),
        frontend_ai_concurrency=_int_env("FRONTEND_AI_CONCURRENCY", 2),
        socket_wait_timeout_seconds=_int_env("SOCKET_WAIT_TIMEOUT", 30),
        frontend_ai_timeout_seconds=_int_env("FRONTEND_AI_TIMEOUT", 12),
        provider_timeout_seconds=_int_env("PROVIDER_TIMEOUT", 20),
        full_job_timeout_seconds=_int_env("FULL_JOB_TIMEOUT", 90),
        candidate_pool_limit_per_tag=_int_env("CANDIDATE_POOL_LIMIT_PER_TAG", 30),
        cheap_rank_limit_per_tag=_int_env("CHEAP_RANK_LIMIT_PER_TAG", 12),
        final_result_limit_per_tag=_int_env("FINAL_RESULT_LIMIT_PER_TAG", 3),
    )


class RuntimeSemaphores:
    def __init__(self, limits: RuntimeLimits):
        self.jobs = asyncio.Semaphore(limits.max_concurrent_jobs)
        self.youtube_api = asyncio.Semaphore(limits.youtube_api_concurrency)
        self.youtube_scraper = asyncio.Semaphore(limits.youtube_scraper_concurrency)
        self.udemy = asyncio.Semaphore(limits.udemy_concurrency)
        self.coursera = asyncio.Semaphore(limits.coursera_concurrency)
        self.frontend_ai = asyncio.Semaphore(limits.frontend_ai_concurrency)


runtime_limits = load_runtime_limits()
runtime_semaphores = RuntimeSemaphores(runtime_limits)
