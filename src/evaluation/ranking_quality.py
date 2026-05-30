import os
import yaml
from src.engine.models import Candidate, SourceName
from src.ranking.cheap_ranker import cheap_rank


def cand_dict_to_obj(cand: dict, tag: str) -> Candidate:
    """Convert a dictionary candidate representation into a Candidate object."""
    raw = dict(cand.get("metadata", {}))
    raw["title"] = cand.get("title")
    raw["url"] = cand.get("url")
    raw["source"] = cand.get("source")

    if "duration_minutes" in cand:
        raw["duration_minutes"] = cand["duration_minutes"]
    if "rating" in cand:
        raw["rating"] = cand["rating"]
    if "raw_score" in cand:
        raw["raw_score"] = cand["raw_score"]
        raw["score"] = cand["raw_score"]

    # Map lectures/lectureCount/videoCount to lecture_count so Candidate.from_dict parses it
    if "lectures" in raw:
        raw["lecture_count"] = raw["lectures"]
    if "lectureCount" in raw:
        raw["lecture_count"] = raw["lectureCount"]
    if "videoCount" in raw:
        raw["lecture_count"] = raw["videoCount"]

    return Candidate.from_dict(raw, SourceName(cand["source"]), tag)


def validate_evaluation_case(case: dict):
    """Validate a quality evaluation case schema strictly."""
    if not case.get("id"):
        raise ValueError("Case is missing id")
    case_id = case["id"]
    if not case.get("tag"):
        raise ValueError(f"Case {case_id} is missing tag")

    candidates = case.get("candidates")
    if not candidates:
        raise ValueError(f"Case {case_id} must have a non-empty candidates list")

    titles = set()
    for cand in candidates:
        if "title" not in cand:
            raise ValueError(f"Case {case_id} has a candidate missing title")
        title = cand["title"]
        if title in titles:
            raise ValueError(f"Case {case_id} has duplicate candidate title: {title}")
        titles.add(title)

        if "url" not in cand:
            raise ValueError(f"Case {case_id} candidate '{title}' is missing url")

        source = cand.get("source")
        if source not in ("coursera", "udemy", "youtube"):
            raise ValueError(
                f"Case {case_id} candidate '{title}' has unknown/invalid source: {source}"
            )

    expectations = case.get("expectations")
    if not expectations:
        raise ValueError(f"Case {case_id} is missing expectations")

    top_sources = expectations.get("top_source_any_of")
    if top_sources:
        for src in top_sources:
            if src not in ("coursera", "udemy", "youtube"):
                raise ValueError(
                    f"Case {case_id} expectation 'top_source_any_of' contains invalid source: {src}"
                )

    must_beat = expectations.get("must_beat")
    if must_beat:
        for pair in must_beat:
            higher = pair.get("higher")
            lower = pair.get("lower")
            if not higher or not lower:
                raise ValueError(
                    f"Case {case_id} must_beat pair must contain both 'higher' and 'lower' titles"
                )
            if higher not in titles:
                raise ValueError(
                    f"Case {case_id} must_beat pair specifies missing 'higher' title: {higher}"
                )
            if lower not in titles:
                raise ValueError(
                    f"Case {case_id} must_beat pair specifies missing 'lower' title: {lower}"
                )

    reason_codes = expectations.get("required_reason_codes_by_title")
    if reason_codes:
        for t in reason_codes:
            if t not in titles:
                raise ValueError(
                    f"Case {case_id} required_reason_codes_by_title specifies missing title: {t}"
                )


def load_ranking_quality_cases(filepath: str) -> list[dict]:
    """Load and validate all ranking quality cases from a YAML file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "cases" not in data:
        raise ValueError("Invalid YAML structure: missing 'cases' key")

    cases = data["cases"]
    seen_ids = set()
    for case in cases:
        case_id = case.get("id")
        if not case_id:
            raise ValueError("A case is missing an id")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate case id found: {case_id}")
        seen_ids.add(case_id)
        validate_evaluation_case(case)

    return cases


def run_evaluation_case(case: dict) -> tuple[bool, list[str]]:
    """Run ranking and validate expectations for a single quality evaluation case."""
    tag = case["tag"]
    candidates_data = case["candidates"]
    expectations = case["expectations"]

    candidates = [cand_dict_to_obj(cand, tag) for cand in candidates_data]

    # Run cheap_rank with debug mode disabled to get standard scores/order
    old_value = os.environ.get("ENABLE_RANKING_DEBUG")
    try:
        os.environ["ENABLE_RANKING_DEBUG"] = "false"
        ranked = cheap_rank(candidates, tag)
    finally:
        if old_value is None:
            os.environ.pop("ENABLE_RANKING_DEBUG", None)
        else:
            os.environ["ENABLE_RANKING_DEBUG"] = old_value

    ranked_by_title = {c.title: c for c in ranked}
    failures = []

    # Check top source expectation
    top_sources = expectations.get("top_source_any_of")
    if top_sources:
        top_cand = ranked[0]
        top_source_val = (
            top_cand.source.value
            if hasattr(top_cand.source, "value")
            else str(top_cand.source)
        )
        if top_source_val not in top_sources:
            failures.append(
                f"Top source '{top_source_val}' is not in expected list: {top_sources}"
            )

    # Check must_beat pairs
    must_beat = expectations.get("must_beat")
    if must_beat:
        for pair in must_beat:
            higher_title = pair["higher"]
            lower_title = pair["lower"]
            higher_cand = ranked_by_title[higher_title]
            lower_cand = ranked_by_title[lower_title]
            if higher_cand.raw_score <= lower_cand.raw_score:
                failures.append(
                    f"Candidate '{higher_title}' (score: {higher_cand.raw_score}) failed to beat "
                    f"'{lower_title}' (score: {lower_cand.raw_score})"
                )

    # Check required reason codes
    reason_codes_by_title = expectations.get("required_reason_codes_by_title")
    if reason_codes_by_title:
        old_value = os.environ.get("ENABLE_RANKING_DEBUG")
        try:
            os.environ["ENABLE_RANKING_DEBUG"] = "true"
            # Re-rank with debug mode enabled to get explanations
            debug_candidates = [cand_dict_to_obj(cand, tag) for cand in candidates_data]
            ranked_debug = cheap_rank(debug_candidates, tag)
            ranked_debug_by_title = {c.title: c for c in ranked_debug}
        finally:
            if old_value is None:
                os.environ.pop("ENABLE_RANKING_DEBUG", None)
            else:
                os.environ["ENABLE_RANKING_DEBUG"] = old_value

        for title, expected_codes in reason_codes_by_title.items():
            cand = ranked_debug_by_title[title]
            explanation = cand.ranking_explanation
            if not explanation:
                failures.append(
                    f"Candidate '{title}' is missing ranking explanation in debug mode"
                )
                continue
            actual_codes = explanation.get("reasonCodes", [])
            for code in expected_codes:
                if code not in actual_codes:
                    failures.append(
                        f"Candidate '{title}' is missing expected reason code '{code}' "
                        f"(actual codes: {actual_codes})"
                    )

    return len(failures) == 0, failures
