"""Regression tests for cycle protection in _get_depth and generate_learning_path."""

import pytest
from src.utils import learning_path


class TestGetDepthCycleProtection:
    """Verify _get_depth handles cyclic prerequisite graphs without RecursionError."""

    def test_simple_cycle_does_not_recurse(self, monkeypatch):
        """a -> b -> c -> a should not cause RecursionError."""
        cyclic_graph = {
            "a": ["b"],
            "b": ["c"],
            "c": ["a"],
        }
        monkeypatch.setattr(learning_path, "PREREQUISITE_GRAPH", cyclic_graph)

        # Should return a finite depth, not crash
        depth = learning_path._get_depth("a")
        assert isinstance(depth, int)
        assert depth >= 0

    def test_self_cycle(self, monkeypatch):
        """A node that lists itself as a prerequisite should not recurse."""
        cyclic_graph = {
            "x": ["x"],
        }
        monkeypatch.setattr(learning_path, "PREREQUISITE_GRAPH", cyclic_graph)

        depth = learning_path._get_depth("x")
        assert depth == 0 or depth == 1  # Either 0 (cycle break) or 1 is acceptable

    def test_cycle_with_branch(self, monkeypatch):
        """Graph: a -> b -> c -> a, and a -> d (no cycle). Should compute d correctly."""
        cyclic_graph = {
            "a": ["b", "d"],
            "b": ["c"],
            "c": ["a"],
            "d": [],
        }
        monkeypatch.setattr(learning_path, "PREREQUISITE_GRAPH", cyclic_graph)

        depth_d = learning_path._get_depth("d")
        assert depth_d == 0

        depth_a = learning_path._get_depth("a")
        assert isinstance(depth_a, int)
        assert depth_a >= 0

    def test_normal_dag_unaffected(self, monkeypatch):
        """Non-cyclic graph should produce correct depths as before."""
        dag = {
            "html": [],
            "css": ["html"],
            "javascript": ["html", "css"],
            "react": ["javascript"],
        }
        monkeypatch.setattr(learning_path, "PREREQUISITE_GRAPH", dag)

        assert learning_path._get_depth("html") == 0
        assert learning_path._get_depth("css") == 1
        assert learning_path._get_depth("javascript") == 2
        assert learning_path._get_depth("react") == 3


class TestGenerateLearningPathWithCycles:
    """Verify that generate_learning_path doesn't crash on cyclic YAML data."""

    def test_generate_with_cycle(self, monkeypatch):
        """Full path generation should succeed even with cycles in the graph."""
        cyclic_graph = {
            "a": ["b"],
            "b": ["a"],
        }
        monkeypatch.setattr(learning_path, "PREREQUISITE_GRAPH", cyclic_graph)

        # Disable YAML-based data to isolate the test
        monkeypatch.setattr(learning_path, "_graph_data", {})

        result = learning_path.generate_learning_path(["a", "b"])
        assert isinstance(result, dict)
        assert "phases" in result
        assert result["total_tags"] == 2
