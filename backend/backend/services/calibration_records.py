"""Read-only decision-to-outcome evidence for canonical activities."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone as utc_timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.config import settings
from backend.db import get_conn
from backend.services.activity_load_service import (
    is_supported_cycling_activity,
    resolve_activity_load,
)
from backend.services.activity_response_service import classify_intensity_band
from backend.services.readiness_composition import READINESS_MODEL_VERSION


ACTIVITY_QUERY = """
select
    r.strava_activity_id, r.activity_type, r.start_date,
    (r.start_date at time zone %s)::date as local_date,
    m.id as metrics_id, m.tss, m.normalized_power, m.intensity_factor,
    f.id as rpe_id, f.feedback_score as rpe_score,
    f.feedback_value as rpe_value, f.feedback_schema_version as rpe_version,
    f.updated_at as rpe_updated_at,
    er.effective_score, er.effective_source, er.disagreement, er.resolved_at,
    observation.id as observation_id, observation.score as observation_score,
    observation.scale_version, observation.schema_version,
    observation.observed_at, observation.received_at,
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
left join activity_rpe_resolution er
  on er.user_id = r.user_id and er.canonical_activity_id = r.strava_activity_id
left join activity_rpe_observation observation
  on observation.user_id = r.user_id
 and observation.canonical_activity_id = r.strava_activity_id
 and observation.source = er.effective_source
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
CURRENT_RPE_SCALE = "rpe_1_10"
CURRENT_RPE_SCHEMA = "rpe_observation_v1"
OUTCOME_CONTRACT_VERSION = "workout_outcome_v1"
COMPLETENESS_CONTRACT_VERSION = "feedback_completeness_v1"
DEFAULT_GAP_LIMIT = 20
MAX_GAP_LIMIT = 100


