import pytest
from unittest.mock import patch
from pathlib import Path
from src.utils.learning_path import (
    generate_learning_path,
    _normalize_tag,
    _resolve_context_alias,
    _get_depth,
    _estimate_hours,
    _get_difficulty,
    PREREQUISITE_GRAPH,
    TAG_ALIASES,
    CONTEXT_ALIASES,
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


def test_new_coverage_aliases():
    # Test new aliases resolution
    assert _normalize_tag("llm") == "llms"
    assert _normalize_tag("genai") == "generative ai"
    assert _normalize_tag("otel") == "opentelemetry"
    assert _normalize_tag("vector db") == "vector databases"
    assert _normalize_tag("k8s") == "kubernetes"


def test_new_coverage_nodes():
    # Verify new nodes are loaded in the graph
    nodes = ["rag", "vector databases", "langchain", "opentelemetry", "cilium", "bun", "astro", "duckdb", "clickhouse", "dbt"]
    for node in nodes:
        assert node in PREREQUISITE_GRAPH


def test_new_coverage_topological_sort():
    # Verify topological order for new terms
    # 1. llms + vector databases before rag
    lp1 = generate_learning_path(["rag", "llms", "vector databases"])
    phase_tags1 = [t["tag"] for p in lp1["phases"] for t in p["tags"]]
    assert phase_tags1.index("llms") < phase_tags1.index("rag")
    assert phase_tags1.index("vector databases") < phase_tags1.index("rag")

    # 2. observability before opentelemetry
    lp2 = generate_learning_path(["opentelemetry", "observability"])
    phase_tags2 = [t["tag"] for p in lp2["phases"] for t in p["tags"]]
    assert phase_tags2.index("observability") < phase_tags2.index("opentelemetry")

    # 3. kubernetes before cilium
    lp3 = generate_learning_path(["cilium", "kubernetes"])
    phase_tags3 = [t["tag"] for p in lp3["phases"] for t in p["tags"]]
    assert phase_tags3.index("kubernetes") < phase_tags3.index("cilium")


def test_existing_behavior_remains():
    # html -> css -> javascript -> react
    lp = generate_learning_path(["react", "javascript", "css", "html"])
    tags = [t["tag"] for p in lp["phases"] for t in p["tags"]]
    assert tags.index("html") < tags.index("css")
    assert tags.index("css") < tags.index("javascript")
    assert tags.index("javascript") < tags.index("react")

    # python -> numpy -> machine learning -> deep learning
    lp_ds = generate_learning_path(["deep learning", "machine learning", "numpy", "python"])
    tags_ds = [t["tag"] for p in lp_ds["phases"] for t in p["tags"]]
    assert tags_ds.index("python") < tags_ds.index("numpy")
    assert tags_ds.index("numpy") < tags_ds.index("machine learning")
    assert tags_ds.index("machine learning") < tags_ds.index("deep learning")


def test_context_aliases_loaded():
    # Verify context aliases are loaded
    assert len(CONTEXT_ALIASES) > 0
    assert "tf" in CONTEXT_ALIASES


def test_tf_resolves_to_tensorflow_in_ml_context():
    # When sibling tags are ML-related, tf should resolve to tensorflow
    ml_context = {"python", "machine learning", "deep learning", "keras"}
    result = _normalize_tag("tf", ml_context)
    assert result == "tensorflow"


def test_tf_resolves_to_terraform_in_devops_context():
    # When sibling tags are DevOps-related, tf should resolve to terraform
    devops_context = {"docker", "kubernetes", "aws", "ci/cd"}
    result = _normalize_tag("tf", devops_context)
    assert result == "terraform"


def test_tf_defaults_to_tensorflow_without_context():
    # Without any context, tf should fall back to the default (tensorflow)
    result = _normalize_tag("tf")
    assert result == "tensorflow"


def test_tf_defaults_to_tensorflow_with_empty_context():
    # With empty context set, tf should fall back to the default
    result = _normalize_tag("tf", set())
    assert result == "tensorflow"


def test_tf_in_mixed_context_prefers_stronger_signal():
    # When both ML and DevOps signals are present, the stronger one should win
    # 3 ML signals vs 1 DevOps signal -> tensorflow
    mixed_context = {"python", "machine learning", "deep learning", "docker"}
    result = _normalize_tag("tf", mixed_context)
    assert result == "tensorflow"

    # 1 ML signal vs 3 DevOps signals -> terraform
    devops_heavy = {"python", "docker", "kubernetes", "aws", "ci/cd"}
    result2 = _normalize_tag("tf", devops_heavy)
    assert result2 == "terraform"


def test_context_aware_alias_in_learning_path():
    # Full integration: generate_learning_path with tf + devops tags
    lp = generate_learning_path(["tf", "docker", "kubernetes", "aws"])
    phase_tags = [t["tag"] for p in lp["phases"] for t in p["tags"]]
    # tf should have been resolved to terraform in this context
    assert "tf" in phase_tags  # original tag name preserved

    # The learning path should detect DevOps domain
    assert lp["domain"] == "DevOps & Cloud"


def test_context_aware_alias_in_ml_learning_path():
    # Full integration: generate_learning_path with tf + ML tags
    lp = generate_learning_path(["tf", "python", "deep learning"])
    phase_tags = [t["tag"] for p in lp["phases"] for t in p["tags"]]
    assert "tf" in phase_tags

    # The learning path should detect Data Science domain
    assert lp["domain"] == "Data Science & AI"


def test_resolve_context_alias_returns_none_for_non_context_alias():
    # A regular alias key that is not in CONTEXT_ALIASES should return None
    result = _resolve_context_alias("golang")
    assert result is None


def test_domain_detection_with_context_alias():
    # Weaker DevOps context like tf + ansible should classify as DevOps
    lp = generate_learning_path(["tf", "ansible"])
    assert lp["domain"] == "DevOps & Cloud"

    # Weaker ML context like tf + numpy should classify as Data Science & AI
    lp_ml = generate_learning_path(["tf", "numpy"])
    assert lp_ml["domain"] == "Data Science & AI"


def test_tf_difficulty_and_hours_varies_by_context():
    # tf in DevOps context should resolve to terraform, which is Intermediate (depth 1)
    devops_ctx = {"docker", "kubernetes", "aws"}
    diff_devops = _get_difficulty("tf", devops_ctx)
    hours_devops = _estimate_hours("tf", context_tags=devops_ctx)

    # tf in ML context should resolve to tensorflow, which is Advanced (depth 4)
    ml_ctx = {"python", "machine learning", "deep learning"}
    diff_ml = _get_difficulty("tf", ml_ctx)
    hours_ml = _estimate_hours("tf", context_tags=ml_ctx)

    assert diff_devops == "Beginner"
    assert diff_ml == "Advanced"
    assert hours_devops < hours_ml


def test_new_context_aliases_resolution():
    # net resolves to .net in .net context
    dotnet_ctx = {"c#", "asp.net", "ef core"}
    assert _normalize_tag("net", dotnet_ctx) == ".net"

    # net resolves to networking in networking context
    network_ctx = {"cybersecurity", "network security", "ethical hacking"}
    assert _normalize_tag("net", network_ctx) == "networking"

    # net defaults to .net
    assert _normalize_tag("net") == ".net"

    # cloud resolves to cloud deployment in devops context
    cloud_devops_ctx = {"docker", "kubernetes", "ci/cd"}
    assert _normalize_tag("cloud", cloud_devops_ctx) == "cloud deployment"

    # cloud resolves to cloud security in security context
    cloud_sec_ctx = {"cybersecurity", "vault", "devsecops"}
    assert _normalize_tag("cloud", cloud_sec_ctx) == "cloud security"

    # cloud defaults to cloud deployment
    assert _normalize_tag("cloud") == "cloud deployment"


def test_normalized_domain_scoring_fullstack_threshold():
    # 1 FE + 1 BE -> Full-Stack (balanced, minority 1.0 >= 0.3 * majority 1.0)
    lp1 = generate_learning_path(["react", "node"])
    assert lp1["domain"] == "Full-Stack Development"

    # 4 FE + 1 BE -> Frontend (highly unbalanced, minority 1.0 < 0.3 * majority 4.0)
    lp2 = generate_learning_path(["react", "html", "css", "tailwind", "node"])
    assert lp2["domain"] == "Frontend Development"

    # 3 FE + 1 BE -> Full-Stack (balanced, minority 1.0 >= 0.3 * majority 3.0)
    lp3 = generate_learning_path(["react", "html", "css", "node"])
    assert lp3["domain"] == "Full-Stack Development"

    # 5 BE + 1 FE -> Backend (highly unbalanced, minority 1.0 < 0.3 * majority 5.0)
    lp4 = generate_learning_path(["node", "express", "nestjs", "fastify", "postgres", "react"])
    assert lp4["domain"] == "Backend Development"


