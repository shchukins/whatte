"""Print aggregate preparation readiness from a private, test-withheld v2 export."""

import argparse
import json
from pathlib import Path
from backend.services.recovery_data_readiness import REPORT_VERSION, recovery_data_readiness
from scripts.run_research_experiment import _load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--fit-as-of", required=True)
    args = parser.parse_args()
    try:
        dataset = _load(args.dataset, 64 * 1024 * 1024)
        result = recovery_data_readiness(dataset, fit_as_of=args.fit_as_of)
    except (OSError, ValueError, TypeError, RecursionError):
        # Never expose input contents, filesystem paths or parser errors.
        print(json.dumps({"report_version": REPORT_VERSION,
                          "status": "invalid_dataset", "reasons": ["dataset_input_invalid"]}))
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "ready_for_preparation" else 1 if result["status"] == "invalid_dataset" else 2


if __name__ == "__main__":
    raise SystemExit(main())
