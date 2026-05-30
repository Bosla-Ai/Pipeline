import urllib.parse
import re
from src.engine.models import Candidate

# Common title filler words to remove before Jaccard similarity comparison
FILLER_WORDS = {
    "full",
    "course",
    "tutorial",
    "complete",
    "beginner",
    "beginners",
    "learn",
}


def normalize_url(url: str) -> str:
    """Normalize a URL by:
    - Converting scheme to https (if http/https)
    - Removing 'www.' from domain
    - Lowercasing domain and path
    - Stripping trailing slash from path
    - Removing tracking query parameters (UTM, couponCode, trackingId, etc.)
    - Sorting remaining query parameters for consistent order
    - Removing fragments
    """
    if not url:
        return ""

    url = url.strip()

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return url.lower()

    # Standardize scheme
    scheme = "https" if parsed.scheme in ("http", "https") else parsed.scheme.lower()

    # Standardize netloc
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Standardize path
    path = parsed.path.lower()
    if path.endswith("/"):
        path = path[:-1]

    # Standardize query parameters
    query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)

    tracking_params = {
        "couponcode",
        "trackingid",
        "cohort",
        "si",
        "feature",
        "ab_channel",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "clickid",
        "fbclid",
        "gclid",
        "gclsrc",
    }

    filtered_params = []
    for k, v in query_params:
        k_lower = k.lower()
        if k_lower not in tracking_params and not k_lower.startswith("utm_"):
            filtered_params.append((k_lower, v))

    # Sort remaining parameters for order consistency
    filtered_params.sort()

    new_query = urllib.parse.urlencode(filtered_params)

    # Reconstruct URL, discarding fragments
    normalized = urllib.parse.urlunparse(
        (scheme, netloc, path, parsed.params, new_query, "")
    )
    return normalized


def extract_youtube_id(url: str) -> tuple[str | None, str | None]:
    """
    Extract video_id and playlist_id from a YouTube URL.
    """
    if not url:
        return None, None
    try:
        parsed = urllib.parse.urlparse(url.strip())
        hostname = parsed.hostname.lower() if parsed.hostname else ""
        if "youtu.be" in hostname:
            video_id = parsed.path.strip("/")
            if video_id:
                return video_id, None
        elif "youtube.com" in hostname:
            query_params = urllib.parse.parse_qs(parsed.query)
            playlist_id = query_params.get("list", [None])[0]
            video_id = query_params.get("v", [None])[0]
            return video_id, playlist_id
    except Exception:
        pass
    return None, None


def normalize_title_for_similarity(title: str) -> str:
    """
    Lowercase, remove punctuation (English and Arabic), and strip filler words.
    """
    if not title:
        return ""
    # Lowercase
    title_lower = title.lower()
    # Remove punctuation using unicode character matching (re.UNICODE)
    title_clean = re.sub(r"[^\w\s]", " ", title_lower)
    # Split, remove filler words
    tokens = [t for t in title_clean.split() if t not in FILLER_WORDS]
    return " ".join(tokens)


def token_set_jaccard(title1: str, title2: str) -> float:
    """
    Calculate Jaccard similarity on normalized token sets.
    """
    words1 = set(normalize_title_for_similarity(title1).split())
    words2 = set(normalize_title_for_similarity(title2).split())
    if not words1 and not words2:
        return 1.0
    if not words1 or not words2:
        return 0.0
    return len(words1.intersection(words2)) / len(words1.union(words2))


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """
    Deduplicate list of candidates based on:
    - Normalized URL
    - YouTube video/playlist ID
    - Source + content_id
    - Same-source Jaccard title similarity >= 0.85
    Preserves the first occurrence.
    """
    seen_urls = set()
    seen_youtube_video_ids = set()
    seen_youtube_playlist_ids = set()
    seen_source_content_ids = set()

    accepted_by_source = {}
    deduped = []

    for c in candidates:
        if not c.url:
            deduped.append(c)
            continue

        norm_url = normalize_url(c.url)
        if norm_url in seen_urls:
            continue

        if c.source == "youtube":
            v_id, pl_id = extract_youtube_id(c.url)
            if v_id and v_id in seen_youtube_video_ids:
                continue
            if pl_id and pl_id in seen_youtube_playlist_ids:
                continue

            if c.content_id:
                if "playlist" in c.url or "list=" in c.url:
                    if c.content_id in seen_youtube_playlist_ids:
                        continue
                else:
                    if c.content_id in seen_youtube_video_ids:
                        continue

        if c.content_id:
            key = (c.source, c.content_id)
            if key in seen_source_content_ids:
                continue

        # Title similarity check (only against same source)
        is_title_duplicate = False
        source_accepted = accepted_by_source.setdefault(c.source, [])
        for accepted_candidate in source_accepted:
            sim = token_set_jaccard(c.title, accepted_candidate.title)
            if sim >= 0.85:
                is_title_duplicate = True
                break

        if is_title_duplicate:
            continue

        # Add candidate
        seen_urls.add(norm_url)
        if c.source == "youtube":
            v_id, pl_id = extract_youtube_id(c.url)
            if v_id:
                seen_youtube_video_ids.add(v_id)
            if pl_id:
                seen_youtube_playlist_ids.add(pl_id)
            if c.content_id:
                if "playlist" in c.url or "list=" in c.url:
                    seen_youtube_playlist_ids.add(c.content_id)
                else:
                    seen_youtube_video_ids.add(c.content_id)

        if c.content_id:
            seen_source_content_ids.add((c.source, c.content_id))

        source_accepted.append(c)
        deduped.append(c)

    return deduped
