import math
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

    avg_views = playlist.get("avg_views", 0)
    avg_likes = playlist.get("avg_likes", 0)

    if avg_views > 0:
        log_views = math.log10(avg_views + 1)
        reliability_multiplier = 1.0 + (log_views * 0.1)
    else:
        reliability_multiplier = 1.0

    engagement_multiplier = 1.0
    if avg_views > 100:
        ratio = (avg_likes / avg_views) * 100
        if ratio > 3.0:
            engagement_multiplier = 1.3
        elif ratio > 1.5:
            engagement_multiplier = 1.15
        elif ratio < 0.5:
            engagement_multiplier = 0.7

    published_at = playlist.get("publishedAt", "")
    freshness_score = _calculate_soft_freshness(published_at, half_life_years=5)
    subscriber_count = playlist.get("subscriberCount", 1000)
    sub_multiplier = 1.0

    if avg_views < 5000:
        if subscriber_count < 10:
            sub_multiplier = 0.5
        elif subscriber_count < 100:
            sub_multiplier = 0.8

    final_score = (
        (count_multiplier * 10)
        * avg_duration_multiplier
        * freshness_score
        * reliability_multiplier
        * engagement_multiplier
        * sub_multiplier
    )

    return final_score


def _calculate_soft_freshness(published_at_str, half_life_years):
    if not published_at_str:
        return 0.5  # Penalty for unknown date

    try:
        published_date = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
    except Exception:
        return 0.5

    if published_date.tzinfo is None:
        published_date = published_date.replace(tzinfo=timezone.utc)

    days_old = max(0, (datetime.now(timezone.utc) - published_date).days)
    years_old = days_old / 365.0

    decay = math.exp(-math.log(2) * (years_old / half_life_years))
    return decay


def _parse_float(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        import re

        cleaned = re.sub(r"[^\d.]", "", str(val))
        return float(cleaned) if cleaned else None
    except Exception:
        return None


def _parse_int(val) -> int | None:
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    try:
        import re

        cleaned = re.sub(r"[^\d]", "", str(val))
        return int(cleaned) if cleaned else None
    except Exception:
        return None


def _parse_duration_hours(val) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        import re

        m = re.search(r"([\d.]+)", str(val))
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


def calculate_udemy_score(
    course: dict, tag: str, explain: bool = False
) -> float | dict:
    """Calculate Udemy-specific quality/relevance score."""
    title = str(course.get("title", "")).lower()
    tag_lower = tag.lower()

    score = 0.0
    scoreBreakdown = {}
    reasonCodes = []

    if tag_lower in title:
        score += 40
        scoreBreakdown["titleMatch"] = 40.0
        reasonCodes.append("title_exact_tag_match")

    tag_words = [word for word in tag_lower.split() if len(word) > 2]
    if tag_words:
        matched = sum(1 for word in tag_words if word in title)
        overlap_score = 25.0 * (matched / len(tag_words))
        score += overlap_score
        if overlap_score > 0:
            scoreBreakdown["wordOverlap"] = overlap_score
            reasonCodes.append("tag_word_overlap")

    rating = _parse_float(course.get("rating"))
    if rating:
        if rating >= 4.7:
            score += 20
            scoreBreakdown["rating"] = 20.0
            reasonCodes.append("high_rating")
        elif rating >= 4.5:
            score += 15
            scoreBreakdown["rating"] = 15.0
            reasonCodes.append("good_rating")
        elif rating >= 4.2:
            score += 8
            scoreBreakdown["rating"] = 8.0
            reasonCodes.append("fair_rating")
        elif rating < 3.8:
            score -= 15
            scoreBreakdown["rating"] = -15.0
            reasonCodes.append("poor_rating")

    # Check lectures under various keys, prioritizing lectureCount/lecture_count
    lectures_val = (
        course.get("lectureCount")
        or course.get("lecture_count")
        or course.get("lectures")
        or course.get("videoCount")
    )
    lectures = _parse_int(lectures_val)
    if lectures:
        if lectures >= 80:
            score += 12
            scoreBreakdown["lectures"] = 12.0
            reasonCodes.append("sufficient_lecture_count")
        elif lectures >= 30:
            score += 8
            scoreBreakdown["lectures"] = 8.0
            reasonCodes.append("medium_lecture_count")
        elif lectures < 10:
            score -= 8
            scoreBreakdown["lectures"] = -8.0
            reasonCodes.append("low_lecture_count")

    hours = _parse_duration_hours(course.get("hours"))
    if hours:
        if 5 <= hours <= 50:
            score += 10
            scoreBreakdown["duration"] = 10.0
            reasonCodes.append("good_duration_range")
        elif hours < 1:
            score -= 10
            scoreBreakdown["duration"] = -10.0
            reasonCodes.append("short_duration")

    # Native Arabic bonus
    has_arabic_char = any(ord(char) >= 0x0600 and ord(char) <= 0x06FF for char in title)
    if has_arabic_char:
        score += 15.0
        scoreBreakdown["arabicBonus"] = 15.0
        reasonCodes.append("arabic_title_bonus")

    final_score = max(score, 0.0)
    if score < 0.0:
        reasonCodes.append("score_floor_applied")
        scoreBreakdown["capAdjustment"] = -score

    if explain:
        return {
            "score": final_score,
            "explanation": {
                "finalScore": final_score,
                "source": "udemy",
                "reasonCodes": reasonCodes,
                "scoreBreakdown": scoreBreakdown,
            },
        }

    return final_score
