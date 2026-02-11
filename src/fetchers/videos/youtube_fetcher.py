import aiohttp
import asyncio
import isodate
from src.utils.key_manager import key_manager
from src.utils.helpers import (
    classify_via_frontend,
    is_relevant,
    is_arabic_content,
    is_garbage_content,
    analyze_topic_scope,
)
from src.utils.constants import (
    TAG_MAP,
    DESCRIPTIVE_TAG_DECOMPOSITION,
    CORE_TECH_KEYWORDS,
)
from src.utils.scoring import calculate_video_score, calculate_playlist_score
from src.utils.cache import cache, generate_cache_key
from src.fetchers.videos.youtube_scraper import emergency_fetch

_api_exhausted = False

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
        params["key"] = key_manager.get_current_key()

        try:
            async with session.get(url, params=params) as response:

                if response.status == 200:
                    return await response.json()

                # Quota Exceeded
                if response.status == 403:
                    error_msg = await response.text()
                    if "quota" in error_msg.lower():
                        print(
                            f"    ❌ Quota Exceeded for Key #{key_manager.current_index + 1}. Rotating..."
                        )
                        key_manager.rotate()
                        attempts += 1
                        continue
                    else:
                        print(f"    ❌ API Error 403 (Not Quota): {error_msg[:100]}")
                        return {}

                # Other Errors
                return {}

        except Exception as e:
            print(f"    ❌ Network Error: {e}")
            return {}

    global _api_exhausted
    _api_exhausted = True
    print("    💀 Fatal: All API Keys exhausted. Emergency scraper will activate.")
    return {}


def build_smart_queries(tag: str) -> list[tuple[str, str]]:
    """
    Generates optimized YouTube search queries from potentially descriptive tags.
    Handles API-generated tags like 'Automated Testing with Jest' by decomposing
    them into core tech + context queries.
    """
    tag_lower = tag.lower().strip()

    # Check if this is a known descriptive pattern
    for pattern, (q1, q2) in DESCRIPTIVE_TAG_DECOMPOSITION.items():
        if pattern in tag_lower:
            # Also check for a core tech keyword in the tag
            core_tech = None
            for tech in CORE_TECH_KEYWORDS:
                if tech in tag_lower and tech != pattern:
                    core_tech = tech
                    break

            if core_tech:
                return [
                    (f"{core_tech} {q1} full course", f"{core_tech} {q2} tutorial"),
                    (f"{tag} full course", f"{tag} tutorial"),
                ]
            return [
                (f"{q1} full course", f"{q2} tutorial"),
                (f"{tag} full course", f"{tag} tutorial"),
            ]

    # For multi-word descriptive tags containing a core tech, lead with the tech
    words = tag_lower.split()
    if len(words) >= 3:
        found_techs = [w for w in words if w in CORE_TECH_KEYWORDS]
        if found_techs:
            primary_tech = found_techs[0]
            context = tag_lower.replace(primary_tech, "").strip()
            context = " ".join(context.split())  # normalize spaces
            if context and len(context) > 2:
                return [
                    (
                        f"{primary_tech} {context} full course",
                        f"{primary_tech} {context} tutorial",
                    ),
                    (f"{tag} full course", f"{tag} tutorial"),
                ]

    # Default: original behavior
    return [(f"{tag} full course", f"{tag} tutorial")]


