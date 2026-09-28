"""Versioned, source-aware RPE observations and deterministic resolution."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from backend.db import get_conn

RPE_SCALE_VERSION = "rpe_1_10"
RPE_OBSERVATION_SCHEMA_VERSION = "rpe_observation_v1"
RPE_SOURCES = ("strava", "telegram", "web")
RPE_LABELS = {
    1: "Very easy",
    2: "Easy",
    3: "Light",
    4: "Comfortable",
    5: "Moderate",
    6: "Steady",
    7: "Hard",
    8: "Very hard",
    9: "Extremely hard",
    10: "Maximal",
}


def resolve_rpe(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick one score; retain the other observations as disagreement evidence."""
    by_source = {row["source"]: row for row in observations}
    selected = next(
        (by_source[source] for source in RPE_SOURCES if source in by_source),
        None,
    )
    score = selected["score"] if selected else None
    return {
        "score": score,
        "source": selected["source"] if selected else None,
        "disagreement": bool(
            selected and any(row["score"] != score for row in observations)
        ),
        "observations": observations,
    }


def _load_observations(cur: Any, activity_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        select source, score, scale_version, schema_version, observed_at, received_at
        from activity_rpe_observation
        where canonical_activity_id = %s
        order by source;
        """,
        (activity_id,),
    )
    return [
        {
            "source": source,
            "score": score,
            "scale_version": scale_version,
            "schema_version": schema_version,
            "observed_at": observed_at,
            "received_at": received_at,
        }
        for source, score, scale_version, schema_version, observed_at, received_at
        in cur.fetchall()
    ]


def refresh_rpe_resolution(
    cur: Any, *, user_id: str, activity_id: int
) -> dict[str, Any]:
    current = resolve_rpe(_load_observations(cur, activity_id))
    cur.execute(
        """
        insert into activity_rpe_resolution (
            canonical_activity_id, user_id, effective_score,
            effective_source, disagreement
        ) values (%s, %s, %s, %s, %s)
        on conflict (canonical_activity_id) do update set
            user_id = excluded.user_id,
            effective_score = excluded.effective_score,
            effective_source = excluded.effective_source,
            disagreement = excluded.disagreement,
            resolved_at = now();
        """,
        (
            activity_id, user_id, current["score"], current["source"],
            current["disagreement"],
        ),
    )
    return current


def upsert_rpe_observation(
    *,
    user_id: str,
    canonical_activity_id: int,
    source: str,
    score: int,
    source_payload: dict[str, Any],
    observed_at: datetime | None = None,
    recompute: bool = True,
) -> dict[str, Any]:
    if source not in RPE_SOURCES or type(score) is not int or not 1 <= score <= 10:
        raise ValueError("RPE must be an integer from 1 to 10 with a known source")
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Serialize updates for the same canonical activity.
            cur.execute("select pg_advisory_xact_lock(%s);", (canonical_activity_id,))
            before = resolve_rpe(_load_observations(cur, canonical_activity_id))
            cur.execute(
                """
                insert into activity_rpe_observation (
                    user_id, canonical_activity_id, source, score, scale_version,
                    schema_version, observed_at, source_payload
                ) values (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                on conflict (canonical_activity_id, source) do update set
                    score = excluded.score,
                    scale_version = excluded.scale_version,
                    schema_version = excluded.schema_version,
                    observed_at = excluded.observed_at,
                    received_at = now(),
                    source_payload = excluded.source_payload;
                """,
                (
                    user_id,
                    canonical_activity_id,
                    source,
                    score,
                    RPE_SCALE_VERSION,
                    RPE_OBSERVATION_SCHEMA_VERSION,
                    observed_at,
                    json.dumps(source_payload),
                ),
            )
            after = refresh_rpe_resolution(
                cur, user_id=user_id, activity_id=canonical_activity_id
            )
            conn.commit()
    changed = before["score"] != after["score"]
    result = {
        **after,
        "effective_changed": changed,
        "activity_id": canonical_activity_id,
    }
    if changed and recompute:
        from backend.services.activity_response_service import (
            compute_and_store_activity_response,
            recompute_later_comparable_responses,
            recompute_readiness_for_response_window,
        )

        response = compute_and_store_activity_response(canonical_activity_id)
        result["response_metrics"] = response
        affected = [response]
        if response["activity_date"]:
            affected.extend(
                recompute_later_comparable_responses(
                    user_id=user_id,
                    activity_id=canonical_activity_id,
                    activity_date=response["activity_date"],
                    activity_type=response["activity_type"],
                    intensity_band=response["intensity_band"],
                )
            )
        dates: set[str] = set()
        for changed_response in affected:
            if changed_response["activity_date"]:
                dates.update(
                    recompute_readiness_for_response_window(
                        user_id=user_id,
                        activity_date=changed_response["activity_date"],
                    )
                )
        result["response_readiness_dates"] = sorted(dates)
    return result


def import_strava_rpe(
    *,
    user_id: str,
    canonical_activity_id: int,
    activity: dict[str, Any],
    recompute: bool = True,
) -> dict[str, Any] | None:
    value = activity.get("perceived_exertion")
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= 10:
        raise ValueError("Strava perceived_exertion must be an integer from 1 to 10")
    return upsert_rpe_observation(
        user_id=user_id,
        canonical_activity_id=canonical_activity_id,
        source="strava",
        score=value,
        # The detailed response does not guarantee an RPE edit timestamp.
        source_payload=activity,
        observed_at=None,
        recompute=recompute,
    )


def reconcile_recent_strava_rpe(user_id: str, *, limit: int = 100) -> dict[str, int]:
    """Check recent activities with missing Strava RPE or manual fallback."""
    from backend.services.strava_auth import refresh_strava_token_if_needed
    from backend.services.strava_client import fetch_activity

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select r.strava_activity_id
                from strava_activity_raw r
                left join activity_rpe_resolution er
                  on er.canonical_activity_id = r.strava_activity_id
                where r.user_id = %s
                  and r.start_date >= now() - interval '14 days'
                  and r.is_deleted = false
                  and r.is_excluded = false
                  and r.duplicate_of_activity_id is null
                  and (er.effective_source is distinct from 'strava')
                order by r.start_date desc, r.strava_activity_id desc
                limit %s;
                """,
                (user_id, limit),
            )
            activity_ids = [row[0] for row in cur.fetchall()]
    if not activity_ids:
        return {"checked": 0, "changed": 0}
    access_token, _, _ = refresh_strava_token_if_needed(user_id)
    changed = 0
    for activity_id in activity_ids:
        activity = fetch_activity(access_token=access_token, activity_id=activity_id)
        result = import_strava_rpe(
            user_id=user_id, canonical_activity_id=activity_id, activity=activity
        )
        changed += bool(result and result["effective_changed"])
    return {"checked": len(activity_ids), "changed": changed}
