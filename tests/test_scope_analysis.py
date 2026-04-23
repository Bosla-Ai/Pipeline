"""
Tests for dynamic heuristic-based scope analysis.
Tests heuristic rules, AI fallback behavior, and edge cases.
"""

import pytest
from unittest.mock import AsyncMock
from src.utils.helpers import analyze_topic_scope, _heuristic_scope


class TestHeuristicScope:
    """Test the _heuristic_scope function (pure, sync, no AI)."""

    # ── Rule 1: Short tags (1-2 words) → Broad ──────────────────────────

    @pytest.mark.parametrize(
        "tag",
        [
            "Python",
            "Docker",
            "Kubernetes",
            "React",
            "TensorFlow",
            "Go",
            "C++",
            "AWS",
            "Rust",
            "GraphQL",
            "Redis",
            "Prometheus",
            "Nginx",
            "Apache",
            "Helm",
            "Machine Learning",
            "Deep Learning",
            "System Design",
            "Clean Code",
        ],
    )
    def test_short_tags_are_broad(self, tag):
        """1-2 word tags (technology names) must be Broad."""
        assert _heuristic_scope(tag) == "Broad", f"'{tag}' should be Broad (short tag)"

    # ── Rule 2: Broad markers → Broad ───────────────────────────────────

    @pytest.mark.parametrize(
        "tag",
        [
            "Docker Mastery",
            "Python Fundamentals",
            "React Bootcamp",
            "Complete Guide to Kubernetes",
            "Comprehensive AWS Training",
            "Advanced JavaScript Patterns",
            "Beginner Python Programming",
            "Java from Scratch",
            "Go Zero to Hero",
            "Deep Dive into Rust",
            "Full Course on Angular",
            "Web Development Masterclass",
        ],
    )
    def test_broad_markers_detected(self, tag):
        """Tags with broad markers (mastery, fundamentals, etc.) must be Broad."""
        assert (
            _heuristic_scope(tag) == "Broad"
        ), f"'{tag}' should be Broad (broad marker)"

    # ── Rule 3: Atomic markers → Atomic ─────────────────────────────────

    @pytest.mark.parametrize(
        "tag",
        [
            "How to install Docker on Ubuntu",
            "Fix Python ImportError",
            "React vs Angular comparison",
            "What is a closure in JavaScript",
            "Quick tip for Git rebase",
            "Python error handling basics",
        ],
    )
    def test_atomic_markers_detected(self, tag):
        """Tags with atomic markers (how to, fix, vs, etc.) must be Atomic."""
        assert (
            _heuristic_scope(tag) == "Atomic"
        ), f"'{tag}' should be Atomic (atomic marker)"

    # ── Rule 4: with/for/using patterns → Broad ─────────────────────────

    @pytest.mark.parametrize(
        "tag",
        [
            "Automated Testing with Jest",
            "Kubernetes for Application Developers",
            "CI/CD Pipeline using Jenkins",
            "Building APIs with FastAPI",
            "Monitoring with Prometheus and Grafana",
        ],
    )
    def test_with_for_using_patterns_are_broad(self, tag):
        """Tags with 'with/for/using' structure are curriculum-style → Broad."""
        assert (
            _heuristic_scope(tag) == "Broad"
        ), f"'{tag}' should be Broad (with/for/using)"

    # ── Rule 5: Title-case multi-word → Broad ───────────────────────────

    @pytest.mark.parametrize(
        "tag",
        [
            "Linux System Administration",
            "Network Security Monitoring",
            "Cloud Native Architecture",
            "Service Mesh Implementation",
        ],
    )
    def test_title_case_tags_are_broad(self, tag):
        """Title-case structured names → Broad."""
        assert _heuristic_scope(tag) == "Broad", f"'{tag}' should be Broad (title case)"

    # ── Uncertain → None (defer to AI) ──────────────────────────────────

    def test_uncertain_returns_none(self):
        """Ambiguous tags should return None (defer to AI)."""
        # 3+ word, no markers, no title-case-only, no with/for/using
        result = _heuristic_scope("some obscure thing here")
        assert result is None, "Ambiguous tags should return None for AI fallback"


