from src.engine.models import Candidate, SourceName


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
        {"title": "Go Tutorial", "url": "https://go.dev/DOC/tutorial ", "score": 12.0},  # Case & whitespace diff
        {"title": "Learn Go Programming", "url": "https://go.dev/learn", "score": 15.0},
    ]
    candidates = [Candidate.from_dict(r, SourceName.COURSERA, "go") for r in raw_list]

    seen_urls = set()
    deduped = []
    for c in candidates:
        url_norm = c.url.strip().lower()
        if url_norm not in seen_urls:
            seen_urls.add(url_norm)
            deduped.append(c)

    assert len(deduped) == 2
    assert deduped[0].title == "Intro to Go"
    assert deduped[1].title == "Learn Go Programming"


def test_cheap_ranking():
    raw_list = [
        {"title": "React C", "url": "url3", "score": 25.0},
        {"title": "React A", "url": "url1", "score": 90.0},
        {"title": "React B", "url": "url2", "score": 50.0},
        {"title": "React D", "url": "url4", "score": 10.0},
    ]
    candidates = [Candidate.from_dict(r, SourceName.YOUTUBE, "react") for r in raw_list]

    # Cheap rank / prune with limit = 2
    ranked = sorted(candidates, key=lambda x: x.raw_score, reverse=True)[:2]

    assert len(ranked) == 2
    assert ranked[0].title == "React A"
    assert ranked[0].raw_score == 90.0
    assert ranked[1].title == "React B"
    assert ranked[1].raw_score == 50.0
