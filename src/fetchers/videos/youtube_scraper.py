import asyncio
import math
from datetime import datetime, timezone
from typing import Optional

from src.utils.helpers import is_relevant, is_garbage_content
from src.utils.scoring import calculate_video_score, calculate_playlist_score


async def scrape_youtube_search(
    tag: str, language: str = "en", max_results: int = 10
) -> list[dict]:
    try:
        import yt_dlp
    except ImportError:
        print("    ❌ [Scraper] yt-dlp not installed. Fallback unavailable.")
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
        print(f"    ⚠️ [Scraper] yt-dlp search error: {e}")

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
    print(
        f"    🆘 [Emergency Scraper] Searching YouTube for '{tag}' without API keys..."
    )

    candidates = await scrape_youtube_search(tag, language, max_results=max_results * 2)

    if not candidates:
        core_tag = _extract_core_topic(tag)
        if core_tag != tag:
            print(f"    🔄 [Emergency Scraper] Retrying with core topic: '{core_tag}'")
            candidates = await scrape_youtube_search(
                core_tag, language, max_results=max_results * 2
            )

    if not candidates:
        print(f"    💀 [Emergency Scraper] No results found for '{tag}'")
        return None

    candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
    winner = candidates[0]
    print(
        f"    🏆 [Emergency Scraper] Found: {winner['title'][:50]}... (Score: {winner['score']:.1f})"
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
