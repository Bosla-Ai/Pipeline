import aiohttp
import asyncio
import isodate
from src.utils.key_manager import key_manager
from src.utils.helpers import (
    classify_via_frontend,
    is_relevant,
    is_arabic_content,
    is_garbage_content,
)
from src.utils.constants import TAG_MAP
from src.utils.scoring import calculate_video_score, calculate_playlist_score

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEO_URL = "https://www.googleapis.com/youtube/v3/videos"
PLAYLIST_URL = "https://www.googleapis.com/youtube/v3/playlists"


async def fetch_youtube_data(session, url, params):
    """
    Fetches data with automatic API Key Rotation on 403 errors.
    """
    max_retries = len(key_manager.keys)
    attempts = 0

    while attempts < max_retries:
        # 1. Inject the CURRENT key dynamically
        params["key"] = key_manager.get_current_key()

        try:
            async with session.get(url, params=params) as response:

                # Success
                if response.status == 200:
                    return await response.json()

                # Quota Exceeded (403) -> ROTATE & RETRY
                if response.status == 403:
                    error_msg = await response.text()
                    if "quota" in error_msg.lower():
                        print(
                            f"    ❌ Quota Exceeded for Key #{key_manager.current_index + 1}. Rotating..."
                        )
                        key_manager.rotate()
                        attempts += 1
                        continue  # Try again with new key
                    else:
                        print(f"    ❌ API Error 403 (Not Quota): {error_msg[:100]}")
                        return {}

                # Other Errors
                return {}

        except Exception as e:
            print(f"    ❌ Network Error: {e}")
            return {}

    print("    💀 Fatal: All API Keys exhausted.")
    return {}


