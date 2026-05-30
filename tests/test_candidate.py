import pytest
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
        "hours": "20 hours",
        "lectures": "120 lectures",
        "lectureCount": 120,
        "lecture_count": 120,
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
    assert "subscriberCount" not in serialized
    assert "publishedAt" not in serialized
    assert "videoCount" not in serialized


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


def test_udemy_cheap_ranking():
    # Verify that Udemy candidates are ranked using calculate_udemy_score
    raw = {
        "contentType": "Course",
        "title": "Python Programming Masterclass",
        "instructor": "Tim Buchalka",
        "rating": "4.8",
        "price": "$19.99",
        "description": "40 hours | 200 lectures",
        "url": "https://www.udemy.com/course/python",
        "hours": "40 hours",
        "lectures": "200 lectures",
        "lectureCount": 200,
        "lecture_count": 200,
        "score": 0.0,
    }
    candidate = Candidate.from_dict(raw, SourceName.UDEMY, "python")
    score = cheap_rank_candidate(candidate, "python")
    assert score > 50.0  # high match score


def test_udemy_fetcher_no_fake_youtube_fields():
    from unittest.mock import MagicMock
    from src.fetchers.videos.udemy_fetcher import UdemyFetcher

    fetcher = UdemyFetcher(["python"])
    card = MagicMock()

    selection_mock = MagicMock()
    link_mock = MagicMock()
    link_mock.text = "Python Programming"
    link_mock.attrib = {"href": "/course/python/"}

    selection_mock.first = link_mock
    selection_mock.__iter__.return_value = []
    card.css.return_value = selection_mock

    course_data = fetcher._extract_from_card(card, "python")
    assert course_data is not None
    assert "subscriberCount" not in course_data
    assert "publishedAt" not in course_data
    assert "videoCount" not in course_data
    assert "hours" in course_data
    assert "lectures" in course_data
    assert "lectureCount" in course_data


def test_coursera_scoring_explanation():
    # 1. Verify score is unchanged when explain=False
    score_normal = calculate_coursera_score(
        title="Python specialization course",
        tag="python",
        url="https://coursera.org/specializations/python",
        search_position=2,
        explain=False,
    )
    # tag exact match: 50
    # tag word overlap: 30
    # type specialization: 10
    # search position (10 - 2): 8
    # Total: 98
    assert score_normal == 98.0

    # 2. Verify explain=True structure and sourceType
    res = calculate_coursera_score(
        title="Python specialization course",
        tag="python",
        url="https://coursera.org/specializations/python",
        search_position=2,
        explain=True,
    )
    assert isinstance(res, dict)
    assert res["score"] == 98.0
    
    explanation = res["explanation"]
    assert explanation["finalScore"] == 98.0
    assert explanation["source"] == "coursera"
    assert explanation["sourceType"] == "specialization"
    assert "title_exact_tag_match" in explanation["reasonCodes"]
    assert "tag_word_overlap" in explanation["reasonCodes"]
    assert "type_bonus" in explanation["reasonCodes"]
    assert "search_position_bonus" in explanation["reasonCodes"]

    # 3. Verify breakdown sums to final score
    breakdown = explanation["scoreBreakdown"]
    assert sum(breakdown.values()) == 98.0


def test_cheap_rank_candidate_explanation():
    # YouTube candidate with penalty
    raw = {
        "title": "React Tutorial Scam Review",
        "url": "https://youtube.com/watch?v=123",
        "duration_minutes": 5.0,  # short duration penalty: *0.5
        "rating": 4.8,  # rating boost: +10.0
        "score": 10.0,
    }
    candidate = Candidate.from_dict(raw, SourceName.YOUTUBE, "react")
    
    # explain=False
    score_normal = cheap_rank_candidate(candidate, "react", explain=False)
    # pre-penalty = 10.0 (base) + 15.0 (relevance: overlap + exact match) + 10.0 (rating) = 35.0
    # penalty: scam (*0.6), review (*0.6), short duration (*0.5) -> 0.18
    # final = 35.0 * 0.18 = 6.3
    assert score_normal == 6.3

    # explain=True
    res = cheap_rank_candidate(candidate, "react", explain=True)
    assert isinstance(res, dict)
    assert res["score"] == 6.3
    
    explanation = res["explanation"]
    assert explanation["finalScore"] == 6.3
    assert explanation["source"] == "youtube"
    assert "tag_word_overlap" in explanation["reasonCodes"]
    assert "title_exact_tag_match" in explanation["reasonCodes"]
    assert "negative_keyword_penalty" in explanation["reasonCodes"]
    assert "short_duration_penalty" in explanation["reasonCodes"]
    assert "high_rating_boost" in explanation["reasonCodes"]

    assert explanation["penaltyMultiplier"] == 0.18
    
    # Verify breakdown sums to final score
    breakdown = explanation["scoreBreakdown"]
    assert breakdown["penaltyAdjustment"] == pytest.approx(6.3 - 35.0)
    assert sum(breakdown.values()) == pytest.approx(6.3)


def test_ranking_debug_flag_behavior(monkeypatch):
    raw = {
        "title": "React Course",
        "url": "https://youtube.com/watch?v=123",
        "score": 10.0,
    }
    candidate = Candidate.from_dict(raw, SourceName.YOUTUBE, "react")

    # 1. By default, debug output is absent and ranking_explanation is None
    monkeypatch.delenv("ENABLE_RANKING_DEBUG", raising=False)
    ranked = cheap_rank([candidate], "react")
    assert ranked[0].ranking_explanation is None
    
    serialized = ranked[0].to_dict()
    assert "_debug" not in serialized
    assert "rankingExplanation" not in serialized

    # 2. Enabled case: ENABLE_RANKING_DEBUG=true (case-insensitive checking)
    monkeypatch.setenv("ENABLE_RANKING_DEBUG", "TrUe")
    ranked_debug = cheap_rank([candidate], "react")
    assert ranked_debug[0].ranking_explanation is not None
    
    serialized_debug = ranked_debug[0].to_dict()
    assert "_debug" in serialized_debug
    assert "rankingExplanation" in serialized_debug["_debug"]
    # Verify that top-level rankingExplanation is NOT present
    assert "rankingExplanation" not in serialized_debug


def test_fallback_negative_score_regression():
    candidate = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="unrelated",
        url="https://youtube.com/watch?v=x",
        raw_score=-10.0,
    )

    assert cheap_rank_candidate(candidate, "python", explain=False) == -10.0
    
    res = cheap_rank_candidate(candidate, "python", explain=True)
    assert res["score"] == -10.0
    assert sum(res["explanation"]["scoreBreakdown"].values()) == pytest.approx(-10.0)



