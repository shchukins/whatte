"""Versioned day-dataset adapter; frozen metric formulas remain evaluator v1's."""

from copy import deepcopy
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from backend.services import research_evaluator as v1
from backend.services.recovery_prediction import canonical_hash, timestamp

EVALUATOR_VERSION = "baseline_evaluator_v2"
DATASET_VERSION = "temporal_dataset_v2"
METRIC_SPECIFICATION = {**v1.METRIC_SPECIFICATION, "evaluator_version": EVALUATOR_VERSION}
METRIC_SPECIFICATION_HASH = canonical_hash(METRIC_SPECIFICATION)
MANIFEST_KEYS = ("dataset_version", "feature_versions", "target_versions", "timezone", "split",
                 "source_feature_snapshot_ids", "row_hashes", "canonical_day_counts")


def _legacy_view(dataset):
    manifest = dataset.get("manifest", {})
    if dataset.get("dataset_version") != DATASET_VERSION or manifest.get("dataset_version") != DATASET_VERSION:
        raise ValueError("unsupported_day_dataset_version")
    if any(k not in manifest for k in MANIFEST_KEYS) or canonical_hash({k: manifest[k] for k in MANIFEST_KEYS}) != manifest.get("dataset_hash"):
        raise ValueError("dataset_manifest_hash_invalid")
    if manifest["feature_versions"] != ["daily_feature_vector_v2"] or manifest["target_versions"] != ["workout_outcome_v1"]:
        raise ValueError("day_dataset_version_mismatch")
    result = deepcopy(dataset)
    result["dataset_version"] = v1.DATASET_VERSION
    result["manifest"]["dataset_version"] = v1.DATASET_VERSION
    result["manifest"]["dataset_hash"] = v1._hash({k: result["manifest"][k] for k in MANIFEST_KEYS if k != "canonical_day_counts"})
    return result


def validate_evaluation_dataset(*, dataset, partition, test_access_granted=False):
    rows, ids, targets = v1.validate_evaluation_dataset(
        dataset=_legacy_view(dataset), partition=partition, test_access_granted=test_access_granted)
    days, users = set(), set()
    for row in rows:
        key = (row["user_id"], row["activity_local_date"])
        if key in days or row.get("observation_unit") != "training_day":
            raise ValueError("duplicate_or_invalid_training_day")
        days.add(key); users.add(row["user_id"])
        day = date.fromisoformat(row["activity_local_date"])
        bounds = dataset["manifest"]["split"]
        lower = date.fromisoformat(bounds["train_start"])
        train_end = date.fromisoformat(bounds["train_end"])
        validation_end = date.fromisoformat(bounds["validation_end"])
        test_end = date.fromisoformat(bounds["test_end"])
        expected = ("train" if lower <= day <= train_end else "validation" if train_end < day <= validation_end
                    else "test" if validation_end < day <= test_end else None)
        if expected != partition or not lower <= train_end <= validation_end <= test_end:
            raise ValueError("day_partition_boundary_mismatch")
        feature = row["feature"]
        vector = feature["values"]
        if vector["user_id"] != row["user_id"] or vector["local_date"] != day.isoformat() or vector["timezone"] != dataset["manifest"]["timezone"]:
            raise ValueError("day_feature_identity_mismatch")
        if not timestamp(feature["cutoff_at"]) <= timestamp(feature["captured_at"]) < timestamp(row["activity_start_at"]):
            raise ValueError("day_start_temporal_boundary")
        decision = row["decision"]
        start = timestamp(row["activity_start_at"])
        if start.astimezone(ZoneInfo(vector["timezone"])).date() != day:
            raise ValueError("activity_local_date_mismatch")
        if feature.get("feature_vector_version") != "daily_feature_vector_v2" or vector.get("feature_vector_version") != "daily_feature_vector_v2":
            raise ValueError("row_feature_version_mismatch")
        if feature["snapshot_id"] not in dataset["manifest"]["source_feature_snapshot_ids"]:
            raise ValueError("source_snapshot_identity_mismatch")
        if timestamp(vector["cutoff_at"]) != timestamp(feature["cutoff_at"]):
            raise ValueError("invalid_feature_cutoff")
        if decision.get("status") != "available" or not timestamp(decision["readiness_computed_at"]) <= timestamp(decision["captured_at"]) < start:
            raise ValueError("day_decision_temporal_boundary")
        expected_id = canonical_hash({
            "user_id": row["user_id"], "local_date": day.isoformat(), "timezone": vector["timezone"],
            "first_activity_id": row["activity_id"], "feature_snapshot_id": feature["snapshot_id"],
            "decision_snapshot_id": decision["source_id"], "target_version": "workout_outcome_v1",
        })
        if row["observation_id"] != expected_id:
            raise ValueError("day_observation_identity_mismatch")
        if row["outcome"].get("contract_version") != "workout_outcome_v1":
            raise ValueError("day_target_version_mismatch")
        target = row["outcome"]["targets"].get("next_day_recovery", {})
        if target.get("status") == "available":
            if str(target.get("target_local_date")) != (day+timedelta(days=1)).isoformat():
                raise ValueError("recovery_target_date_mismatch")
            if timestamp(target["updated_at"]).astimezone(ZoneInfo(vector["timezone"])).date() < day+timedelta(days=1):
                raise ValueError("recovery_feedback_before_target_date")
    count = dataset["manifest"]["canonical_day_counts"].get(partition)
    if type(count) is not int or count < len(rows):
        raise ValueError("invalid_canonical_day_count")
    if len(users) > 1:
        raise ValueError("cross_user_dataset_unsupported")
    return rows, ids, targets


def evaluate_research_candidate(*, dataset, partition, baseline_artifact, candidate_artifact,
                               test_access_granted=False):
    validate_evaluation_dataset(dataset=dataset, partition=partition, test_access_granted=test_access_granted)
    legacy = _legacy_view(dataset)
    artifacts = []
    for artifact in (baseline_artifact, candidate_artifact):
        if artifact["dataset_hash"] != dataset["manifest"]["dataset_hash"]:
            raise ValueError("prediction_dataset_hash_mismatch")
        adapted = deepcopy(artifact)
        adapted["dataset_hash"] = legacy["manifest"]["dataset_hash"]
        artifacts.append(adapted)
    result = v1.evaluate_research_candidate(dataset=legacy, partition=partition,
                                          baseline_artifact=artifacts[0], candidate_artifact=artifacts[1],
                                          test_access_granted=test_access_granted)
    result.update(evaluator_version=EVALUATOR_VERSION, metric_specification_hash=METRIC_SPECIFICATION_HASH)
    result["dataset"].update(dataset_version=DATASET_VERSION, dataset_hash=dataset["manifest"]["dataset_hash"])
    result.pop("evaluation_hash")
    result["evaluation_hash"] = canonical_hash(result)
    return result
