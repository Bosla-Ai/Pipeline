import pytest
from unittest.mock import patch
from src.engine.models import Candidate, SourceName
from src.inference.schemas import ClassificationRequest
from src.inference.edge_client import EdgeInferenceClient


class _FakeTransport:
    """Stands in for the active inference transport in edge_client tests.

    ``target`` controls whether a client is considered attached;
    ``response`` (or ``raises``) controls what ``call`` returns.
    """

    def __init__(self, target="sid-1", response=None):
        self._target = target
        self._response = response

    def target_for_job(self, job_id):
        return self._target

    async def call(self, *, job_id, event, data, timeout):
        return self._response


def _patch_transport(transport):
    return patch(
        "src.inference.edge_client.get_inference_transport",
        return_value=transport,
    )


def _one_candidate_request(job_id="job-1"):
    return ClassificationRequest(
        job_id=job_id,
        tag="python",
        candidates=[
            Candidate(
                source=SourceName.YOUTUBE,
                tag="python",
                title="Course",
                url="https://youtube.com/watch?v=123",
            )
        ],
        labels=["relevant", "irrelevant"],
    )


@pytest.mark.asyncio
async def test_no_socket_returns_empty():
    req = _one_candidate_request(job_id="job-none")
    with _patch_transport(_FakeTransport(target=None)):
        res = await EdgeInferenceClient.classify(req)
        assert res == []


@pytest.mark.asyncio
async def test_malformed_response_ignored():
    req = _one_candidate_request()
    with _patch_transport(_FakeTransport(response={"not_a": "list"})):
        res = await EdgeInferenceClient.classify(req)
        assert res == []


@pytest.mark.asyncio
async def test_unknown_candidate_key_ignored():
    req = _one_candidate_request()
    response = [
        {
            "candidate_key": "https://youtube.com/watch?v=different",
            "label": "relevant",
            "confidence": 0.9,
        }
    ]
    with _patch_transport(_FakeTransport(response=response)):
        res = await EdgeInferenceClient.classify(req)
        assert res == []


@pytest.mark.asyncio
async def test_confidence_clamped_or_rejected():
    req = _one_candidate_request()
    response = [
        {
            "candidate_key": "https://youtube.com/watch?v=123",
            "label": "relevant",
            "confidence": 1.5,  # Should be clamped to 1.0
        }
    ]
    with _patch_transport(_FakeTransport(response=response)):
        res = await EdgeInferenceClient.classify(req)
        assert len(res) == 1
        assert res[0].confidence == 1.0


@pytest.mark.asyncio
async def test_timeout_returns_empty():
    # transport.call returns None on timeout — same code path as a transport error.
    req = _one_candidate_request()
    with _patch_transport(_FakeTransport(response=None)):
        res = await EdgeInferenceClient.classify(req)
        assert res == []


@pytest.mark.asyncio
async def test_valid_response_maps_to_candidate():
    req = _one_candidate_request()
    response = [
        {
            "candidate_key": "https://youtube.com/watch?v=123",
            "label": "relevant",
            "confidence": 0.85,
        }
    ]
    with _patch_transport(_FakeTransport(response=response)):
        res = await EdgeInferenceClient.classify(req)
        assert len(res) == 1
        assert res[0].candidate_key == "https://youtube.com/watch?v=123"
        assert res[0].label == "relevant"
        assert res[0].confidence == 0.85
