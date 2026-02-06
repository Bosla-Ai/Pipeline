import pytest
import math
from src.utils.helpers import is_relevant, is_garbage_content, is_too_basic
from src.utils.scoring import calculate_video_score, calculate_playlist_score
from datetime import datetime, timezone, timedelta


class TestHelpers:
    def test_is_relevant_exact_match(self):
        assert is_relevant("c#", "Learn C# in 10 mins", "") is True

    def test_is_relevant_partial_match(self):
        assert is_relevant("net core", "ASP.NET Core Tutorial", "") is True

    def test_is_relevant_negative_match(self):
        # "shorts" is in NEGATIVE_KEYWORDS
        assert is_relevant("python", "Python Shorts", "") is False

    def test_is_relevant_miss(self):
        assert is_relevant("java", "Learn Python", "") is False

    def test_is_garbage_content(self):
        # Hindi characters
        assert is_garbage_content("Learn Python in Hindi", "हिंदी") is True
        assert is_garbage_content("Clean Title", "Clean Description") is False

    def test_is_too_basic(self):
        # "introduction" is in BEGINNER_KEYWORDS
        assert is_too_basic("Introduction to AI", "", "advanced") is True
        # User is beginner -> False (allowed)
        assert is_too_basic("Introduction to AI", "", "beginner") is False


class TestScoring:
    def test_calculate_video_score_basics(self):
        video = {
            "viewCount": 5000,
            "likeCount": 100,
            "publishedAt": datetime.now(timezone.utc).isoformat(),
        }
        score = calculate_video_score(video)
        assert score > 0

    def test_calculate_video_score_low_views(self):
        video = {
            "viewCount": 10,
            "likeCount": 1,
            "publishedAt": datetime.now(timezone.utc).isoformat(),
        }
        score = calculate_video_score(video)
        # v2 logic: no hard gate for low views
        assert score > 0

    def test_calculate_playlist_score(self):
        # Recent playlist, 20 videos
        playlist = {
            "videoCount": 20,
            "publishedAt": datetime.now(timezone.utc).isoformat(),
        }
        score = calculate_playlist_score(playlist)
        # Richness should be > 1.0, Freshness high
        assert score > 1.0

    def test_calculate_playlist_score_old(self):
        # Old playlist (5 years ago)
        old_date = datetime.now(timezone.utc) - timedelta(days=365 * 5)
        playlist = {"videoCount": 20, "publishedAt": old_date.isoformat()}
        score_old = calculate_playlist_score(playlist)

        # New playlist
        playlist["publishedAt"] = datetime.now(timezone.utc).isoformat()
        score_new = calculate_playlist_score(playlist)

        assert score_new > score_old
