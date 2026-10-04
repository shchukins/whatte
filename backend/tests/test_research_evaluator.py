import hashlib
import json
import math
import sys

import pytest

from backend.services.research_evaluator import (
    CALIBRATION_BIN_COUNT,
    EVALUATOR_VERSION,
    METRIC_SPECIFICATION_HASH,
    evaluate_research_candidate,
)
from scripts.evaluate_research_candidate import main as evaluator_cli_main


def _canonical_hash(value):
    encoded = json.dumps(
        value, default=str, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _target(*, status="available", score=None, value=None, scale=None, unit="activity"):
    result = {"unit": unit, "status": status}
    if score is not None:
        result["score"] = score
    if value is not None:
        result["value"] = value
    if scale is not None:
        result["scale"] = scale
    return result


def _row(observation_id, rpe, recovery, sustainable, *, partition="validation"):
    return {
        "observation_id": observation_id,
        "partition": partition,
        "outcome": {
            "contract_version": "workout_outcome_v1",
            "targets": {
                "post_workout_rpe": rpe,
                "next_day_recovery": recovery,
                "sustainable_session": sustainable,
            },
        },
    }


def _dataset(*, partition="validation"):
    rows = [
        _row(
            "obs-1",
            _target(score=4, scale="1-10"),
            _target(score=2, scale="1-5", unit="training_day"),
            _target(value=1, scale="binary"),
            partition=partition,
        ),
        _row(
            "obs-2",
            _target(score=8, scale="1-10"),
            _target(status="shared_training_day_target", unit="training_day"),
            _target(value=0, scale="binary"),
            partition=partition,
        ),
        _row(
            "obs-3",
            _target(status="missing"),
            _target(score=4, scale="1-5", unit="training_day"),
            _target(status="missing"),
            partition=partition,
        ),
    ]
    for row in rows:
        row["row_hash"] = _canonical_hash(row)
    manifest_state = {
        "dataset_version": "temporal_dataset_v1",
        "feature_versions": ["daily_feature_vector_v1"],
        "target_versions": ["workout_outcome_v1"],
        "timezone": "Europe/Moscow",
        "split": {
            "train_start": "2026-09-01", "train_end": "2026-09-01",
            "validation_end": "2026-09-02", "test_end": "2026-09-03",
        },
        "source_feature_snapshot_ids": [1, 2, 3],
        "row_hashes": [row["row_hash"] for row in rows],
    }
    return {
        "dataset_version": "temporal_dataset_v1",
        "manifest": {**manifest_state, "dataset_hash": _canonical_hash(manifest_state)},
        "partitions": {partition: rows},
    }


def _dataset_hash(*, partition="validation"):
    return _dataset(partition=partition)["manifest"]["dataset_hash"]


def _empty_dataset():
    dataset = _dataset()
    dataset["manifest"]["row_hashes"] = []
    dataset["manifest"]["dataset_hash"] = _canonical_hash({
        key: dataset["manifest"][key]
        for key in (
            "dataset_version", "feature_versions", "target_versions", "timezone",
            "split", "source_feature_snapshot_ids", "row_hashes",
        )
    })
    dataset["partitions"]["validation"] = []
    return dataset


def _artifact(candidate_id, *, rpe, binary, recovery=None, partition="validation"):
    specs = [
        {"target_name": "post_workout_rpe", "prediction_type": "point", "scale": "1-10"},
        {
            "target_name": "sustainable_session",
            "prediction_type": "binary_probability",
            "scale": "binary",
        },
    ]
    if recovery is not None:
        specs.append({
            "target_name": "next_day_recovery",
            "prediction_type": "point",
            "scale": "1-5",
        })
    predictions = []
    for observation_id in ("obs-1", "obs-2", "obs-3"):
        targets = {}
        if observation_id in rpe:
            targets["post_workout_rpe"] = rpe[observation_id]
        if observation_id in binary:
            targets["sustainable_session"] = binary[observation_id]
        if recovery is not None and observation_id in recovery:
            targets["next_day_recovery"] = recovery[observation_id]
        predictions.append({"observation_id": observation_id, "targets": targets})
    return {
        "prediction_schema_version": "prediction_artifact_v1",
        "candidate_id": candidate_id,
        "candidate_version": "v1",
        "dataset_hash": _dataset_hash(partition=partition),
        "partition": partition,
        "target_specs": specs,
        "predictions": predictions,
    }


def _evaluate():
    baseline = _artifact(
        "baseline",
        rpe={"obs-1": {"value": 5}, "obs-2": {"value": 7}},
        binary={"obs-1": {"probability": 0.8}, "obs-2": {"probability": 0.4}},
        recovery={"obs-1": {"value": 3}, "obs-3": {"value": 3}},
    )
    candidate = _artifact(
        "candidate",
        rpe={"obs-1": {"value": 4}, "obs-2": {"value": 8}},
        binary={"obs-1": {"probability": 0.9}, "obs-2": {"probability": 0.1}},
        recovery={"obs-1": {"value": 2}, "obs-3": {"value": 4}},
    )
    return evaluate_research_candidate(
        dataset=_dataset(), partition="validation",
        baseline_artifact=baseline, candidate_artifact=candidate,
    )


def _result_target(result, side, target_name):
    return next(item for item in result[side]["targets"] if item["target_name"] == target_name)


def _comparison_target(result, target_name):
    return next(
        item for item in result["comparison"]["targets"]
        if item["target_name"] == target_name
    )


def test_evaluator_returns_known_point_and_paired_metrics():
    result = _evaluate()

    assert result["evaluator_version"] == EVALUATOR_VERSION
    assert result["metric_specification_hash"] == METRIC_SPECIFICATION_HASH
    assert result["dataset"] == {
        "dataset_version": "temporal_dataset_v1",
        "dataset_hash": _dataset_hash(),
        "partition": "validation",
        "row_count": 3,
    }
    baseline_rpe = _result_target(result, "baseline", "post_workout_rpe")
    candidate_rpe = _result_target(result, "candidate", "post_workout_rpe")
    comparison = _comparison_target(result, "post_workout_rpe")
    assert baseline_rpe["metrics"]["mae"] == 1.0
    assert candidate_rpe["metrics"]["mae"] == 0.0
    assert baseline_rpe["eligible_target_count"] == 2
    assert baseline_rpe["missing_target_count"] == 1
    assert comparison["paired_count"] == 2
    assert comparison["candidate_minus_baseline"] == {"mae": -1.0}


def test_evaluator_returns_known_probability_and_calibration_metrics():
    result = _evaluate()

    baseline = _result_target(result, "baseline", "sustainable_session")["metrics"]
    candidate = _result_target(result, "candidate", "sustainable_session")["metrics"]
    comparison = _comparison_target(result, "sustainable_session")
    assert baseline["brier_score"] == pytest.approx(0.1)
    assert baseline["log_loss"] == pytest.approx((-math.log(0.8) - math.log(0.6)) / 2)
    assert baseline["calibration"]["expected_calibration_error"] == pytest.approx(0.3)
    assert len(baseline["calibration"]["bins"]) == CALIBRATION_BIN_COUNT
    assert candidate["brier_score"] == pytest.approx(0.01)
    assert candidate["log_loss"] == pytest.approx(-math.log(0.9))
    assert candidate["calibration"]["expected_calibration_error"] == pytest.approx(0.1)
    assert comparison["candidate_minus_baseline"]["brier_score"] == pytest.approx(-0.09)


def test_recovery_uses_only_the_single_available_training_day_target():
    result = _evaluate()

    recovery = _result_target(result, "candidate", "next_day_recovery")
    assert recovery["eligible_target_count"] == 2
    assert recovery["incompatible_target_count"] == 1
    assert recovery["scored_count"] == 2
    assert recovery["metrics"]["mae"] == 0.0


def test_missing_and_invalid_predictions_are_counted_and_null_metrics_are_stable():
    baseline = _artifact(
        "baseline", rpe={"obs-1": {"value": "bad"}}, binary={},
    )
    candidate = _artifact(
        "candidate", rpe={}, binary={"obs-1": {"probability": 2.0}},
    )
    result = evaluate_research_candidate(
        dataset=_dataset(), partition="validation",
        baseline_artifact=baseline, candidate_artifact=candidate,
    )

    baseline_rpe = _result_target(result, "baseline", "post_workout_rpe")
    assert baseline_rpe["invalid_prediction_count"] == 1
    assert baseline_rpe["missing_prediction_count"] == 1
    assert baseline_rpe["scored_count"] == 0
    assert baseline_rpe["metrics"] == {"mae": None}
    candidate_binary = _result_target(result, "candidate", "sustainable_session")
    assert candidate_binary["invalid_prediction_count"] == 1
    assert candidate_binary["missing_prediction_count"] == 1
    assert candidate_binary["metrics"]["brier_score"] is None
    assert candidate_binary["metrics"]["calibration"]["expected_calibration_error"] is None


def test_empty_partition_returns_zero_denominators_and_null_metrics():
    dataset = _empty_dataset()
    baseline = _artifact("baseline", rpe={}, binary={})
    candidate = _artifact("candidate", rpe={}, binary={})
    for artifact in (baseline, candidate):
        artifact["dataset_hash"] = dataset["manifest"]["dataset_hash"]
        artifact["predictions"] = []

    result = evaluate_research_candidate(
        dataset=dataset, partition="validation",
        baseline_artifact=baseline, candidate_artifact=candidate,
    )

    rpe = _result_target(result, "candidate", "post_workout_rpe")
    assert rpe["partition_row_count"] == 0
    assert rpe["eligible_target_count"] == 0
    assert rpe["scored_count"] == 0
    assert rpe["metrics"] == {"mae": None}


def test_result_is_identical_when_artifact_rows_are_reordered():
    first = _evaluate()
    baseline = _artifact(
        "baseline",
        rpe={"obs-1": {"value": 5}, "obs-2": {"value": 7}},
        binary={"obs-1": {"probability": 0.8}, "obs-2": {"probability": 0.4}},
        recovery={"obs-1": {"value": 3}, "obs-3": {"value": 3}},
    )
    candidate = _artifact(
        "candidate",
        rpe={"obs-1": {"value": 4}, "obs-2": {"value": 8}},
        binary={"obs-1": {"probability": 0.9}, "obs-2": {"probability": 0.1}},
        recovery={"obs-1": {"value": 2}, "obs-3": {"value": 4}},
    )
    baseline["predictions"].reverse()
    candidate["predictions"].reverse()
    second = evaluate_research_candidate(
        dataset=_dataset(), partition="validation",
        baseline_artifact=baseline, candidate_artifact=candidate,
    )

    assert second == first


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda artifact: artifact.update({"metrics": ["accuracy"]}), "fields must be exactly"),
        (lambda artifact: artifact.update({"dataset_hash": "wrong"}), "dataset hash"),
        (
            lambda artifact: artifact["predictions"].append(artifact["predictions"][0]),
            "duplicate prediction observation",
        ),
        (
            lambda artifact: artifact["predictions"].append(
                {"observation_id": "unknown", "targets": {}}
            ),
            "unknown observation",
        ),
    ],
)
def test_artifact_cannot_change_metrics_or_dataset_identity(mutation, message):
    baseline = _artifact("baseline", rpe={}, binary={})
    candidate = _artifact("candidate", rpe={}, binary={})
    mutation(candidate)

    with pytest.raises(ValueError, match=message):
        evaluate_research_candidate(
            dataset=_dataset(), partition="validation",
            baseline_artifact=baseline, candidate_artifact=candidate,
        )


