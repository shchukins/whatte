"""Deterministic offline research exports from immutable decision-time inputs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any, Iterable

from backend.config import settings
from backend.db import get_conn
from backend.services.calibration_records import (
    OUTCOME_CONTRACT_VERSION,
    generate_calibration_records,
)


DATASET_VERSION = "temporal_dataset_v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value)
    else:
        raise ValueError("snapshot timestamp is missing or invalid")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("snapshot timestamp must be timezone-aware")
    return result.astimezone(timezone.utc)


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _as_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("feature snapshot payload must be an object")


@dataclass(frozen=True)
class TemporalSplit:
    train_start: date
    train_end: date
    validation_end: date
    test_end: date

    def __post_init__(self) -> None:
        if not (self.train_start <= self.train_end <= self.validation_end <= self.test_end):
            raise ValueError("temporal split bounds must be ordered")

    def partition_for(self, local_date: date) -> str | None:
        if self.train_start <= local_date <= self.train_end:
            return "train"
        if self.train_end < local_date <= self.validation_end:
            return "validation"
        if self.validation_end < local_date <= self.test_end:
            return "test"
        return None

    def as_dict(self) -> dict[str, str]:
        return {
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "validation_end": self.validation_end.isoformat(),
            "test_end": self.test_end.isoformat(),
        }


def _choose_feature_snapshot(
    snapshots: Iterable[dict[str, Any]], *, local_date: date, activity_start: datetime,
) -> dict[str, Any] | None:
    eligible = []
    for snapshot in snapshots:
        if _as_date(snapshot["local_date"]) != local_date:
            continue
        captured_at = _as_datetime(snapshot["captured_at"])
        cutoff_at = _as_datetime(snapshot["cutoff_at"])
        # Both the capture and every vector source boundary must precede the
        # observed activity. A later snapshot is not historical evidence.
        if captured_at >= activity_start or cutoff_at > captured_at:
            continue
        eligible.append((captured_at, int(snapshot["id"]), snapshot))
    return max(eligible, default=(None, None, None), key=lambda item: item[:2])[2]


def _observation_id(record: dict[str, Any], snapshot: dict[str, Any]) -> str:
    decision = record["decision"]
    return _hash({
        "user_id": record["user_id"],
        "activity_id": record["activity_id"],
        "feature_snapshot_id": snapshot["id"],
        "decision_snapshot_id": decision["source_id"],
        "feature_version": snapshot["feature_vector_version"],
        "target_version": record["outcome"]["contract_version"],
    })


def build_temporal_dataset(
    *, records: Iterable[dict[str, Any]], feature_snapshots: Iterable[dict[str, Any]],
    split: TemporalSplit, timezone_name: str, include_test: bool = False,
) -> dict[str, Any]:
    """Build a reproducible dataset without reading current feature state.

    ``records`` supplies versioned outcome envelopes. ``feature_snapshots`` is
    the sole feature source: absent immutable evidence excludes an observation.
    """
    snapshot_rows = list(feature_snapshots)
    accepted: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    used_snapshot_ids: set[int] = set()
    seen_recovery_days: set[str] = set()

    for record in records:
        local_date = _as_date(record["activity_local_date"])
        partition = split.partition_for(local_date)
        if partition is None:
            continue
        activity_start = _as_datetime(record["activity_start_at"])
        decision = record.get("decision")
        if not decision or decision.get("status") != "available":
            excluded.append({
                "activity_id": record["activity_id"],
                "local_date": local_date.isoformat(),
                "reason": "eligible_pre_activity_decision_missing",
            })
            continue
        snapshot = _choose_feature_snapshot(
            snapshot_rows, local_date=local_date, activity_start=activity_start,
        )
        if snapshot is None:
            excluded.append({
                "activity_id": record["activity_id"],
                "local_date": local_date.isoformat(),
                "reason": "immutable_feature_snapshot_missing",
            })
            continue
        feature_json = _as_json_dict(snapshot["feature_json"])
        if feature_json.get("feature_vector_version") != snapshot["feature_vector_version"]:
            raise ValueError("feature snapshot version does not match its payload")
        outcome = deepcopy(record["outcome"])
        if outcome.get("contract_version") != OUTCOME_CONTRACT_VERSION:
            raise ValueError("unsupported outcome contract version")
        day_key = local_date.isoformat()
        recovery = outcome["targets"].get("next_day_recovery")
        if recovery is not None and day_key in seen_recovery_days:
            outcome["targets"]["next_day_recovery"] = {
                "unit": "training_day",
                "status": "shared_training_day_target",
                "value": None,
                "shared_with_local_date": day_key,
            }
        else:
            seen_recovery_days.add(day_key)
        observation = {
            "observation_id": _observation_id(record, snapshot),
            "partition": partition,
            "activity_id": record["activity_id"],
            "activity_start_at": activity_start.isoformat(),
            "activity_local_date": day_key,
            "feature": {
                "snapshot_id": snapshot["id"],
                "feature_vector_version": snapshot["feature_vector_version"],
                "cutoff_at": _as_datetime(snapshot["cutoff_at"]).isoformat(),
                "captured_at": _as_datetime(snapshot["captured_at"]).isoformat(),
                "values": feature_json,
            },
            "decision": decision,
            "outcome": outcome,
        }
        observation["row_hash"] = _hash(observation)
        accepted.append(observation)
        used_snapshot_ids.add(int(snapshot["id"]))

    accepted.sort(key=lambda row: (row["activity_start_at"], row["observation_id"]))
    visible = [row for row in accepted if include_test or row["partition"] != "test"]
    partition_counts = {
        name: sum(row["partition"] == name for row in accepted)
        for name in ("train", "validation", "test")
    }
    manifest_state = {
        "dataset_version": DATASET_VERSION,
        "feature_versions": sorted({row["feature"]["feature_vector_version"] for row in accepted}),
        "target_versions": sorted({row["outcome"]["contract_version"] for row in accepted}),
        "timezone": timezone_name,
        "split": split.as_dict(),
        "source_feature_snapshot_ids": sorted(used_snapshot_ids),
        "row_hashes": [row["row_hash"] for row in accepted],
    }
    manifest = {
        **manifest_state,
        "dataset_hash": _hash(manifest_state),
        "partition_counts": partition_counts,
        "test_access": "included" if include_test else "withheld",
        "excluded_observations": excluded,
    }
    return {
        "dataset_version": DATASET_VERSION,
        "manifest": manifest,
        "partitions": {
            name: [row for row in visible if row["partition"] == name]
            for name in ("train", "validation", "test")
            if include_test or name != "test"
        },
    }


def generate_temporal_dataset(
    *, user_id: str, split: TemporalSplit, timezone_name: str | None = None,
    include_test: bool = False, test_access_granted: bool = False,
) -> dict[str, Any]:
    """Load persisted sources and create a read-only research dataset."""
    if include_test and not test_access_granted:
        raise PermissionError("test export requires explicit access")
    timezone_name = timezone_name or settings.whatte_timezone
    report = generate_calibration_records(
        user_id=user_id, date_from=split.train_start, date_to=split.test_end,
        timezone=timezone_name,
    )
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("set transaction isolation level repeatable read, read only")
            cur.execute(
                """
                select id, local_date, feature_vector_version, cutoff_at,
                       feature_json, captured_at
                from research_feature_snapshot
                where user_id = %s and local_date between %s and %s
                  and event_type = 'daily_readiness_delivery'
                order by local_date, captured_at, id;
                """,
                (user_id, split.train_start, split.test_end),
            )
            snapshots = [
                dict(zip(
                    ("id", "local_date", "feature_vector_version", "cutoff_at",
                     "feature_json", "captured_at"), row,
                ))
                for row in cur.fetchall()
            ]
    return build_temporal_dataset(
        records=report["records"], feature_snapshots=snapshots, split=split,
        timezone_name=timezone_name, include_test=include_test,
    )
