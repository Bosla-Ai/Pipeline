import pytest
from scripts.validate_graph import (
    load_aliases,
    load_skill_graphs,
    load_context_aliases,
    validate_graph,
    validate_context_aliases,
)


def test_live_graph_validation():
    # 1. Load active graph, aliases, and context aliases
    aliases, alias_errors = load_aliases()
    graph, node_sources, graph_errors = load_skill_graphs()
    context_aliases, ctx_alias_errors = load_context_aliases()

    # 2. Check loading errors
    assert len(alias_errors) == 0, f"Aliases load failed: {alias_errors}"
    assert len(graph_errors) == 0, f"Graphs load failed: {graph_errors}"
    assert (
        len(ctx_alias_errors) == 0
    ), f"Context aliases load failed: {ctx_alias_errors}"

    # 3. Validate graph
    errors, warnings = validate_graph(graph, aliases, node_sources)
    assert len(errors) == 0, f"Graph validation errors found: {errors}"

    # 4. Validate context aliases
    ctx_errors, ctx_warnings = validate_context_aliases(context_aliases, graph, aliases)
    assert len(ctx_errors) == 0, f"Context alias validation errors found: {ctx_errors}"


def test_validator_detects_missing_prerequisite():
    # Setup a mock graph with a missing prerequisite
    mock_graph = {"node a": {"prerequisites": ["node b"]}}  # node b is missing
    mock_aliases = {}
    mock_sources = {"node a": "mock.yaml"}

    errors, warnings = validate_graph(mock_graph, mock_aliases, mock_sources)

    assert any("missing/unknown prerequisite" in err for err in errors)


def test_validator_detects_cycles():
    # Setup a mock graph with a cycle: node a -> node b -> node a
    mock_graph = {
        "node a": {"prerequisites": ["node b"]},
        "node b": {"prerequisites": ["node a"]},
    }
    mock_aliases = {}
    mock_sources = {"node a": "mock.yaml", "node b": "mock.yaml"}

    errors, warnings = validate_graph(mock_graph, mock_aliases, mock_sources)

    assert any("cycle detected" in err.lower() for err in errors)


def test_validator_detects_alias_target_missing():
    # Setup a mock alias pointing to a non-existent target
    mock_graph = {"node a": {"prerequisites": []}}
    mock_aliases = {"alias key": "non existent target"}
    mock_sources = {"node a": "mock.yaml"}

    errors, warnings = validate_graph(mock_graph, mock_aliases, mock_sources)

    assert any("points to target" in err for err in errors)


def test_validator_detects_alias_node_conflicts():
    # Setup a mock alias where the key is also a canonical node in the graph
    mock_graph = {"node a": {"prerequisites": []}}
    mock_aliases = {"node a": "node b"}
    mock_sources = {"node a": "mock.yaml"}

    errors, warnings = validate_graph(mock_graph, mock_aliases, mock_sources)

    assert any("also defined as a canonical node" in err for err in errors)


def test_context_alias_missing_target():
    mock_graph = {
        "tensorflow": {"prerequisites": []},
    }
    mock_ctx_aliases = {
        "tf": [
            {"target": "tensorflow", "default": True, "context": ["deep learning"]},
            {"target": "nonexistent", "context": ["docker"]},
        ]
    }
    errors, warnings = validate_context_aliases(mock_ctx_aliases, mock_graph, {})
    assert any("nonexistent" in err and "does not exist" in err for err in errors)


def test_context_alias_conflicts_with_simple_alias():
    mock_graph = {
        "tensorflow": {"prerequisites": []},
        "terraform": {"prerequisites": []},
    }
    mock_simple_aliases = {"tf": "tensorflow"}
    mock_ctx_aliases = {
        "tf": [
            {"target": "tensorflow", "default": True, "context": ["deep learning"]},
            {"target": "terraform", "context": ["docker"]},
        ]
    }
    errors, warnings = validate_context_aliases(
        mock_ctx_aliases, mock_graph, mock_simple_aliases
    )
    assert any("also exists in simple aliases" in err for err in errors)


def test_context_alias_warns_no_default():
    mock_graph = {
        "tensorflow": {"prerequisites": []},
        "terraform": {"prerequisites": []},
    }
    mock_ctx_aliases = {
        "tf": [
            {"target": "tensorflow", "context": ["deep learning"]},
            {"target": "terraform", "context": ["docker"]},
        ]
    }
    errors, warnings = validate_context_aliases(mock_ctx_aliases, mock_graph, {})
    assert any("no default" in w for w in warnings)
