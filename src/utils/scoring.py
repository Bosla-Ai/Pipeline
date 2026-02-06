import math
import isodate
import re
from datetime import datetime, timezone


def calculate_video_score(video):
    """
    Scoring V2.0: Prioritize Depth (Duration) & Quality (Engagement)
    """
    duration = video.get("duration_mins", 0)

    if duration < 10:
        duration_multiplier = 0.5
    elif 10 <= duration < 30:
        duration_multiplier = 1.0
    elif 30 <= duration < 60:
        duration_multiplier = 1.5
    else:
        duration_multiplier = 2.0

    views = video.get("viewCount", 0)
    likes = video.get("likeCount", 0)

    engagement_multiplier = 1.0

    if views > 100:
        ratio = (likes / views) * 100
        if ratio > 4.0:
            engagement_multiplier = 1.5
        elif ratio < 0.5:
            engagement_multiplier = 0.5

    title = video.get("title", "").lower()
    desc = video.get("description", "").lower()

    live_keywords = ["live", "stream", "q&a"]
    is_live_title = any(k in title for k in live_keywords)
    has_timestamps = any(k in desc for k in ["timestamp", "chapter", "0:00", "00:00"])

    live_penalty = 1.0
    if is_live_title and not has_timestamps:
        live_penalty = 0.7

    published_at = video.get("publishedAt", "")
    freshness_score = _calculate_soft_freshness(published_at, half_life_years=3)

    base_popularity = math.log10(views + 1) if views > 0 else 0

    final_score = (
        (base_popularity * 0.2 + 5.0)
        * duration_multiplier
        * engagement_multiplier
        * live_penalty
        * freshness_score
    )

    return final_score


def calculate_playlist_score(playlist):
    """
    Scoring V2.0: Anti-Shorts & Richness
    """
    count = playlist.get("videoCount", 0)

    if count == 0:
        return 0

    if count < 5:
        count_multiplier = 0.5
    elif 5 <= count <= 10:
        count_multiplier = 1.0
    elif 11 <= count <= 20:
        count_multiplier = 1.5
    elif 21 <= count <= 40:
        count_multiplier = 2.0
    else:
        count_multiplier = 2.5

    items = playlist.get("items", [])
    avg_duration_multiplier = 1.0

    if items:
        valid_durations = [
            item.get("duration_mins", 0)
            for item in items
            if item.get("duration_mins", 0) > 0
        ]

        if valid_durations:
            avg_min = sum(valid_durations) / len(valid_durations)

            if avg_min < 5.0:
                avg_duration_multiplier = 0.3  # CRUSH SHORTS PLAYLISTS
            elif avg_min > 20.0:
                avg_duration_multiplier = 1.1  # Deep content bonus
        else:
            avg_min = 10

    published_at = playlist.get("publishedAt", "")
    freshness_score = _calculate_soft_freshness(published_at, half_life_years=5)

    final_score = (count_multiplier * 10) * avg_duration_multiplier * freshness_score

    return final_score


def _calculate_soft_freshness(published_at_str, half_life_years):
    if not published_at_str:
        return 0.5  # Penalty for unknown date

    try:
        published_date = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
    except:
        return 0.5

    if published_date.tzinfo is None:
        published_date = published_date.replace(tzinfo=timezone.utc)

    days_old = max(0, (datetime.now(timezone.utc) - published_date).days)
    years_old = days_old / 365.0

    decay = math.exp(-math.log(2) * (years_old / half_life_years))
    return decay
