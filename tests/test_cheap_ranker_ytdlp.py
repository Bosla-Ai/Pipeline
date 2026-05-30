from src.engine.models import Candidate, SourceName, TopicScope
from src.ranking.cheap_ranker import cheap_rank, cheap_rank_candidate


def test_broad_python_prefers_full_course():
    # Setup candidates
    video_cand = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Tutorial",
        url="https://youtube.com/watch?v=123",
        duration_minutes=15,
    )
    playlist_cand = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Full Course",
        url="https://youtube.com/playlist?list=PL123",
    )

    ranked = cheap_rank(
        [video_cand, playlist_cand], "python", scope=TopicScope.TECHNOLOGY
    )
    # Playlist should be first
    assert ranked[0].url == playlist_cand.url


def test_atomic_error_prefers_specific_video():
    video_cand = Candidate(
        source=SourceName.YOUTUBE,
        tag="fix docker permission denied error",
        title="How to fix docker permission denied error",
        url="https://youtube.com/watch?v=123",
        duration_minutes=5,
    )
    playlist_cand = Candidate(
        source=SourceName.YOUTUBE,
        tag="fix docker permission denied error",
        title="Docker Series Playlist",
        url="https://youtube.com/playlist?list=PL123",
    )

    ranked = cheap_rank(
        [playlist_cand, video_cand],
        "fix docker permission denied error",
        scope=TopicScope.DEBUGGING_QUERY,
    )
    # Video should be first
    assert ranked[0].url == video_cand.url


def test_missing_metrics_does_not_crash():
    cand = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Course",
        url="https://youtube.com/watch?v=123",
        # All optional fields as None
        duration_minutes=None,
        view_count=None,
        like_count=None,
        rating=None,
    )
    score = cheap_rank_candidate(cand, "python")
    assert isinstance(score, float)
    assert score >= 0.0


def test_shorts_title_penalized():
    normal = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Tutorial",
        url="https://youtube.com/watch?v=123",
    )
    shorts = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Tutorial #shorts",
        url="https://youtube.com/watch?v=456",
    )
    score_normal = cheap_rank_candidate(normal, "python")
    score_shorts = cheap_rank_candidate(shorts, "python")
    assert score_shorts < score_normal


def test_arabic_title_not_wrongly_filtered():
    normal = Candidate(
        source=SourceName.YOUTUBE,
        tag="بايثون للمبتدئين",
        title="دورة تعلم بايثون للمبتدئين بالكامل",
        url="https://youtube.com/watch?v=123",
    )
    score = cheap_rank_candidate(normal, "بايثون للمبتدئين")
    assert score > 0.0
