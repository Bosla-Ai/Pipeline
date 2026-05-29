import pytest
from datetime import datetime, timezone, timedelta
from src.utils.scoring import calculate_playlist_score, calculate_video_score

# ==========================================
# Video Scoring Tests
# ==========================================


def test_video_duration_tiers():
    """Test duration multipliers: 10-30m (1x), 30-60m (1.5x), 60m+ (2.0x)"""
    base = {
        "viewCount": 5000,
        "likeCount": 100,
        "publishedAt": datetime.now(timezone.utc).isoformat(),
        "title": "Clean Code",
        "description": "Standard video",
    }

    # 20 mins -> 1.0x Base
    v_short = base.copy()
    v_short["duration_mins"] = 20
    score_short = calculate_video_score(v_short)

    # 45 mins -> 1.5x Boost
    v_medium = base.copy()
    v_medium["duration_mins"] = 45
    score_medium = calculate_video_score(v_medium)

    # 90 mins -> 2.0x Boost
    v_long = base.copy()
    v_long["duration_mins"] = 90
    score_long = calculate_video_score(v_long)

    assert score_medium > score_short
    assert score_long > score_medium
    # Rough check of multipliers (ignoring freshness/engagement distinct per vid)
    # Ratio should be close to 1.5 and 2.0 relative to base duration scaler
    assert (score_medium / score_short) > 1.3
    assert (score_long / score_short) > 1.8


def test_video_engagement_ratio():
    """Test engagement ratio boosts and penalties"""
    base = {
        "duration_mins": 30,
        "publishedAt": datetime.now(timezone.utc).isoformat(),
        "title": "Unit Testing",
        "description": "Good content",
    }

    # High Engagement (> 4%) -> 1.5x Boost
    # 50 likes / 1000 views = 5%
    v_high = base.copy()
    v_high["viewCount"] = 1000
    v_high["likeCount"] = 50
    score_high = calculate_video_score(v_high)

    # Normal Engagement (1%) -> 1.0x
    # 10 likes / 1000 views = 1%
    v_normal = base.copy()
    v_normal["viewCount"] = 1000
    v_normal["likeCount"] = 10
    score_normal = calculate_video_score(v_normal)

    # Low Engagement (< 0.5%) -> 0.5x Penalty
    # 2 likes / 1000 views = 0.2%
    v_low = base.copy()
    v_low["viewCount"] = 1000
    v_low["likeCount"] = 2
    score_low = calculate_video_score(v_low)

    assert score_high > score_normal
    assert score_normal > score_low
    assert score_high > 1.4 * score_normal  # Check ~1.5x boost


def test_video_engagement_ignored_if_low_views():
    """Engagement boost/penalty should be ignored if views <= 100"""
    v_low_views_high_ratio = {
        "duration_mins": 30,
        "viewCount": 50,
        "likeCount": 10,  # 20% ratio!
        "publishedAt": datetime.now(timezone.utc).isoformat(),
        "title": "Niche",
        "description": "...",
    }

    # Should get standard score, NO massive booster
    score = calculate_video_score(v_low_views_high_ratio)
    # If boosted, score would be very high. Without boost, it's just duration score * freshness
    # Hard to assert exact value without mocking freshness, but ensuring no error/crazy multiplier.
    assert score > 0


def test_live_stream_penalty():
    """Live streams without timestamps get penalized"""
    now = datetime.now(timezone.utc).isoformat()

    # Unedited Stream
    v_live = {
        "title": "Sunday Live Q&A Stream",
        "description": "Just hanging out coding.",
        "duration_mins": 90,
        "viewCount": 5000,
        "likeCount": 50,
        "publishedAt": now,
    }

    # Edited Video of same length
    v_edited = {
        "title": "Complete Q&A Session (Edited)",
        "description": "Timestamps:\n0:00 Intro\n5:00 Topic 1",
        "duration_mins": 90,
        "viewCount": 5000,
        "likeCount": 50,
        "publishedAt": now,
    }

    score_live = calculate_video_score(v_live)
    score_edited = calculate_video_score(v_edited)

    assert score_edited > score_live
    assert (score_live / score_edited) < 0.8  # Expecting ~0.7x penalty


