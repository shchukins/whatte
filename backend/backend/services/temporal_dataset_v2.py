"""Explicit first-activity training-day export; legacy datasets are not rewritten."""

from copy import deepcopy
from collections import Counter
from backend.services.temporal_dataset import _as_date, _as_datetime, _choose_feature_snapshot, _as_json_dict
from backend.services.recovery_prediction import canonical_hash
from backend.services.research_evaluator_v2 import MANIFEST_KEYS

DATASET_VERSION = "temporal_dataset_v2"


def build_day_dataset(*, records, feature_snapshots, split, timezone_name, include_test=False):
    records = list(records)
    if len({r["user_id"] for r in records}) > 1:
        raise ValueError("cross_user_dataset_unsupported")
    # Canonical first activity is selected before any eligibility filtering.
    first = {}
    for record in sorted(records, key=lambda r: (_as_datetime(r["activity_start_at"]), r["activity_id"])):
        key = (record["user_id"], str(record["activity_local_date"]))
        first.setdefault(key, record)
    snapshots = list(feature_snapshots)
    accepted, excluded = [], []
    counts = Counter()
    for (user_id, day), record in sorted(first.items()):
        partition = split.partition_for(_as_date(day))
        if partition is None:
            continue
        counts[partition] += 1
        decision = record.get("decision")
        if not decision or decision.get("status") != "available":
            excluded.append({"partition": partition, "reason": "eligible_day_start_decision_missing"})
            continue
        start = _as_datetime(record["activity_start_at"])
        snapshot = _choose_feature_snapshot(
            [s for s in snapshots if s["user_id"] == user_id],
            local_date=_as_date(day), activity_start=start)
        if snapshot is None:
            excluded.append({"partition": partition, "reason": "immutable_day_start_snapshot_missing"})
            continue
        vector = _as_json_dict(snapshot["feature_json"])
        if snapshot["feature_vector_version"] != "daily_feature_vector_v2" or vector.get("feature_vector_version") != "daily_feature_vector_v2":
            excluded.append({"partition": partition, "reason": "response_baseline_context_not_snapshotted"})
            continue
        observation_id = canonical_hash({
            "user_id": user_id, "local_date": day, "timezone": timezone_name,
            "first_activity_id": record["activity_id"], "feature_snapshot_id": snapshot["id"],
            "decision_snapshot_id": decision["source_id"], "target_version": "workout_outcome_v1",
        })
        if record["outcome"].get("contract_version") != "workout_outcome_v1":
            raise ValueError("unsupported_outcome_contract_version")
        target = deepcopy(record["outcome"]["targets"]["next_day_recovery"])
        row = {
            "observation_id": observation_id, "observation_unit": "training_day",
            "user_id": user_id, "partition": partition, "activity_id": record["activity_id"],
            "activity_start_at": start.isoformat(), "activity_local_date": day,
            "feature": {"snapshot_id": snapshot["id"], "feature_vector_version": "daily_feature_vector_v2",
                        "cutoff_at": _as_datetime(snapshot["cutoff_at"]).isoformat(),
                        "captured_at": _as_datetime(snapshot["captured_at"]).isoformat(), "values": vector},
            "decision": deepcopy(decision),
            "outcome": {"contract_version": "workout_outcome_v1", "targets": {"next_day_recovery": target}},
        }
        row["row_hash"] = canonical_hash(row)
        accepted.append(row)
    state = {
        "dataset_version": DATASET_VERSION, "feature_versions": ["daily_feature_vector_v2"],
        "target_versions": ["workout_outcome_v1"], "timezone": timezone_name, "split": split.as_dict(),
        "source_feature_snapshot_ids": sorted({r["feature"]["snapshot_id"] for r in accepted}),
        "row_hashes": [r["row_hash"] for r in accepted],
        "canonical_day_counts": {name: counts[name] for name in ("train", "validation", "test")},
    }
    assert set(state) == set(MANIFEST_KEYS)
    return {
        "dataset_version": DATASET_VERSION,
        "manifest": {**state, "dataset_hash": canonical_hash(state), "excluded_observations": excluded,
                     "partition_counts": {n: sum(r["partition"] == n for r in accepted) for n in counts},
                     "test_access": "included" if include_test else "withheld"},
        "partitions": {n: [r for r in accepted if r["partition"] == n]
                       for n in ("train", "validation", "test") if include_test or n != "test"},
    }
