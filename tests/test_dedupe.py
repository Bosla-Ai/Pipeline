from src.engine.models import Candidate, SourceName
from src.ranking.dedupe import dedupe_candidates, token_set_jaccard


def test_dedupes_same_youtube_id_with_different_url_forms():
    c1 = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Course",
        url="https://youtube.com/watch?v=12345",
    )
    c2 = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Course Different Title",
        url="https://youtu.be/12345",
    )
    res = dedupe_candidates([c1, c2])
    assert len(res) == 1
    assert res[0].url == "https://youtube.com/watch?v=12345"


def test_dedupes_same_playlist_id():
    c1 = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Playlist",
        url="https://youtube.com/playlist?list=PL_123",
    )
    c2 = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Playlist 2",
        url="https://www.youtube.com/playlist?list=PL_123",
    )
    res = dedupe_candidates([c1, c2])
    assert len(res) == 1


def test_dedupes_tracking_url_variants():
    c1 = Candidate(
        source=SourceName.UDEMY,
        tag="python",
        title="Udemy Course",
        url="https://www.udemy.com/course/python-basics/?couponCode=discount",
    )
    c2 = Candidate(
        source=SourceName.UDEMY,
        tag="python",
        title="Udemy Course Different",
        url="https://www.udemy.com/course/python-basics/?couponCode=another",
    )
    res = dedupe_candidates([c1, c2])
    assert len(res) == 1


def test_dedupes_near_duplicate_titles_same_source():
    c1 = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Full Course for Beginners",
        url="https://youtube.com/watch?v=abc",
    )
    c2 = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Tutorial for Beginners!",
        url="https://youtube.com/watch?v=def",
    )
    res = dedupe_candidates([c1, c2])
    assert len(res) == 1


def test_keeps_similar_titles_from_different_sources():
    c1 = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="Python Full Course for Beginners",
        url="https://youtube.com/watch?v=abc",
    )
    c2 = Candidate(
        source=SourceName.UDEMY,
        tag="python",
        title="Python Full Course for Beginners",
        url="https://udemy.com/course/python",
    )
    res = dedupe_candidates([c1, c2])
    assert len(res) == 2


def test_keeps_candidates_without_url():
    c1 = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="No URL course 1",
        url="",
    )
    c2 = Candidate(
        source=SourceName.YOUTUBE,
        tag="python",
        title="No URL course 2",
        url="",
    )
    res = dedupe_candidates([c1, c2])
    assert len(res) == 2
