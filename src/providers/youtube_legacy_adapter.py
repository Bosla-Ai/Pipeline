import urllib.parse
from src.engine.models import Candidate, SourceName
from src.security.url_policy import is_valid_url


def canonicalize_youtube_url(url: str) -> str:
    """
    Returns a standardized canonical YouTube URL for videos or playlists.
    E.g. https://youtu.be/abc -> https://www.youtube.com/watch?v=abc
    """
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url.strip())
        hostname = parsed.hostname.lower() if parsed.hostname else ""

        if "youtu.be" in hostname:
            video_id = parsed.path.strip("/")
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
        elif "youtube.com" in hostname:
            query_params = urllib.parse.parse_qs(parsed.query)
            if "list" in query_params:
                playlist_id = query_params["list"][0]
                return f"https://www.youtube.com/playlist?list={playlist_id}"
            elif "v" in query_params:
                video_id = query_params["v"][0]
                return f"https://www.youtube.com/watch?v={video_id}"
    except Exception:
        pass
    return url


def normalize_youtube_candidate(raw: dict, tag: str) -> Candidate | None:
    """
    Normalizes a raw YouTube payload dictionary into a clean Candidate.
    Returns None if the payload contains invalid URL or missing fields.
    """
    url = raw.get("url") or ""
    if not is_valid_url(url):
        return None

    title = raw.get("title") or ""
    if not title.strip():
        return None

    # Canonicalize URL before candidate creation
    canonical_url = canonicalize_youtube_url(url)
    raw_copy = dict(raw)
    raw_copy["url"] = canonical_url

    candidate = Candidate.from_dict(raw_copy, SourceName.YOUTUBE, tag)

    # Content type & Content ID extraction
    content_type = "unknown"
    content_id = candidate.content_id

    try:
        parsed = urllib.parse.urlparse(canonical_url)
        query_params = urllib.parse.parse_qs(parsed.query)
        if "list" in query_params:
            content_type = "playlist"
            if not content_id:
                content_id = query_params["list"][0]
        elif "v" in query_params:
            content_type = "video"
            if not content_id:
                content_id = query_params["v"][0]
    except Exception:
        pass

    # Ensure metadata exists
    if candidate.metadata is None:
        candidate.metadata = {}

    # Store normalized content type
    candidate.metadata["content_type"] = content_type

    # Update candidate with parsed content_id
    if content_id:
        candidate.content_id = content_id

    return candidate
