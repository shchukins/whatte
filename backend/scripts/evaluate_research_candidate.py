#!/usr/bin/env python3
"""Compare baseline and candidate predictions on a frozen dataset partition."""

import argparse
import json
import os
from pathlib import Path
from typing import Any

from backend.services.research_evaluator import evaluate_research_candidate


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument(
        "--partition", choices=("train", "validation", "test"), default="validation",
    )
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    args = parser.parse_args()
    test_access_granted = os.getenv("WHATTE_RESEARCH_TEST_ACCESS") == "granted"
    if args.partition == "test" and not test_access_granted:
        parser.error("test evaluation requires WHATTE_RESEARCH_TEST_ACCESS=granted")
    result = evaluate_research_candidate(
        dataset=_load_json(args.dataset),
        partition=args.partition,
        baseline_artifact=_load_json(args.baseline),
        candidate_artifact=_load_json(args.candidate),
        test_access_granted=test_access_granted,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
