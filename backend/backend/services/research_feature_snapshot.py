"""Persist immutable daily feature vectors at an accepted decision delivery."""

from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from typing import Any

from backend.config import settings
from backend.db import get_conn
from backend.services.daily_feature_vector import build_daily_feature_vector


RESEARCH_FEATURE_SNAPSHOT_EVENT = "daily_readiness_delivery"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))


def capture_research_feature_snapshot(
    *, user_id: str, local_date: date, reference_key: str,
    cutoff_at: datetime | None = None,
    feature_vector_version: str = "daily_feature_vector_v2",
) -> dict[str, Any]:
    """Store a daily vector without reconstructing historical source state.

    The cutoff is captured before querying source rows.  Thus the vector is
    evidence of what was available for this delivery, even if those mutable
    rows later change.
    """
    cutoff = cutoff_at or datetime.now(timezone.utc)
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("cutoff_at must be timezone-aware")
    vector = build_daily_feature_vector(
        user_id=user_id,
        local_date=local_date,
        cutoff_at=cutoff,
        timezone_name=settings.whatte_timezone,
        feature_vector_version=feature_vector_version,
    )
    content = _canonical_json(vector)
    fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into research_feature_snapshot (
                    user_id, local_date, event_type, reference_key,
                    feature_vector_version, cutoff_at, feature_json,
                    content_fingerprint
                ) values (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                on conflict (
                    user_id, local_date, event_type, reference_key,
                    content_fingerprint
                ) do nothing
                returning id, captured_at;
                """,
                (
                    user_id, local_date, RESEARCH_FEATURE_SNAPSHOT_EVENT,
                    reference_key, vector["feature_vector_version"], cutoff,
                    content, fingerprint,
                ),
            )
            inserted = cur.fetchone()
            conn.commit()
    return {
        "inserted": inserted is not None,
        "id": inserted[0] if inserted else None,
        "captured_at": inserted[1] if inserted else None,
        "content_fingerprint": fingerprint,
        "feature_vector": vector,
    }
