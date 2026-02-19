"""
Aggressive tests for scope analysis and KNOWN_BROAD_TOPICS safety net.
Tests edge cases, fuzzy matching, fallback behavior, and stress scenarios.
"""

import pytest
from unittest.mock import AsyncMock, patch
from src.utils.helpers import analyze_topic_scope
from src.utils.constants import KNOWN_BROAD_TOPICS


class TestKnownBroadTopics:
    """Test the KNOWN_BROAD_TOPICS safety net."""

    # Programming Languages - Must be Broad
    @pytest.mark.parametrize(
        "topic",
        [
            "python",
            "Python",
            "PYTHON",
            "javascript",
            "JavaScript",
            "java",
            "c++",
            "C++",
            "c#",
            "C#",
            "rust",
            "go",
            "golang",
            "swift",
            "kotlin",
            "typescript",
            "php",
            "ruby",
            "scala",
            "perl",
            "r",
            "matlab",
            "julia",
            "haskell",
            "elixir",
            "dart",
            "lua",
            "assembly",
            "fortran",
            "cobol",
        ],
    )
    def test_programming_languages_in_known_broad(self, topic):
        """All major programming languages must be in KNOWN_BROAD_TOPICS."""
        assert (
            topic.lower() in KNOWN_BROAD_TOPICS
        ), f"'{topic}' should be in KNOWN_BROAD_TOPICS"

    # Frameworks - Must be Broad
    @pytest.mark.parametrize(
        "topic",
        [
            "react",
            "angular",
            "vue",
            "django",
            "flask",
            "fastapi",
            "spring",
            "spring boot",
            "express",
            "laravel",
            "rails",
            "ruby on rails",
            "asp.net",
            ".net",
            ".net core",
            "nestjs",
            "next.js",
            "nextjs",
            "nuxt",
            "svelte",
            "gatsby",
            "flutter",
            "react native",
        ],
    )
    def test_frameworks_in_known_broad(self, topic):
        """All major frameworks must be in KNOWN_BROAD_TOPICS."""
        assert (
            topic.lower() in KNOWN_BROAD_TOPICS
        ), f"'{topic}' should be in KNOWN_BROAD_TOPICS"

    # DevOps/Cloud - Must be Broad
    @pytest.mark.parametrize(
        "topic",
        [
            "docker",
            "kubernetes",
            "k8s",
            "aws",
            "azure",
            "gcp",
            "google cloud",
            "terraform",
            "ansible",
            "jenkins",
            "ci/cd",
            "github actions",
            "devops",
        ],
    )
    def test_devops_cloud_in_known_broad(self, topic):
        """All DevOps/Cloud tools must be in KNOWN_BROAD_TOPICS."""
        assert (
            topic.lower() in KNOWN_BROAD_TOPICS
        ), f"'{topic}' should be in KNOWN_BROAD_TOPICS"

    # Security - Must be Broad
    @pytest.mark.parametrize(
        "topic",
        [
            "cybersecurity",
            "cyber security",
            "ethical hacking",
            "penetration testing",
            "pen testing",
            "network security",
            "application security",
            "cryptography",
            "infosec",
            "information security",
        ],
    )
    def test_security_topics_in_known_broad(self, topic):
        """All security topics must be in KNOWN_BROAD_TOPICS."""
        assert (
            topic.lower() in KNOWN_BROAD_TOPICS
        ), f"'{topic}' should be in KNOWN_BROAD_TOPICS"

    # Architecture - Must be Broad
    @pytest.mark.parametrize(
        "topic",
        [
            "system design",
            "software architecture",
            "microservices",
            "micro services",
            "design patterns",
            "rest api",
            "restful api",
            "clean architecture",
            "clean code",
            "solid principles",
            "domain driven design",
            "ddd",
        ],
    )
    def test_architecture_topics_in_known_broad(self, topic):
        """All architecture topics must be in KNOWN_BROAD_TOPICS."""
        assert (
            topic.lower() in KNOWN_BROAD_TOPICS
        ), f"'{topic}' should be in KNOWN_BROAD_TOPICS"

    # CS Fundamentals - Must be Broad
    @pytest.mark.parametrize(
        "topic",
        [
            "algorithms",
            "data structures",
            "dsa",
            "operating systems",
            "networking",
            "computer networks",
            "compilers",
            "databases",
            "distributed systems",
        ],
    )
    def test_cs_fundamentals_in_known_broad(self, topic):
        """All CS fundamentals must be in KNOWN_BROAD_TOPICS."""
        assert (
            topic.lower() in KNOWN_BROAD_TOPICS
        ), f"'{topic}' should be in KNOWN_BROAD_TOPICS"

    # AI/ML - Must be Broad
    @pytest.mark.parametrize(
        "topic",
        [
            "machine learning",
            "deep learning",
            "ai",
            "artificial intelligence",
            "nlp",
            "natural language processing",
            "computer vision",
            "tensorflow",
            "pytorch",
            "data science",
            "big data",
        ],
    )
    def test_ai_ml_topics_in_known_broad(self, topic):
        """All AI/ML topics must be in KNOWN_BROAD_TOPICS."""
        assert (
            topic.lower() in KNOWN_BROAD_TOPICS
        ), f"'{topic}' should be in KNOWN_BROAD_TOPICS"


