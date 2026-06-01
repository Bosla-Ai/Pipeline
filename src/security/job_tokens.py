import os
import hmac
import hashlib
import json
import base64
import time
from src.config.settings import PIPELINE_SHARED_SECRET, FREE_HF_MODE

_EPHEMERAL_SECRET = os.urandom(32)
_warned_once = False


def get_secret() -> bytes:
    global _warned_once
    if PIPELINE_SHARED_SECRET:
        return PIPELINE_SHARED_SECRET.encode()

    is_prod = os.getenv("ENVIRONMENT") == "production"
    if is_prod or FREE_HF_MODE:
        raise ValueError(
            "PIPELINE_SHARED_SECRET must be configured in production or Free-HF mode."
        )

    if not _warned_once:
        print(
            "WARNING: PIPELINE_SHARED_SECRET is not set in development mode. Using a process-local ephemeral key."
        )
        _warned_once = True

    return _EPHEMERAL_SECRET


def generate_token(payload: dict) -> str:
    secret = get_secret()
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    signature = hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{payload_b64}.{sig_b64}"


def verify_token(token: str) -> dict | None:
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_b64, sig_b64 = parts
        secret = get_secret()

        # Pad b64 string if necessary
        payload_b64_padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        sig_b64_padded = sig_b64 + "=" * (-len(sig_b64) % 4)

        expected_sig = hmac.new(secret, payload_b64.encode(), hashlib.sha256).digest()
        expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).decode().rstrip("=")

        if not hmac.compare_digest(sig_b64, expected_sig_b64):
            return None

        payload_bytes = base64.urlsafe_b64decode(payload_b64_padded.encode())
        payload = json.loads(payload_bytes.decode())

        exp = payload.get("exp")
        if exp and time.time() > exp:
            return None

        return payload
    except Exception:
        return None


def generate_job_access_token(job_id: str, ttl_seconds: int = 900) -> str:
    payload = {
        "type": "job_access",
        "job_id": job_id,
        "iat": int(time.time()),
        "exp": int(time.time() + ttl_seconds),
    }
    return generate_token(payload)


def generate_socket_token(job_id: str, ttl_seconds: int | None = None) -> str:
    if ttl_seconds is None:
        from src.engine.runtime import runtime_limits

        ttl_seconds = int(os.getenv(
            "SOCKET_TOKEN_TTL_SECONDS",
            str(max(300, runtime_limits.full_job_timeout_seconds + 120)),
        ))

    payload = {
        "type": "socket",
        "job_id": job_id,
        "iat": int(time.time()),
        "exp": int(time.time() + ttl_seconds),
    }
    return generate_token(payload)
