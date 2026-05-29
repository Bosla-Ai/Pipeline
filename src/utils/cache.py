"""
Redis cache utility for storing fetcher responses.
Caches results by platform + tag + language to save quota and improve performance.
"""

import os
import json
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
