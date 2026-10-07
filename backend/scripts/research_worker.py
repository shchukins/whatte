"""Fixed entrypoint for credential-free research containers."""

import json
from pathlib import Path
import sys

from backend.services.research_evaluator import (
    EVALUATOR_VERSION, METRIC_SPECIFICATION_HASH, evaluate_research_candidate,
)
from backend.services.research_parameter_space import validate_candidate_config

PROTOCOL_VERSION = "research_execution_v1"


def process_request(request):
    if request.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("unsupported_protocol")
    if request["operation"] == "candidate":
        config = validate_candidate_config(request["config"])
        # A schema identity is not an implemented outcome-prediction model.
        # Missing baseline context is not equivalent to unavailable response.
        reason = ("response_baseline_context_not_snapshotted" if config["response_enabled"]
                  else "outcome_prediction_contract_not_implemented")
        return {"protocol_version": PROTOCOL_VERSION, "status": "unsupported", "reason": reason}
    if request["operation"] != "evaluate":
        raise ValueError("unsupported_operation")
    if request["evaluator_version"] != EVALUATOR_VERSION or request["metric_specification_hash"] != METRIC_SPECIFICATION_HASH:
        raise ValueError("evaluator_identity_mismatch")
    result = evaluate_research_candidate(
        dataset=request["dataset"], partition=request["partition"],
        baseline_artifact=request["baseline"], candidate_artifact=request["candidate"],
        test_access_granted=request["test_access_granted"],
    )
    return {"protocol_version": PROTOCOL_VERSION, "status": "ok", "result": result}


def main():
    try:
        request = json.loads(Path("/input/request.json").read_text(encoding="utf-8"))
        result = process_request(request)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0 if result["status"] == "ok" else 2
    except Exception:
        # Never expose private source data or exception values in container logs.
        print("research_worker_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
