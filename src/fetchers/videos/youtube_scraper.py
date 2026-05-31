import asyncio
import math
import os
import time
from datetime import datetime, timezone
from typing import Optional

from src.utils.helpers import is_relevant, is_garbage_content
from src.utils.scoring import calculate_video_score, calculate_playlist_score

try:
    _SCRAPER_COOLDOWN_SECONDS = max(
        30, int(os.getenv("YT_DLP_ERROR_COOLDOWN_SECONDS", "300"))
    )
except ValueError:
    _SCRAPER_COOLDOWN_SECONDS = 300
_scraper_disabled_until = 0.0


def _scraper_circuit_open() -> bool:
    return time.monotonic() < _scraper_disabled_until


def _trip_scraper_circuit(message: str) -> None:
    global _scraper_disabled_until
    lowered = message.lower()
    trigger_words = [
        "ssl",
        "eof occurred in violation of protocol",
        "429",
        "too many requests",
        "captcha",
        "sign in to confirm",
        "http error 403",
        "http error 429",
        "blocked",
        "bot detection",
        "timeout",
    ]
    if any(w in lowered for w in trigger_words):
        _scraper_disabled_until = time.monotonic() + _SCRAPER_COOLDOWN_SECONDS
        print(
            "    [Scraper] Temporarily disabled after repeated failures/blocks/timeouts. "
            f"Cooldown: {_SCRAPER_COOLDOWN_SECONDS}s"
        )


async def scrape_youtube_search(
    tag: str, language: str = "en", max_results: int = 10
) -> list[dict]:
    if _scraper_circuit_open():
        print("    [Scraper] Circuit open. Skipping yt-dlp search.")
        return []

    try:
        import yt_dlp
    except ImportError:
        print("    [Scraper] yt-dlp not installed. Fallback unavailable.")
        return []

    search_queries = [
        f"ytsearch{max_results}:{tag} full course",
        f"ytsearch{max_results}:{tag} tutorial",
    ]

    all_entries = []

    for query in search_queries:
        entries = await asyncio.to_thread(_extract_search_results, query, language)
        all_entries.extend(entries)
        if len(all_entries) >= max_results:
            break

    seen_ids = set()
    unique = []
    for e in all_entries:
        vid_id = e.get("id") or e.get("url", "")
        if vid_id not in seen_ids:
            seen_ids.add(vid_id)
            unique.append(e)

    candidates = []
    for entry in unique[: max_results * 2]:
        parsed = _parse_entry(entry, tag, language)
        if parsed:
            candidates.append(parsed)

    candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
    return candidates[:max_results]


def _extract_search_results(query: str, language: str) -> list[dict]:
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "ignoreerrors": True,
        "geo_bypass": True,
        "extractor_args": {"youtube": {"lang": [language]}},
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(query, download=False)
            if result and "entries" in result:
                return [e for e in result["entries"] if e is not None]
    except Exception as e:
        print(f"    [Scraper] yt-dlp search error: {e}")
        _trip_scraper_circuit(str(e))

    return []


