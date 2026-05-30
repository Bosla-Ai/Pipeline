import json
import re
from fastapi import HTTPException
from src.config import settings
from src.engine.models import CourseSource


def validate_roadmap_request_data(
    tags: list[str],
    language: str,
    sources: list[str] | None = None,
    tag_checkpoints: dict | None = None,
    job_id: str | None = None,
) -> list[str]:
    """
    Validates and normalizes incoming roadmap requests.
    Raises fastapi.HTTPException(status_code=422) if validation fails.
    Returns the normalized, deduped list of tags.
    """
    if language not in ("en", "ar"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid language '{language}'. Supported languages are 'en' and 'ar'.",
        )

    if not tags:
        raise HTTPException(status_code=422, detail="Tag list cannot be empty.")

    normalized = []
    seen = set()
    total_chars = 0

    for tag in tags:
        if not tag:
            continue
        cleaned = " ".join(tag.strip().split())
        if not cleaned:
            continue

        # Check individual tag length
        if len(cleaned) > settings.MAX_TAG_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"Tag exceeds maximum length of {settings.MAX_TAG_LENGTH} characters: '{cleaned[:30]}...'",
            )

        lower_cleaned = cleaned.lower()
        if lower_cleaned not in seen:
            seen.add(lower_cleaned)
            normalized.append(cleaned)
            total_chars += len(cleaned)

    if not normalized:
        raise HTTPException(
            status_code=422, detail="Request must contain at least one non-empty tag."
        )

    # Check tags count limit
    if len(normalized) > settings.MAX_TAGS:
        raise HTTPException(
            status_code=422,
            detail=f"Request contains {len(normalized)} tags, exceeding the maximum limit of {settings.MAX_TAGS}.",
        )

    # Check total characters limit
    if total_chars > settings.MAX_TOTAL_TAG_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Total tag character count ({total_chars}) exceeds limit of {settings.MAX_TOTAL_TAG_CHARS}.",
        )

    if sources is not None:
        if not isinstance(sources, list):
            raise HTTPException(status_code=422, detail="Sources must be a list.")
        if len(sources) > 3:
            raise HTTPException(
                status_code=422, detail="Sources list exceeds maximum allowed length."
            )

        valid_sources = {s.value for s in CourseSource}
        for s in sources:
            if s not in valid_sources:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid source value '{s}'. Valid sources are {list(valid_sources)}.",
                )

    if tag_checkpoints is not None:
        try:
            serialized = json.dumps(tag_checkpoints)
            if len(serialized) > 20000:
                raise HTTPException(
                    status_code=422,
                    detail="tag_checkpoints payload size exceeds limit.",
                )
        except (TypeError, ValueError) as e:
            raise HTTPException(
                status_code=422, detail=f"tag_checkpoints is not JSON-serializable: {e}"
            )

    if job_id is not None:
        if not re.match(r"^[a-zA-Z0-9_\-]+$", job_id):
            raise HTTPException(
                status_code=422,
                detail="job_id must only contain alphanumeric characters, underscores, or dashes.",
            )
        if len(job_id) > 64:
            raise HTTPException(
                status_code=422,
                detail="job_id length exceeds maximum limit of 64 characters.",
            )

    return normalized
