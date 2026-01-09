import math
from datetime import datetime, timezone


def calculate_video_score(video):
    views = video.get("viewCount", 0)
    likes = video.get("likeCount", 0)

    if views < 1000 or likes == 0:
        return 0

<<<<<<< HEAD
<<<<<<< HEAD
    engagement = (math.log10(likes) / math.log10(views)) * 10

=======
    # Engagement Ratio
    engagement = (math.log10(likes) / math.log10(views)) * 10

    # Freshness Decay
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
=======
    engagement = (math.log10(likes) / math.log10(views)) * 10

>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
    published_date = datetime.fromisoformat(video["publishedAt"].replace("Z", "+00:00"))
    if published_date.tzinfo is None:
        published_date = published_date.replace(tzinfo=timezone.utc)

    days_old = max(0, (datetime.now(timezone.utc) - published_date).days)
    freshness = math.exp(-math.log(2) * (days_old / (365 * 5)))

    return engagement * freshness


def calculate_playlist_score(playlist):
<<<<<<< HEAD
<<<<<<< HEAD
=======
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
    """
    Scores a playlist based primarily on 'Richness' (Video Count).
    We assume a 'Roadmap' needs a structured series (10-100 videos).
    """
<<<<<<< HEAD
=======
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
=======
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
    count = playlist.get("videoCount", 0)
    pub_at = playlist.get("publishedAt", "")

    if not pub_at or count == 0:
        return 0

<<<<<<< HEAD
<<<<<<< HEAD
=======
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
    if count < 5:
        richness = 1.0
    elif count <= 50:
        richness = 2.0 + (count / 50.0) * 8.0
    else:
        richness = 10.0
<<<<<<< HEAD
=======
    # Favor playlists with substantial content (up to 50 videos)
    count_score = (min(count, 50.0) / 50.0) * 10
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
=======
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)

    published_date = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
    if published_date.tzinfo is None:
        published_date = published_date.replace(tzinfo=timezone.utc)

    days_old = max(0, (datetime.now(timezone.utc) - published_date).days)
<<<<<<< HEAD
<<<<<<< HEAD
    freshness = math.exp(-math.log(2) * (days_old / (365 * 6)))

    final_score = (richness * 0.85) + (freshness * 1.5)

    return final_score
=======
    freshness = math.exp(-math.log(2) * (days_old / (365 * 5)))

    # Weighted Score: 70% Content Volume, 30% Freshness
    return (count_score * 0.7) + (freshness * 3.0)
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
=======
    freshness = math.exp(-math.log(2) * (days_old / (365 * 6)))

    final_score = (richness * 0.85) + (freshness * 1.5)

    return final_score
>>>>>>> 7b328ee (Improved Scoring Functions and Editing logic to use Scoring first)
