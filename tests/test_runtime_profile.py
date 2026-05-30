import os
import importlib
import pytest


def test_free_hf_mode_defaults_and_caps(monkeypatch):
    # Enforce FREE_HF_MODE=true
    monkeypatch.setenv("FREE_HF_MODE", "true")
    monkeypatch.setenv(
        "SOCKET_WAIT_TIMEOUT", "invalid"
    )  # should fallback to default in _positive_int_env

    # Reload modules to apply monkeypatched env variables
    import src.config.runtime_profile as rp
    import src.engine.runtime as rt

    importlib.reload(rp)
    importlib.reload(rt)

    assert rp.FREE_HF_MODE is True
    assert rp.DISABLE_YOUTUBE_API is True
    assert rp.ENABLE_UDEMY is False
    assert rp.ENABLE_COURSERA is False
    assert rp.ENABLE_BROWSER_SCRAPING is False
    assert rp.SKIP_GLOBAL_DRIVER_INIT is True

    limits = rt.load_runtime_limits()
    assert limits.max_concurrent_jobs == 1
    assert limits.youtube_provider_concurrency == 1
    assert limits.frontend_ai_concurrency == 1
    assert (
        limits.socket_wait_timeout_seconds == 3
    )  # default fallback value for invalid env


def test_non_free_hf_mode_custom_limits(monkeypatch):
    # Enforce FREE_HF_MODE=false
    monkeypatch.setenv("FREE_HF_MODE", "false")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "5")
    monkeypatch.setenv("SOCKET_WAIT_TIMEOUT", "15")

    import src.config.runtime_profile as rp
    import src.engine.runtime as rt

    importlib.reload(rp)
    importlib.reload(rt)

    assert rp.FREE_HF_MODE is False

    limits = rt.load_runtime_limits()
    assert limits.max_concurrent_jobs == 5
    assert limits.socket_wait_timeout_seconds == 15
