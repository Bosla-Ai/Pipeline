import aiohttp
import asyncio
import isodate
import re
from src.utils.key_manager import key_manager
from src.utils.helpers import (
    classify_via_frontend,
    is_relevant,
    is_arabic_content,
    is_garbage_content,
    analyze_topic_scope,
    strict_relevance_score,
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

_QUERY_TOKEN_EXPANSIONS = {
    "eng": "engineer",
    "engr": "engineer",
    "dev": "developer",
}

_ROLE_TOPIC_SUFFIXES = {
    "analyst": "analytics",
    "designer": "design",
    "developer": "development",
    "engineer": "engineering",
    "tester": "testing",
}


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
    print("    💀 Fatal: All API Keys exhausted.")
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

    if len(words) >= 2 and words[-1] in _ROLE_TOPIC_SUFFIXES:
        discipline_tag = " ".join(
            [*words[:-1], _ROLE_TOPIC_SUFFIXES[words[-1]]]
        ).strip()
        if discipline_tag and discipline_tag != tag_lower:
            return [
                (
                    f"{discipline_tag} full course",
                    f"{discipline_tag} tutorial",
                ),
                (f"{tag} full course", f"{tag} tutorial"),
            ]

    # Default: original behavior
    return [(f"{tag} full course", f"{tag} tutorial")]


def normalize_search_tag(tag: str) -> str:
    clean = " ".join(tag.replace("-", " ").split()).strip()
    tokens = [
        _QUERY_TOKEN_EXPANSIONS.get(token.lower(), token) for token in clean.split()
    ]
    expanded = " ".join(tokens).strip()
    return TAG_MAP.get(expanded.lower(), expanded)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def build_search_tag(tag: str, language: str) -> str:
    normalized = normalize_search_tag(tag)

    if language != "en":
        return normalized

    if not re.search(r"[\u0600-\u06FF]", normalized):
        return normalized

    ascii_terms = []
    for token in re.findall(r"[A-Za-z0-9#+.]+", normalized):
        lowered = token.lower()
        mapped = TAG_MAP.get(lowered, lowered)
        ascii_terms.append(mapped)

    ascii_terms = _dedupe_preserve_order(ascii_terms)
    return " ".join(ascii_terms) if ascii_terms else normalized


def build_search_plans(tag: str, language: str) -> list[dict]:
    normalized = normalize_search_tag(tag)
    has_arabic_query = bool(re.search(r"[\u0600-\u06FF]", normalized))
    requested_language = "ar" if language == "ar" and has_arabic_query else "en"
    plans = []
    seen = set()

    def add_plan(query: str, relevance_language: str | None):
        clean_query = " ".join(query.split()).strip()
        if not clean_query:
            return

        key = (clean_query.lower(), relevance_language or "")
        if key in seen:
            return

        seen.add(key)
        plans.append(
            {
                "query": clean_query,
                "relevance_language": relevance_language,
            }
        )

    add_plan(normalized, requested_language)

    if language == "ar":
        add_plan(normalized, None)

        english_fallback = build_search_tag(normalized, "en")
        if has_arabic_query and english_fallback.lower() != normalized.lower():
            add_plan(english_fallback, "en")

    return plans


async def process_single_tag(
    session, sio, socket_id, tag, language, max_results, precomputed_scope=None
):
    cache_key = generate_cache_key("youtube", tag, language)
    cached_result = await cache.get(cache_key)
    if cached_result:
        print(f"    ✅ [Cache Hit] YouTube: {tag} ({language})")
        return tag, cached_result

    search_plans = build_search_plans(tag, language)
    primary_search_tag = search_plans[0]["query"] if search_plans else tag

    # ── Try yt-dlp scraper first (no API quota cost) ──
    print(f"    🔍 [yt-dlp] Trying scraper first for '{primary_search_tag}'...")
    scraper_result = await emergency_fetch(primary_search_tag, language)
    if scraper_result:
        print(
            f"    ✅ [yt-dlp] Found result for '{tag}': {scraper_result.get('title', '')[:50]}"
        )
        await cache.set(cache_key, scraper_result)
        return tag, scraper_result

    print(f"    ⚠️ [yt-dlp] No results for '{tag}'. Falling back to YouTube API...")

    candidates = []

    fetch_limit = 20

    for attempt_index, search_plan in enumerate(search_plans, start=1):
        search_tag = search_plan["query"]
        relevance_language = search_plan["relevance_language"]
        plan_label = relevance_language or "any"
        print(
            f"\n--- Processing: {tag} (Attempt {attempt_index}/{len(search_plans)}: {plan_label}, query: {search_tag}) ---"
        )

        queries_to_try = build_smart_queries(search_tag)

        for q_playlist, q_video in queries_to_try:
            if len(candidates) >= 10:
                break

            playlist_params = {
                "part": "snippet",
                "q": q_playlist,
                "type": "playlist",
                "maxResults": fetch_limit,
            }
            if relevance_language:
                playlist_params["relevanceLanguage"] = relevance_language

            pl_data = await fetch_youtube_data(session, SEARCH_URL, playlist_params)

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

                    if language != "ar":
                        if is_garbage_content(title, desc):
                            continue

                    count = int(item["contentDetails"].get("itemCount", 0))
                    if count < 4:
                        continue

                    thumbnails = snippet.get("thumbnails", {})
                    thumb_url = (
                        thumbnails.get("high")
                        or thumbnails.get("medium")
                        or thumbnails.get("default")
                        or {}
                    ).get("url", "")

                    data = {
                        "contentType": "Playlist",
                        "contentId": item["id"],
                        "url": f"https://www.youtube.com/playlist?list={item['id']}",
                        "title": title,
                        "description": desc,
                        "thumbnailUrl": thumb_url,
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
                video_params = {
                    "part": "snippet",
                    "q": q_video,
                    "type": "video",
                    "videoDuration": "long",
                    "maxResults": fetch_limit,
                }
                if relevance_language:
                    video_params["relevanceLanguage"] = relevance_language

                vid_data = await fetch_youtube_data(session, SEARCH_URL, video_params)

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

                        if language != "ar":
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

    if not candidates:
        print(f"    💀 No results for '{tag}' from either scraper or API.")
        return tag, None

    if precomputed_scope:
        scope = precomputed_scope
    else:
        scope = await analyze_topic_scope(sio, socket_id, tag)

    from src.engine.models import Candidate, SourceName
    from src.engine.runtime import runtime_limits

    # Phase 6: Limit candidate pool and normalize
    pool_candidates = candidates[:runtime_limits.candidate_pool_limit_per_tag]
    candidate_objs = [
        Candidate.from_dict(c, SourceName.YOUTUBE, tag)
        for c in pool_candidates
    ]

    # Phase 7: Deduplicate
    seen_urls = set()
    deduped_objs = []
    for c in candidate_objs:
        url_norm = c.url.strip().lower()
        if url_norm not in seen_urls:
            seen_urls.add(url_norm)
            deduped_objs.append(c)

    # Phase 8: Cheap Ranker / Pruning
    if scope == "Broad":
        ranked_objs = sorted(
            deduped_objs,
            key=lambda x: (x.metadata.get("contentType") == "Playlist", x.raw_score),
            reverse=True
        )[:runtime_limits.cheap_rank_limit_per_tag]
    else:
        ranked_objs = sorted(
            deduped_objs,
            key=lambda x: x.raw_score,
            reverse=True
        )[:runtime_limits.cheap_rank_limit_per_tag]

    top_candidates = [c.to_dict() for c in ranked_objs]
    
    if not top_candidates:
        print(f"    💀 No candidates remaining after normalization and deduplication for '{tag}'.")
        return tag, None

    math_winner = top_candidates[0]
    strict_candidates = [
        {
            **candidate,
            "_strict_score": strict_relevance_score(
                tag,
                candidate.get("title", ""),
                candidate.get("description", ""),
            ),
        }
        for candidate in top_candidates
    ]
    strict_candidates = [c for c in strict_candidates if c["_strict_score"] >= 0.72]
    strict_candidates.sort(key=lambda x: (x["_strict_score"], x["score"]), reverse=True)

    if strict_candidates:
        best_strict = strict_candidates[0]
        lead_margin = (
            best_strict["_strict_score"] - strict_candidates[1]["_strict_score"]
            if len(strict_candidates) > 1
            else best_strict["_strict_score"]
        )
        if not socket_id or best_strict["_strict_score"] >= 0.9 or lead_margin >= 0.2:
            result = {k: v for k, v in best_strict.items() if k != "_strict_score"}
            print(
                f"    ✅ Strict local match accepted: {result['title'][:40]}... "
                f"(strict={best_strict['_strict_score']:.2f}, score={result['score']:.1f})"
            )
            await cache.set(cache_key, result)
            return tag, result

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
        if strict_candidates:
            result = {
                k: v for k, v in strict_candidates[0].items() if k != "_strict_score"
            }
            print(
                f"    ⚠️ AI unavailable/rejected. Using strict local candidate: "
                f"{result['title'][:40]}..."
            )
            await cache.set(cache_key, result)
            return tag, result

        print(f"    ⚠️ AI rejected all and no strict local candidate matched '{tag}'.")
        return tag, None


def _ensure_url(resource: dict | None) -> dict | None:
    """Guarantee every resource dict has a usable `url` field."""
    if resource is None or not isinstance(resource, dict):
        return resource
    url = resource.get("url")
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        return resource
    # Reconstruct from contentId
    content_id = resource.get("contentId", "")
    if isinstance(content_id, str) and content_id.startswith(("http://", "https://")):
        resource["url"] = content_id
        return resource
    ct = str(resource.get("contentType") or "").lower()
    if content_id:
        if ct == "playlist":
            resource["url"] = f"https://www.youtube.com/playlist?list={content_id}"
        elif ct == "video":
            resource["url"] = f"https://www.youtube.com/watch?v={content_id}"
        else:
            # Default to video
            resource["url"] = f"https://www.youtube.com/watch?v={content_id}"
    return resource


async def search_embeddable_video(query: str, language: str = "en") -> dict | None:
    """
    Search YouTube for an embeddable video matching the query.
    Returns dict with {url, title, channelTitle, thumbnail, viewCount} or None.
    """
    api_lang = "ar" if language == "ar" else "en"

    async with aiohttp.ClientSession() as session:
        search_results = await fetch_youtube_data(
            session,
            SEARCH_URL,
            {
                "part": "snippet",
                "q": f"{query} tutorial",
                "type": "video",
                "videoEmbeddable": "true",
                "maxResults": 5,
                "relevanceLanguage": api_lang,
            },
        )

        if not search_results or not search_results.get("items"):
            return None

        # confirm embeddable + stats
        video_ids = [item["id"]["videoId"] for item in search_results["items"]]

        details_data = await fetch_youtube_data(
            session,
            VIDEO_URL,
            {
                "part": "snippet,statistics,status",
                "id": ",".join(video_ids),
            },
        )

        if not details_data or not details_data.get("items"):
            # Fallback: use first search result
            first = search_results["items"][0]
            return {
                "url": f"https://www.youtube.com/watch?v={first['id']['videoId']}",
                "title": first["snippet"]["title"],
                "channelTitle": first["snippet"].get("channelTitle", ""),
                "thumbnail": first["snippet"]["thumbnails"]
                .get("high", {})
                .get("url", ""),
            }

        best = None
        best_views = -1

        for item in details_data.get("items", []):
            status = item.get("status", {})
            if not status.get("embeddable", False):
                continue

            views = int(item.get("statistics", {}).get("viewCount", "0"))
            if views > best_views:
                best_views = views
                best = item

        if not best:
            first = search_results["items"][0]
            return {
                "url": f"https://www.youtube.com/watch?v={first['id']['videoId']}",
                "title": first["snippet"]["title"],
                "channelTitle": first["snippet"].get("channelTitle", ""),
                "thumbnail": first["snippet"]["thumbnails"]
                .get("high", {})
                .get("url", ""),
            }

        return {
            "url": f"https://www.youtube.com/watch?v={best['id']}",
            "title": best["snippet"]["title"],
            "channelTitle": best["snippet"].get("channelTitle", ""),
            "thumbnail": best["snippet"]["thumbnails"].get("high", {}).get("url", ""),
            "viewCount": best_views,
        }


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
        normalized_tags.append(normalize_search_tag(t))

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

        final_roadmap = {}
        for i, (normalized_key, res) in enumerate(results):
            original_key = (
                original_tags[i] if i < len(original_tags) else normalized_key
            )
            res = _ensure_url(res)
            if res is not None:
                final_roadmap[original_key] = res
            else:
                print(
                    f"    ⚠️ [YouTube] No result for tag '{original_key}' — skipped in roadmap."
                )

    return final_roadmap
