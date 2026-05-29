import urllib.parse
from src.engine.models import Candidate


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


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Remove candidates with duplicate normalized URLs, preserving the first occurrence."""
    seen_urls = set()
    deduped = []
    for c in candidates:
        if not c.url:
            deduped.append(c)
            continue
        norm = normalize_url(c.url)
        if norm not in seen_urls:
            seen_urls.add(norm)
            deduped.append(c)
    return deduped
