"""Frozen, deterministic metrics for offline research prediction artifacts."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
import math
from typing import Any

from backend.services.research_versions import DATASET_VERSION


EVALUATOR_VERSION = "baseline_evaluator_v1"
PREDICTION_ARTIFACT_VERSION = "prediction_artifact_v1"
CALIBRATION_BIN_COUNT = 10
LOG_LOSS_EPSILON = 1e-15

# This specification is owned by the evaluator. Candidate artifacts cannot
# supply metric names, bin boundaries, clipping values, or comparison rules.
METRIC_SPECIFICATION = {
    "evaluator_version": EVALUATOR_VERSION,
    "point": {"metrics": ["mae"]},
    "binary_probability": {
        "metrics": [
            "brier_score", "log_loss",
            "calibration.expected_calibration_error",
        ],
        "calibration_bin_count": CALIBRATION_BIN_COUNT,
        "log_loss_epsilon": LOG_LOSS_EPSILON,
    },
    "comparison": "paired_observations_only",
    "metric_direction": "lower_is_better",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, default=str, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


METRIC_SPECIFICATION_HASH = _hash(METRIC_SPECIFICATION)


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{label} fields must be exactly {sorted(expected)}; got {sorted(actual)}"
        )


def _is_number(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _validated_artifact(
    artifact: dict[str, Any], *, dataset_hash: str, partition: str,
    observation_ids: set[str], known_targets: set[str],
) -> dict[str, Any]:
    _require_exact_keys(
        artifact,
        {
            "prediction_schema_version", "candidate_id", "candidate_version",
            "dataset_hash", "partition", "target_specs", "predictions",
        },
        "prediction artifact",
    )
    if artifact["prediction_schema_version"] != PREDICTION_ARTIFACT_VERSION:
        raise ValueError("unsupported prediction artifact version")
    if artifact["dataset_hash"] != dataset_hash:
        raise ValueError("prediction artifact dataset hash does not match dataset")
    if artifact["partition"] != partition:
        raise ValueError("prediction artifact partition does not match evaluation partition")
    for field in ("candidate_id", "candidate_version"):
        if not isinstance(artifact[field], str) or not artifact[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    if not isinstance(artifact["target_specs"], list) or not artifact["target_specs"]:
        raise ValueError("target_specs must be a non-empty list")
    if not isinstance(artifact["predictions"], list):
        raise ValueError("predictions must be a list")

    specs: list[dict[str, str]] = []
    declared_targets: set[str] = set()
    for raw_spec in artifact["target_specs"]:
        if not isinstance(raw_spec, dict):
            raise ValueError("target spec must be an object")
        _require_exact_keys(
            raw_spec, {"target_name", "prediction_type", "scale"}, "target spec",
        )
        target_name = raw_spec["target_name"]
        prediction_type = raw_spec["prediction_type"]
        scale = raw_spec["scale"]
        if known_targets and target_name not in known_targets:
            raise ValueError(f"unknown target in target_specs: {target_name}")
        if prediction_type not in {"point", "binary_probability"}:
            raise ValueError(f"unsupported prediction type: {prediction_type}")
        if not isinstance(scale, str) or not scale:
            raise ValueError("target spec scale must be a non-empty string")
        if target_name in declared_targets:
            raise ValueError(f"duplicate target spec: {target_name}/{scale}")
        declared_targets.add(target_name)
        specs.append({
            "target_name": target_name,
            "prediction_type": prediction_type,
            "scale": scale,
        })

    predictions: dict[str, dict[str, Any]] = {}
    for raw_prediction in artifact["predictions"]:
        if not isinstance(raw_prediction, dict):
            raise ValueError("prediction row must be an object")
        _require_exact_keys(raw_prediction, {"observation_id", "targets"}, "prediction row")
        observation_id = raw_prediction["observation_id"]
        if observation_id not in observation_ids:
            raise ValueError(f"prediction references unknown observation: {observation_id}")
        if observation_id in predictions:
            raise ValueError(f"duplicate prediction observation: {observation_id}")
        if not isinstance(raw_prediction["targets"], dict):
            raise ValueError("prediction row targets must be an object")
        unknown = set(raw_prediction["targets"]) - declared_targets
        if unknown:
            raise ValueError(f"prediction contains undeclared targets: {sorted(unknown)}")
        predictions[observation_id] = deepcopy(raw_prediction["targets"])

    return {
        "candidate_id": artifact["candidate_id"],
        "candidate_version": artifact["candidate_version"],
        "target_specs": sorted(
            specs, key=lambda item: (item["target_name"], item["scale"]),
        ),
        "predictions": predictions,
    }


def _target_actual(target: dict[str, Any], spec: dict[str, str]) -> tuple[bool, Any]:
    if target.get("status") != "available" or target.get("scale") != spec["scale"]:
        return False, None
    if spec["prediction_type"] == "point":
        actual = target.get("score", target.get("value"))
        return (_is_number(actual), actual)
    actual = target.get("value")
    if type(actual) is bool:
        return True, int(actual)
    if type(actual) is int and actual in {0, 1}:
        return True, actual
    return False, None


def _prediction_value(raw: Any, prediction_type: str) -> tuple[bool, float | None]:
    if not isinstance(raw, dict):
        return False, None
    expected_key = "value" if prediction_type == "point" else "probability"
    if set(raw) != {expected_key} or not _is_number(raw[expected_key]):
        return False, None
    value = float(raw[expected_key])
    if prediction_type == "binary_probability" and not 0.0 <= value <= 1.0:
        return False, None
    return True, value


def _calibration_summary(pairs: list[tuple[float, int]]) -> dict[str, Any]:
    bins = []
    weighted_error = 0.0
    for index in range(CALIBRATION_BIN_COUNT):
        lower = index / CALIBRATION_BIN_COUNT
        upper = (index + 1) / CALIBRATION_BIN_COUNT
        members = [
            (probability, actual) for probability, actual in pairs
            if lower <= probability < upper
            or (index == CALIBRATION_BIN_COUNT - 1 and probability == 1.0)
        ]
        if members:
            mean_probability = sum(item[0] for item in members) / len(members)
            observed_rate = sum(item[1] for item in members) / len(members)
            absolute_error = abs(mean_probability - observed_rate)
            weighted_error += len(members) * absolute_error
        else:
            mean_probability = None
            observed_rate = None
            absolute_error = None
        bins.append({
            "index": index,
            "lower_inclusive": lower,
            "upper_inclusive": index == CALIBRATION_BIN_COUNT - 1,
            "upper": upper,
            "count": len(members),
            "mean_probability": mean_probability,
            "observed_rate": observed_rate,
            "absolute_error": absolute_error,
        })
    return {
        "bin_count": CALIBRATION_BIN_COUNT,
        "expected_calibration_error": weighted_error / len(pairs) if pairs else None,
        "bins": bins,
    }


def _metrics(pairs: list[tuple[float, float]], prediction_type: str) -> dict[str, Any]:
    if not pairs:
        if prediction_type == "point":
            return {"mae": None}
        return {
            "brier_score": None,
            "log_loss": None,
            "calibration": _calibration_summary([]),
        }
    if prediction_type == "point":
        return {"mae": sum(abs(predicted - actual) for predicted, actual in pairs) / len(pairs)}
    binary_pairs = [(predicted, int(actual)) for predicted, actual in pairs]
    brier = sum((predicted - actual) ** 2 for predicted, actual in binary_pairs) / len(binary_pairs)
    losses = []
    for predicted, actual in binary_pairs:
        clipped = min(max(predicted, LOG_LOSS_EPSILON), 1.0 - LOG_LOSS_EPSILON)
        losses.append(-(actual * math.log(clipped) + (1 - actual) * math.log(1 - clipped)))
    return {
        "brier_score": brier,
        "log_loss": sum(losses) / len(losses),
        "calibration": _calibration_summary(binary_pairs),
    }


def _series_for(
    rows: list[dict[str, Any]], artifact: dict[str, Any], spec: dict[str, str],
) -> tuple[dict[str, Any], dict[str, tuple[float, float]]]:
    status_counts: Counter[str] = Counter()
    pairs: dict[str, tuple[float, float]] = {}
    missing_prediction_count = 0
    invalid_prediction_count = 0
    incompatible_scale_count = 0
    target_name = spec["target_name"]

    for row in rows:
        target = row["outcome"]["targets"].get(target_name)
        if not isinstance(target, dict):
            status_counts["absent"] += 1
            continue
        status_counts[str(target.get("status", "unknown"))] += 1
        if target.get("status") == "available" and target.get("scale") != spec["scale"]:
            incompatible_scale_count += 1
        actual_valid, actual = _target_actual(target, spec)
        if not actual_valid:
            continue
        raw = artifact["predictions"].get(row["observation_id"], {}).get(target_name)
        if raw is None:
            missing_prediction_count += 1
            continue
        prediction_valid, predicted = _prediction_value(raw, spec["prediction_type"])
        if not prediction_valid:
            invalid_prediction_count += 1
            continue
        pairs[row["observation_id"]] = (predicted, float(actual))

    result = {
        **spec,
        "partition_row_count": len(rows),
        "eligible_target_count": len(pairs) + missing_prediction_count + invalid_prediction_count,
        "missing_target_count": status_counts.get("missing", 0) + status_counts.get("absent", 0),
        "incompatible_target_count": (
            sum(
                count for status, count in status_counts.items()
                if status not in {"available", "missing", "absent"}
            )
            + incompatible_scale_count
        ),
        "missing_prediction_count": missing_prediction_count,
        "invalid_prediction_count": invalid_prediction_count,
        "scored_count": len(pairs),
        "target_status_counts": dict(sorted(status_counts.items())),
        "metrics": _metrics(list(pairs.values()), spec["prediction_type"]),
    }
    return result, pairs


def _evaluate_artifact(
    rows: list[dict[str, Any]], artifact: dict[str, Any],
) -> tuple[dict[str, Any], dict[tuple[str, str, str], dict[str, tuple[float, float]]]]:
    target_results = []
    pair_sets = {}
    for spec in artifact["target_specs"]:
        result, pairs = _series_for(rows, artifact, spec)
        target_results.append(result)
        pair_sets[(spec["target_name"], spec["prediction_type"], spec["scale"])] = pairs
    return {
        "candidate_id": artifact["candidate_id"],
        "candidate_version": artifact["candidate_version"],
        "targets": target_results,
    }, pair_sets


def _metric_deltas(
    baseline: dict[str, Any], candidate: dict[str, Any], prediction_type: str,
) -> dict[str, Any]:
    if prediction_type == "point":
        return {"mae": candidate["mae"] - baseline["mae"]}
    return {
        "brier_score": candidate["brier_score"] - baseline["brier_score"],
        "log_loss": candidate["log_loss"] - baseline["log_loss"],
        "calibration_error": (
            candidate["calibration"]["expected_calibration_error"]
            - baseline["calibration"]["expected_calibration_error"]
        ),
    }


def _comparison(
    baseline_pairs: dict[tuple[str, str, str], dict[str, tuple[float, float]]],
    candidate_pairs: dict[tuple[str, str, str], dict[str, tuple[float, float]]],
) -> dict[str, Any]:
    targets = []
    for key in sorted(set(baseline_pairs) | set(candidate_pairs)):
        target_name, prediction_type, scale = key
        if key not in baseline_pairs or key not in candidate_pairs:
            targets.append({
                "target_name": target_name, "prediction_type": prediction_type,
                "scale": scale, "status": "not_comparable_target_spec",
                "paired_count": 0, "baseline_metrics": None,
                "candidate_metrics": None, "candidate_minus_baseline": None,
            })
            continue
        common_ids = sorted(set(baseline_pairs[key]) & set(candidate_pairs[key]))
        baseline_values = [baseline_pairs[key][item] for item in common_ids]
        candidate_values = [candidate_pairs[key][item] for item in common_ids]
        baseline_metrics = _metrics(baseline_values, prediction_type)
        candidate_metrics = _metrics(candidate_values, prediction_type)
        targets.append({
            "target_name": target_name,
            "prediction_type": prediction_type,
            "scale": scale,
            "status": "comparable" if common_ids else "no_paired_observations",
            "paired_count": len(common_ids),
            "baseline_metrics": baseline_metrics,
            "candidate_metrics": candidate_metrics,
            "candidate_minus_baseline": (
                _metric_deltas(baseline_metrics, candidate_metrics, prediction_type)
                if common_ids else None
            ),
        })
    return {"comparison_rule": "paired_observations_only", "targets": targets}


def evaluate_research_candidate(
    *, dataset: dict[str, Any], partition: str,
    baseline_artifact: dict[str, Any], candidate_artifact: dict[str, Any],
    test_access_granted: bool = False,
) -> dict[str, Any]:
    """Compare frozen prediction artifacts on one immutable dataset partition."""
    rows, observation_ids, known_targets = validate_evaluation_dataset(
        dataset=dataset, partition=partition, test_access_granted=test_access_granted,
    )
    manifest = dataset["manifest"]
    artifact_args = {
        "dataset_hash": manifest["dataset_hash"],
        "partition": partition,
        "observation_ids": set(observation_ids),
        "known_targets": known_targets,
    }
    baseline = _validated_artifact(baseline_artifact, **artifact_args)
    candidate = _validated_artifact(candidate_artifact, **artifact_args)
    baseline_result, baseline_pairs = _evaluate_artifact(rows, baseline)
    candidate_result, candidate_pairs = _evaluate_artifact(rows, candidate)
    result = {
        "evaluator_version": EVALUATOR_VERSION,
        "prediction_schema_version": PREDICTION_ARTIFACT_VERSION,
        "metric_specification_hash": METRIC_SPECIFICATION_HASH,
        "dataset": {
            "dataset_version": DATASET_VERSION,
            "dataset_hash": manifest["dataset_hash"],
            "partition": partition,
            "row_count": len(rows),
        },
        "baseline": baseline_result,
        "candidate": candidate_result,
        "comparison": _comparison(baseline_pairs, candidate_pairs),
    }
    result["evaluation_hash"] = _hash(result)
    return result


def validate_evaluation_dataset(
    *, dataset: dict[str, Any], partition: str, test_access_granted: bool = False,
) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    """Validate frozen input before execution, using the evaluator's own rules."""
    if dataset.get("dataset_version") != DATASET_VERSION:
        raise ValueError("unsupported temporal dataset version")
    manifest = dataset.get("manifest")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("dataset_hash"), str):
        raise ValueError("dataset manifest hash is missing")
    manifest_state_keys = (
        "dataset_version", "feature_versions", "target_versions", "timezone",
        "split", "source_feature_snapshot_ids", "row_hashes",
    )
    if any(key not in manifest for key in manifest_state_keys):
        raise ValueError("dataset manifest state is incomplete")
    manifest_state = {key: manifest[key] for key in manifest_state_keys}
    if manifest_state["dataset_version"] != DATASET_VERSION:
        raise ValueError("dataset manifest version does not match dataset")
    if _hash(manifest_state) != manifest["dataset_hash"]:
        raise ValueError("dataset manifest hash is invalid")
    if partition == "test" and not test_access_granted:
        raise PermissionError("test evaluation requires explicit access")
    partitions = dataset.get("partitions")
    if not isinstance(partitions, dict) or partition not in partitions:
        raise ValueError(f"dataset partition is unavailable: {partition}")
    rows = partitions[partition]
    if not isinstance(rows, list):
        raise ValueError("dataset partition must be a list")
    observation_ids = []
    known_targets: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("observation_id"), str):
            raise ValueError("dataset row has no observation_id")
        if row.get("partition") != partition:
            raise ValueError("dataset row partition does not match requested partition")
        if not isinstance(row.get("row_hash"), str):
            raise ValueError("dataset row hash is missing")
        row_state = {key: value for key, value in row.items() if key != "row_hash"}
        if _hash(row_state) != row["row_hash"]:
            raise ValueError("dataset row hash is invalid")
        if row["row_hash"] not in manifest["row_hashes"]:
            raise ValueError("dataset row hash is absent from manifest")
        observation_ids.append(row["observation_id"])
        targets = row.get("outcome", {}).get("targets")
        if not isinstance(targets, dict):
            raise ValueError("dataset row has no outcome targets")
        known_targets.update(targets)
    if len(observation_ids) != len(set(observation_ids)):
        raise ValueError("dataset partition contains duplicate observation IDs")

    return rows, observation_ids, known_targets
