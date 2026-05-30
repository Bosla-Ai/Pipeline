from src.providers.youtube_legacy_adapter import normalize_youtube_candidate


def test_candidate_from_ytdlp_has_required_fields():
    raw = {
        "title": "Python full course",
        "url": "https://youtu.be/rfscVS0vtbw",
        "viewCount": 5000,
        "duration_minutes": 120,
    }
    candidate = normalize_youtube_candidate(raw, "python")
    assert candidate is not None
    assert candidate.title == "Python full course"
    assert candidate.url == "https://www.youtube.com/watch?v=rfscVS0vtbw"
    assert candidate.content_id == "rfscVS0vtbw"
    assert candidate.metadata["content_type"] == "video"


def test_missing_content_type_does_not_crash():
    raw = {
        "title": "Some video",
        "url": "https://www.youtube.com/watch?v=12345",
    }
    candidate = normalize_youtube_candidate(raw, "python")
    assert candidate is not None
    assert candidate.metadata["content_type"] == "video"
    assert candidate.content_id == "12345"
