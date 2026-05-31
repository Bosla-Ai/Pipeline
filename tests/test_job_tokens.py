import os
import time
import pytest
from src.security.job_tokens import (
    generate_token,
    verify_token,
    generate_job_access_token,
    generate_socket_token,
    get_secret,
)


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    # Set standard dev/test secret and turn off free HF mode for general tests
    monkeypatch.setattr("src.security.job_tokens.FREE_HF_MODE", False)
    monkeypatch.setattr(
        "src.security.job_tokens.PIPELINE_SHARED_SECRET", "test-secret-key"
    )


def test_token_signature_and_verification():
    payload = {"job_id": "abc123", "type": "socket"}
    token = generate_token(payload)

    # Verification should succeed
    verified = verify_token(token)
    assert verified is not None
    assert verified["job_id"] == "abc123"
    assert verified["type"] == "socket"


def test_tampered_token_rejected():
    payload = {"job_id": "abc123", "type": "socket"}
    token = generate_token(payload)

    # Tamper with signature
    parts = token.split(".")
    tampered = parts[0] + "." + parts[1][:-2] + "xx"

    assert verify_token(tampered) is None


def test_expired_token_rejected():
    # Expired 10 seconds ago
    payload = {"job_id": "abc123", "exp": int(time.time() - 10)}
    token = generate_token(payload)
    assert verify_token(token) is None


def test_dev_ephemeral_fallback(monkeypatch):
    # Ensure PIPELINE_SHARED_SECRET is None, and not in production mode
    monkeypatch.setattr("src.security.job_tokens.PIPELINE_SHARED_SECRET", "")
    monkeypatch.setenv("ENVIRONMENT", "development")

    secret = get_secret()
    assert secret is not None
    assert len(secret) == 32


def test_prod_fail_fast_on_missing_secret(monkeypatch):
    monkeypatch.setattr("src.security.job_tokens.PIPELINE_SHARED_SECRET", "")
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(ValueError) as exc:
        get_secret()
    assert "must be configured in production or Free-HF" in str(exc.value)


def test_free_hf_fail_on_missing_secret(monkeypatch):
    # Missing secret, FREE_HF_MODE=True
    monkeypatch.setattr("src.security.job_tokens.PIPELINE_SHARED_SECRET", "")
    monkeypatch.setattr("src.security.job_tokens.FREE_HF_MODE", True)

    with pytest.raises(ValueError) as exc:
        get_secret()
    assert "must be configured in production or Free-HF" in str(exc.value)


def test_free_hf_prevent_ephemeral_token_signing(monkeypatch):
    # Ephemeral signing occurs when secret is missing.
    # In Free-HF mode, missing secret must prevent token generation.
    monkeypatch.setattr("src.security.job_tokens.PIPELINE_SHARED_SECRET", "")
    monkeypatch.setattr("src.security.job_tokens.FREE_HF_MODE", True)

    with pytest.raises(ValueError) as exc:
        generate_token({"job_id": "abc123"})
    assert "must be configured in production or Free-HF" in str(exc.value)