@pytest.mark.parametrize("tamper", ("manifest", "row"))
def test_evaluator_rejects_tampered_dataset_content(tamper):
    dataset = _dataset()
    if tamper == "manifest":
        dataset["manifest"]["timezone"] = "UTC"
    else:
        dataset["partitions"]["validation"][0]["outcome"]["targets"][
            "post_workout_rpe"
        ]["score"] = 10
    baseline = _artifact("baseline", rpe={}, binary={})
    candidate = _artifact("candidate", rpe={}, binary={})

    with pytest.raises(ValueError, match="hash is invalid"):
        evaluate_research_candidate(
            dataset=dataset, partition="validation",
            baseline_artifact=baseline, candidate_artifact=candidate,
        )


def test_test_partition_requires_explicit_access():
    baseline = _artifact("baseline", rpe={}, binary={}, partition="test")
    candidate = _artifact("candidate", rpe={}, binary={}, partition="test")

    with pytest.raises(PermissionError, match="explicit access"):
        evaluate_research_candidate(
            dataset=_dataset(partition="test"), partition="test",
            baseline_artifact=baseline, candidate_artifact=candidate,
        )


def test_cli_evaluates_baseline_and_candidate_to_stable_json(tmp_path, monkeypatch, capsys):
    dataset_path = tmp_path / "dataset.json"
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    dataset_path.write_text(json.dumps(_dataset()), encoding="utf-8")
    baseline_path.write_text(json.dumps(_artifact("baseline", rpe={}, binary={})), encoding="utf-8")
    candidate_path.write_text(
        json.dumps(_artifact("candidate", rpe={}, binary={})), encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", [
        "evaluate_research_candidate",
        "--dataset", str(dataset_path),
        "--partition", "validation",
        "--baseline", str(baseline_path),
        "--candidate", str(candidate_path),
    ])

    evaluator_cli_main()

    output = json.loads(capsys.readouterr().out)
    assert output["evaluator_version"] == EVALUATOR_VERSION
    assert output["dataset"]["dataset_hash"] == _dataset_hash()
    assert output["baseline"]["candidate_id"] == "baseline"
    assert output["candidate"]["candidate_id"] == "candidate"
