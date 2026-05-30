import pytest
import os
from src.security.socket_auth import validate_socket_connection
from src.security.job_tokens import generate_socket_token


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    monkeypatch.setattr("src.security.job_tokens.FREE_HF_MODE", False)
    monkeypatch.setattr(
        "src.security.job_tokens.PIPELINE_SHARED_SECRET", "test-secret-key"
    )


def test_socket_auth_dev_disabled(monkeypatch):
    # Set dev mode with REQUIRE_SOCKET_TOKEN=false
    monkeypatch.setattr("src.security.socket_auth.REQUIRE_SOCKET_TOKEN", False)

    auth = {"jobId": "job123"}
    is_valid, reason, job_id = validate_socket_connection(auth)
    assert is_valid is True
    assert job_id == "job123"


def test_socket_auth_required_valid_token(monkeypatch):
    monkeypatch.setattr("src.security.socket_auth.REQUIRE_SOCKET_TOKEN", True)

    token = generate_socket_token("job123")
    auth = {"jobId": "job123", "socketToken": token}

    is_valid, reason, job_id = validate_socket_connection(auth)
    assert is_valid is True
    assert job_id == "job123"


def test_socket_auth_missing_token(monkeypatch):
    monkeypatch.setattr("src.security.socket_auth.REQUIRE_SOCKET_TOKEN", True)

    auth = {"jobId": "job123"}
    is_valid, reason, job_id = validate_socket_connection(auth)
    assert is_valid is False
    assert reason == "missing_socket_token"


def test_socket_auth_job_id_mismatch(monkeypatch):
    monkeypatch.setattr("src.security.socket_auth.REQUIRE_SOCKET_TOKEN", True)

    token = generate_socket_token("job999")
    auth = {"jobId": "job123", "socketToken": token}

    is_valid, reason, job_id = validate_socket_connection(auth)
    assert is_valid is False
    assert reason == "job_id_mismatch"
