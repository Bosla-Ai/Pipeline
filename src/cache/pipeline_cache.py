from typing import Any, Optional
from src.utils.cache import cache
from src.utils.event_log import event_log
from src.cache.keys import get_raw_ytdlp_key, get_normalized_key, get_ranked_key


async def get_raw_ytdlp_candidates(query: str, lang: str) -> Optional[list[dict]]:
    """Get raw candidates from cache."""
    key = get_raw_ytdlp_key(query, lang)
    try:
        await cache.connect()
        res = await cache.get(key)
        if res is not None:
            event_log.log(
                "success",
                "cache",
                "cache_hit",
                details={"type": "raw_ytdlp", "query": query},
            )
        return res
    except Exception as e:
        event_log.log("error", "cache", f"Failed to get raw ytdlp cache: {e}")
        return None


async def set_raw_ytdlp_candidates(
    query: str, lang: str, candidates: list[dict], ttl: int = 43200
) -> bool:
    """Set raw candidates cache (TTL: 12h default)."""
    key = get_raw_ytdlp_key(query, lang)
    try:
        await cache.connect()
        return await cache.set(key, candidates, ttl=ttl)
    except Exception as e:
        event_log.log("error", "cache", f"Failed to set raw ytdlp cache: {e}")
        return False


async def get_normalized_candidates(source: str, raw_hash: str) -> Optional[list[dict]]:
    """Get normalized candidates from cache."""
    key = get_normalized_key(source, raw_hash)
    try:
        await cache.connect()
        res = await cache.get(key)
        if res is not None:
            event_log.log(
                "success",
                "cache",
                "cache_hit",
                details={"type": "normalized", "source": source},
            )
        return res
    except Exception as e:
        event_log.log("error", "cache", f"Failed to get normalized cache: {e}")
        return None


async def set_normalized_candidates(
    source: str, raw_hash: str, candidates: list[dict], ttl: int = 86400
) -> bool:
    """Set normalized candidates cache (TTL: 24h default)."""
    key = get_normalized_key(source, raw_hash)
    try:
        await cache.connect()
        return await cache.set(key, candidates, ttl=ttl)
    except Exception as e:
        event_log.log("error", "cache", f"Failed to set normalized cache: {e}")
        return False


async def get_ranked_candidates(
    tag: str, source: str, candidate_set_hash: str
) -> Optional[list[dict]]:
    """Get ranked candidates from cache."""
    key = get_ranked_key(tag, source, candidate_set_hash)
    try:
        await cache.connect()
        res = await cache.get(key)
        if res is not None:
            event_log.log(
                "success",
                "cache",
                "cache_hit",
                details={"type": "ranked", "tag": tag, "source": source},
            )
        return res
    except Exception as e:
        event_log.log("error", "cache", f"Failed to get ranked cache: {e}")
        return None


async def set_ranked_candidates(
    tag: str,
    source: str,
    candidate_set_hash: str,
    candidates: list[dict],
    ttl: int = 43200,
) -> bool:
    """Set ranked candidates cache (TTL: 12h default)."""
    key = get_ranked_key(tag, source, candidate_set_hash)
    try:
        await cache.connect()
        return await cache.set(key, candidates, ttl=ttl)
    except Exception as e:
        event_log.log("error", "cache", f"Failed to set ranked cache: {e}")
        return False
