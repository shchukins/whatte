from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from typing import Any

from backend.db import get_conn
from backend.services.decision_engine import build_recommendation
from backend.services.readiness_composition import READINESS_MODEL_VERSION


def _coerce_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def capture_decision_context_snapshot(
    *,
    user_id: str,
    snapshot_date: str | date,
    event_type: str,
    reference_key: str,
    event_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the current backend-owned decision without recomputing it."""
    normalized_date = _coerce_date(snapshot_date)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    readiness_score,
                    good_day_probability,
                    status_text,
                    explanation_json,
                    updated_at
                from readiness_daily
                where user_id = %s
                  and date = %s
                  and version = %s
                limit 1;
                """,
                (user_id, normalized_date, READINESS_MODEL_VERSION),
            )
            row = cur.fetchone()

            if row is None:
                readiness_score = None
                good_day_probability = None
                status_text = None
                explanation: dict[str, Any] = {}
                readiness_computed_at = None
                recommendation = None
            else:
                (
                    readiness_score,
                    good_day_probability,
                    status_text,
                    explanation_json,
                    readiness_computed_at,
                ) = row
                explanation = _as_dict(explanation_json)
                recommendation = build_recommendation(
                    readiness_score=float(readiness_score),
                    explanation=explanation,
                )["recommendation"] if readiness_score is not None else None

            snapshot = {
                "snapshot_date": normalized_date.isoformat(),
                "model_version": READINESS_MODEL_VERSION,
                "readiness_computed_at": readiness_computed_at,
                "readiness_score": readiness_score,
                "good_day_probability": good_day_probability,
                "status_text": status_text,
                "recommendation": recommendation,
                "explanation": explanation,
                "event_context": event_context or {},
            }
            canonical_json = json.dumps(snapshot, default=str, sort_keys=True, separators=(",", ":"))
            # Computation time is evidence stored in the snapshot, but it is not
            # decision state. Excluding it keeps a retry idempotent when a
            # recompute produces the same score, recommendation, and factors.
            fingerprint_state = {
                key: value
                for key, value in snapshot.items()
                if key != "readiness_computed_at"
            }
            fingerprint_json = json.dumps(
                fingerprint_state,
                default=str,
                sort_keys=True,
                separators=(",", ":"),
            )
            fingerprint = hashlib.sha256(fingerprint_json.encode("utf-8")).hexdigest()
            cur.execute(
                """
                insert into decision_context_snapshot (
                    user_id,
                    snapshot_date,
                    event_type,
                    reference_key,
                    model_version,
                    readiness_score,
                    good_day_probability,
                    recommendation,
                    status_text,
                    snapshot_json,
                    content_fingerprint
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                on conflict (
                    user_id,
                    snapshot_date,
                    event_type,
                    reference_key,
                    content_fingerprint
                ) do nothing
                returning id, captured_at;
                """,
                (
                    user_id,
                    normalized_date,
                    event_type,
                    reference_key,
                    READINESS_MODEL_VERSION,
                    readiness_score,
                    good_day_probability,
                    recommendation,
                    status_text,
                    canonical_json,
                    fingerprint,
                ),
            )
            inserted = cur.fetchone()
            conn.commit()

    return {
        "inserted": inserted is not None,
        "id": inserted[0] if inserted else None,
        "captured_at": inserted[1] if inserted else None,
        "content_fingerprint": fingerprint,
        **snapshot,
    }