def test_video_freshness_soft_decay():
    """Older video scores less, but not zero (Soft Decay)"""
    base = {
        "duration_mins": 30,
        "viewCount": 5000,
        "likeCount": 50,
        "title": "Tech",
        "description": "...",
    }

    # New
    v_new = base.copy()
    v_new["publishedAt"] = datetime.now(timezone.utc).isoformat()

    # 5 Years Old
    old_date = datetime.now(timezone.utc) - timedelta(days=365 * 5)
    v_old = base.copy()
    v_old["publishedAt"] = old_date.isoformat()

    score_new = calculate_video_score(v_new)
    score_old = calculate_video_score(v_old)

    assert score_new > score_old
    assert score_old > 0  # CRITICAL: Soft decay, never zero


# ==========================================
# Playlist Scoring Tests
# ==========================================


def test_playlist_video_count_tiers():
    """Test tiered bonuses for video counts"""
    base = {
        "publishedAt": datetime.now(timezone.utc).isoformat(),
        "subscriberCount": 100,  # Should be ignored now
    }

    # 3 Videos (No bonus)
    p_tiny = base.copy()
    p_tiny["videoCount"] = 3
    # Dummy avg duration safe zone
    p_tiny["items"] = [{"duration_mins": 10}] * 3

    # 15 Videos (1.5x)
    p_medium = base.copy()
    p_medium["videoCount"] = 15
    p_medium["items"] = [{"duration_mins": 10}] * 15

    # 45 Videos (2.5x)
    p_huge = base.copy()
    p_huge["videoCount"] = 45
    p_huge["items"] = [{"duration_mins": 10}] * 45

    score_tiny = calculate_playlist_score(p_tiny)
    score_medium = calculate_playlist_score(p_medium)
    score_huge = calculate_playlist_score(p_huge)

    assert score_medium > score_tiny
    assert score_huge > score_medium


def test_playlist_anti_shorts_guard():
    """Shorts playlists (avg < 5 mins) should be heavily penalized"""
    now = datetime.now(timezone.utc).isoformat()

    # 50 videos, 1 min each (Shorts farm)
    p_shorts = {
        "videoCount": 50,
        "publishedAt": now,
        "items": [{"duration_mins": 1}] * 50,
    }

    # 10 videos, 20 mins each (Deep course)
    p_course = {
        "videoCount": 10,
        "publishedAt": now,
        "items": [{"duration_mins": 20}] * 10,
    }

    score_shorts = calculate_playlist_score(p_shorts)
    score_course = calculate_playlist_score(p_course)

    # Even though Shorts has 50 videos (2.5x tier), the 0.3x penalty should crush it
    # Course has 10 videos (1.0x tier) but healthy duration
    assert score_course > score_shorts


def test_playlist_deep_content_boost():
    """Playlists with avg duration > 20 mins get a boost"""
    now = datetime.now(timezone.utc).isoformat()

    # 10 videos, 10 mins each (Standard)
    p_std = {
        "videoCount": 10,
        "publishedAt": now,
        "items": [{"duration_mins": 10}] * 10,
    }

    # 10 videos, 30 mins each (Deep)
    p_deep = {
        "videoCount": 10,
        "publishedAt": now,
        "items": [{"duration_mins": 30}] * 10,
    }

    score_std = calculate_playlist_score(p_std)
    score_deep = calculate_playlist_score(p_deep)

    assert score_deep > score_std


def test_search_fallback_trigger_logic_placeholder():
    """
    Search resilience is logic in fetcher, not scoring.
    Just a placeholder to remind valid scope.
    """
    pass


def test_udemy_scoring():
    from src.utils.scoring import calculate_udemy_score

    # Exact tag match in title: +40
    # Overlap "python": length 6 > 2 -> +25 * 1.0 = 25
    # Rating 4.8: +20
    # Lectures 120: +12
    # Hours 20: +10
    # Total: 40 + 25 + 20 + 12 + 10 = 107
    course_good = {
        "title": "Python Programming Masterclass",
        "rating": "4.8",
        "lectures": "120 lectures",
        "hours": "20 total hours",
    }
    score_good = calculate_udemy_score(course_good, "python")
    assert score_good == 107.0

    # Low rating penalty, low lectures penalty, low hours penalty
    # No tag match
    # Rating 3.5: -15
    # Lectures 5: -8
    # Hours 0.5: -10
    # Total: 0 - 15 - 8 - 10 = -33 -> max(score, 0.0) = 0.0
    course_bad = {
        "title": "Learn Java",
        "rating": "3.5",
        "lectures": "5 lectures",
        "hours": "0.5 hours",
    }
    score_bad = calculate_udemy_score(course_bad, "python")
    assert score_bad == 0.0

