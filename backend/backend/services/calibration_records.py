"""Read-only decision-to-outcome evidence for canonical activities."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as utc_timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.config import settings
from backend.db import get_conn
from backend.services.activity_load_service import (
    is_supported_cycling_activity,
    resolve_activity_load,
)
from backend.services.readiness_composition import READINESS_MODEL_VERSION


ACTIVITY_QUERY = """
select
    r.strava_activity_id, r.activity_type, r.start_date,
    (r.start_date at time zone %s)::date as local_date,
    m.id as metrics_id, m.tss, m.normalized_power, m.intensity_factor,
    f.id as rpe_id, f.feedback_score as rpe_score,
    f.feedback_value as rpe_value, f.feedback_schema_version as rpe_version,
    f.updated_at as rpe_updated_at,
    recovery.id as recovery_id, recovery.feedback_score as recovery_score,
    recovery.feedback_value as recovery_value,
    recovery.feedback_schema_version as recovery_version,
    recovery.updated_at as recovery_updated_at
from strava_activity_raw r
left join activity_metrics m
  on m.user_id = r.user_id and m.strava_activity_id = r.strava_activity_id
 and m.version = 'v1'
left join activity_subjective_feedback f
  on f.user_id = r.user_id and f.canonical_activity_id = r.strava_activity_id
 and f.feedback_type = 'post_ride_rpe'
left join activity_subjective_feedback recovery
  on recovery.user_id = r.user_id
 and recovery.activity_date = (r.start_date at time zone %s)::date + 1
 and recovery.feedback_type = 'next_day_recovery'
 and recovery.strava_activity_id is null
where r.user_id = %s
  and (r.start_date at time zone %s)::date between %s and %s
  and r.is_deleted = false and r.is_excluded = false
  and r.duplicate_of_activity_id is null
order by r.start_date, r.strava_activity_id;
"""

SNAPSHOT_QUERY = """
select id, snapshot_date, event_type, reference_key, model_version,
       readiness_score, recommendation, snapshot_json, captured_at
from decision_context_snapshot
where user_id = %s and snapshot_date between %s and %s
order by snapshot_date, captured_at, id;
"""

RPE_VALUES = {1: "very_easy", 2: "easy", 3: "moderate", 4: "hard", 5: "very_hard"}
RECOVERY_VALUES = {1: "exhausted", 2: "tired", 3: "okay", 4: "fresh", 5: "very_fresh"}
FEEDBACK_VERSIONS = {"v1", "v1_extensible"}


def _feedback(record_id: Any, score: Any, value: Any, version: Any,
              updated_at: Any, expected: dict[int, str]) -> dict[str, Any]:
    if record_id is None:
        return {"status": "missing", "source_id": None}
    compatible = version in FEEDBACK_VERSIONS and expected.get(score) == value
    return {
        "status": "available" if compatible else "incompatible_scale_or_version",
        "source_id": record_id,
        "score": score,
        "value": value,
        "scale": "1-5" if compatible else None,
        "schema_version": version,
        "updated_at": updated_at,
    }


def _select_snapshot(snapshots: list[tuple[Any, ...]], start: datetime,
                     local_day: date) -> tuple[dict[str, Any] | None, str | None]:
    same_day = [s for s in snapshots if s[1] == local_day]
    before = [s for s in same_day if s[8] < start]
    eligible = []
    for s in before:
        payload = s[7] if isinstance(s[7], dict) else {}
        computed_at = payload.get("readiness_computed_at")
        try:
            computed = datetime.fromisoformat(computed_at) if isinstance(computed_at, str) else computed_at
        except ValueError:
            continue
        if computed is None or computed.tzinfo is None or computed > s[8] or computed >= start:
            continue
        eligible.append((s, computed))
    if not eligible:
        reason = (
            "no_snapshot" if not same_day else
            "no_snapshot_before_activity" if not before else
            "missing_or_invalid_pre_activity_computation"
        )
        return None, reason
    # Latest capture wins; the primary key gives a stable tie break.
    s, computed = max(eligible, key=lambda item: (item[0][8], item[0][0]))
    return {
        "source_id": s[0], "event_type": s[2], "reference_key": s[3],
        "model_version": s[4], "readiness_score": s[5],
        "recommendation": s[6], "captured_at": s[8],
        "readiness_computed_at": computed,
        "age_seconds": (start - s[8]).total_seconds(),
        "status": (
            "available" if s[4] == READINESS_MODEL_VERSION and s[5] is not None
            and s[6] is not None else "incompatible_or_incomplete_decision"
        ),
    }, None


def build_calibration_records(*, user_id: str, date_from: date, date_to: date,
                              timezone: str, activities: list[tuple[Any, ...]],
                              snapshots: list[tuple[Any, ...]],
                              generated_at: datetime) -> dict[str, Any]:
    zone = ZoneInfo(timezone)
    records = []
    for row in activities:
        (activity_id, activity_type, start, local_day, metrics_id, tss,
         normalized_power, intensity_factor, rpe_id, rpe_score, rpe_value,
         rpe_version, rpe_updated_at, recovery_id, recovery_score,
         recovery_value, recovery_version, recovery_updated_at) = row
        snapshot, missing_reason = _select_snapshot(snapshots, start, local_day)
        load = resolve_activity_load(
            activity_type=activity_type, tss=tss,
            normalized_power=normalized_power, intensity_factor=intensity_factor,
        )
        records.append({
            "activity_id": activity_id,
            "activity_type": activity_type,
            "activity_start_at": start,
            "activity_local_start": start.astimezone(zone).isoformat(),
            "activity_local_date": local_day,
            "decision": snapshot,
            "decision_missing_reason": missing_reason,
            "load": {
                "metrics_source_id": metrics_id,
                "metrics_version": "v1" if metrics_id is not None else None,
                "tss": tss,
                "inclusion_state": (
                    "included" if load["load_model_included"] else
                    "unsupported_sport" if not is_supported_cycling_activity(activity_type)
                    else "missing_power_metrics" if metrics_id is not None
                    else "missing_metrics"
                ),
            },
            "post_ride_rpe": _feedback(
                rpe_id, rpe_score, rpe_value, rpe_version, rpe_updated_at, RPE_VALUES,
            ),
            "next_day_recovery": {
                **_feedback(recovery_id, recovery_score, recovery_value,
                            recovery_version, recovery_updated_at, RECOVERY_VALUES),
                "target_local_date": local_day + timedelta(days=1),
                "semantics": "day_level_context_shared_by_all_activities_on_previous_day",
            },
        })
    return {
        "user_id": user_id, "date_from": date_from, "date_to": date_to,
        "timezone": timezone, "generated_at": generated_at,
        "records": records,
    }


def generate_calibration_records(*, user_id: str, date_from: date,
                                 date_to: date, timezone: str | None = None) -> dict[str, Any]:
    if date_to < date_from:
        raise ValueError("date_to must be on or after date_from")
    report_timezone = timezone or settings.whatte_timezone
    ZoneInfo(report_timezone)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("set transaction isolation level repeatable read, read only")
            cur.execute(ACTIVITY_QUERY, (report_timezone, report_timezone, user_id,
                                         report_timezone, date_from, date_to))
            activities = cur.fetchall()
            cur.execute(SNAPSHOT_QUERY, (user_id, date_from, date_to))
            snapshots = cur.fetchall()
    return build_calibration_records(
        user_id=user_id, date_from=date_from, date_to=date_to,
        timezone=report_timezone, activities=activities, snapshots=snapshots,
        generated_at=datetime.now(utc_timezone.utc),
    )
