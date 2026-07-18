from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import TypeAlias

from src.config.settings import PIPELINE_CACHE_DIR

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def cache_directory() -> Path:
    configured = Path(os.getenv("PIPELINE_CACHE_DIR", str(PIPELINE_CACHE_DIR))).resolve()
    if configured.drive.upper() != "D:":
        raise OSError("PIPELINE_CACHE_DIR must be located on D:")
    configured.mkdir(parents=True, exist_ok=True)
    return configured


def cache_path(namespace: str, key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    directory = cache_directory() / namespace
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{digest}.json"


def read_json(namespace: str, key: str) -> dict[str, JsonValue] | None:
    path = cache_path(namespace, key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_json(namespace: str, key: str, payload: dict[str, JsonValue]) -> None:
    path = cache_path(namespace, key)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def read_json_list(namespace: str, key: str) -> list[dict] | None:
    path = cache_path(namespace, key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, list) else None


def write_json_list(namespace: str, key: str, payload: list[dict]) -> None:
    path = cache_path(namespace, key)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)
