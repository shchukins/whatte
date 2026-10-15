"""Run frozen PED research; private files, existing evaluator/executor/audit only."""
import argparse
import json
import os
from pathlib import Path
from backend.services.research_runner import run_ped_study
from backend.services.research_writer import research_writer_connection
from scripts.run_research_experiment import _load


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "evidence", "output-root"):
        parser.add_argument("--"+name, type=Path, required=True)
    for name in ("fit-as-of", "experiment-id"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--partition", choices=("validation", "test"), default="validation")
    parser.add_argument("--image")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    dsn = os.getenv("WHATTE_RESEARCH_DATABASE_URL")
    if args.audit and not dsn:
        parser.error("--audit requires dedicated WHATTE_RESEARCH_DATABASE_URL")
    try:
        report = run_ped_study(dataset=_load(args.dataset, 64*1024*1024),
            evidence=_load(args.evidence, 64*1024*1024), fit_as_of=args.fit_as_of,
            partition=args.partition, test_access_granted=os.getenv("WHATTE_RESEARCH_TEST_ACCESS") == "granted",
            experiment_id=args.experiment_id, output_root=args.output_root, image=args.image,
            connection_factory=(lambda: research_writer_connection(dsn)) if args.audit else None)
    except Exception:
        print(json.dumps({"status": "failed", "reason": "ped_study_input_or_execution_invalid"}))
        return 1
    print(json.dumps({k: report[k] for k in ("study_version", "recommendation", "report_hash")}))
    return 2 if report["recommendation"] == "insufficient_evidence" else 0


if __name__ == "__main__":
    raise SystemExit(main())
