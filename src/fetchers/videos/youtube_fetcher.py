import aiohttp
import asyncio
import isodate
<<<<<<< HEAD
<<<<<<< HEAD
from src.utils.key_manager import key_manager
=======
from src.config.settings import YOUTUBE_API_KEY
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
=======
from src.utils.key_manager import key_manager
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
from src.utils.helpers import (
    classify_via_frontend,
    is_relevant,
    is_arabic_content,
    is_too_basic,
    is_garbage_content,
)
from src.utils.constants import TAG_MAP
from src.utils.scoring import calculate_video_score, calculate_playlist_score

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEO_URL = "https://www.googleapis.com/youtube/v3/videos"
PLAYLIST_URL = "https://www.googleapis.com/youtube/v3/playlists"

<<<<<<< HEAD

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

=======

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

>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)

async def process_single_tag(
    session, sio, socket_id, tag, user_level, language, max_results
):
    current_lang = language
    candidates = []

    attempts = 0
    max_attempts = 2 if language == "ar" else 1

    is_advanced_mode = user_level in ["intermediate", "advanced"]
    fetch_limit = 20

    while attempts < max_attempts:
        attempts += 1
        print(f"\n--- Processing: {tag} (Attempt {attempts}: {current_lang}) ---")

        queries_to_try = []
        if is_advanced_mode:
            queries_to_try = [
                (f"{tag} advanced architecture course", f"{tag} advanced deep dive"),
                (f"{tag} advanced course", f"{tag} internal architecture"),
                (f"{tag} full course", f"{tag} tutorial"),
            ]
        else:
            queries_to_try = [(f"{tag} full course", f"{tag} tutorial")]

        api_lang = "ar" if current_lang == "ar" else "en"

        for q_playlist, q_video in queries_to_try:
            if len(candidates) >= 3:
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
<<<<<<< HEAD
<<<<<<< HEAD
=======
                    "key": YOUTUBE_API_KEY,
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
=======
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
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
<<<<<<< HEAD
<<<<<<< HEAD
=======
                        "key": YOUTUBE_API_KEY,
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
=======
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
                    },
                )

                for item in details_data.get("items", []):
                    snippet = item["snippet"]
                    title = snippet["title"]
                    desc = snippet.get("description", "")

                    if not is_relevant(tag, title, desc):
                        continue
                    if is_advanced_mode and is_too_basic(title, desc, user_level):
                        continue

                    if current_lang == "ar":
                        if not is_arabic_content(snippet):
                            continue
                    else:
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
                    }
                    data["score"] = calculate_playlist_score(data)
                    candidates.append(data)

            # 2. Search Videos (Fallback)
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
<<<<<<< HEAD
<<<<<<< HEAD
=======
                        "key": YOUTUBE_API_KEY,
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
=======
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
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
<<<<<<< HEAD
<<<<<<< HEAD
=======
                            "key": YOUTUBE_API_KEY,
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
=======
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
                        },
                    )

                    for item in stats_data.get("items", []):
                        snippet = item["snippet"]
                        title = snippet["title"]
                        desc = snippet.get("description", "")

                        if not is_relevant(tag, title, desc):
                            continue
                        if is_advanced_mode and is_too_basic(title, desc, user_level):
                            continue

                        if current_lang == "ar":
                            if not is_arabic_content(snippet):
                                continue
                        else:
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

                        if is_advanced_mode and duration_mins < 15:
                            continue

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
                        }
                        data["score"] = calculate_video_score(data)
                        candidates.append(data)

        if candidates:
            break

        if current_lang == "ar":
            print(f"    ⚠️ No Arabic content for '{tag}'. Switching to English...")
            current_lang = "en"
        else:
            break

<<<<<<< HEAD
<<<<<<< HEAD
    # Final Selection
    if not candidates:
        return tag, None

    # Sort candidates by (IsPlaylist, Score)
    candidates.sort(
        key=lambda x: (x["contentType"] == "Playlist", x["score"]), reverse=True
    )

    # Filter Top 3 for AI
    top_candidates = candidates[:3]
    math_winner = top_candidates[0]

    if is_advanced_mode:
        print(f"    🤖 AI Analyzing Top {len(top_candidates)} Richest Candidates...")
=======
=======
    # Final Selection
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
    if not candidates:
        return tag, None

    # Sort candidates by (IsPlaylist, Score)
    candidates.sort(
        key=lambda x: (x["contentType"] == "Playlist", x["score"]), reverse=True
    )

    # Filter Top 3 for AI
    top_candidates = candidates[:3]
    math_winner = top_candidates[0]

    if is_advanced_mode:
<<<<<<< HEAD
        top_candidates = candidates[:8]
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
=======
        print(f"    🤖 AI Analyzing Top {len(top_candidates)} Richest Candidates...")
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
        valid_items = await classify_via_frontend(
            sio, socket_id, top_candidates, user_level
        )

        if valid_items:
            valid_items.sort(
                key=lambda x: (x["contentType"] == "Playlist", x["score"]), reverse=True
            )
<<<<<<< HEAD
<<<<<<< HEAD
=======
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
            result = valid_items[0]
            print(
                f"    🏆 AI Selected: {result['title'][:40]}... (Score: {result['score']:.1f})"
            )
            return tag, result
<<<<<<< HEAD
        else:
            print(f"    ⚠️ AI rejected all. Using Richest Candidate (Safety Net).")
            return tag, math_winner
    else:
        print(f"    📊 Beginner: Selected Richest Candidate.")
=======
            return tag, valid_items[0]
=======
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
        else:
            print(f"    ⚠️ AI rejected all. Using Richest Candidate (Safety Net).")
            return tag, math_winner
    else:
<<<<<<< HEAD
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
=======
        print(f"    📊 Beginner: Selected Richest Candidate.")
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
        return tag, math_winner


async def fetch(sio, socket_id, tags, user_level, language="en", max_results=5):
    if not tags:
        return {}

    normalized_tags = []
    for t in tags:
        clean = t.lower().replace("-", " ").strip()
        final_tag = TAG_MAP.get(clean, clean)
        normalized_tags.append(final_tag)

    async with aiohttp.ClientSession() as session:
        tasks = [
            process_single_tag(
                session, sio, socket_id, tag, user_level, language, max_results
            )
            for tag in normalized_tags
        ]
        results = await asyncio.gather(*tasks)
        final_roadmap = {tag: res for tag, res in results}

    return final_roadmap