class TestAnalyzeTopicScope:
    """Test the full analyze_topic_scope function (heuristic + AI fallback)."""

    @pytest.fixture
    def mock_sio(self):
        return AsyncMock()

    # ── No socket → Broad fallback ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_no_socket_returns_broad(self, mock_sio):
        """When socket_id is None, should return 'Broad' (safe fallback)."""
        result = await analyze_topic_scope(mock_sio, None, "anything")
        assert result == "Broad"

    @pytest.mark.asyncio
    async def test_empty_socket_returns_broad(self, mock_sio):
        """When socket_id is empty string, should return 'Broad'."""
        result = await analyze_topic_scope(mock_sio, "", "anything")
        assert result == "Broad"

    # ── Heuristic bypass: known patterns skip AI ────────────────────────

    @pytest.mark.asyncio
    async def test_short_tag_bypasses_ai(self, mock_sio):
        """Short tags (1-2 words) should return 'Broad' WITHOUT calling AI."""
        result = await analyze_topic_scope(mock_sio, "valid_socket_id", "python")
        assert result == "Broad"
        mock_sio.call.assert_not_called()

    @pytest.mark.asyncio
    async def test_broad_marker_bypasses_ai(self, mock_sio):
        """Tags with broad markers should return 'Broad' WITHOUT calling AI."""
        result = await analyze_topic_scope(
            mock_sio, "valid_socket_id", "Docker Mastery"
        )
        assert result == "Broad"
        mock_sio.call.assert_not_called()

    @pytest.mark.asyncio
    async def test_case_insensitive(self, mock_sio):
        """Heuristic should be case insensitive."""
        for variant in ["Python", "PYTHON", "PyThOn"]:
            result = await analyze_topic_scope(mock_sio, "valid_socket_id", variant)
            assert result == "Broad", f"'{variant}' should be classified as Broad"

    @pytest.mark.asyncio
    async def test_cpp_is_broad(self, mock_sio):
        """C++ specifically must be classified as Broad."""
        result = await analyze_topic_scope(mock_sio, "valid_socket_id", "c++")
        assert result == "Broad"

    # ── AI fallback for ambiguous topics ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_ambiguous_topic_calls_ai(self, mock_sio):
        """Ambiguous topics should call the AI for classification."""
        mock_sio.call.return_value = [
            {
                "labels": [
                    "an entire programming language, framework, or major technology",
                    "a specific programming concept, error, or technique",
                ],
                "scores": [0.8, 0.2],
            }
        ]

        result = await analyze_topic_scope(
            mock_sio, "valid_socket_id", "some obscure thing here"
        )

        mock_sio.call.assert_called_once()
        assert result == "Broad"  # 0.8 > 0.2

    @pytest.mark.asyncio
    async def test_ai_returns_atomic(self, mock_sio):
        """When AI scores favor atomic, should return 'Atomic'."""
        mock_sio.call.return_value = [
            {
                "labels": [
                    "an entire programming language, framework, or major technology",
                    "a specific programming concept, error, or technique",
                ],
                "scores": [0.2, 0.8],
            }
        ]

        result = await analyze_topic_scope(
            mock_sio, "valid_socket_id", "some obscure thing here"
        )
        assert result == "Atomic"  # 0.2 < 0.8

    @pytest.mark.asyncio
    async def test_ai_timeout_returns_atomic(self, mock_sio):
        """When AI call times out, returns 'Broad' (safer roadmap fallback)."""
        mock_sio.call.side_effect = Exception("Timeout")

        result = await analyze_topic_scope(
            mock_sio, "valid_socket_id", "some obscure thing here"
        )
        assert result == "Broad"

    @pytest.mark.asyncio
    async def test_ai_empty_response_returns_atomic(self, mock_sio):
        """When AI returns empty response, returns 'Broad'."""
        mock_sio.call.return_value = None

        result = await analyze_topic_scope(
            mock_sio, "valid_socket_id", "some obscure thing here"
        )
        assert result == "Broad"

    @pytest.mark.asyncio
    async def test_ai_empty_list_returns_atomic(self, mock_sio):
        """When AI returns empty list, returns 'Broad'."""
        mock_sio.call.return_value = []

        result = await analyze_topic_scope(
            mock_sio, "valid_socket_id", "some obscure thing here"
        )
        assert result == "Broad"


class TestRealWorldTags:
    """Test the originally-failing tags from the deployed pipeline."""

    @pytest.mark.parametrize(
        "tag,expected",
        [
            ("Docker Mastery", "Broad"),
            ("Linux System Administration", "Broad"),
            ("Automated Testing with Jest", "Broad"),
            ("Python", "Broad"),
            ("Kubernetes for Application Developers", "Broad"),
            ("Monitoring with Prometheus and Grafana", "Broad"),
            ("CI/CD Pipeline using Jenkins", "Broad"),
            ("Nginx", "Broad"),
            ("Helm", "Broad"),
        ],
    )
    def test_deployed_tags_all_broad(self, tag, expected):
        """All 9 tags from the failing deployment must be classified as Broad by heuristics."""
        result = _heuristic_scope(tag)
        assert (
            result == expected
        ), f"'{tag}' classified as '{result}', expected '{expected}'"
