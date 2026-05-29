import pytest
from unittest.mock import AsyncMock, patch
from src.engine.models import CourseSource
from src.planning.source_planner import SourcePlanner
from src.planning.query_planner import QueryPlanner


def test_source_planner_plan_sources():
    # Test case 1: No sources specified, free preferred
    assert SourcePlanner.plan_sources(None, prefer_paid=False) == [CourseSource.YOUTUBE]

    # Test case 2: No sources specified, paid preferred
    assert SourcePlanner.plan_sources(None, prefer_paid=True) == [CourseSource.UDEMY]

    # Test case 3: Sources specified, free preferred
    assert SourcePlanner.plan_sources(
        [CourseSource.YOUTUBE, CourseSource.COURSERA], prefer_paid=False
    ) == [CourseSource.YOUTUBE, CourseSource.COURSERA]

    # Test case 4: Sources specified, paid preferred (strips YouTube if other paid sources exist)
    assert SourcePlanner.plan_sources(
        [CourseSource.YOUTUBE, CourseSource.COURSERA], prefer_paid=True
    ) == [CourseSource.COURSERA]

    # Test case 5: Only YouTube specified, paid preferred (cannot strip YouTube if it is the only one)
    assert SourcePlanner.plan_sources([CourseSource.YOUTUBE], prefer_paid=True) == [
        CourseSource.YOUTUBE
    ]


@pytest.mark.asyncio
async def test_source_planner_plan_tag_scopes():
    sio = None
    socket_id = "test-session"
    tags = ["React Basics", "Python Advanced", "Machine Learning"]

    mock_scopes = {
        "React Basics": "Atomic",
        "Python Advanced": "Atomic",
        "Machine Learning": "Broad",
    }

    async def mock_analyze(sio_val, sid_val, tag_val):
        return mock_scopes[tag_val]

    with patch("src.planning.source_planner.analyze_topic_scope", new=mock_analyze):
        broad, atomic, cache = await SourcePlanner.plan_tag_scopes(sio, socket_id, tags)

        assert broad == ["Machine Learning"]
        assert set(atomic) == {"React Basics", "Python Advanced"}
        assert cache == {
            "React Basics": "Atomic",
            "Python Advanced": "Atomic",
            "Machine Learning": "Broad",
        }


def test_query_planner_normalize_search_tag():
    # Test abbreviation expansions
    assert QueryPlanner.normalize_search_tag("game dev") == "game developer"
    assert QueryPlanner.normalize_search_tag("software eng") == "software engineer"

    # Test custom mapping
    assert QueryPlanner.normalize_search_tag("engr") == "engineer"


def test_query_planner_build_search_plans():
    # Test english query
    plans = QueryPlanner.build_search_plans("Python Basics", "en")
    assert len(plans) == 1
    assert plans[0] == {"query": "Python Basics", "relevance_language": "en"}

    # Test arabic query with ar language
    plans = QueryPlanner.build_search_plans("أساسيات Unity", "ar")
    assert plans[0] == {"query": "أساسيات Unity", "relevance_language": "ar"}
    assert {"query": "أساسيات Unity", "relevance_language": None} in plans
    # 'Unity' -> english terms mapped via TAG_MAP to 'unity'
    assert {"query": "unity", "relevance_language": "en"} in plans


def test_query_planner_build_smart_queries():
    # Test simple tag
    assert QueryPlanner.build_smart_queries("react") == [
        ("react full course", "react tutorial")
    ]

    # Test descriptive role suffix conversion
    assert QueryPlanner.build_smart_queries("software developer") == [
        ("software development full course", "software development tutorial"),
        ("software developer full course", "software developer tutorial"),
    ]
