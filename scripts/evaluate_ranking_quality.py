#!/usr/bin/env python3
import sys
from pathlib import Path

# Add project root to sys.path so src imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluation.ranking_quality import load_ranking_quality_cases, run_evaluation_case, cand_dict_to_obj
from src.ranking.cheap_ranker import cheap_rank


def main():
    filepath = "data/evaluation/ranking_quality_cases.yaml"
    try:
        cases = load_ranking_quality_cases(filepath)
    except Exception as e:
        print(f"Error loading evaluation cases: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(cases)} ranking quality cases.")
    passed = 0
    failed = 0

    for case in cases:
        case_id = case["id"]
        success, failures = run_evaluation_case(case)
        if success:
            passed += 1
            print(f"Case '{case_id}': PASSED")
        else:
            failed += 1
            print(f"\nCase '{case_id}': FAILED", file=sys.stderr)
            for f in failures:
                print(f"  - Failed expectation: {f}", file=sys.stderr)
            
            # Print actual ranking order with scores
            tag = case["tag"]
            candidates = [cand_dict_to_obj(c, tag) for c in case["candidates"]]
            ranked = cheap_rank(candidates, tag)
            print("  - Actual ranking order:", file=sys.stderr)
            for i, c in enumerate(ranked):
                print(f"    {i+1}. {c.title} (source: {c.source.value if hasattr(c.source, 'value') else str(c.source)}, score: {c.raw_score})", file=sys.stderr)
            print()

    print(f"\nSummary:")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
