import math
from datetime import datetime, timezone


def calculate_video_score(video):
    views = video.get("viewCount", 0)
    likes = video.get("likeCount", 0)

    if views < 1000 or likes == 0:
        return 0

    engagement_ratio = 0
    if views > 0:
        engagement_ratio = (likes / views) * 100

    duration = video.get("duration_mins", 0)
    duration_score = 1.0
    if duration > 10:
        duration_score = 1.0 + (duration / 60.0)

    view_score = 0
    if views > 1000:
        view_score = math.log10(views)

    published_date = datetime.fromisoformat(video["publishedAt"].replace("Z", "+00:00"))
    if published_date.tzinfo is None:
        published_date = published_date.replace(tzinfo=timezone.utc)
    days_old = max(0, (datetime.now(timezone.utc) - published_date).days)
    freshness = math.exp(-math.log(2) * (days_old / (365 * 4)))

    final_score = (
        (engagement_ratio * 1.5 + view_score * 0.5) * duration_score * freshness
    )
    return final_score


def calculate_playlist_score(playlist):
    """
    Scores a playlist based strictly on:
    1. Video Count (w*n) - User Request: "w*n of videos"
    2. Authority (Trusted People) - Subscriber Count
    3. Freshness
    """

    count = playlist.get("videoCount", 0)
    pub_at = playlist.get("publishedAt", "")

    if not pub_at or count == 0:
        return 0

    richness = 0
    if count < 5:
        richness = 1.0
    else:
        richness = count / 5.0

    if richness > 30:
        richness = 30

    subscriber_count = playlist.get("subscriberCount", 0)
    authority_score = 1.0
    if subscriber_count > 1000:
        log_val = math.log10(subscriber_count)
        authority_score = 1.0 + (log_val - 3) * 0.5

    published_date = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
    if published_date.tzinfo is None:
        published_date = published_date.replace(tzinfo=timezone.utc)
    days_old = max(0, (datetime.now(timezone.utc) - published_date).days)
    freshness = math.exp(-math.log(2) * (days_old / (365 * 5)))

    final_score = (richness * 2.0) * authority_score * freshness

    return final_score
