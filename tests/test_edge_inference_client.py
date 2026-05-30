import pytest
from unittest.mock import AsyncMock, patch
from src.engine.models import Candidate, SourceName
from src.inference.schemas import ClassificationRequest
from src.inference.edge_client import EdgeInferenceClient


@pytest.mark.asyncio
async def test_no_socket_returns_empty():
    req = ClassificationRequest(
        job_id="job-none",
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
    with patch("src.inference.edge_client.get_socket_for_job", return_value=None):
        res = await EdgeInferenceClient.classify(req)
        assert res == []


@pytest.mark.asyncio
async def test_malformed_response_ignored():
    req = ClassificationRequest(
        job_id="job-1",
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
    # Mock socket exists, but returns non-list response
    with patch(
        "src.inference.edge_client.get_socket_for_job", return_value="sid-1"
    ), patch("src.inference.edge_client.sio.call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = {"not_a": "list"}
        res = await EdgeInferenceClient.classify(req)
        assert res == []


@pytest.mark.asyncio
async def test_unknown_candidate_key_ignored():
    req = ClassificationRequest(
        job_id="job-1",
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
    # Mock socket exists, returns list with unknown candidate URL
    with patch(
        "src.inference.edge_client.get_socket_for_job", return_value="sid-1"
    ), patch("src.inference.edge_client.sio.call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = [
            {
                "candidate_key": "https://youtube.com/watch?v=different",
                "label": "relevant",
                "confidence": 0.9,
            }
        ]
        res = await EdgeInferenceClient.classify(req)
        assert res == []


@pytest.mark.asyncio
async def test_confidence_clamped_or_rejected():
    req = ClassificationRequest(
        job_id="job-1",
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
    with patch(
        "src.inference.edge_client.get_socket_for_job", return_value="sid-1"
    ), patch("src.inference.edge_client.sio.call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = [
            {
                "candidate_key": "https://youtube.com/watch?v=123",
                "label": "relevant",
                "confidence": 1.5,  # Should be clamped to 1.0
            }
        ]
        res = await EdgeInferenceClient.classify(req)
        assert len(res) == 1
        assert res[0].confidence == 1.0


@pytest.mark.asyncio
async def test_timeout_returns_empty():
    req = ClassificationRequest(
        job_id="job-1",
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
    with patch(
        "src.inference.edge_client.get_socket_for_job", return_value="sid-1"
    ), patch("src.inference.edge_client.sio.call", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = TimeoutError()
        res = await EdgeInferenceClient.classify(req)
        assert res == []


@pytest.mark.asyncio
async def test_valid_response_maps_to_candidate():
    req = ClassificationRequest(
        job_id="job-1",
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
    with patch(
        "src.inference.edge_client.get_socket_for_job", return_value="sid-1"
    ), patch("src.inference.edge_client.sio.call", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = [
            {
                "candidate_key": "https://youtube.com/watch?v=123",
                "label": "relevant",
                "confidence": 0.85,
            }
        ]
        res = await EdgeInferenceClient.classify(req)
        assert len(res) == 1
        assert res[0].candidate_key == "https://youtube.com/watch?v=123"
        assert res[0].label == "relevant"
        assert res[0].confidence == 0.85