def build_feedback_completeness(
    records: list[dict[str, Any]], *, timezone: str, generated_at: datetime,
    gap_limit: int = DEFAULT_GAP_LIMIT,
) -> dict[str, Any]:
    """Count current feedback independently of prediction/load eligibility."""
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    if not 0 <= gap_limit <= MAX_GAP_LIMIT:
        raise ValueError(f"gap_limit must be between 0 and {MAX_GAP_LIMIT}")
    zone = ZoneInfo(timezone)
    rpe_counts = dict.fromkeys(("usable_current", "legacy_only", "missing", "incompatible"), 0)
    recovery_counts = dict.fromkeys(("usable", "missing", "incompatible", "window_open"), 0)
    legacy_count = disagreement_count = 0
    activity_gaps: list[dict[str, Any]] = []
    day_gaps: list[dict[str, Any]] = []
    by_day: dict[date, dict[str, Any]] = {}
    ordered = sorted(records, key=lambda r: (r["activity_start_at"], r["activity_id"]))
    for record in ordered:
        rpe = record["post_ride_rpe"]
        legacy = record["legacy_post_ride_rpe"] or rpe
        legacy_count += int(legacy["status"] == "available" and legacy.get("scale") == "1-5")
        disagreement_count += int(bool(rpe.get("disagreement")))
        if rpe["status"] == "available":
            state = "usable_current" if rpe["scale"] == "1-10" else "legacy_only"
            reason = "legacy_rpe_only" if state == "legacy_only" else None
        elif rpe["status"] == "missing":
            state, reason = "missing", "missing_rpe"
        else:
            state, reason = "incompatible", rpe["status"]
        rpe_counts[state] += 1
        if reason and len(activity_gaps) < gap_limit:
            activity_gaps.append({
                "activity_id": record["activity_id"],
                "activity_local_date": record["activity_local_date"],
                "state": state, "reason_code": reason,
                "source_id": rpe["source_id"], "source": rpe.get("source"),
            })
        by_day.setdefault(record["activity_local_date"], record["next_day_recovery"])

    for day, recovery in sorted(by_day.items()):
        # The entire D+1 calendar date is allowed for feedback. Construct local
        # D+2 midnight rather than adding 24 hours; DST days may be 23/25 hours.
        closes_at = datetime.combine(day + timedelta(days=2), time.min, tzinfo=zone)
        if recovery["status"] == "available":
            state, reason = "usable", None
        elif recovery["status"] != "missing":
            state, reason = "incompatible", recovery["status"]
        elif generated_at < closes_at:
            state, reason = "window_open", "next_day_recovery_window_open"
        else:
            state, reason = "missing", "missing_next_day_recovery"
        recovery_counts[state] += 1
        if reason and len(day_gaps) < gap_limit:
            day_gaps.append({
                "training_local_date": day,
                "target_local_date": recovery["target_local_date"],
                "window_closes_at": closes_at.isoformat(),
                "state": state, "reason_code": reason,
                "source_id": recovery["source_id"],
            })

    def coverage(numerator: int, denominator: int) -> dict[str, Any]:
        return {"numerator": numerator, "denominator": denominator,
                "fraction": numerator / denominator if denominator else None}

    activity_gap_count = len(records) - rpe_counts["usable_current"]
    day_gap_count = len(by_day) - recovery_counts["usable"]
    return {
        "contract_version": COMPLETENESS_CONTRACT_VERSION,
        "status": "ok",
        "canonical_workout_count": len(records),
        "rpe": {
            **rpe_counts,
            "current_scale": "1-10", "legacy_scale": "1-5",
            "compatible_legacy_observation_count": legacy_count,
            "source_disagreement_count": disagreement_count,
            "current_coverage": coverage(rpe_counts["usable_current"], len(records)),
        },
        "training_day_count": len(by_day),
        "next_day_recovery": {
            **recovery_counts, "scale": "1-5",
            "window_rule": "missing_after_start_of_local_D_plus_2",
            "coverage": coverage(recovery_counts["usable"], len(by_day)),
        },
        "gaps": {
            "limit_per_list": gap_limit,
            "activity_gap_count": activity_gap_count,
            "activity_gaps_truncated": activity_gap_count > len(activity_gaps),
            "activities": activity_gaps,
            "training_day_gap_count": day_gap_count,
            "training_day_gaps_truncated": day_gap_count > len(day_gaps),
            "training_days": day_gaps,
        },
        "state_semantics": "current_mutable_canonical_activity_and_feedback_not_historical_as_of",
        "interpretation": "observation_completeness_only_not_model_quality_or_research_sufficiency",
    }


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


def _current_rpe(
    effective_score: Any, effective_source: Any, disagreement: Any,
    resolved_at: Any, observation_id: Any, observation_score: Any,
    scale_version: Any, schema_version: Any, observed_at: Any, received_at: Any,
) -> dict[str, Any] | None:
    if effective_score is None and effective_source is None and observation_id is None:
        return None
    compatible = (
        type(effective_score) is int and 1 <= effective_score <= 10
        and effective_source in {"strava", "telegram", "web"}
        and observation_id is not None and observation_score == effective_score
        and scale_version == CURRENT_RPE_SCALE
        and schema_version == CURRENT_RPE_SCHEMA
    )
    return {
        "status": "available" if compatible else "incompatible_scale_or_resolution",
        "source_id": observation_id,
        "source": effective_source,
        "score": effective_score,
        "scale": "1-10" if compatible else None,
        "scale_version": scale_version,
        "schema_version": schema_version,
        "disagreement": disagreement,
        "observed_at": observed_at,
        "received_at": received_at,
        "resolved_at": resolved_at,
    }


