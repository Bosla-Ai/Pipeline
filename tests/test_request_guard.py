import pytest
from fastapi import HTTPException
from src.security.request_guard import validate_roadmap_request_data
from src.config.settings import (
    MAX_TAGS,
    MAX_TAG_LENGTH,
    MAX_TOTAL_TAG_CHARS,
)


def test_request_guard_valid_request():
    tags = [" Python ", "Docker ", "Python", ""]
    # Should normalize, trim, deduplicate, and discard empty strings
    normalized = validate_roadmap_request_data(tags, "en")
    assert normalized == ["Python", "Docker"]


def test_request_guard_invalid_language():
    with pytest.raises(HTTPException) as exc:
        validate_roadmap_request_data(["Python"], "fr")
    assert exc.value.status_code == 422
    assert "Invalid language" in exc.value.detail


def test_request_guard_too_many_tags():
    tags = [f"tag{i}" for i in range(MAX_TAGS + 2)]
    with pytest.raises(HTTPException) as exc:
        validate_roadmap_request_data(tags, "en")
    assert exc.value.status_code == 422
    assert "exceeding the maximum limit" in exc.value.detail


def test_request_guard_tag_too_long():
    tags = ["a" * (MAX_TAG_LENGTH + 10)]
    with pytest.raises(HTTPException) as exc:
        validate_roadmap_request_data(tags, "en")
    assert exc.value.status_code == 422
    assert "exceeds maximum length" in exc.value.detail


def test_request_guard_total_chars_exceeded(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "MAX_TOTAL_TAG_CHARS", 1000)
    # Generate 10 unique tags, each of 110 characters
    tags = [f"{i:03d}" + "a" * 107 for i in range(10)]
    with pytest.raises(HTTPException) as exc:
        validate_roadmap_request_data(tags, "en")
    assert exc.value.status_code == 422
    assert "exceeds limit of" in exc.value.detail


def test_request_guard_invalid_sources():
    with pytest.raises(HTTPException) as exc:
        validate_roadmap_request_data(["Python"], "en", sources=["invalid_source"])
    assert exc.value.status_code == 422
    assert "Invalid source value" in exc.value.detail


def test_request_guard_invalid_job_id():
    with pytest.raises(HTTPException) as exc:
        validate_roadmap_request_data(["Python"], "en", job_id="job/../123")
    assert exc.value.status_code == 422
    assert "job_id must only contain" in exc.value.detail


def test_request_guard_empty_tags_rejected():
    with pytest.raises(HTTPException) as exc:
        validate_roadmap_request_data([], "en")
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        validate_roadmap_request_data(["  ", ""], "en")
    assert exc.value.status_code == 422
