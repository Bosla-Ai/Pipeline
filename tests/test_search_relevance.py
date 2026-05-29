import pytest
from unittest.mock import AsyncMock, MagicMock
from src.utils.helpers import classify_via_frontend


@pytest.fixture
def mock_sio():
    return AsyncMock()


@pytest.mark.asyncio
async def test_classify_via_frontend_exact_match(mock_sio):
    """
    Scenario: Perfect match.
    Tag: "asp.net core"
    Title: "ASP.NET Core Full Course"
    Expectation: Selected.
    """
    candidates = [
        {
            "contentType": "Playlist",
            "title": "ASP.NET Core Full Course",
            "description": "A complete guide to ASP.NET Core.",
            "url": "http://youtube.com/1",
            "score": 10.0,
        }
    ]

    # Mock Response: High score for "primarily about {tag}"
    # Label structure (simulated): [primarily, incidental, unrelated]
    # We expect the scores to correspond to the labels we send.
    # Let's assume the new implementation sends [Main Topic, Distractor, Unrelated]

    # Response format from sio.call matches the huggingface output or our processed version?
    # Based on current code, it returns a list of items with "scores".
    mock_sio.call.return_value = [
        {
            "contentType": "Playlist",
            "title": "ASP.NET Core Full Course",
            "scores": [0.9, 0.05, 0.05],  # High confidence in first label (Main Topic)
            "labels": [
                "a comprehensive course primarily about asp.net core",
                "...",
                "...",
            ],
        }
    ]

    result = await classify_via_frontend(mock_sio, "sid", "asp.net core", candidates)

    assert len(result) == 1
    assert result[0]["title"] == "ASP.NET Core Full Course"


@pytest.mark.asyncio
async def test_classify_via_frontend_distractor(mock_sio):
    """
    Scenario: Distractor / Roadmap Incompatible.
    Tag: "asp.net core"
    Title: "Microservices with ASP.NET Core"
    Expectation: Rejected because it's using the tag for another topic.
    """
    candidates = [
        {
            "contentType": "Playlist",
            "title": "Microservices with ASP.NET Core",
            "description": "Learn Microservices architecture using .NET.",
            "url": "http://youtube.com/2",
            "score": 10.0,
        }
    ]

    # Mock Response: High score for "incidental" or "distractor" label
    # Label 1: Main Topic (low)
    # Label 2: Specific usage / Distractor (high)
    mock_sio.call.return_value = [
        {
            "contentType": "Playlist",
            "title": "Microservices with ASP.NET Core",
            "scores": [0.1, 0.8, 0.1],
        }
    ]

    result = await classify_via_frontend(mock_sio, "sid", "asp.net core", candidates)

    assert len(result) == 0  # Should be filtered out


@pytest.mark.asyncio
async def test_classify_via_frontend_unrelated(mock_sio):
    """
    Scenario: Unrelated / Garbage.
    Tag: "asp.net core"
    Title: "Random Vlog"
    Expectation: Rejected.
    """
    candidates = [
        {
            "contentType": "Video",
            "title": "Random Vlog",
            "description": "Just chatting.",
            "url": "http://youtube.com/3",
            "score": 5.0,
        }
    ]

    # Label 3: Unrelated (high)
    mock_sio.call.return_value = [
        {"contentType": "Video", "title": "Random Vlog", "scores": [0.0, 0.0, 1.0]}
    ]

    result = await classify_via_frontend(mock_sio, "sid", "asp.net core", candidates)

    assert len(result) == 0


@pytest.mark.asyncio
async def test_classify_via_frontend_batching(mock_sio):
    """Scenario: Concurrent classification requests for the same tag are batched."""
    import asyncio

    candidates1 = [
        {
            "contentType": "Playlist",
            "title": "ASP.NET Core Course 1",
            "description": "Complete Guide 1",
            "url": "http://youtube.com/1",
            "score": 10.0,
        }
    ]
    candidates2 = [
        {
            "contentType": "Playlist",
            "title": "ASP.NET Core Course 2",
            "description": "Complete Guide 2",
            "url": "http://youtube.com/2",
            "score": 10.0,
        }
    ]

    # The mock Socket.IO call needs to return results for BOTH candidates in the order they are batched
    mock_sio.call.return_value = [
        {
            "contentType": "Playlist",
            "title": "ASP.NET Core Course 1",
            "scores": [0.9, 0.05, 0.05],
            "labels": [
                "a comprehensive course primarily about asp.net core",
                "...",
                "...",
            ],
        },
        {
            "contentType": "Playlist",
            "title": "ASP.NET Core Course 2",
            "scores": [0.8, 0.1, 0.1],
            "labels": [
                "a comprehensive course primarily about asp.net core",
                "...",
                "...",
            ],
        },
    ]

    # Trigger both concurrently
    res1, res2 = await asyncio.gather(
        classify_via_frontend(mock_sio, "sid", "asp.net core", candidates1),
        classify_via_frontend(mock_sio, "sid", "asp.net core", candidates2),
    )

    # Assert that only ONE call was made to mock_sio.call
    mock_sio.call.assert_called_once()

    # Verify both got their correct results
    assert len(res1) == 1
    assert res1[0]["title"] == "ASP.NET Core Course 1"
    assert len(res2) == 1
    assert res2[0]["title"] == "ASP.NET Core Course 2"
