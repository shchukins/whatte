"""Trusted offline supervisor for version-pinned, isolated experiments."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from backend.services.research_container import DockerExecutor, ResourceLimits, validate_image
from backend.services.research_evaluator import (
    EVALUATOR_VERSION, METRIC_SPECIFICATION_HASH, evaluate_research_candidate,
    validate_evaluation_dataset,
)
from backend.services.research_experiment import create_research_experiment, finish_research_experiment
from backend.services.research_parameter_space import candidate_config_hash, validate_candidate_config

PROTOCOL_VERSION = "research_execution_v1"


def _write_receipt(directory, value):
    temporary = directory / "receipt.tmp"
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2, default=str), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(directory / "receipt.json")


def run_research_experiment(*, config, dataset, baseline, experiment_id, hypothesis,
                            image, output_root, connection_factory,
                            partition="validation", test_access_granted=False, limits=None):
    config = validate_candidate_config(config)
    image = validate_image(image)
    limits = limits or ResourceLimits()
    if not isinstance(experiment_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", experiment_id):
        raise ValueError("experiment_id must be a safe, unique identifier (1-96 characters)")
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        raise ValueError("hypothesis must be non-empty")
    if partition not in {"train", "validation", "test"}:
        raise ValueError("invalid partition")
    rows, _, _ = validate_evaluation_dataset(dataset=dataset, partition=partition,
                                            test_access_granted=test_access_granted)
    if dataset["manifest"]["feature_versions"] != [config["feature_vector_version"]]:
        raise ValueError("feature_version_mismatch")
    if dataset["manifest"]["target_versions"] != ["workout_outcome_v1"]:
        raise ValueError("target_version_mismatch")
    # Frozen baseline validation occurs before audit creation or execution.
    selected_dataset = deepcopy(dataset)
    selected_dataset["partitions"] = {partition: deepcopy(rows)}
    evaluate_research_candidate(dataset=selected_dataset, partition=partition,
                               baseline_artifact=baseline, candidate_artifact=baseline,
                               test_access_granted=test_access_granted)
    for row in rows:
        feature = row.get("feature", {})
        if feature.get("feature_vector_version") != config["feature_vector_version"]:
            raise ValueError("row_feature_version_mismatch")
        if not isinstance(feature.get("values"), dict):
            raise ValueError("row_feature_payload_missing")
    dataset_hash = dataset["manifest"]["dataset_hash"]
    config_hash = candidate_config_hash(config)
    baseline_hash = hashlib.sha256(json.dumps(baseline, sort_keys=True, separators=(",", ":"),
                                               allow_nan=False).encode()).hexdigest()
    # Pin host supervisor implementation as well as worker image and metric spec.
    source_files = [Path(__file__), Path(__file__).with_name("research_container.py"),
                    Path(__file__).with_name("research_writer.py"),
                    Path(__file__).with_name("research_evaluator.py"),
                    Path(__file__).with_name("research_experiment.py"),
                    Path(__file__).with_name("research_parameter_space.py")]
    source_hash = hashlib.sha256(b"".join(path.read_bytes() for path in source_files)).hexdigest()
    metadata = {"protocol_version": PROTOCOL_VERSION, "image": image,
                "limits": limits.as_dict(), "baseline_artifact_hash": baseline_hash,
                "runner_source_hash": source_hash, "stages": []}
    # Private parent prevents exposing readable bind-mounted input to other users.
    root = Path(output_root).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_mode & 0o077:
        raise ValueError("output_root must be private (mode 0700)")
    directory = root / experiment_id
    directory.mkdir(mode=0o700)  # Repeated IDs never overwrite local artifacts.
    receipt = {"experiment_id": experiment_id, "candidate_config_hash": config_hash,
               "dataset_hash": dataset_hash, "status": "creating", "execution_metadata": metadata}
    _write_receipt(directory, receipt)
    create_research_experiment(
        experiment_id=experiment_id, hypothesis=hypothesis,
        candidate_model_version=config["candidate_model_version"], candidate_config=config,
        dataset_version=config["dataset_version"], dataset_hash=dataset_hash,
        dataset_partition=partition, evaluator_version=EVALUATOR_VERSION,
        evaluator_specification_hash=METRIC_SPECIFICATION_HASH,
        provider_metadata={"runner_protocol": PROTOCOL_VERSION, "image": image,
                           "limits": limits.as_dict(), "baseline_artifact_hash": baseline_hash,
                           "runner_source_hash": source_hash}, connection_factory=connection_factory,
    )
    receipt["status"] = "running"
    metrics, failure = None, None
    try:
        _write_receipt(directory, receipt)
        executor = DockerExecutor(image, limits)
        request = {"protocol_version": PROTOCOL_VERSION, "operation": "candidate",
                   "config": config, "candidate_config_hash": config_hash,
                   "experiment_id": experiment_id, "dataset_hash": dataset_hash,
                   "partition": partition,
                   "observations": [{"observation_id": row["observation_id"],
                                     "feature": row["feature"]} for row in rows]}
        stage = executor.execute(request, directory / "candidate")
        metadata["stages"].append(stage["metadata"])
        response = stage["response"]
        if isinstance(response, dict) and response.get("protocol_version") == PROTOCOL_VERSION and response.get("status") == "unsupported":
            # Fixed worker reasons only; untrusted error text never enters audit.
            reason = response.get("reason")
            if reason in {"response_baseline_context_not_snapshotted", "outcome_prediction_contract_not_implemented"} and stage["metadata"].get("cleanup_succeeded"):
                raise ValueError(reason)
        if stage["metadata"]["failure_reason"]:
            raise ValueError(stage["metadata"]["failure_reason"])
        if not isinstance(response, dict) or response.get("protocol_version") != PROTOCOL_VERSION or response.get("status") != "ok" or response.get("candidate_config_hash") != config_hash:
            raise ValueError("candidate_response_identity_mismatch")
        candidate = response["result"]
        if candidate.get("candidate_id") != config_hash or candidate.get("candidate_version") != config["candidate_model_version"]:
            raise ValueError("candidate_artifact_identity_mismatch")
        stage = executor.execute({"protocol_version": PROTOCOL_VERSION, "operation": "evaluate",
                                  "evaluator_version": EVALUATOR_VERSION,
                                  "metric_specification_hash": METRIC_SPECIFICATION_HASH,
                                  "dataset": selected_dataset, "baseline": baseline,
                                  "candidate": candidate, "partition": partition,
                                  "test_access_granted": test_access_granted}, directory / "evaluator")
        metadata["stages"].append(stage["metadata"])
        response = stage["response"]
        if stage["metadata"]["failure_reason"]:
            raise ValueError(stage["metadata"]["failure_reason"])
        if not isinstance(response, dict) or response.get("protocol_version") != PROTOCOL_VERSION or response.get("status") != "ok":
            raise ValueError("invalid_evaluator_response")
        metrics = response["result"]
        # Independently verify the frozen result; candidate image cannot rewrite metrics.
        expected = evaluate_research_candidate(dataset=selected_dataset, partition=partition,
                                               baseline_artifact=baseline, candidate_artifact=candidate,
                                               test_access_granted=test_access_granted)
        if metrics != expected:
            raise ValueError("frozen_evaluation_result_mismatch")
    except (Exception, KeyboardInterrupt) as error:
        metrics = None
        # Reason codes from local checks are safe; arbitrary exception messages are private.
        allowed = {"response_baseline_context_not_snapshotted", "outcome_prediction_contract_not_implemented",
                   "candidate_response_identity_mismatch", "candidate_artifact_identity_mismatch",
                   "invalid_evaluator_response", "frozen_evaluation_result_mismatch",
                   "container_input_limit_exceeded", "bind_mount_path_contains_comma"}
        allowed.update(s.get("failure_reason") for s in metadata["stages"] if s.get("failure_reason"))
        failure = ("runner_interrupted" if isinstance(error, KeyboardInterrupt) else
                   str(error) if isinstance(error, ValueError) and str(error) in allowed else "runner_execution_failed")
    status = "failed" if failure else "candidate"
    receipt.update(status=status, failure_reason=failure)
    try:
        _write_receipt(directory, receipt)
    except OSError:
        # A full local disk must not prevent the terminal database transition.
        metadata["local_receipt_write_failed"] = True
    try:
        result = finish_research_experiment(
            experiment_id=experiment_id, status=status, metrics=metrics, failure_reason=failure,
            failure_log_reference=str(directory / "receipt.json") if failure else None,
            execution_metadata=metadata, connection_factory=connection_factory,
        )
    except Exception:
        receipt["status"] = "persistence_failed"
        try:
            _write_receipt(directory, receipt)
        except OSError:
            pass
        raise RuntimeError("audit_persistence_failed; inspect private receipt, do not rerun same ID") from None
    receipt["persisted"] = True
    receipt_updated = True
    try:
        _write_receipt(directory, receipt)
    except OSError:
        receipt_updated = False
    return {"experiment_id": experiment_id, "status": result["status"],
            "failure_reason": failure, "receipt_reference": str(directory / "receipt.json"),
            "receipt_updated": receipt_updated}
