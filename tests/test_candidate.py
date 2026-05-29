from src.engine.models import Candidate, SourceName
from src.ranking.dedupe import dedupe_candidates, normalize_url
from src.ranking.cheap_ranker import (
    cheap_rank,
    cheap_rank_candidate,
    calculate_coursera_score,
)


def test_youtube_normalization():
    raw = {
        "contentType": "Playlist",
        "contentId": "PL123",
        "url": "https://www.youtube.com/playlist?list=PL123",
        "title": "React Tutorial",
        "description": "Learn React from scratch",
        "videoCount": 25,
        "publishedAt": "2024-05-01T00:00:00Z",
        "channelTitle": "CodeAcademy",
        "subscriberCount": 1000000,
        "avg_views": 50000,
        "avg_likes": 2000,
        "score": 42.5,
    }
    candidate = Candidate.from_dict(raw, SourceName.YOUTUBE, "react js")

    assert candidate.source == SourceName.YOUTUBE
    assert candidate.tag == "react js"
    assert candidate.title == "React Tutorial"
    assert candidate.url == "https://www.youtube.com/playlist?list=PL123"
    assert candidate.content_id == "PL123"
    assert candidate.description == "Learn React from scratch"
    assert candidate.channel_or_provider == "CodeAcademy"
    assert candidate.view_count == 50000
    assert candidate.like_count == 2000
    assert candidate.lecture_count == 25
    assert candidate.published_at == "2024-05-01T00:00:00Z"
    assert candidate.raw_score == 42.5

    # Test serialization back to dict
    serialized = candidate.to_dict()
    assert serialized["contentType"] == "Playlist"
    assert serialized["score"] == 42.5
    assert serialized["url"] == "https://www.youtube.com/playlist?list=PL123"


def test_udemy_normalization():
    raw = {
        "contentType": "Course",
        "title": "Python for Beginners",
        "instructor": "John Doe",
        "rating": "4.7",
        "price": "$19.99",
        "description": "20 hours | 120 lectures",
        "url": "https://www.udemy.com/course/python",
        "imageUrl": "https://img.udemy.com/python.jpg",
        "platform": "Udemy",
        "videoCount": 120,
        "subscriberCount": 0,
        "publishedAt": "",
        "score": 85.0,
    }
    candidate = Candidate.from_dict(raw, SourceName.UDEMY, "python")

    assert candidate.source == SourceName.UDEMY
    assert candidate.tag == "python"
    assert candidate.title == "Python for Beginners"
    assert candidate.channel_or_provider == "John Doe"
    assert candidate.rating == 4.7
    assert candidate.lecture_count == 120
    assert candidate.raw_score == 85.0

    serialized = candidate.to_dict()
    assert serialized["price"] == "$19.99"
    assert serialized["instructor"] == "John Doe"


def test_candidate_deduplication():
    # Simulate duplicate URLs
    raw_list = [
        {"title": "Intro to Go", "url": "https://go.dev/doc/tutorial", "score": 10.0},
        {
            "title": "Go Tutorial",
            "url": "https://go.dev/DOC/tutorial ",
            "score": 12.0,
        },  # Case & whitespace diff
        {"title": "Learn Go Programming", "url": "https://go.dev/learn", "score": 15.0},
    ]
    candidates = [Candidate.from_dict(r, SourceName.COURSERA, "go") for r in raw_list]
    deduped = dedupe_candidates(candidates)

    assert len(deduped) == 2
    assert deduped[0].title == "Intro to Go"
    assert deduped[1].title == "Learn Go Programming"


def test_url_normalization_edge_cases():
    # Trailing slash dedupe
    url1 = "https://example.com/course/"
    url2 = "https://example.com/course"
    assert normalize_url(url1) == normalize_url(url2)

    # UTM and Coupon query parameter removal
    url_utm = "https://example.com/course?couponcode=SALE100&utm_source=fb&utm_medium=cpc&trackingid=abc"
    assert normalize_url(url_utm) == "https://example.com/course"


def test_cheap_ranking():
    raw_list = [
        {"title": "React C", "url": "url3", "score": 25.0},
        {"title": "React A", "url": "url1", "score": 90.0},
        {"title": "React B", "url": "url2", "score": 50.0},
        {"title": "React D", "url": "url4", "score": 10.0},
    ]
    candidates = [Candidate.from_dict(r, SourceName.YOUTUBE, "react") for r in raw_list]
    ranked = cheap_rank(candidates, "react")

    # Verify sorting and that raw_score is updated to the cheap-rank score
    assert len(ranked) == 4
    assert ranked[0].title == "React A"
    # Should be greater than the baseline of 90 due to tag-word match boosts
    assert ranked[0].raw_score > 90.0
    assert ranked[1].title == "React B"


def test_coursera_scoring_certificates():
    # professional-certificates outranks learn
    cert_score = calculate_coursera_score(
        title="Python",
        tag="python",
        url="https://coursera.org/professional-certificates/python",
        search_position=1,
    )
    learn_score = calculate_coursera_score(
        title="Python",
        tag="python",
        url="https://coursera.org/learn/python",
        search_position=1,
    )
    assert cert_score > learn_score


def test_negative_keyword_penalty():
    cand_ok = Candidate.from_dict(
        {"title": "Python Programming", "url": "https://ok.com", "score": 50.0},
        SourceName.YOUTUBE,
        "python",
    )
    cand_penalized = Candidate.from_dict(
        {"title": "Python Programming Review", "url": "https://bad.com", "score": 50.0},
        SourceName.YOUTUBE,
        "python",
    )

    score_ok = cheap_rank_candidate(cand_ok, "python")
    score_penalized = cheap_rank_candidate(cand_penalized, "python")
    assert score_penalized < score_ok


def test_raw_score_float_casting():
    # String raw_score is cast to float
    cand_str = Candidate.from_dict(
        {"title": "Test", "url": "https://test.com", "score": "45.5"},
        SourceName.YOUTUBE,
        "test",
    )
    assert cand_str.raw_score == 45.5

    # Invalid raw_score casts to 0.0
    cand_invalid = Candidate.from_dict(
        {"title": "Test", "url": "https://test.com", "score": "invalid-score"},
        SourceName.YOUTUBE,
        "test",
    )
    assert cand_invalid.raw_score == 0.0
