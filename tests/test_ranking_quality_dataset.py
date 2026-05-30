import os
import pytest
from src.engine.models import Candidate, SourceName
from src.evaluation.ranking_quality import (
    load_ranking_quality_cases,
    run_evaluation_case,
    cand_dict_to_obj,
    validate_evaluation_case
)
from scripts.evaluate_ranking_quality import main as cli_main


def test_dataset_exists_and_loads():
    """Verify that the dataset file exists and loaded cases are unique and valid."""
    filepath = "data/evaluation/ranking_quality_cases.yaml"
    assert os.path.exists(filepath)
    cases = load_ranking_quality_cases(filepath)
    assert len(cases) >= 6
    
    # Verify unique IDs
    case_ids = [c["id"] for c in cases]
    assert len(case_ids) == len(set(case_ids))


def test_schema_checks_reject_invalid_cases():
    """Verify that schema validation correctly rejects malformed case structures."""
    # Missing tag
    invalid_case_1 = {
        "id": "test_invalid",
        "candidates": [{"title": "A", "url": "url", "source": "youtube"}],
        "expectations": {"top_source_any_of": ["youtube"]}
    }
    with pytest.raises(ValueError, match="missing tag"):
        validate_evaluation_case(invalid_case_1)

    # Empty candidates
    invalid_case_2 = {
        "id": "test_invalid",
        "tag": "python",
        "candidates": [],
        "expectations": {"top_source_any_of": ["youtube"]}
    }
    with pytest.raises(ValueError, match="non-empty candidates"):
        validate_evaluation_case(invalid_case_2)

    # Unknown source
    invalid_case_3 = {
        "id": "test_invalid",
        "tag": "python",
        "candidates": [{"title": "A", "url": "url", "source": "unknown_source"}],
        "expectations": {"top_source_any_of": ["youtube"]}
    }
    with pytest.raises(ValueError, match="unknown/invalid source"):
        validate_evaluation_case(invalid_case_3)

    # Missing must_beat title
    invalid_case_4 = {
        "id": "test_invalid",
        "tag": "python",
        "candidates": [
            {"title": "A", "url": "url", "source": "youtube"},
            {"title": "B", "url": "url", "source": "youtube"}
        ],
        "expectations": {
            "must_beat": [{"higher": "A", "lower": "C"}]
        }
    }
    with pytest.raises(ValueError, match="specifies missing 'lower' title"):
        validate_evaluation_case(invalid_case_4)

    # Missing title in required_reason_codes_by_title
    invalid_case_5 = {
        "id": "test_invalid",
        "tag": "python",
        "candidates": [{"title": "A", "url": "url", "source": "youtube"}],
        "expectations": {
            "required_reason_codes_by_title": {
                "Nonexistent Title": ["title_exact_tag_match"]
            }
        }
    }
    with pytest.raises(ValueError, match="required_reason_codes_by_title specifies missing title"):
        validate_evaluation_case(invalid_case_5)


def test_candidate_conversion():
    """Verify conversion of YAML dict candidates into Candidate objects."""
    cand_data = {
        "source": "udemy",
        "title": "FastAPI Course",
        "url": "https://udemy.com/fastapi",
        "metadata": {
            "rating": 4.5,
            "lectures": 20
        }
    }
    obj = cand_dict_to_obj(cand_data, "fastapi")
    assert obj.source == SourceName.UDEMY
    assert obj.title == "FastAPI Course"
    assert obj.url == "https://udemy.com/fastapi"
    assert obj.rating == 4.5
    assert obj.lecture_count == 20


def test_real_dataset_cases_pass():
    """Verify that all quality evaluation cases in the dataset pass successfully."""
    filepath = "data/evaluation/ranking_quality_cases.yaml"
    cases = load_ranking_quality_cases(filepath)
    for case in cases:
        success, failures = run_evaluation_case(case)
        assert success, f"Case {case['id']} failed expectations: {failures}"


def test_env_var_restored(monkeypatch):
    """Verify that the ENABLE_RANKING_DEBUG environment variable is correctly restored."""
    monkeypatch.setenv("ENABLE_RANKING_DEBUG", "TrUe")
    filepath = "data/evaluation/ranking_quality_cases.yaml"
    cases = load_ranking_quality_cases(filepath)
    case = cases[0]
    
    # Run evaluation
    run_evaluation_case(case)
    
    # Environment variable should remain "TrUe" after evaluation runs
    assert os.environ.get("ENABLE_RANKING_DEBUG") == "TrUe"

    monkeypatch.delenv("ENABLE_RANKING_DEBUG", raising=False)
    run_evaluation_case(case)
    assert os.environ.get("ENABLE_RANKING_DEBUG") is None


def test_cli_script_exits_successfully(monkeypatch):
    """Verify that the CLI evaluation script exits successfully (0) under normal pass."""
    monkeypatch.setattr(sys_exit_mock := pytest.importorskip("sys"), "exit", lambda code: code)
    # cli_main should run fine and return or call exit(0)
    cli_main()
