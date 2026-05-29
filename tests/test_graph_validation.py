import pytest
from scripts.validate_graph import (
    load_aliases,
    load_skill_graphs,
    validate_graph,
)

def test_live_graph_validation():
    # 1. Load active graph and aliases
    aliases, alias_errors = load_aliases()
    graph, node_sources, graph_errors = load_skill_graphs()
    
    # 2. Check loading errors
    assert len(alias_errors) == 0, f"Aliases load failed: {alias_errors}"
    assert len(graph_errors) == 0, f"Graphs load failed: {graph_errors}"
    
    # 3. Validate
    errors, warnings = validate_graph(graph, aliases, node_sources)
    assert len(errors) == 0, f"Graph validation errors found: {errors}"


def test_validator_detects_missing_prerequisite():
    # Setup a mock graph with a missing prerequisite
    mock_graph = {
        "node a": {
            "prerequisites": ["node b"] # node b is missing
        }
    }
    mock_aliases = {}
    mock_sources = {"node a": "mock.yaml"}
    
    errors, warnings = validate_graph(mock_graph, mock_aliases, mock_sources)
    
    assert any("missing/unknown prerequisite" in err for err in errors)


def test_validator_detects_cycles():
    # Setup a mock graph with a cycle: node a -> node b -> node a
    mock_graph = {
        "node a": {
            "prerequisites": ["node b"]
        },
        "node b": {
            "prerequisites": ["node a"]
        }
    }
    mock_aliases = {}
    mock_sources = {"node a": "mock.yaml", "node b": "mock.yaml"}
    
    errors, warnings = validate_graph(mock_graph, mock_aliases, mock_sources)
    
    assert any("cycle detected" in err.lower() for err in errors)


def test_validator_detects_alias_target_missing():
    # Setup a mock alias pointing to a non-existent target
    mock_graph = {
        "node a": {
            "prerequisites": []
        }
    }
    mock_aliases = {
        "alias key": "non existent target"
    }
    mock_sources = {"node a": "mock.yaml"}
    
    errors, warnings = validate_graph(mock_graph, mock_aliases, mock_sources)
    
    assert any("points to target" in err for err in errors)


def test_validator_detects_alias_node_conflicts():
    # Setup a mock alias where the key is also a canonical node in the graph
    mock_graph = {
        "node a": {
            "prerequisites": []
        }
    }
    mock_aliases = {
        "node a": "node b"
    }
    mock_sources = {"node a": "mock.yaml"}
    
    errors, warnings = validate_graph(mock_graph, mock_aliases, mock_sources)
    
    assert any("also defined as a canonical node" in err for err in errors)
