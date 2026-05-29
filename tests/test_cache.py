from unittest import mock
from src.utils.cache import generate_cache_key


def test_generate_cache_key_default_version():
    # Test default version (v1)
    key = generate_cache_key("udemy", "python programming", "en")
    assert key == "v1:udemy:python_programming:en"


def test_generate_cache_key_custom_version():
    with mock.patch("src.utils.cache.CACHE_VERSION", "v2"):
        key = generate_cache_key("youtube", "react js", "ar")
        assert key == "v2:youtube:react_js:ar"


def test_generate_cache_key_no_version():
    with mock.patch("src.utils.cache.CACHE_VERSION", ""):
        key = generate_cache_key("coursera", "machine learning", "en")
        assert key == "coursera:machine_learning:en"
