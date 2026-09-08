"""Verify deployment identity, authentication and the real resource-search route."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify(base_url: str, secret: str, revision: str, request=None, pause=time.sleep):
    if base_url not in {"https://pipeline.almiraj.xyz", "http://127.0.0.1:7860"}:
        raise ValueError("Unsupported verification endpoint")
    if not secret or "\n" in secret or "\r" in secret:
        raise ValueError("PIPELINE_SHARED_SECRET must be configured")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("EXPECTED_REVISION must be a full commit SHA")
    opener = urllib.request.build_opener(NoRedirect())

    def send(path, payload=None, authenticated=False):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["X-Pipeline-Secret"] = secret
        req = urllib.request.Request(base_url + path, headers=headers,
                                     data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with opener.open(req, timeout=8 if path == "/health" else 60) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, None

    request = request or send
    for attempt in range(12):
        try:
            status, body = request("/health")
            if status == 200 and isinstance(body, dict) and body.get("revision") == revision:
                break
        except (OSError, ValueError):
            pass
        if attempt == 11:
            raise RuntimeError("Production health did not report the expected revision")
        pause(5)

    payload = {"source": "youtube", "query": "Python tutorial for beginners", "language": "en", "limit": 1}
    status, _ = request("/tools/search_resources", payload, False)
    if status != 401:
        raise RuntimeError(f"Unauthenticated search must return 401; received {status}")
    status, body = request("/tools/search_resources", payload, True)
    candidates = body.get("candidates") if isinstance(body, dict) else None
    if status != 200 or not isinstance(candidates, list) or not candidates:
        raise RuntimeError(f"Authenticated search failed or returned no candidates (HTTP {status})")
    return {"revision": revision, "authenticated_search": status, "candidates": len(candidates)}


if __name__ == "__main__":
    try:
        result = verify(os.getenv("PIPELINE_BASE_URL", "https://pipeline.almiraj.xyz"),
                        os.getenv("PIPELINE_SHARED_SECRET", ""), os.getenv("EXPECTED_REVISION", ""))
        print(json.dumps(result))
    except RuntimeError as error:
        print(f"Pipeline verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    except (ValueError, OSError):
        # Never print exception/request objects: they may contain credentials.
        print("Pipeline verification failed: check revision, health, authentication and container logs.", file=sys.stderr)
        raise SystemExit(1)