def _parse_entry(entry: dict, tag: str, language: str) -> Optional[dict]:
    title = entry.get("title", "")
    description = entry.get("description", "") or ""
    video_id = entry.get("id", "")
    url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"

    if not title or not video_id:
        return None

    if not is_relevant(tag, title, description):
        return None

    if language != "ar" and is_garbage_content(title, description):
        return None

    duration_secs = entry.get("duration") or 0
    duration_mins = int(duration_secs / 60) if duration_secs else 0

    if duration_mins < 5:
        return None

    view_count = entry.get("view_count") or 0
    like_count = entry.get("like_count") or 0

    uploaded = entry.get("upload_date", "")
    published_at = ""
    if uploaded and len(uploaded) == 8:
        try:
            published_at = (
                datetime.strptime(uploaded, "%Y%m%d")
                .replace(tzinfo=timezone.utc)
                .isoformat()
            )
        except:
            pass

    is_playlist = entry.get("_type") == "playlist"

    if is_playlist:
        count = entry.get("playlist_count") or entry.get("n_entries") or 0
        thumb = entry.get("thumbnail") or ""
        if not thumb:
            thumbs = entry.get("thumbnails") or []
            if thumbs:
                thumb = (
                    thumbs[-1].get("url", "") if isinstance(thumbs[-1], dict) else ""
                )
        data = {
            "contentType": "Playlist",
            "contentId": video_id,
            "url": (
                url
                if "playlist" in url
                else f"https://www.youtube.com/playlist?list={video_id}"
            ),
            "title": title,
            "description": description[:500],
            "thumbnailUrl": thumb,
            "videoCount": count,
            "publishedAt": published_at,
            "metadata_info": f"Playlist with {count} videos (scraped fallback)",
            "channelTitle": entry.get("channel", "") or entry.get("uploader", ""),
            "subscriberCount": 1000,
            "items": [],
            "avg_views": view_count,
            "avg_likes": like_count,
            "source": "scraper_fallback",
        }
        data["score"] = calculate_playlist_score(data)
    else:
        data = {
            "contentType": "Video",
            "contentId": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": title,
            "description": description[:500],
            "viewCount": view_count,
            "likeCount": like_count,
            "publishedAt": published_at,
            "duration_mins": duration_mins,
            "metadata_info": f"Video Duration: {duration_mins} mins (scraped fallback)",
            "channelTitle": entry.get("channel", "") or entry.get("uploader", ""),
            "source": "scraper_fallback",
        }
        data["score"] = calculate_video_score(data)

    return data


async def emergency_fetch(
    tag: str, language: str = "en", max_results: int = 5
) -> Optional[dict]:
    print(f"    [Emergency Scraper] Searching YouTube for '{tag}' without API keys...")

    candidates = await scrape_youtube_search(tag, language, max_results=max_results * 2)

    if not candidates:
        core_tag = _extract_core_topic(tag)
        if core_tag != tag:
            print(f"    [Emergency Scraper] Retrying with core topic: '{core_tag}'")
            candidates = await scrape_youtube_search(
                core_tag, language, max_results=max_results * 2
            )

    if not candidates:
        print(f"    [Emergency Scraper] No results found for '{tag}'")
        return None

    candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
    winner = candidates[0]
    print(
        f"    [Emergency Scraper] Found: {winner['title'][:50]}... (Score: {winner['score']:.1f})"
    )
    return winner


def _extract_core_topic(tag: str) -> str:
    stop_phrases = [" for ", " in ", " with ", " using ", " and ", " on ", " via "]
    clean = tag
    for phrase in stop_phrases:
        if phrase in clean.lower():
            parts = clean.lower().split(phrase)
            candidates = [p.strip() for p in parts if len(p.strip()) > 2]
            if candidates:
                clean = max(candidates, key=len)
                break
    return clean


async def scrape_youtube_query_candidates(
    query: str, tag: str, language: str = "en", max_results: int = 10
) -> list[dict]:
    if _scraper_circuit_open():
        print("    [Scraper] Circuit open. Skipping yt-dlp search.")
        return []

    try:
        import yt_dlp
    except ImportError:
        print("    [Scraper] yt-dlp not installed. Scraper candidates unavailable.")
        return []

    from src.config.settings import YT_DLP_HARD_TIMEOUT_SECONDS

    yt_query = f"ytsearch{max_results}:{query}"
    print(
        f"    [DEBUG] scrape_youtube_query_candidates query={query} _extract_search_results={_extract_search_results}",
        flush=True,
    )
    try:
        raw_entries = await asyncio.wait_for(
            asyncio.to_thread(_extract_search_results, yt_query, language),
            timeout=float(YT_DLP_HARD_TIMEOUT_SECONDS),
        )
        print(f"    [DEBUG] Completed wait_for, raw_entries={raw_entries}", flush=True)
    except asyncio.TimeoutError:
        print(
            f"    [Scraper] yt-dlp query extraction timed out after {YT_DLP_HARD_TIMEOUT_SECONDS}s",
            flush=True,
        )
        _trip_scraper_circuit("timeout")
        raw_entries = []

    seen_ids = set()
    unique = []
    for e in raw_entries:
        if not e:
            continue
        vid_id = e.get("id") or e.get("url", "")
        if vid_id not in seen_ids:
            seen_ids.add(vid_id)
            unique.append(e)

    candidates = []
    for entry in unique:
        parsed = _parse_entry(entry, tag, language)
        if parsed:
            candidates.append(parsed)

    return candidates[:max_results]
