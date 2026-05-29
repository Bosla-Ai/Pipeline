import pytest
from unittest.mock import patch
from pathlib import Path
from src.utils.learning_path import (
    generate_learning_path,
    _normalize_tag,
    _get_depth,
    _estimate_hours,
    _get_difficulty,
    PREREQUISITE_GRAPH,
    TAG_ALIASES,
)

def test_yaml_files_loaded():
    # Verify that the prerequisite graph loaded from YAML has the expected structure and is not empty
    assert len(PREREQUISITE_GRAPH) > 0
    assert "html" in PREREQUISITE_GRAPH
    assert "css" in PREREQUISITE_GRAPH
    assert "python" in PREREQUISITE_GRAPH
    assert "git" in PREREQUISITE_GRAPH
    assert "data science" in PREREQUISITE_GRAPH

    # Verify basic prerequisites
    assert PREREQUISITE_GRAPH["css"] == ["html"]
    assert PREREQUISITE_GRAPH["javascript"] == ["html", "css"]


def test_aliases_loaded():
    # Verify aliases are present
    assert len(TAG_ALIASES) > 0
    assert TAG_ALIASES["node.js"] == "node"
    assert TAG_ALIASES["golang"] == "go"


def test_normalize_tag():
    assert _normalize_tag("Node.js") == "node"
    assert _normalize_tag("golang") == "go"
    assert _normalize_tag("HTML") == "html"
    assert _normalize_tag("next-js") == "next.js"


def test_generate_learning_path_basic():
    tags = ["html", "css", "javascript", "react"]
    lp = generate_learning_path(tags)
    
    assert isinstance(lp, dict)
    assert lp["total_tags"] == 4
    assert "phases" in lp
    assert len(lp["phases"]) > 0
    
    # Ensure topological sort order (html -> css -> javascript -> react)
    phase_tags = []
    for phase in lp["phases"]:
        for t in phase["tags"]:
            phase_tags.append(t["tag"])
            
    assert "html" in phase_tags
    assert "css" in phase_tags
    assert "javascript" in phase_tags
    assert "react" in phase_tags
    
    # Check that html comes before css, css before javascript, javascript before react
    assert phase_tags.index("html") < phase_tags.index("css")
    assert phase_tags.index("css") < phase_tags.index("javascript")
    assert phase_tags.index("javascript") < phase_tags.index("react")


def test_yaml_overrides(monkeypatch):
    mock_graph = {
        "custom tag": {
            "prerequisites": ["html"],
            "difficulty": "expert",
            "estimated_hours": 99.5
        }
    }
    monkeypatch.setattr("src.utils.learning_path._graph_data", mock_graph)
    
    # Difficulty should be Capitalized from YAML
    assert _get_difficulty("custom-tag") == "Expert"
    
    # Estimated hours override should be used
    assert _estimate_hours("custom-tag") == 99.5


def test_empty_tags():
    assert generate_learning_path([]) == {}
