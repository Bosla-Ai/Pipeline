import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.planning.query_planner import QueryPlanner
from src.fetchers.videos.youtube_fetcher import (
    process_single_tag,
)

build_search_plans = QueryPlanner.build_search_plans
build_search_tag = QueryPlanner.build_search_tag


def test_build_search_tag_extracts_dynamic_english_fallback_terms():
    assert build_search_tag("أساسيات Unity", "en") == "unity"
    assert build_search_tag("تصميم مستويات في Unity", "en") == "unity"
    assert build_search_tag("game eng", "en") == "game engineer"


def test_build_search_plans_keep_original_query_before_tech_fallback():
    plans = build_search_plans("تصميم مستويات في Unity", "ar")

    assert plans[0] == {
        "query": "تصميم مستويات في Unity",
        "relevance_language": "ar",
    }
    assert {
        "query": "تصميم مستويات في Unity",
        "relevance_language": None,
    } in plans
    assert {"query": "unity", "relevance_language": "en"} in plans


def test_build_search_plans_dont_force_arabic_filter_on_english_shorthand():
    plans = build_search_plans("game eng", "ar")

    assert plans[0] == {"query": "game engineer", "relevance_language": "en"}
    assert {"query": "game engineer", "relevance_language": None} in plans


@pytest.mark.asyncio
async def test_process_single_tag_returns_none_when_only_unrelated_candidates_exist():
    session = MagicMock()

    mocked_api_responses = [
        {},  # playlist search
        {
            "items": [
                {"id": {"videoId": "bad1"}},
                {"id": {"videoId": "bad2"}},
            ]
        },  # video search
        {
            "items": [
                {
                    "id": "bad1",
                    "snippet": {
                        "title": "Learn English with TV Series | Game of Thrones",
                        "description": "English practice with TV scenes",
                        "publishedAt": "2025-01-01T00:00:00Z",
                    },
                    "statistics": {"viewCount": "100000", "likeCount": "5000"},
                    "contentDetails": {"duration": "PT65M"},
                },
                {
                    "id": "bad2",
                    "snippet": {
                        "title": "Random Gaming News",
                        "description": "Weekly gaming roundup",
                        "publishedAt": "2025-01-02T00:00:00Z",
                    },
                    "statistics": {"viewCount": "90000", "likeCount": "4000"},
                    "contentDetails": {"duration": "PT55M"},
                },
            ]
        },  # video details
    ]

    with patch(
        "src.fetchers.videos.youtube_fetcher.cache.get",
        new=AsyncMock(return_value=None),
    ), patch("src.fetchers.videos.youtube_fetcher.cache.set", new=AsyncMock()), patch(
        "src.fetchers.videos.youtube_fetcher.emergency_fetch",
        new=AsyncMock(return_value=None),
    ), patch(
        "src.planning.query_planner.QueryPlanner.build_smart_queries",
        return_value=[("game development full course", "game development tutorial")],
    ), patch(
        "src.fetchers.videos.youtube_fetcher.fetch_youtube_data",
        new=AsyncMock(side_effect=mocked_api_responses),
    ), patch(
        "src.fetchers.videos.youtube_fetcher.classify_via_frontend",
        new=AsyncMock(return_value=[]),
    ):
        result = await process_single_tag(
            session,
            sio=None,
            socket_id=None,
            tag="game development",
            language="en",
            max_results=5,
            precomputed_scope="Broad",
        )

    assert result == ("game development", None)