class TestAnalyzeTopicScope:
    """Test the analyze_topic_scope function behavior."""

    @pytest.fixture
    def mock_sio(self):
        return AsyncMock()

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

    @pytest.mark.asyncio
    async def test_known_broad_topic_bypasses_ai(self, mock_sio):
        """Known broad topics should return 'Broad' WITHOUT calling AI."""
        result = await analyze_topic_scope(mock_sio, "valid_socket_id", "python")

        assert result == "Broad"
        mock_sio.call.assert_not_called()  # AI should NOT be called

    @pytest.mark.asyncio
    async def test_known_broad_topic_case_insensitive(self, mock_sio):
        """Known broad topics check should be case insensitive."""
        for variant in ["Python", "PYTHON", "PyThOn"]:
            result = await analyze_topic_scope(mock_sio, "valid_socket_id", variant)
            assert result == "Broad", f"'{variant}' should be classified as Broad"

    @pytest.mark.asyncio
    async def test_cpp_is_broad(self, mock_sio):
        """C++ specifically must be classified as Broad (original bug case)."""
        result = await analyze_topic_scope(mock_sio, "valid_socket_id", "c++")
        assert result == "Broad"

    @pytest.mark.asyncio
    async def test_unknown_topic_calls_ai(self, mock_sio):
        """Unknown topics should call the AI for classification."""
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
            mock_sio, "valid_socket_id", "some_obscure_topic"
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
            mock_sio, "valid_socket_id", "binary search algorithm"
        )
        assert result == "Atomic"  # 0.2 < 0.8

    @pytest.mark.asyncio
    async def test_ai_timeout_returns_atomic(self, mock_sio):
        """When AI call times out on unknown topic, returns 'Atomic' (current behavior)."""
        mock_sio.call.side_effect = Exception("Timeout")

        result = await analyze_topic_scope(mock_sio, "valid_socket_id", "unknown_topic")
        assert result == "Atomic"  # Current fallback for exceptions

    @pytest.mark.asyncio
    async def test_ai_empty_response_returns_atomic(self, mock_sio):
        """When AI returns empty response on unknown topic, returns 'Atomic'."""
        mock_sio.call.return_value = None

        result = await analyze_topic_scope(mock_sio, "valid_socket_id", "unknown_topic")
        assert result == "Atomic"  # Current fallback for empty response

    @pytest.mark.asyncio
    async def test_ai_empty_list_returns_atomic(self, mock_sio):
        """When AI returns empty list on unknown topic, returns 'Atomic'."""
        mock_sio.call.return_value = []

        result = await analyze_topic_scope(mock_sio, "valid_socket_id", "unknown_topic")
        assert result == "Atomic"  # Current fallback - empty list triggers IndexError


class TestKnownBroadTopicsCompleteness:
    """Stress tests to ensure KNOWN_BROAD_TOPICS is comprehensive."""

    def test_minimum_topic_count(self):
        """KNOWN_BROAD_TOPICS should have at least 150 entries."""
        assert (
            len(KNOWN_BROAD_TOPICS) >= 150
        ), f"Expected at least 150 topics, got {len(KNOWN_BROAD_TOPICS)}"

    def test_no_duplicates(self):
        """KNOWN_BROAD_TOPICS should not have duplicates (it's a set, but sanity check)."""
        topics_list = list(KNOWN_BROAD_TOPICS)
        assert len(topics_list) == len(set(topics_list))

    def test_all_lowercase(self):
        """All entries in KNOWN_BROAD_TOPICS should be lowercase."""
        for topic in KNOWN_BROAD_TOPICS:
            assert topic == topic.lower(), f"Topic '{topic}' is not lowercase"

    def test_no_empty_strings(self):
        """KNOWN_BROAD_TOPICS should not contain empty strings."""
        assert "" not in KNOWN_BROAD_TOPICS
        assert " " not in KNOWN_BROAD_TOPICS

    def test_no_leading_trailing_spaces(self):
        """No topic should have leading or trailing whitespace."""
        for topic in KNOWN_BROAD_TOPICS:
            assert (
                topic == topic.strip()
            ), f"Topic '{topic}' has leading/trailing spaces"
