"""Explicit train-only fitting and pinned baseline preparation for #150."""

import argparse
import json
import os
from pathlib import Path
from backend.services.recovery_prediction import (
    fit_recovery_state, canonical_hash, prediction_artifact,
)
from backend.services.recovery_prediction_config import baseline_prediction_config
from backend.services.research_evaluator_v2 import validate_evaluation_dataset
from scripts.run_research_experiment import _load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--fit-as-of", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--partition", choices=("validation", "test"), default="validation")
    args = parser.parse_args()
    test_access = os.getenv("WHATTE_RESEARCH_TEST_ACCESS") == "granted"
    dataset = _load(args.dataset, 64 * 1024 * 1024)
    rows, _, _ = validate_evaluation_dataset(dataset=dataset, partition=args.partition,
                                            test_access_granted=test_access)
    state = fit_recovery_state(dataset, fit_as_of=args.fit_as_of)
    config = baseline_prediction_config(canonical_hash(state))
    artifact, missing = prediction_artifact(observations=rows, config=config, state=state,
                                            dataset_hash=dataset["manifest"]["dataset_hash"], partition=args.partition)
    # Create once; never overwrite a frozen baseline or expose private state.
    args.output_root.mkdir(mode=0o700)
    for name, value in (("learned-state.json", state), ("baseline-config.json", config),
                        ("baseline-predictions.json", artifact), ("prediction-missingness.json", missing)):
        path = args.output_root / name
        with path.open("x", encoding="utf-8") as stream:
            path.chmod(0o600)
            json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
    print(json.dumps({"status": "prepared", "learned_state_hash": canonical_hash(state)}))


if __name__ == "__main__":
    main()
