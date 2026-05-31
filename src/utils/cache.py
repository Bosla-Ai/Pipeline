"""
Redis cache utility for storing fetcher responses.
Caches results by platform + tag + language to save quota and improve performance.
"""

import os
import json
import asyncio
import redis.asyncio as redis
from typing import Optional, Any

from src.engine.runtime import REDIS_HOST, REDIS_PORT

# Configuration
DEFAULT_TTL = 60 * 60 * 24  # 24 hours in seconds
CACHE_VERSION = os.getenv("CACHE_VERSION", "v1")


class RedisCache:
    """Async Redis cache wrapper for fetcher results."""

    _instance: Optional["RedisCache"] = None
    _client: Optional[redis.Redis] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def is_available(self) -> bool:
        """Returns True if the Redis client is connected and available."""
        return self._client is not None

    async def connect(self):
        """Initialize Redis connection."""
        if self._client is None:
            try:
                self._client = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    decode_responses=True,
                )
                await self._client.ping()
                print(f"[Cache] Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
            except Exception as e:
                print(f"[Cache] Redis unavailable: {e}. Caching disabled.")
                self._client = None

    async def get(self, key: str) -> Optional[Any]:
        """Get cached value by key. Returns None if not found or Redis unavailable."""
        if self._client is None:
            return None
        try:
            value = await self._client.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            print(f"[Cache] Get error: {e}")
        return None

    async def set(self, key: str, value: Any, ttl: int = DEFAULT_TTL) -> bool:
        """Set cached value with TTL. Returns True on success."""
        if self._client is None:
            return False
        try:
            await self._client.set(key, json.dumps(value), ex=ttl)
            return True
        except Exception as e:
            print(f"[Cache] Set error: {e}")
            return False

    async def acquire_lock(self, key: str, token: str, ttl: int = 30) -> Optional[bool]:
        """Acquire a light Redis lock. Returns True if acquired, False if lock held, None if Redis unavailable/error."""
        if self._client is None:
            return None
        try:
            acquired = await self._client.set(f"lock:{key}", token, nx=True, ex=ttl)
            return bool(acquired)
        except Exception as e:
            print(f"[Cache] Lock acquisition error for {key}: {e}")
            return None

    async def release_lock(self, key: str, token: str) -> bool:
        """Release a light Redis lock if the token matches."""
        if self._client is None:
            return False
        try:
            lock_key = f"lock:{key}"
            script = """
                if redis.call("get", KEYS[1]) == ARGV[1] then
                    return redis.call("del", KEYS[1])
                else
                    return 0
                end
            """
            if hasattr(self._client, "eval"):
                result = await self._client.eval(script, 1, lock_key, token)
                return bool(result)
            else:
                # Fallback for simple mock clients in tests
                current = await self._client.get(lock_key)
                if current:
                    val = current.decode() if isinstance(current, bytes) else current
                    if val == token:
                        await self._client.delete(lock_key)
                        return True
                return False
        except Exception as e:
            print(f"[Cache] Lock release error for {key}: {e}")
            return False

    async def get_or_set_with_lock(
        self,
        key: str,
        ttl: int,
        factory,
        job_id: Optional[str] = None,
        source: Optional[str] = None,
        tag: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Any:
        """
        Get value from cache. If not found, acquire a lock and use factory to generate value,
        then save to cache. Prevents cache stampede.
        """
        from src.utils.event_log import event_log

        # 1. Initial Cache Check
        cached = await self.get(key)
        if cached is not None:
            if source and tag and language:
                print(f"    [Cache Hit] {source}: {tag} ({language})")
                event_log.log(
                    "success",
                    "cache",
                    "cache_hit",
                    job_id=job_id,
                    metadata={
                        "source": source,
                        "tag": tag,
                        "language": language,
                    },
                )
            return cached

        # 2. Setup lock
        import uuid

        token = str(uuid.uuid4())

        # Acquire lock
        acquired = await self.acquire_lock(key, token, ttl=30)
        if acquired is True:
            if source and tag and language:
                event_log.log(
                    "info",
                    "cache",
                    "cache_miss",
                    job_id=job_id,
                    metadata={
                        "source": source,
                        "tag": tag,
                        "language": language,
                    },
                )
            try:
                value = await factory()
                await self.set(key, value, ttl)
                return value
            finally:
                await self.release_lock(key, token)
        elif acquired is None:
            # Redis is unavailable or errored: bypass waiting, compute immediately
            return await factory()

        # 3. Someone else is computing it. Wait and check cache.
        if source and tag and language:
            print(
                f"    [Cache Stampede Protection] Waiting for {source} lock on '{tag}' ({language})..."
            )

        for _ in range(15):  # 15 iterations * 0.5s = 7.5 seconds max wait
            await asyncio.sleep(0.5)
            try:
                cached = await self.get(key)
            except Exception as ce:
                print(f"    [Cache Wait] Error reading cache key {key}: {ce}")
                cached = None
            if cached is not None:
                if source and tag and language:
                    print(f"    [Cache Hit via Lock] {source}: {tag} ({language})")
                    event_log.log(
                        "success",
                        "cache",
                        "cache_hit",
                        job_id=job_id,
                        metadata={
                            "source": source,
                            "tag": tag,
                            "language": language,
                        },
                    )
                return cached

        # Fallback: compute anyway after waiting.
        if source and tag and language:
            event_log.log(
                "info",
                "cache",
                "cache_miss_fallback",
                job_id=job_id,
                metadata={
                    "source": source,
                    "tag": tag,
                    "language": language,
                    "reason": "lock_wait_timeout",
                },
            )
        return await factory()

    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None


def generate_cache_key(platform: str, tag: str, language: str) -> str:
    """
    Generate a cache key from platform, tag, and language.
    Example: "v1:youtube:python:en"
    """
    # Normalize: lowercase, strip whitespace
    normalized_tag = tag.lower().strip().replace(" ", "_")
    prefix = f"{CACHE_VERSION}:" if CACHE_VERSION else ""
    return f"{prefix}{platform}:{normalized_tag}:{language}"


# Singleton instance
cache = RedisCache()
