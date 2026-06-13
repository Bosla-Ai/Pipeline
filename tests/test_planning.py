import pytest
from unittest.mock import AsyncMock, patch
from src.engine.models import CourseSource
from src.planning.source_planner import SourcePlanner
from src.planning.query_planner import QueryPlanner


def test_source_planner_plan_sources():
    # Test case 1: No sources specified, free preferred
    assert SourcePlanner.plan_sources(None, prefer_paid=False) == [CourseSource.YOUTUBE]

    # Test case 2: No sources specified, paid preferred (defaults to YouTube under new fallback rules)
    assert SourcePlanner.plan_sources(None, prefer_paid=True) == [CourseSource.YOUTUBE]

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


def test_query_planner_plan_queries_for_tag():
    from src.engine.stages import PreparedTag, PlannedSource
    from src.engine.models import TopicScope, SourceName

    # 1. python_generates_full_course_and_tutorial
    tag_py = PreparedTag(
        original="python",
        normalized="python",
        language="en",
        scope=TopicScope.TECHNOLOGY,
    )
    sources = [
        PlannedSource(
            tag=tag_py,
            source=SourceName.YOUTUBE,
            enabled=True,
            reason="ok",
            estimated_cost="free",
        )
    ]
    queries = QueryPlanner.plan_queries_for_tag(
        tag_py, sources, max_results=5, query_limit_per_tag=2
    )
    assert len(queries) == 2
    assert queries[0].query == "python full course"
    assert queries[0].expected_content_type == "playlist"
    assert queries[1].query == "python tutorial"
    assert queries[1].expected_content_type == "video"

    # 2. role_generates_roadmap_query
    tag_role = PreparedTag(
        original="devops",
        normalized="devops",
        language="en",
        scope=TopicScope.ROLE_ROADMAP,
    )
    sources_role = [
        PlannedSource(
            tag=tag_role,
            source=SourceName.YOUTUBE,
            enabled=True,
            reason="ok",
            estimated_cost="free",
        )
    ]
    queries_role = QueryPlanner.plan_queries_for_tag(
        tag_role, sources_role, max_results=5, query_limit_per_tag=2
    )
    assert len(queries_role) == 2
    assert queries_role[0].query == "devops roadmap"
    assert queries_role[0].expected_content_type == "playlist"
    assert queries_role[1].query == "devops full course"
    assert queries_role[1].expected_content_type == "playlist"

    # 3. free_hf_limits_queries_to_two
    tag_limits = PreparedTag(
        original="git", normalized="git", language="en", scope=TopicScope.TECHNOLOGY
    )
    sources_limits = [
        PlannedSource(
            tag=tag_limits,
            source=SourceName.YOUTUBE,
            enabled=True,
            reason="ok",
            estimated_cost="free",
        )
    ]
    # Set limit to 1
    queries_limits = QueryPlanner.plan_queries_for_tag(
        tag_limits, sources_limits, max_results=5, query_limit_per_tag=1
    )
    assert len(queries_limits) == 1
    assert queries_limits[0].query == "git full course"

    # 4. arabic_query_keeps_arabic_first
    tag_ar = PreparedTag(
        original="بايثون للمبتدئين",
        normalized="بايثون للمبتدئين",
        language="ar",
        scope=TopicScope.TECHNOLOGY,
    )
    sources_ar = [
        PlannedSource(
            tag=tag_ar,
            source=SourceName.YOUTUBE,
            enabled=True,
            reason="ok",
            estimated_cost="free",
        )
    ]
    queries_ar = QueryPlanner.plan_queries_for_tag(
        tag_ar, sources_ar, max_results=5, query_limit_per_tag=2
    )
    assert len(queries_ar) == 2
    assert queries_ar[0].query == "بايثون للمبتدئين full course"
    assert queries_ar[1].query == "بايثون للمبتدئين tutorial"

    # With English fallback
    tag_ar_fallback = PreparedTag(
        original="أساسيات Unity",
        normalized="أساسيات Unity",
        language="ar",
        scope=TopicScope.TECHNOLOGY,
    )
    sources_ar_fallback = [
        PlannedSource(
            tag=tag_ar_fallback,
            source=SourceName.YOUTUBE,
            enabled=True,
            reason="ok",
            estimated_cost="free",
        )
    ]
    queries_ar_fallback = QueryPlanner.plan_queries_for_tag(
        tag_ar_fallback, sources_ar_fallback, max_results=5, query_limit_per_tag=2
    )
    assert len(queries_ar_fallback) == 2
    assert queries_ar_fallback[0].query == "أساسيات Unity full course"
    assert queries_ar_fallback[1].query == "unity full course"

    # 5. query_dedup_preserves_order
    tag_dup = PreparedTag(
        original="python",
        normalized="python",
        language="en",
        scope=TopicScope.TECHNOLOGY,
    )
    sources_dup = [
        PlannedSource(
            tag=tag_dup,
            source=SourceName.YOUTUBE,
            enabled=True,
            reason="ok",
            estimated_cost="free",
        )
    ]
    queries_dup = QueryPlanner.plan_queries_for_tag(
        tag_dup, sources_dup, max_results=5, query_limit_per_tag=3
    )
    assert len(queries_dup) == 2