async def process_single_tag(
    session, sio, socket_id, tag, language, max_results, precomputed_scope=None
):
    cache_key = generate_cache_key("youtube", tag, language)
    cached_result = await cache.get(cache_key)
    if cached_result:
        print(f"    ✅ [Cache Hit] YouTube: {tag} ({language})")
        return tag, cached_result

    global _api_exhausted
    if _api_exhausted:
        print(
            f"    ⚡ [Short-Circuit] API exhausted. Going straight to emergency scraper for '{tag}'"
        )
        fallback_result = await emergency_fetch(tag, language)
        if fallback_result:
            await cache.set(cache_key, fallback_result)
        return tag, fallback_result

    current_lang = language
    candidates = []

    attempts = 0
    max_attempts = 2 if language == "ar" else 1

    fetch_limit = 20

    while attempts < max_attempts:
        attempts += 1
        print(
            f"\n--- Processing: {tag} (Attempt {attempts}/{max_attempts}: {current_lang}) ---"
        )

        queries_to_try = build_smart_queries(tag)

        api_lang = "ar" if current_lang == "ar" else "en"

        for q_playlist, q_video in queries_to_try:
            if len(candidates) >= 10:
                break

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
                        "items": [],
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

                        filtered_candidates = []

                        for c in batch_candidates:
                            if c["channelId"] in subs_map:
                                c["subscriberCount"] = subs_map[c["channelId"]]

                                # No Hard Filter on Subs (User Request) - handled in Scoring

                                subs_k = (
                                    f"{c['subscriberCount']/1000:.1f}K"
                                    if c["subscriberCount"] > 1000
                                    else str(c["subscriberCount"])
                                )
                                c["metadata_info"] += f" | {subs_k} Subs"
                                filtered_candidates.append(c)

                        batch_candidates = filtered_candidates

                    sampling_candidates = batch_candidates[:10]
                    all_sample_vid_ids = []
                    playlist_vid_map = {}

                    # Parallel fetch of playlistItems for Anti-Shorts & Ownership Check
                    async def fetch_playlist_items(c):
                        pl_items_data = await fetch_youtube_data(
                            session,
                            "https://www.googleapis.com/youtube/v3/playlistItems",
                            {
                                "part": "snippet,contentDetails",
                                "playlistId": c["contentId"],
                                "maxResults": 10,  # Increased slightly for better sample
                            },
                        )
                        items = pl_items_data.get("items", [])
                        video_ids = []
                        owned_count = 0

                        playlist_owner = c.get("channelId", "")

                        for item in items:
                            video_ids.append(item["contentDetails"]["videoId"])
                            # Check ownership
                            video_owner = item["snippet"].get("videoOwnerChannelId", "")
                            if video_owner and video_owner == playlist_owner:
                                owned_count += 1

                        originality_ratio = (owned_count / len(items)) if items else 0.0
                        return c["contentId"], video_ids, originality_ratio

                    results = await asyncio.gather(
                        *[fetch_playlist_items(c) for c in sampling_candidates],
                        return_exceptions=True,
                    )

                    valid_candidates = []
                    # Create a map for candidates to filter them
                    candidate_map = {c["contentId"]: c for c in sampling_candidates}

                    for result in results:
                        if isinstance(result, Exception):
                            continue
                        pl_id, p_vids, originality = result

                        # Filter Mixed Playlists
                        if originality < 0.7:
                            c_title = candidate_map.get(pl_id, {}).get(
                                "title", "Unknown"
                            )
                            print(
                                f"    🗑️ Dropped Mixed Playlist '{c_title[:30]}' (Originality: {originality:.0%})"
                            )
                            # Remove from candidate_map effectively or just don't process
                            if pl_id in candidate_map:
                                del candidate_map[pl_id]
                            continue

                        playlist_vid_map[pl_id] = p_vids
                        all_sample_vid_ids.extend(p_vids)

                    sampling_candidates = list(candidate_map.values())

                    batch_candidates = sampling_candidates

                    if all_sample_vid_ids:
                        vid_chunk_ids = list(set(all_sample_vid_ids))
                        durations_map = {}

                        v_details_data = await fetch_youtube_data(
                            session,
                            VIDEO_URL,
                            {
                                "part": "contentDetails,statistics",
                                "id": ",".join(vid_chunk_ids),
                            },
                        )

                        durations_map = {}
                        stats_map = {}

                        for item in v_details_data.get("items", []):
                            duration_iso = item["contentDetails"].get(
                                "duration", "PT0S"
                            )
                            try:
                                d_mins = int(
                                    isodate.parse_duration(duration_iso).total_seconds()
                                    / 60
                                )
                            except:
                                d_mins = 0
                            durations_map[item["id"]] = d_mins

                            stats = item.get("statistics", {})
                            stats_map[item["id"]] = {
                                "viewCount": int(stats.get("viewCount", 0)),
                                "likeCount": int(stats.get("likeCount", 0)),
                                "commentCount": int(stats.get("commentCount", 0)),
                            }

                        for c in sampling_candidates:
                            p_id = c["contentId"]

                            total_views = 0
                            total_likes = 0
                            total_comments = 0
                            valid_video_count = 0

                            if p_id in playlist_vid_map:
                                for vid_id in playlist_vid_map[p_id]:
                                    if vid_id in durations_map:
                                        c["items"].append(
                                            {"duration_mins": durations_map[vid_id]}
                                        )

                                    if vid_id in stats_map:
                                        s = stats_map[vid_id]
                                        total_views += s["viewCount"]
                                        total_likes += s["likeCount"]
                                        total_comments += s["commentCount"]
                                        valid_video_count += 1

                            if valid_video_count > 0:
                                c["avg_views"] = total_views // valid_video_count
                                c["avg_likes"] = total_likes // valid_video_count
                                c["avg_comments"] = total_comments // valid_video_count
                            else:
                                c["avg_views"] = 0
                                c["avg_likes"] = 0
                                c["avg_comments"] = 0
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

        if not candidates and attempts == 1 and current_lang == "en":
            stop_words = [" for ", " in ", " with ", " using ", " and "]
            new_tag = tag
            for word in stop_words:
                if word in tag.lower():
                    parts = tag.lower().split(word)
                    if len(parts) > 1:
                        new_tag = parts[0].strip()
                        break

            if new_tag != tag and len(new_tag) > 2:
                print(
                    f"    ⚠️ No results for '{tag}'. Fallback to Core Topic: '{new_tag}'"
                )
                tag = new_tag
                attempts -= 1
                await asyncio.sleep(1)
                continue

        if len(candidates) >= 2:
            break

        if current_lang == "ar":
            print(f"    ⚠️ No Arabic content for '{tag}'. Switching to English...")
            current_lang = "en"
        else:
            break

    if not candidates:
        print(f"    ⚠️ No API results for '{tag}'. Activating emergency scraper...")
        fallback_result = await emergency_fetch(tag, language)
        if fallback_result:
            await cache.set(cache_key, fallback_result)
        return tag, fallback_result

    if precomputed_scope:
        scope = precomputed_scope
    else:
        scope = await analyze_topic_scope(sio, socket_id, tag)

    if scope == "Broad":
        candidates.sort(
            key=lambda x: (x["contentType"] == "Playlist", x["score"]), reverse=True
        )
    else:
        candidates.sort(key=lambda x: x["score"], reverse=True)

    top_candidates = candidates[:2]
    math_winner = top_candidates[0]

    print(f"    🤖 AI Analyzing Top {len(top_candidates)} Candidates...")
    valid_items = await classify_via_frontend(sio, socket_id, tag, top_candidates)

    if valid_items:
        if scope == "Broad":
            valid_items.sort(
                key=lambda x: (x["contentType"] == "Playlist", x["score"]), reverse=True
            )
        else:
            valid_items.sort(key=lambda x: x["score"], reverse=True)

        result = valid_items[0]
        print(
            f"    🏆 AI Selected: {result['title'][:40]}... (Score: {result['score']:.1f})"
        )
        await cache.set(cache_key, result)
        return tag, result
    else:
        print(f"    ⚠️ AI rejected all. Using Richest Candidate (Safety Net).")
        await cache.set(cache_key, math_winner)
        return tag, math_winner


async def fetch(sio, socket_id, tags, language="en", max_results=5, scope_cache=None):
    """
    Fetches content from YouTube.
    Args:
        scope_cache: Optional map (tag -> 'Broad'|'Atomic') to optimize AI usage.
    """
    if not tags:
        return {}

    await cache.connect()

    normalized_tags = []
    original_tags = []  # Keep original for scope_cache lookup
    for t in tags:
        original_tags.append(t)
        clean = t.lower().replace("-", " ").strip()
        final_tag = TAG_MAP.get(clean, clean)
        normalized_tags.append(final_tag)

    async with aiohttp.ClientSession() as session:
        tasks = []
        for i, tag in enumerate(normalized_tags):
            # Use original tag for scope_cache lookup (api.py builds cache with original tags)
            original = original_tags[i]
            precomputed = scope_cache.get(original) if scope_cache else None
            tasks.append(
                process_single_tag(
                    session, sio, socket_id, tag, language, max_results, precomputed
                )
            )
        results = await asyncio.gather(*tasks)
        final_roadmap = {tag: res for tag, res in results}

    return final_roadmap
