"""Research-only persistence for auditable offline experiment lifecycles."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping

from backend.db import get_conn


EXPERIMENT_SCHEMA_VERSION = "research_experiment_v1"
RUNNING = "running"
TERMINAL_STATUSES = frozenset({"candidate", "rejected", "failed"})


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _nonempty(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _object(value: Mapping[str, Any] | None, field: str, *, required: bool) -> dict[str, Any] | None:
    if value is None and not required:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return dict(value)


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def create_research_experiment(
    *,
    experiment_id: str,
    hypothesis: str,
    candidate_model_version: str,
    candidate_config: Mapping[str, Any],
    dataset_version: str,
    dataset_hash: str,
    dataset_partition: str,
    evaluator_version: str,
    evaluator_specification_hash: str,
    parent_experiment_id: str | None = None,
    baseline_experiment_id: str | None = None,
    provider_metadata: Mapping[str, Any] | None = None,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    """Create a running audit record without executing a candidate or reading user data."""
    normalized_id = _nonempty(experiment_id, "experiment_id")
    parent = _nonempty(parent_experiment_id, "parent_experiment_id") if parent_experiment_id else None
    baseline = _nonempty(baseline_experiment_id, "baseline_experiment_id") if baseline_experiment_id else None
    if normalized_id in {parent, baseline}:
        raise ValueError("experiment cannot reference itself")
    if dataset_partition not in {"train", "validation", "test"}:
        raise ValueError("dataset_partition must be train, validation, or test")
    config = _object(candidate_config, "candidate_config", required=True)
    metadata = _object(provider_metadata, "provider_metadata", required=False)
    started = _aware(started_at or datetime.now(timezone.utc), "started_at")
    config_json = _canonical_json(config)
    config_hash = hashlib.sha256(config_json.encode("utf-8")).hexdigest()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into research_experiment (
                    experiment_id, parent_experiment_id, baseline_experiment_id,
                    hypothesis, candidate_model_version, candidate_config,
                    candidate_config_hash, dataset_version, dataset_hash,
                    dataset_partition, evaluator_version, evaluator_specification_hash,
                    status, provider_metadata, created_at, started_at
                ) values (
                    %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s,
                    %s, %s::jsonb, %s, %s
                )
                returning id, created_at, started_at;
                """,
                (
                    normalized_id, parent, baseline, _nonempty(hypothesis, "hypothesis"),
                    _nonempty(candidate_model_version, "candidate_model_version"), config_json,
                    config_hash, _nonempty(dataset_version, "dataset_version"),
                    _nonempty(dataset_hash, "dataset_hash"), dataset_partition,
                    _nonempty(evaluator_version, "evaluator_version"),
                    _nonempty(evaluator_specification_hash, "evaluator_specification_hash"),
                    RUNNING, _canonical_json(metadata) if metadata is not None else None, started, started,
                ),
            )
            row = cur.fetchone()
            conn.commit()
    return {
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "id": row[0],
        "experiment_id": normalized_id,
        "status": RUNNING,
        "candidate_config_hash": config_hash,
        "created_at": row[1],
        "started_at": row[2],
    }


def finish_research_experiment(
    *,
    experiment_id: str,
    status: str,
    finished_at: datetime | None = None,
    metrics: Mapping[str, Any] | None = None,
    failure_reason: str | None = None,
    failure_log_reference: str | None = None,
) -> dict[str, Any]:
    """Write one terminal audit result; automatic promotion is deliberately unsupported."""
    if status not in TERMINAL_STATUSES:
        raise ValueError("status must be candidate, rejected, or failed")
    normalized_id = _nonempty(experiment_id, "experiment_id")
    completed = _aware(finished_at or datetime.now(timezone.utc), "finished_at")
    if status == "failed":
        if metrics is not None:
            raise ValueError("failed experiment cannot store metrics")
        reason = _nonempty(failure_reason or "", "failure_reason")
        log_reference = _nonempty(failure_log_reference, "failure_log_reference") if failure_log_reference else None
        metrics_json = None
    else:
        if failure_reason is not None or failure_log_reference is not None:
            raise ValueError("successful terminal experiment cannot store failure metadata")
        metric_object = _object(metrics, "metrics", required=True)
        metrics_json = _canonical_json(metric_object)
        reason = None
        log_reference = None

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select started_at
                from research_experiment
                where experiment_id = %s and status = %s
                for update;
                """,
                (normalized_id, RUNNING),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("running research experiment not found")
            started = _aware(row[0], "stored started_at")
            duration_ms = round((completed - started).total_seconds() * 1000)
            if duration_ms < 0:
                raise ValueError("finished_at cannot precede started_at")
            cur.execute(
                """
                update research_experiment
                set status = %s,
                    finished_at = %s,
                    execution_duration_ms = %s,
                    metrics_json = %s::jsonb,
                    failure_reason = %s,
                    failure_log_reference = %s
                where experiment_id = %s and status = %s
                returning id, created_at, started_at, finished_at, execution_duration_ms;
                """,
                (status, completed, duration_ms, metrics_json, reason, log_reference, normalized_id, RUNNING),
            )
            updated = cur.fetchone()
            if updated is None:
                raise ValueError("research experiment terminal transition was not applied")
            conn.commit()
    return {
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "id": updated[0],
        "experiment_id": normalized_id,
        "status": status,
        "created_at": updated[1],
        "started_at": updated[2],
        "finished_at": updated[3],
        "execution_duration_ms": updated[4],
        "metrics": json.loads(metrics_json) if metrics_json is not None else None,
        "failure_reason": reason,
        "failure_log_reference": log_reference,
    }
