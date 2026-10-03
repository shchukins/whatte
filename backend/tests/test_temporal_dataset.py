from datetime import date, datetime, timedelta, timezone

import pytest

from backend.services.temporal_dataset import (
    TemporalSplit,
    build_temporal_dataset,
    generate_temporal_dataset,
)


UTC = timezone.utc


def _record(activity_id: int, local_day: date, *, start_hour: int = 8):
    start = datetime.combine(local_day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=start_hour)
    return {
        "user_id": "u",
        "activity_id": activity_id,
        "activity_start_at": start,
        "activity_local_date": local_day,
        "decision": {"status": "available", "source_id": 100 + activity_id},
        "outcome": {
            "contract_version": "workout_outcome_v1",
            "targets": {
                "post_workout_rpe": {"unit": "activity", "status": "available", "score": 7},
                "next_day_recovery": {
                    "unit": "training_day", "status": "available", "score": 4,
                },
            },
        },
    }


def _snapshot(snapshot_id: int, local_day: date, *, hour: int = 6):
    timestamp = datetime.combine(local_day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=hour)
    return {
        "id": snapshot_id,
        "local_date": local_day,
        "feature_vector_version": "daily_feature_vector_v1",
        "cutoff_at": timestamp,
        "captured_at": timestamp,
        "feature_json": {
            "feature_vector_version": "daily_feature_vector_v1",
            "cutoff_at": timestamp.isoformat(),
            "features": {"load.tss": {"value": None, "availability": "unavailable", "reason_codes": ["missing"]}},
        },
    }


def _split():
    return TemporalSplit(date(2026, 9, 1), date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3))


def test_temporal_dataset_is_deterministic_and_withholds_test_rows():
    records = [_record(1, date(2026, 9, 1)), _record(2, date(2026, 9, 2)), _record(3, date(2026, 9, 3))]
    snapshots = [_snapshot(1, date(2026, 9, 1)), _snapshot(2, date(2026, 9, 2)), _snapshot(3, date(2026, 9, 3))]

    first = build_temporal_dataset(
        records=records, feature_snapshots=snapshots, split=_split(), timezone_name="Europe/Moscow",
    )
    second = build_temporal_dataset(
        records=records, feature_snapshots=snapshots, split=_split(), timezone_name="Europe/Moscow",
    )

    assert first["manifest"]["dataset_hash"] == second["manifest"]["dataset_hash"]
    assert set(first["partitions"]) == {"train", "validation"}
    assert first["manifest"]["partition_counts"] == {"train": 1, "validation": 1, "test": 1}
    assert first["manifest"]["test_access"] == "withheld"
    visible_ids = [row["activity_id"] for rows in first["partitions"].values() for row in rows]
    assert visible_ids == [1, 2]


def test_temporal_dataset_never_uses_a_feature_snapshot_captured_after_activity():
    result = build_temporal_dataset(
        records=[_record(1, date(2026, 9, 1))],
        feature_snapshots=[_snapshot(1, date(2026, 9, 1), hour=9)],
        split=_split(), timezone_name="Europe/Moscow",
    )

    assert result["partitions"]["train"] == []
    assert result["manifest"]["excluded_observations"] == [{
        "activity_id": 1, "local_date": "2026-09-01", "reason": "immutable_feature_snapshot_missing",
    }]


def test_temporal_dataset_keeps_empty_partitions_explicit():
    result = build_temporal_dataset(
        records=[_record(1, date(2026, 9, 1))],
        feature_snapshots=[_snapshot(1, date(2026, 9, 1))],
        split=_split(), timezone_name="Europe/Moscow",
    )

    assert result["partitions"]["validation"] == []
    assert result["manifest"]["partition_counts"] == {"train": 1, "validation": 0, "test": 0}


def test_next_day_recovery_is_not_duplicated_for_same_training_day():
    result = build_temporal_dataset(
        records=[_record(1, date(2026, 9, 1), start_hour=8), _record(2, date(2026, 9, 1), start_hour=10)],
        feature_snapshots=[_snapshot(1, date(2026, 9, 1))],
        split=_split(), timezone_name="Europe/Moscow",
    )

    first, second = result["partitions"]["train"]
    assert first["outcome"]["targets"]["next_day_recovery"]["status"] == "available"
    assert second["outcome"]["targets"]["next_day_recovery"] == {
        "unit": "training_day", "status": "shared_training_day_target", "value": None,
        "shared_with_local_date": "2026-09-01",
    }


def test_temporal_split_rejects_non_temporal_boundaries():
    with pytest.raises(ValueError, match="ordered"):
        TemporalSplit(date(2026, 9, 2), date(2026, 9, 1), date(2026, 9, 3), date(2026, 9, 4))


def test_test_partition_requires_explicit_access():
    with pytest.raises(PermissionError, match="explicit access"):
        generate_temporal_dataset(user_id="u", split=_split(), include_test=True)