def _outcome_targets(rpe: dict[str, Any], recovery: dict[str, Any]) -> dict[str, Any]:
    """Keep independent observed targets and explicit uncollected targets."""
    return {
        "contract_version": OUTCOME_CONTRACT_VERSION,
        "targets": {
            "post_workout_rpe": {"unit": "activity", **rpe},
            "subjective_result": {
                "unit": "activity", "status": "not_collected", "value": None,
            },
            "completion_state": {
                "unit": "activity", "status": "not_collected", "value": None,
            },
            "completion_ratio": {
                "unit": "activity", "status": "no_plan_source", "value": None,
            },
            "planned_vs_actual_duration": {
                "unit": "activity", "status": "no_plan_source", "value": None,
            },
            "planned_vs_actual_load": {
                "unit": "activity", "status": "no_plan_source", "value": None,
            },
            "next_day_recovery": {"unit": "training_day", **recovery},
        },
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
    explanation = s[7].get("explanation") if isinstance(s[7], dict) else None
    families = explanation.get("signal_families") if isinstance(explanation, dict) else None
    availability = (
        {name: family.get("availability") for name, family in families.items()
         if isinstance(family, dict)}
        if isinstance(families, dict) else None
    )
    return {
        "source_id": s[0], "event_type": s[2], "reference_key": s[3],
        "model_version": s[4], "readiness_score": s[5],
        "recommendation": s[6], "captured_at": s[8],
        "readiness_computed_at": computed,
        "age_seconds": (start - s[8]).total_seconds(),
        "signal_availability": availability,
        "status": (
            "available" if s[4] == READINESS_MODEL_VERSION and s[5] is not None
            and s[6] is not None else "incompatible_or_incomplete_decision"
        ),
    }, None


def build_evaluation(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe observed outcomes without treating them as prediction errors."""
    activity_states: Counter[str] = Counter()
    rpe_groups: dict[tuple[str, str, str, str, str, str], Counter[int]] = {}
    review_cases: list[dict[str, Any]] = []
    by_day: dict[date, list[dict[str, Any]]] = {}

    for record in records:
        by_day.setdefault(record["activity_local_date"], []).append(record)
        decision = record["decision"]
        rpe = record["post_ride_rpe"]
        load = record["load"]
        decision_state = decision["status"] if decision else record["decision_missing_reason"]
        activity_states[f"decision:{decision_state}"] += 1
        activity_states[f"load:{load['inclusion_state']}"] += 1
        activity_states[f"rpe:{rpe['status']}:{rpe.get('scale') or 'unknown'}"] += 1

        if decision_state != "available" or rpe["status"] != "available":
            continue
        group = (
            rpe["scale"],
            decision["recommendation"],
            record["activity_type"] or "unknown",
            load["inclusion_state"],
            load["intensity_band"] or "unavailable",
            (decision["signal_availability"] or {}).get("physiology") or "unknown",
        )
        rpe_groups.setdefault(group, Counter())[rpe["score"]] += 1

        # These are session-effort review cases, not verdicts on the daily model.
        if rpe["scale"] != "1-10" or load["inclusion_state"] != "included":
            continue
        band = load["intensity_band"]
        score = rpe["score"]
        case_type = None
        if band in {"recovery", "endurance"} and score >= 8:
            case_type = "low_intensity_high_rpe"
        elif band in {"threshold", "high_intensity"} and score <= 3:
            case_type = "high_intensity_low_rpe"
        if case_type:
            review_cases.append({
                "type": case_type, "activity_id": record["activity_id"],
                "decision_source_id": decision["source_id"],
                "rpe_source_id": rpe["source_id"], "rpe_source": rpe["source"],
                "intensity_band": band, "rpe_score": score,
                "tss": load["tss"], "activity_type": record["activity_type"],
            })

    recovery_days: list[dict[str, Any]] = []
    recovery_groups: dict[tuple[str, str, str], Counter[int]] = {}
    day_states: Counter[str] = Counter()
    for local_day, day_records in sorted(by_day.items()):
        first = day_records[0]
        decision = first["decision"]
        recovery = first["next_day_recovery"]
        decision_state = decision["status"] if decision else first["decision_missing_reason"]
        included_count = sum(
            row["load"]["inclusion_state"] == "included" for row in day_records
        )
        load_coverage = (
            "all_included" if included_count == len(day_records)
            else "none_included" if included_count == 0
            else "partially_included"
        )
        day_states[f"decision:{decision_state}"] += 1
        day_states[f"recovery:{recovery['status']}"] += 1
        day_states[f"load_coverage:{load_coverage}"] += 1
        day = {
            "training_local_date": local_day,
            "activity_count": len(day_records),
            "activity_ids": [row["activity_id"] for row in day_records],
            "included_tss": sum(
                row["load"]["tss"] for row in day_records
                if row["load"]["inclusion_state"] == "included"
            ),
            "load_included_count": included_count,
            "load_coverage": load_coverage,
            "decision_source_id": decision["source_id"] if decision else None,
            "recommendation": decision["recommendation"] if decision_state == "available" else None,
            "physiology_availability": (
                (decision["signal_availability"] or {}).get("physiology") or "unknown"
                if decision else "unknown"
            ),
            "recovery_source_id": recovery["source_id"],
            "recovery_score": recovery.get("score") if recovery["status"] == "available" else None,
            "comparison_status": (
                "available" if decision_state == "available" and recovery["status"] == "available"
                else "unavailable"
            ),
        }
        recovery_days.append(day)
        if day["comparison_status"] == "available":
            recovery_groups.setdefault(
                (day["recommendation"], load_coverage,
                 day["physiology_availability"]), Counter()
            )[day["recovery_score"]] += 1
            if (
                day["recommendation"] == "high_intensity"
                and day["recovery_score"] <= 2
                and load_coverage == "all_included"
            ):
                review_cases.append({
                    "type": "high_intensity_advice_low_next_day_recovery",
                    "training_local_date": local_day,
                    "activity_ids": day["activity_ids"],
                    "decision_source_id": day["decision_source_id"],
                    "recovery_source_id": day["recovery_source_id"],
                    "recovery_score": day["recovery_score"],
                    "included_tss": day["included_tss"],
                    "load_included_count": day["load_included_count"],
                })

    return {
        "model_error": {
            "status": "not_measurable",
            "reason": "no_validated_prediction_target_or_outcome_baseline",
        },
        "activity_count": len(records),
        "activity_states": dict(sorted(activity_states.items())),
        "rpe_distributions": [
            {
                "scale": scale, "recommendation": recommendation,
                "activity_type": activity_type, "load_inclusion_state": inclusion,
                "intensity_band": band, "physiology_availability": physiology,
                "count": sum(scores.values()),
                "score_counts": dict(sorted(scores.items())),
            }
            for (scale, recommendation, activity_type, inclusion, band, physiology), scores
            in sorted(rpe_groups.items())
        ],
        "training_day_count": len(recovery_days),
        "day_states": dict(sorted(day_states.items())),
        "recovery_days": recovery_days,
        "recovery_distributions": [
            {"recommendation": recommendation, "load_coverage": coverage,
             "physiology_availability": physiology,
             "day_count": sum(scores.values()),
             "score_counts": dict(sorted(scores.items()))}
            for (recommendation, coverage, physiology), scores
            in sorted(recovery_groups.items())
        ],
        "review_cases": review_cases,
    }


def build_outcome_evaluation(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Count each activity target separately and recovery once per training day."""
    activity_states: dict[str, Counter[str]] = {}
    recovery_by_day: dict[date, str] = {}
    for record in records:
        for name, target in record["outcome"]["targets"].items():
            if target["unit"] == "activity":
                activity_states.setdefault(name, Counter())[target["status"]] += 1
            else:
                recovery_by_day.setdefault(record["activity_local_date"], target["status"])
    return {
        "contract_version": OUTCOME_CONTRACT_VERSION,
        "activity_count": len(records),
        "activity_target_states": {
            name: dict(sorted(states.items()))
            for name, states in sorted(activity_states.items())
        },
        "training_day_count": len(recovery_by_day),
        "next_day_recovery_states": dict(sorted(Counter(recovery_by_day.values()).items())),
    }


def build_calibration_records(*, user_id: str, date_from: date, date_to: date,
                              timezone: str, activities: list[tuple[Any, ...]],
                              snapshots: list[tuple[Any, ...]],
                              generated_at: datetime,
                              gap_limit: int = DEFAULT_GAP_LIMIT) -> dict[str, Any]:
    if date_to < date_from:
        raise ValueError("date_to must be on or after date_from")
    zone = ZoneInfo(timezone)
    records = []
    for row in activities:
        (activity_id, activity_type, start, local_day, metrics_id, tss,
         normalized_power, intensity_factor, rpe_id, rpe_score, rpe_value,
         rpe_version, rpe_updated_at, effective_score, effective_source,
         disagreement, resolved_at, observation_id, observation_score,
         scale_version, schema_version, observed_at, received_at,
         recovery_id, recovery_score, recovery_value, recovery_version,
         recovery_updated_at) = row
        snapshot, missing_reason = _select_snapshot(snapshots, start, local_day)
        legacy_rpe = _feedback(
            rpe_id, rpe_score, rpe_value, rpe_version, rpe_updated_at, RPE_VALUES,
        )
        current_rpe = _current_rpe(
            effective_score, effective_source, disagreement, resolved_at,
            observation_id, observation_score, scale_version, schema_version,
            observed_at, received_at,
        )
        load = resolve_activity_load(
            activity_type=activity_type, tss=tss,
            normalized_power=normalized_power, intensity_factor=intensity_factor,
        )
        effective_rpe = current_rpe or legacy_rpe
        next_day_recovery = {
            **_feedback(recovery_id, recovery_score, recovery_value,
                        recovery_version, recovery_updated_at, RECOVERY_VALUES),
            "target_local_date": local_day + timedelta(days=1),
            "semantics": "day_level_context_shared_by_all_activities_on_previous_day",
        }
        records.append({
            "user_id": user_id,
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
                "intensity_factor": intensity_factor,
                "intensity_band": (
                    classify_intensity_band(intensity_factor)
                    if load["load_model_included"] else None
                ),
                "inclusion_state": (
                    "included" if load["load_model_included"] else
                    "unsupported_sport" if not is_supported_cycling_activity(activity_type)
                    else "missing_power_metrics" if metrics_id is not None
                    else "missing_metrics"
                ),
            },
            "post_ride_rpe": effective_rpe,
            "legacy_post_ride_rpe": legacy_rpe if current_rpe is not None else None,
            "next_day_recovery": next_day_recovery,
            "outcome": _outcome_targets(effective_rpe, next_day_recovery),
        })
    report = {
        "user_id": user_id, "date_from": date_from, "date_to": date_to,
        "timezone": timezone, "generated_at": generated_at,
        "records": records,
    }
    report["evaluation"] = build_evaluation(records)
    report["outcome_evaluation"] = build_outcome_evaluation(records)
    report["feedback_completeness"] = build_feedback_completeness(
        records, timezone=timezone, generated_at=generated_at, gap_limit=gap_limit,
    )
    return report


def generate_calibration_records(*, user_id: str, date_from: date,
                                 date_to: date, timezone: str | None = None,
                                 generated_at: datetime | None = None,
                                 gap_limit: int = DEFAULT_GAP_LIMIT) -> dict[str, Any]:
    if date_to < date_from:
        raise ValueError("date_to must be on or after date_from")
    report_timezone = timezone or settings.whatte_timezone
    ZoneInfo(report_timezone)
    report_time = generated_at if generated_at is not None else datetime.now(utc_timezone.utc)
    # Validate options before opening a database connection, including empty ranges.
    build_feedback_completeness([], timezone=report_timezone,
                                generated_at=report_time, gap_limit=gap_limit)
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
        generated_at=report_time, gap_limit=gap_limit,
    )
