from src.cache.keys import get_raw_ytdlp_key, get_normalized_key, get_ranked_key


def test_raw_ytdlp_key():
    key = get_raw_ytdlp_key("python course", "en")
    assert "pipeline:v2:raw:youtube_yt_dlp" in key
    assert "lang=en" in key
    assert "q=" in key


def test_normalized_key():
    key = get_normalized_key("youtube", "abc123hash")
    assert "pipeline:v2:normalized:source=youtube" in key
    assert "raw=abc123hash" in key


def test_ranked_key():
    key = get_ranked_key("python", "youtube", "xyz789hash")
    assert "pipeline:v2:ranked:tag=" in key
    assert "source=youtube" in key
    assert "candidate_set=xyz789hash" in key
