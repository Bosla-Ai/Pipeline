from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request

import pytest

spec = importlib.util.spec_from_file_location(
    "check_pipeline", Path(__file__).resolve().parents[1] / "scripts/check_pipeline.py"
)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
REVISION = "a" * 40
URL = "https://pipeline.almiraj.xyz"


def test_real_transport_identifies_checker_and_limits_secret_to_authenticated_search(monkeypatch):
    authenticated_requests = []

    def open_request(request, timeout):
        if request.get_header("User-agent") != "Bosla-Deployment-Check/1.0":
            raise HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b"error code: 1010"))
        secret = request.get_header("X-pipeline-secret")
        authenticated_requests.append(secret)
        if request.full_url == URL + "/health":
            body = {"revision": REVISION}
        elif secret is None:
            raise HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO())
        else:
            assert secret == "test-secret"
            body = {"candidates": [{"id": "test"}]}
        response = io.BytesIO(json.dumps(body).encode())
        response.status = 200
        return response

    opener = Mock()
    opener.open.side_effect = open_request
    monkeypatch.setattr(checker.urllib.request, "build_opener", lambda handler: opener)
    result = checker.verify(URL, "test-secret", REVISION, pause=Mock())
    assert result == {"revision": REVISION, "authenticated_search": 200, "candidates": 1}
    assert authenticated_requests == [None, None, "test-secret"]


def test_checks_identity_and_both_sides_of_authentication():
    request = Mock(side_effect=[(200, {"revision": REVISION}), (401, None),
                               (200, {"candidates": [{"id": "test"}]})])
    result = checker.verify(URL, "test-secret", REVISION, request=request)
    assert result == {"revision": REVISION, "authenticated_search": 200, "candidates": 1}
    assert request.call_args_list[1].args[2] is False
    assert request.call_args_list[2].args[2] is True


def test_stale_revision_never_reaches_search():
    request = Mock(return_value=(200, {"revision": "b" * 40}))
    pause = Mock()
    with pytest.raises(RuntimeError, match="expected revision"):
        checker.verify(URL, "test-secret", REVISION, request=request, pause=pause)
    assert request.call_count == 12
    assert all(call.args == ("/health",) for call in request.call_args_list)
    assert pause.call_count == 11


@pytest.mark.parametrize("status,body", [(500, None), (200, {"candidates": []}), (200, {})])
def test_failed_search_is_not_a_successful_deployment(status, body):
    request = Mock(side_effect=[(200, {"revision": REVISION}), (401, None), (status, body)])
    with pytest.raises(RuntimeError, match="Authenticated search failed"):
        checker.verify(URL, "test-secret", REVISION, request=request)


def test_authentication_bypass_is_rejected():
    request = Mock(side_effect=[(200, {"revision": REVISION}), (200, {"candidates": [1]})])
    with pytest.raises(RuntimeError, match="must return 401"):
        checker.verify(URL, "test-secret", REVISION, request=request)
    assert request.call_count == 2


@pytest.mark.parametrize("url,secret,revision", [
    ("https://untrusted.invalid", "secret", REVISION),
    (URL, "", REVISION), (URL, "secret\r\ninjected: value", REVISION),
    (URL, "secret", "not-a-sha"),
])
def test_invalid_configuration_never_sends_credentials(url, secret, revision):
    request = Mock()
    with pytest.raises(ValueError):
        checker.verify(url, secret, revision, request=request)
    request.assert_not_called()


def test_redirects_cannot_forward_credentials():
    request = Request(URL + "/tools/search_resources", headers={"X-Pipeline-Secret": "test"})
    assert checker.NoRedirect().redirect_request(
        request, None, 302, "Moved", {}, "https://untrusted.invalid"
    ) is None


@pytest.mark.asyncio
async def test_health_keeps_existing_shape_without_release_metadata(monkeypatch):
    from src.api import health
    monkeypatch.delenv("BOSLA_PIPELINE_REVISION", raising=False)
    assert await health() == {"status": "healthy"}
    monkeypatch.setenv("BOSLA_PIPELINE_REVISION", REVISION)
    assert await health() == {"status": "healthy", "revision": REVISION}
