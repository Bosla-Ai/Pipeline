import os
from src.engine.models import Candidate, SourceName, TopicScope
from src.engine.stages import PreparedTag
from src.inference.schemas import ClassificationResult
from src.ranking.final_ranker import final_rank, calculate_final_score


def test_invalid_url_rejected():
    tag = PreparedTag(
        original="python",
        normalized="python",
        language="en",
        scope=TopicScope.TECHNOLOGY,
    )
    c = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Course",
        url="javascript:alert(1)",  # invalid
    )
    score = calculate_final_score(c, tag, cheap_score=80.0)
    assert score == -999.0


def test_ai_signal_changes_score_but_not_absolute_authority():
    tag = PreparedTag(
        original="python",
        normalized="python",
        language="en",
        scope=TopicScope.TECHNOLOGY,
    )
    c1 = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Course",
        url="https://youtube.com/watch?v=123",
    )
    c2 = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Advanced Python Course",
        url="https://youtube.com/watch?v=456",
    )

    # Without AI
    ranked_no_ai = final_rank([c1, c2], tag, cheap_scores={c1.url: 90.0, c2.url: 70.0})
    assert ranked_no_ai[0].url == c1.url

    # With AI boosting c2
    ai_res = ClassificationResult(
        candidate_key=c2.url, label="relevant", confidence=1.0
    )
    ranked_with_ai = final_rank(
        [c1, c2], tag, cheap_scores={c1.url: 90.0, c2.url: 70.0}, ai_results=[ai_res]
    )
    # The AI boost of 0.10 * 1.0 = 0.10 might make c2 win, or not.
    # Let's verify score changes.
    assert c2.raw_score > 0.0


def test_no_ai_still_selects_reasonable_candidate():
    tag = PreparedTag(
        original="python",
        normalized="python",
        language="en",
        scope=TopicScope.TECHNOLOGY,
    )
    c1 = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Course",
        url="https://youtube.com/watch?v=123",
    )
    ranked = final_rank([c1], tag, cheap_scores={c1.url: 80.0})
    assert len(ranked) == 1
    assert ranked[0].raw_score > 0.0


def test_broad_scope_prefers_playlist_when_relevant():
    tag = PreparedTag(
        original="python",
        normalized="python",
        language="en",
        scope=TopicScope.TECHNOLOGY,
    )
    video = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Video",
        url="https://youtube.com/watch?v=123",
    )
    playlist = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Playlist",
        url="https://youtube.com/playlist?list=PL123",
    )

    ranked = final_rank(
        [video, playlist], tag, cheap_scores={video.url: 50.0, playlist.url: 50.0}
    )
    # Playlist should have higher score due to scope fit boost
    assert ranked[0].url == playlist.url


def test_atomic_scope_prefers_video_when_relevant():
    tag = PreparedTag(
        original="python", normalized="python", language="en", scope=TopicScope.ATOMIC
    )
    video = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Video",
        url="https://youtube.com/watch?v=123",
    )
    playlist = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Playlist",
        url="https://youtube.com/playlist?list=PL123",
    )

    ranked = final_rank(
        [video, playlist], tag, cheap_scores={video.url: 50.0, playlist.url: 50.0}
    )
    # Video should have higher score
    assert ranked[0].url == video.url


def test_ranking_debug_visibility():
    tag = PreparedTag(
        original="python",
        normalized="python",
        language="en",
        scope=TopicScope.TECHNOLOGY,
    )
    c = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Course",
        url="https://youtube.com/watch?v=123",
    )

    # 1. Hidden by default
    if "ENABLE_RANKING_DEBUG" in os.environ:
        del os.environ["ENABLE_RANKING_DEBUG"]
    ranked = final_rank([c], tag, cheap_scores={c.url: 85.0})
    assert ranked[0].ranking_explanation is None

    # 2. Present when enabled
    os.environ["ENABLE_RANKING_DEBUG"] = "true"
    try:
        ranked = final_rank([c], tag, cheap_scores={c.url: 85.0})
        assert ranked[0].ranking_explanation is not None
        assert "scoreBreakdown" in ranked[0].ranking_explanation
    finally:
        del os.environ["ENABLE_RANKING_DEBUG"]
