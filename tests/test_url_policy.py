from src.security.url_policy import is_valid_url


def test_accepts_youtube_watch_url():
    assert is_valid_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True
    assert is_valid_url("https://m.youtube.com/watch?v=dQw4w9WgXcQ") is True


def test_accepts_youtube_playlist_url():
    assert is_valid_url("https://youtube.com/playlist?list=PL33026A55") is True


def test_accepts_youtu_be_url():
    assert is_valid_url("https://youtu.be/dQw4w9WgXcQ") is True


def test_rejects_javascript_url():
    assert is_valid_url("javascript:alert(1)") is False


def test_rejects_localhost_url():
    assert is_valid_url("http://localhost:8000/test") is False
    assert is_valid_url("https://127.0.0.1/test") is False
    assert is_valid_url("http://192.168.1.1/test") is False


def test_rejects_unknown_domain():
    assert is_valid_url("https://evil.com/malware") is False
    assert is_valid_url("https://google.com") is False
