"""Read-only, versioned daily research features with an explicit as-of boundary.

This module intentionally does not call readiness or recommendation services.  It
exposes current persisted state only when the state and its underlying source
were available no later than ``cutoff_at``; an unprovable historical value stays
unavailable instead of being reconstructed from a newer row.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from backend.config import settings
from backend.db import get_conn


DAILY_FEATURE_VECTOR_VERSION = "daily_feature_vector_v1"
RECENT_RESPONSE_DAYS = 7


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cutoff_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _unavailable(reason: str) -> dict[str, Any]:
    return {"value": None, "availability": "unavailable", "reason_codes": [reason]}


def _available(value: Any, *, available_at: datetime | None, source: str) -> dict[str, Any]:
    if value is None:
        return _unavailable("source_value_unavailable")
    return {
        "value": value,
        "availability": "available",
        "reason_codes": [],
        "source": source,
        "available_at": _iso(available_at),
    }


def _eligible(value: datetime | None, cutoff_at: datetime) -> bool:
    return value is not None and value <= cutoff_at


def select_recent_response_activities(
    activities: Iterable[dict[str, Any]], *, cutoff_at: datetime
) -> list[dict[str, Any]]:
    """Keep only activities and derived responses known before the cutoff."""
    eligible = [
        activity for activity in activities
        if _eligible(activity.get("activity_start_at"), cutoff_at)
        and _eligible(activity.get("source_available_at"), cutoff_at)
        and _eligible(activity.get("computed_at"), cutoff_at)
    ]
    return sorted(
        eligible,
        key=lambda item: (item["activity_start_at"], item["activity_id"]),
        reverse=True,
    )


def build_daily_feature_vector_from_sources(
    *,
    user_id: str,
    local_date: date,
    cutoff_at: datetime,
    timezone_name: str,
    load: dict[str, Any] | None,
    responses: Iterable[dict[str, Any]],
    feeling: dict[str, Any] | None,
    manual_physiology: dict[str, Any] | None,
    historical_physiology: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the stable public contract from already selected source rows."""
    cutoff = _as_utc(cutoff_at)
    response_rows = select_recent_response_activities(responses, cutoff_at=cutoff)
    features: dict[str, dict[str, Any]] = {}

    for name in ("tss", "fitness", "fatigue_fast", "fatigue_slow", "fatigue_total", "freshness"):
        features[f"load.{name}"] = (
            _available(load.get(name), available_at=load.get("updated_at"), source="load_state_daily_v2")
            if load and _eligible(load.get("updated_at"), cutoff)
            else _unavailable("load_state_unavailable_as_of_cutoff")
        )

    features["training_response.recent_activity_count"] = _available(
        len(response_rows), available_at=cutoff, source="activity_response_metrics"
    )
    latest = response_rows[0] if response_rows else None
    for name in (
        "activity_id", "normalized_power_to_hr", "aerobic_decoupling_pct",
        "rpe_score", "session_rpe_load", "rpe_per_intensity_factor",
        "session_rpe_load_per_tss", "intensity_band",
    ):
        features[f"training_response.latest.{name}"] = (
            _available(latest.get(name), available_at=latest.get("computed_at"), source="activity_response_metrics")
            if latest else _unavailable("no_recent_response_activity_as_of_cutoff")
        )

    features["feeling.next_day_recovery_score"] = (
        _available(feeling.get("score"), available_at=feeling.get("updated_at"), source="activity_subjective_feedback")
        if feeling and _eligible(feeling.get("created_at"), cutoff) and _eligible(feeling.get("updated_at"), cutoff)
        else _unavailable("feeling_unavailable_as_of_cutoff")
    )

    manual_names = (
        "sleep_duration_minutes", "hrv_ms", "resting_hr_bpm", "hrv_ratio",
        "hrv_deviation", "resting_hr_delta_bpm", "sleep_duration_deviation_minutes",
        "sleep_duration_debt_minutes",
    )
    manual_is_eligible = manual_physiology and _eligible(manual_physiology.get("updated_at"), cutoff) and _eligible(manual_physiology.get("computed_at"), cutoff)
    for name in manual_names:
        features[f"physiology.manual.{name}"] = (
            _available(manual_physiology.get(name), available_at=manual_physiology.get("computed_at"), source="personal_physiology_feature_daily")
            if manual_is_eligible else _unavailable("manual_physiology_unavailable_as_of_cutoff")
        )
    features["physiology.historical.recovery_score"] = (
        _available(historical_physiology.get("recovery_score"), available_at=historical_physiology.get("updated_at"), source="health_recovery_daily")
        if historical_physiology and _eligible(historical_physiology.get("updated_at"), cutoff)
        else _unavailable("historical_physiology_unavailable_as_of_cutoff")
    )

    return {
        "feature_vector_version": DAILY_FEATURE_VECTOR_VERSION,
        "user_id": user_id,
        "local_date": local_date.isoformat(),
        "cutoff_at": cutoff.isoformat(),
        "timezone": timezone_name,
        "features": features,
        "source_metadata": {
            "load": {"status": "available" if load and _eligible(load.get("updated_at"), cutoff) else "unavailable", "updated_at": _iso(load.get("updated_at")) if load else None},
            "training_response": {"status": "available" if latest else "unavailable", "activity_count": len(response_rows)},
            "feeling": {"status": "available" if features["feeling.next_day_recovery_score"]["availability"] == "available" else "unavailable"},
            "manual_physiology": {"status": "available" if manual_is_eligible else "unavailable"},
            "historical_physiology": {"status": "available" if features["physiology.historical.recovery_score"]["availability"] == "available" else "unavailable"},
        },
        "recent_response_activities": [
            {key: value for key, value in activity.items() if key not in {"source_available_at", "computed_at"}}
            for activity in response_rows
        ],
    }


