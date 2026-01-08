import math
from datetime import datetime, timezone


def calculate_video_score(video):
    views = video.get("viewCount", 0)
    likes = video.get("likeCount", 0)

    if views < 1000 or likes == 0:
        return 0

    # Engagement Ratio
    engagement = (math.log10(likes) / math.log10(views)) * 10

    # Freshness Decay
    published_date = datetime.fromisoformat(video["publishedAt"].replace("Z", "+00:00"))
    if published_date.tzinfo is None:
        published_date = published_date.replace(tzinfo=timezone.utc)

    days_old = max(0, (datetime.now(timezone.utc) - published_date).days)
    freshness = math.exp(-math.log(2) * (days_old / (365 * 5)))

    return engagement * freshness


def calculate_playlist_score(playlist):
    count = playlist.get("videoCount", 0)
    pub_at = playlist.get("publishedAt", "")

    if not pub_at or count == 0:
        return 0

    # Favor playlists with substantial content (up to 50 videos)
    count_score = (min(count, 50.0) / 50.0) * 10

    published_date = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
    if published_date.tzinfo is None:
        published_date = published_date.replace(tzinfo=timezone.utc)

    days_old = max(0, (datetime.now(timezone.utc) - published_date).days)
    freshness = math.exp(-math.log(2) * (days_old / (365 * 5)))

    # Weighted Score: 70% Content Volume, 30% Freshness
    return (count_score * 0.7) + (freshness * 3.0)
