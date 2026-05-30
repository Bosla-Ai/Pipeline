import os
from src.config.settings import FREE_HF_MODE
from src.security.job_tokens import verify_token

# Always require socket token in production/free-HF mode
if (os.getenv("ENVIRONMENT") == "production") or FREE_HF_MODE:
    REQUIRE_SOCKET_TOKEN = True
else:
    REQUIRE_SOCKET_TOKEN = os.getenv("REQUIRE_SOCKET_TOKEN", "true").lower() == "true"


def validate_socket_connection(auth: dict) -> tuple[bool, str | None, str | None]:
    """
    Validate socket connection payload.
    Returns: (is_valid, error_reason, job_id)
    """
    auth = auth or {}
    job_id = auth.get("jobId") or auth.get("job_id")
    token = auth.get("socketToken") or auth.get("socket_token")

    if not job_id:
        return False, "missing_job_id", None

    if not REQUIRE_SOCKET_TOKEN:
        return True, None, job_id

    if not token:
        return False, "missing_socket_token", None

    payload = verify_token(token)
    if not payload:
        return False, "invalid_socket_token", None

    if payload.get("type") != "socket":
        return False, "invalid_token_type", None

    if payload.get("job_id") != job_id:
        return False, "job_id_mismatch", None

    return True, None, job_id