def build_daily_feature_vector(
    *, user_id: str, local_date: date, cutoff_at: datetime, timezone_name: str | None = None
) -> dict[str, Any]:
    """Load a vector in one repeatable-read, read-only transaction."""
    timezone_name = timezone_name or settings.whatte_timezone
    cutoff = _as_utc(cutoff_at)
    zone = ZoneInfo(timezone_name)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("set transaction isolation level repeatable read, read only")
            cur.execute("""
                select tss, fitness, fatigue_fast, fatigue_slow, fatigue_total, freshness, updated_at
                from load_state_daily_v2
                where user_id = %s and date = %s and version = 'v2' and updated_at <= %s
                limit 1;
            """, (user_id, local_date, cutoff))
            row = cur.fetchone()
            load = dict(zip(("tss", "fitness", "fatigue_fast", "fatigue_slow", "fatigue_total", "freshness", "updated_at"), row)) if row else None

            cur.execute("""
                select arm.strava_activity_id, r.start_date, r.fetched_at, arm.computed_at,
                       arm.normalized_power_to_hr, arm.aerobic_decoupling_pct, arm.rpe_score,
                       arm.session_rpe_load, arm.rpe_per_intensity_factor,
                       arm.session_rpe_load_per_tss, arm.intensity_band
                from activity_response_metrics arm
                join strava_activity_raw r on r.strava_activity_id = arm.strava_activity_id
                where arm.user_id = %s
                  and (r.start_date at time zone %s)::date between (%s::date - %s) and %s
                  and r.start_date <= %s and r.fetched_at <= %s and arm.computed_at <= %s
                  and r.is_deleted = false and r.is_excluded = false and r.duplicate_of_activity_id is null
                order by r.start_date desc, arm.strava_activity_id desc;
            """, (user_id, timezone_name, local_date, RECENT_RESPONSE_DAYS, local_date, cutoff, cutoff, cutoff))
            responses = [dict(zip(("activity_id", "activity_start_at", "source_available_at", "computed_at", "normalized_power_to_hr", "aerobic_decoupling_pct", "rpe_score", "session_rpe_load", "rpe_per_intensity_factor", "session_rpe_load_per_tss", "intensity_band"), item)) for item in cur.fetchall()]

            cur.execute("""
                select feedback_score, created_at, updated_at from activity_subjective_feedback
                where user_id = %s and activity_date = %s and feedback_type = 'next_day_recovery'
                  and strava_activity_id is null and created_at <= %s and updated_at <= %s
                order by updated_at desc limit 1;
            """, (user_id, local_date, cutoff, cutoff))
            row = cur.fetchone()
            feeling = dict(zip(("score", "created_at", "updated_at"), row)) if row else None

            cur.execute("""
                select o.sleep_duration_minutes, o.hrv_ms, o.resting_hr_bpm, p.hrv_ratio,
                       p.hrv_deviation, p.resting_hr_delta_bpm, p.sleep_duration_deviation_minutes,
                       p.sleep_duration_debt_minutes, o.updated_at, p.computed_at
                from manual_physiology_observation o
                join personal_physiology_feature_daily p
                  on p.user_id = o.user_id and p.local_date = o.local_date
                where o.user_id = %s and o.local_date = %s
                  and o.updated_at <= %s and p.computed_at <= %s
                  and p.feature_version = 'personal_physiology_features_v1'
                limit 1;
            """, (user_id, local_date, cutoff, cutoff))
            row = cur.fetchone()
            manual = dict(zip(("sleep_duration_minutes", "hrv_ms", "resting_hr_bpm", "hrv_ratio", "hrv_deviation", "resting_hr_delta_bpm", "sleep_duration_deviation_minutes", "sleep_duration_debt_minutes", "updated_at", "computed_at"), row)) if row else None

            cur.execute("""
                select recovery_score_simple, updated_at from health_recovery_daily
                where user_id = %s and date = %s and updated_at <= %s limit 1;
            """, (user_id, local_date, cutoff))
            row = cur.fetchone()
            historical = dict(zip(("recovery_score", "updated_at"), row)) if row else None

    return build_daily_feature_vector_from_sources(
        user_id=user_id, local_date=local_date, cutoff_at=cutoff, timezone_name=zone.key,
        load=load, responses=responses, feeling=feeling, manual_physiology=manual,
        historical_physiology=historical,
    )