async def process_single_tag(session, sio, socket_id, tag, language, max_results):
    current_lang = language
    candidates = []

    attempts = 0
    max_attempts = 2 if language == "ar" else 1

    fetch_limit = 20

    while attempts < max_attempts:
        attempts += 1
        print(f"\n--- Processing: {tag} (Attempt {attempts}: {current_lang}) ---")

        # Simple quality-focused queries for all users
        queries_to_try = [(f"{tag} full course", f"{tag} tutorial")]

        api_lang = "ar" if current_lang == "ar" else "en"

        for q_playlist, q_video in queries_to_try:
            if len(candidates) >= 10:
                break

            # 1. Search Playlists
            pl_data = await fetch_youtube_data(
                session,
                SEARCH_URL,
                {
                    "part": "snippet",
                    "q": q_playlist,
                    "type": "playlist",
                    "maxResults": fetch_limit,
                    "relevanceLanguage": api_lang,
                },
            )

            pl_ids = [i["id"]["playlistId"] for i in pl_data.get("items", [])]

            if pl_ids:
                details_data = await fetch_youtube_data(
                    session,
                    PLAYLIST_URL,
                    {
                        "part": "snippet,contentDetails",
                        "id": ",".join(pl_ids),
                    },
                )

                # Pre-filter candidates locally for relevance & garbage (fast checks)
                batch_candidates = []

                for item in details_data.get("items", []):
                    snippet = item["snippet"]
                    title = snippet["title"]
                    desc = snippet.get("description", "")

                    if not is_relevant(tag, title, desc):
                        continue

                    if current_lang != "ar":
                        if is_garbage_content(title, desc):
                            continue

                    count = int(item["contentDetails"].get("itemCount", 0))
                    if count < 4:
                        continue

                    data = {
                        "contentType": "Playlist",
                        "contentId": item["id"],
                        "url": f"https://www.youtube.com/playlist?list={item['id']}",
                        "title": title,
                        "description": desc,
                        "videoCount": count,
                        "publishedAt": snippet["publishedAt"],
                        "metadata_info": f"Playlist with {count} videos",
                        "defaultAudioLanguage": snippet.get("defaultAudioLanguage", ""),
                        "defaultLanguage": snippet.get("defaultLanguage", ""),
                        "channelId": snippet.get("channelId", ""),
                        "channelTitle": snippet.get("channelTitle", ""),
                    }
                    batch_candidates.append(data)

                if batch_candidates:
                    channel_ids = list(
                        set(
                            [c["channelId"] for c in batch_candidates if c["channelId"]]
                        )
                    )
                    for i in range(0, len(channel_ids), 50):
                        chunk_ids = channel_ids[i : i + 50]
                        chan_data = await fetch_youtube_data(
                            session,
                            "https://www.googleapis.com/youtube/v3/channels",
                            {"part": "statistics", "id": ",".join(chunk_ids)},
                        )
                        subs_map = {}
                        for item in chan_data.get("items", []):
                            s_count = item["statistics"].get("subscriberCount", "0")
                            subs_map[item["id"]] = (
                                int(s_count) if s_count.isdigit() else 0
                            )

                        for c in batch_candidates:
                            if c["channelId"] in subs_map:
                                c["subscriberCount"] = subs_map[c["channelId"]]
                                subs_k = (
                                    f"{c['subscriberCount']/1000:.1f}K"
                                    if c["subscriberCount"] > 1000
                                    else str(c["subscriberCount"])
                                )
                                c["metadata_info"] += f" | {subs_k} Subs"

                for c in batch_candidates:
                    c["score"] = calculate_playlist_score(c)

                candidates.extend(batch_candidates)

            if len(candidates) < 3:
                vid_data = await fetch_youtube_data(
                    session,
                    SEARCH_URL,
                    {
                        "part": "snippet",
                        "q": q_video,
                        "type": "video",
                        "videoDuration": "long",
                        "maxResults": fetch_limit,
                        "relevanceLanguage": api_lang,
                    },
                )

                vid_ids = [i["id"]["videoId"] for i in vid_data.get("items", [])]
                if vid_ids:
                    stats_data = await fetch_youtube_data(
                        session,
                        VIDEO_URL,
                        {
                            "part": "snippet,statistics,contentDetails",
                            "id": ",".join(vid_ids),
                        },
                    )

                    batch_videos = []
                    for item in stats_data.get("items", []):
                        snippet = item["snippet"]
                        title = snippet["title"]
                        desc = snippet.get("description", "")

                        if not is_relevant(tag, title, desc):
                            continue

                        if current_lang != "ar":
                            if is_garbage_content(title, desc):
                                continue

                        duration_iso = item["contentDetails"].get("duration", "PT0S")
                        try:
                            duration_mins = int(
                                isodate.parse_duration(duration_iso).total_seconds()
                                / 60
                            )
                        except:
                            duration_mins = 0

                        data = {
                            "contentType": "Video",
                            "contentId": item["id"],
                            "url": f"https://www.youtube.com/watch?v={item['id']}",
                            "title": title,
                            "description": desc,
                            "viewCount": int(item["statistics"].get("viewCount", 0)),
                            "likeCount": int(item["statistics"].get("likeCount", 0)),
                            "publishedAt": snippet["publishedAt"],
                            "duration_mins": duration_mins,
                            "metadata_info": f"Video Duration: {duration_mins} mins",
                            "defaultAudioLanguage": snippet.get(
                                "defaultAudioLanguage", ""
                            ),
                            "defaultLanguage": snippet.get("defaultLanguage", ""),
                        }
                        data["score"] = calculate_video_score(data)
                        batch_videos.append(data)

                    candidates.extend(batch_videos)

        if len(candidates) >= 2:
            break

        if current_lang == "ar":
            print(f"    ⚠️ No Arabic content for '{tag}'. Switching to English...")
            current_lang = "en"
        else:
            break

    # Final Selection
    if not candidates:
        return tag, None

    candidates.sort(
        key=lambda x: (x["contentType"] == "Playlist", x["score"]), reverse=True
    )

    top_candidates = candidates[:2]
    math_winner = top_candidates[0]

    print(f"    🤖 AI Analyzing Top {len(top_candidates)} Candidates...")
    valid_items = await classify_via_frontend(sio, socket_id, tag, top_candidates)

    if valid_items:
        valid_items.sort(
            key=lambda x: (x["contentType"] == "Playlist", x["score"]), reverse=True
        )
        result = valid_items[0]
        print(
            f"    🏆 AI Selected: {result['title'][:40]}... (Score: {result['score']:.1f})"
        )
        return tag, result
    else:
        print(f"    ⚠️ AI rejected all. Using Richest Candidate (Safety Net).")
        return tag, math_winner


async def fetch(sio, socket_id, tags, language="en", max_results=5):
    if not tags:
        return {}

    normalized_tags = []
    for t in tags:
        clean = t.lower().replace("-", " ").strip()
        final_tag = TAG_MAP.get(clean, clean)
        normalized_tags.append(final_tag)

    async with aiohttp.ClientSession() as session:
        tasks = [
            process_single_tag(session, sio, socket_id, tag, language, max_results)
            for tag in normalized_tags
        ]
        results = await asyncio.gather(*tasks)
        final_roadmap = {tag: res for tag, res in results}

    return final_roadmap
