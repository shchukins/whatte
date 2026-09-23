from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from backend.config import settings
from backend.db import get_conn
from backend.services.decision_engine import build_recommendation
from backend.services.activity_load_service import (
    is_supported_cycling_activity,
    resolve_activity_load,
)
from backend.services.readiness_composition import READINESS_MODEL_VERSION


PILOT_QUERY = """
with days as (
    select generate_series(%s::date, %s::date, interval '1 day')::date as day
), activity_stats as (
    select
        (r.start_date at time zone %s)::date as day,
        count(*) as activity_count,
        count(*) filter (
            where delivery.id is not null
               or feedback.id is null
        ) as rpe_eligible_count,
        count(*) filter (
            where delivery.id is null
              and feedback.id is not null
        ) as rpe_eligibility_unknown_count,
        count(*) filter (
            where delivery.delivery_status = 'sent'
        ) as rpe_prompt_count,
        count(*) filter (
            where delivery.id is not null
              and delivery.delivery_status != 'sent'
        ) as rpe_failed_or_incomplete_prompt_count,
        count(*) filter (
            where delivery.id is null
              and feedback.id is null
        ) as rpe_missing_prompt_count,
        count(*) filter (
            where delivery.delivery_status = 'sent'
              and feedback.id is not null
        ) as rpe_prompted_response_count,
        count(*) filter (
            where feedback.id is not null
        ) as rpe_recorded_response_count,
        count(*) filter (
            where delivery.id is null
              and feedback.id is not null
        ) as rpe_unprompted_response_count
    from strava_activity_raw r
    left join activity_delivery_log delivery
      on delivery.activity_id = r.strava_activity_id
     and delivery.delivery_type = 'post_ride_rpe'
    left join activity_subjective_feedback feedback
      on feedback.canonical_activity_id = r.strava_activity_id
     and feedback.feedback_type = 'post_ride_rpe'
    where r.user_id = %s
      and (r.start_date at time zone %s)::date between %s::date and %s::date
      and r.is_deleted = false
      and r.is_excluded = false
    group by 1
), snapshot_stats as (
    select
        snapshot_date as day,
        (array_agg(
            jsonb_build_object('snapshot', snapshot_json, 'captured_at', captured_at)
            order by captured_at
        )
            filter (where event_type = 'recovery_checkin_before'))[1] as checkin_before,
        (array_agg(
            jsonb_build_object('snapshot', snapshot_json, 'captured_at', captured_at)
            order by captured_at desc
        )
            filter (where event_type = 'recovery_checkin_after'))[1] as checkin_after,
        (array_agg(
            jsonb_build_object('snapshot', snapshot_json, 'captured_at', captured_at)
            order by captured_at desc
        )
            filter (where event_type = 'daily_readiness_delivery'))[1] as delivery_snapshot
    from decision_context_snapshot
    where user_id = %s
      and snapshot_date between %s::date and %s::date
    group by snapshot_date
), ingest_failures as (
    select
        (coalesce(finished_at, started_at, scheduled_at) at time zone %s)::date as day,
        count(*) as failure_count
    from strava_activity_ingest_job
    where user_id = %s
      and status in ('failed', 'error')
      and (coalesce(finished_at, started_at, scheduled_at) at time zone %s)::date
          between %s::date and %s::date
    group by 1
)
select
    days.day,
    readiness.readiness_score,
    readiness.good_day_probability,
    readiness.status_text,
    readiness.explanation_json,
    readiness.updated_at,
    notification.delivery_status,
    coalesce(previous_load.activities_count, 0),
    coalesce(previous_load.tss, 0),
    prompt.delivery_status,
    recovery_feedback.id is not null,
    coalesce(activity_stats.activity_count, 0),
    coalesce(activity_stats.rpe_eligible_count, 0),
    coalesce(activity_stats.rpe_eligibility_unknown_count, 0),
    coalesce(activity_stats.rpe_prompt_count, 0),
    coalesce(activity_stats.rpe_failed_or_incomplete_prompt_count, 0),
    coalesce(activity_stats.rpe_missing_prompt_count, 0),
    coalesce(activity_stats.rpe_prompted_response_count, 0),
    coalesce(activity_stats.rpe_recorded_response_count, 0),
    coalesce(activity_stats.rpe_unprompted_response_count, 0),
    snapshot_stats.checkin_before,
    snapshot_stats.checkin_after,
    snapshot_stats.delivery_snapshot,
    coalesce(ingest_failures.failure_count, 0),
    case
        when notification.delivery_status = 'failed' then 1
        else 0
    end + case
        when prompt.delivery_status = 'failed' then 1
        else 0
    end as delivery_failures
from days
left join readiness_daily readiness
  on readiness.user_id = %s
 and readiness.date = days.day
 and readiness.version = %s
left join notification_log notification
  on notification.user_id = %s
 and notification.notification_type = 'daily_readiness'
 and notification.notification_date = days.day
left join daily_training_load previous_load
  on previous_load.user_id = %s
 and previous_load.date = days.day - 1
left join subjective_feedback_prompt_log prompt
  on prompt.user_id = %s
 and prompt.prompt_type = 'next_day_recovery'
 and prompt.target_date = days.day
left join activity_subjective_feedback recovery_feedback
  on recovery_feedback.user_id = %s
 and recovery_feedback.activity_date = days.day
 and recovery_feedback.feedback_type = 'next_day_recovery'
 and recovery_feedback.strava_activity_id is null
left join activity_stats on activity_stats.day = days.day
left join snapshot_stats on snapshot_stats.day = days.day
left join ingest_failures on ingest_failures.day = days.day
order by days.day;
"""


LOAD_COVERAGE_QUERY = """
select
    (r.start_date at time zone %s)::date as local_day,
    r.strava_activity_id,
    r.activity_type,
    r.start_date at time zone %s as local_start,
    coalesce(m.duration_s, r.moving_time_s, r.elapsed_time_s) as duration_s,
    r.is_deleted,
    r.is_excluded,
    r.duplicate_of_activity_id,
    m.id is not null as has_metrics,
    m.tss,
    m.normalized_power,
    m.intensity_factor
from strava_activity_raw r
left join activity_metrics m
  on m.strava_activity_id = r.strava_activity_id
 and m.user_id = r.user_id
 and m.version = 'v1'
where r.user_id = %s
  and (r.start_date at time zone %s)::date between %s::date and %s::date
order by local_day, local_start, r.strava_activity_id;
"""


def build_load_coverage(
    *,
    date_from: date,
    date_to: date,
    rows: list[tuple[Any, ...]],
) -> dict[str, Any]:
    """Assess current stored load coverage without reconstructing past decisions."""
    days: dict[str, dict[str, Any]] = {}
    day = date_from
    while day <= date_to:
        days[day.isoformat()] = {
            "date": day.isoformat(),
            "canonical_activities": 0,
            "included": 0,
            "not_included": 0,
            "unknown_assessment": 0,
            "excluded_records": {"deleted": 0, "duplicate": 0, "user_excluded": 0},
            "not_included_activities": [],
        }
        day += timedelta(days=1)

    for row in rows:
        (
            local_day, activity_id, activity_type, local_start, duration_s,
            is_deleted, is_excluded, duplicate_of_activity_id, has_metrics,
            tss, normalized_power, intensity_factor,
        ) = row
        entry = days[local_day.isoformat()]
        if is_deleted:
            entry["excluded_records"]["deleted"] += 1
            continue
        if duplicate_of_activity_id is not None:
            entry["excluded_records"]["duplicate"] += 1
            continue
        if is_excluded:
            entry["excluded_records"]["user_excluded"] += 1
            continue

        entry["canonical_activities"] += 1
        if not has_metrics:
            reason = "unavailable_metrics_record"
            entry["unknown_assessment"] += 1
        else:
            assessment = resolve_activity_load(
                activity_type=activity_type,
                tss=tss,
                normalized_power=normalized_power,
                intensity_factor=intensity_factor,
            )
            if assessment["load_model_included"]:
                entry["included"] += 1
                continue
            reason = (
                "unsupported_sport"
                if not is_supported_cycling_activity(activity_type)
                else "missing_required_power_metrics"
            )
            entry["not_included"] += 1
        entry["not_included_activities"].append({
            "activity_id": activity_id,
            "sport": activity_type,
            "local_start": local_start,
            "duration_s": duration_s,
            "reason": reason,
        })

    for entry in days.values():
        counted = entry["canonical_activities"]
        classified = sum(entry["excluded_records"].values())
        if not counted:
            entry["coverage_state"] = (
                "excluded_only" if classified else "no_recorded_activity"
            )
        elif sum(int(entry[key] > 0) for key in (
            "included", "not_included", "unknown_assessment"
        )) > 1:
            entry["coverage_state"] = "mixed_coverage"
        elif entry["included"]:
            entry["coverage_state"] = "supported_measured_load"
        elif entry["not_included"]:
            entry["coverage_state"] = "recorded_unmodeled_activity"
        else:
            entry["coverage_state"] = "unknown_assessment"

    return {
        "semantics": "current_stored_assessment_not_historical_decision_evidence",
        "days": list(days.values()),
    }


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _snapshot_record(value: Any) -> tuple[dict[str, Any], Any]:
    record = _as_dict(value)
    if "snapshot" not in record:
        return record, None
    return _as_dict(record.get("snapshot")), record.get("captured_at")


def _score_delta(before: dict[str, Any], after: dict[str, Any]) -> float | None:
    before_score = before.get("readiness_score")
    after_score = after.get("readiness_score")
    if before_score is None or after_score is None:
        return None
    return round(float(after_score) - float(before_score), 4)


def _category_changed(
    before: dict[str, Any],
    after: dict[str, Any],
) -> bool | None:
    before_category = before.get("recommendation")
    after_category = after.get("recommendation")
    if before_category is None or after_category is None:
        return None
    return before_category != after_category


def _decision_changed(before: Any, after: Any) -> bool | None:
    before = _as_dict(before)
    after = _as_dict(after)
    if not before or not after:
        return None
    score_delta = _score_delta(before, after)
    category_changed = _category_changed(before, after)
    if score_delta is None and category_changed is None:
        return None
    return bool((score_delta is not None and score_delta != 0) or category_changed)


def build_pilot_report(
    *,
    user_id: str,
    date_from: date,
    date_to: date,
    timezone: str,
    rows: list[tuple[Any, ...]],
) -> dict[str, Any]:
    if date_to < date_from:
        raise ValueError("date_to must be on or after date_from")

    signal_distribution = {
        family: {"available_days": 0, "used_days": 0}
        for family in ("load", "freshness", "response", "feeling", "physiology")
    }
    days: list[dict[str, Any]] = []
    valid_recommendations = 0
    valid_without_physiology = 0
    recovery_eligible = recovery_responses = 0
    rpe_eligible = rpe_eligibility_unknown = 0
    rpe_prompts = rpe_prompted_responses = 0
    rpe_failed_or_incomplete_prompts = rpe_missing_prompts = 0
    rpe_recorded_responses = rpe_unprompted_responses = 0
    checkin_observed = checkin_changed = 0
    checkin_score_observed = checkin_category_observed = 0
    checkin_score_changed = checkin_category_changed = 0
    stale_or_missing_training_days = 0
    ingest_failures = delivery_failures = 0

    for row in rows:
        (
            day,
            readiness_score,
            good_day_probability,
            status_text,
            explanation_json,
            readiness_computed_at,
            notification_status,
            previous_activities_count,
            previous_tss,
            recovery_prompt_status,
            has_recovery_feedback,
            activity_count,
            day_rpe_eligible,
            day_rpe_eligibility_unknown,
            day_rpe_prompts,
            day_rpe_failed_or_incomplete_prompts,
            day_rpe_missing_prompts,
            day_rpe_prompted_responses,
            day_rpe_recorded_responses,
            day_rpe_unprompted_responses,
            checkin_before_record,
            checkin_after_record,
            delivery_snapshot_record,
            day_ingest_failures,
            day_delivery_failures,
        ) = row
        explanation = _as_dict(explanation_json)
        families = _as_dict(explanation.get("signal_families"))
        source_timestamps = _as_dict(explanation.get("source_timestamps"))
        training_source_at = source_timestamps.get("training_source_at")
        training_is_current = (
            training_source_at is not None and str(training_source_at) == str(day)
        )
        stale_or_missing_training_days += int(not training_is_current)
        recommendation = None
        if readiness_score is not None:
            recommendation = build_recommendation(
                readiness_score=float(readiness_score),
                explanation=explanation,
            )["recommendation"]
            valid_recommendations += 1
            if (
                _as_dict(families.get("physiology")).get("availability")
                != "available"
            ):
                valid_without_physiology += 1

        for family, counts in signal_distribution.items():
            state = _as_dict(families.get(family))
            counts["available_days"] += int(
                state.get("availability") == "available"
            )
            counts["used_days"] += int(bool(state.get("used")))

        physiology_available = (
            _as_dict(families.get("physiology")).get("availability")
            == "available"
        )

        eligible = int(previous_activities_count or 0) > 0 or float(previous_tss or 0) > 0
        recovery_eligible += int(eligible)
        recovery_responses += int(eligible and bool(has_recovery_feedback))
        rpe_eligible += int(day_rpe_eligible or 0)
        rpe_eligibility_unknown += int(day_rpe_eligibility_unknown or 0)
        rpe_prompts += int(day_rpe_prompts or 0)
        rpe_failed_or_incomplete_prompts += int(
            day_rpe_failed_or_incomplete_prompts or 0
        )
        rpe_missing_prompts += int(day_rpe_missing_prompts or 0)
        rpe_prompted_responses += int(day_rpe_prompted_responses or 0)
        rpe_recorded_responses += int(day_rpe_recorded_responses or 0)
        rpe_unprompted_responses += int(day_rpe_unprompted_responses or 0)
        checkin_before, checkin_before_at = _snapshot_record(checkin_before_record)
        checkin_after, checkin_after_at = _snapshot_record(checkin_after_record)
        delivery_snapshot, delivery_snapshot_at = _snapshot_record(
            delivery_snapshot_record
        )
        changed = _decision_changed(checkin_before, checkin_after)
        score_delta = _score_delta(checkin_before, checkin_after)
        score_changed = None if score_delta is None else score_delta != 0
        category_changed = _category_changed(checkin_before, checkin_after)
        if changed is not None:
            checkin_observed += 1
            checkin_changed += int(changed)
        if score_changed is not None:
            checkin_score_observed += 1
            checkin_score_changed += int(bool(score_changed))
        if category_changed is not None:
            checkin_category_observed += 1
            checkin_category_changed += int(bool(category_changed))
        ingest_failures += int(day_ingest_failures or 0)
        delivery_failures += int(day_delivery_failures or 0)

        days.append({
            "date": str(day),
            "readiness_score": readiness_score,
            "good_day_probability": good_day_probability,
            "status_text": status_text,
            "recommendation": recommendation,
            "physiology_available": physiology_available,
            "readiness_computed_at": readiness_computed_at,
            "notification_status": notification_status,
            "recovery_prompt_status": recovery_prompt_status,
            "recovery_feedback": bool(has_recovery_feedback),
            "activities": int(activity_count or 0),
            "rpe_eligible_activities": int(day_rpe_eligible or 0),
            "rpe_eligibility_unknown": int(day_rpe_eligibility_unknown or 0),
            "rpe_prompts": int(day_rpe_prompts or 0),
            "rpe_failed_or_incomplete_prompts": int(
                day_rpe_failed_or_incomplete_prompts or 0
            ),
            "rpe_missing_prompts": int(day_rpe_missing_prompts or 0),
            "rpe_responses": int(day_rpe_prompted_responses or 0),
            "rpe_recorded_responses": int(day_rpe_recorded_responses or 0),
            "rpe_unprompted_responses": int(day_rpe_unprompted_responses or 0),
            "rpe_not_successfully_prompted": max(
                int(day_rpe_eligible or 0) - int(day_rpe_prompts or 0), 0
            ),
            "rpe_unanswered_prompts": max(
                int(day_rpe_prompts or 0) - int(day_rpe_prompted_responses or 0),
                0,
            ),
            "checkin_decision_changed": changed,
            "checkin_score_changed": score_changed,
            "checkin_score_delta": score_delta,
            "checkin_category_changed": category_changed,
            "checkin_category_transition": (
                {
                    "from": checkin_before.get("recommendation"),
                    "to": checkin_after.get("recommendation"),
                }
                if category_changed is not None
                else None
            ),
            "delivery_snapshot_available": bool(delivery_snapshot),
            "decision_states": {
                "delivery": {
                    "captured_at": delivery_snapshot_at,
                    "snapshot": delivery_snapshot or None,
                },
                "checkin_daily_comparison": {
                    "semantics": "first_before_to_last_after_not_individually_paired",
                    "before_captured_at": checkin_before_at,
                    "before_snapshot": checkin_before or None,
                    "after_captured_at": checkin_after_at,
                    "after_snapshot": checkin_after or None,
                },
                "current_persisted": {
                    "updated_at": readiness_computed_at,
                    "readiness_score": readiness_score,
                    "recommendation": recommendation,
                    "status_text": status_text,
                },
            },
            "training_input_current": training_is_current,
            "ingest_failures": int(day_ingest_failures or 0),
            "delivery_failures": int(day_delivery_failures or 0),
        })

    day_count = len(days)
    return {
        "scope": {
            "user_id": user_id,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "timezone": timezone,
            "days": day_count,
            "minimum_14_consecutive_days_met": day_count >= 14,
            "model_version": READINESS_MODEL_VERSION,
        },
        "metrics": {
            "valid_morning_recommendations": {
                "numerator": valid_recommendations,
                "denominator": day_count,
                "rate": _rate(valid_recommendations, day_count),
            },
            "valid_recommendations_without_physiology": {
                "numerator": valid_without_physiology,
                "denominator": valid_recommendations,
                "rate": _rate(valid_without_physiology, valid_recommendations),
            },
            "morning_recovery_response": {
                "numerator": recovery_responses,
                "denominator": recovery_eligible,
                "rate": _rate(recovery_responses, recovery_eligible),
            },
            "post_workout_rpe_completion": {
                "numerator": rpe_prompted_responses,
                "denominator": rpe_prompts,
                "rate": _rate(rpe_prompted_responses, rpe_prompts),
            },
            "post_workout_rpe_funnel": {
                "eligible_canonical_activities": rpe_eligible,
                "eligibility_unknown": rpe_eligibility_unknown,
                "successfully_prompted": rpe_prompts,
                "failed_or_incomplete_prompts": rpe_failed_or_incomplete_prompts,
                "missing_prompt_records": rpe_missing_prompts,
                "not_successfully_prompted": max(rpe_eligible - rpe_prompts, 0),
                "recorded_responses": rpe_recorded_responses,
                "prompted_responses": rpe_prompted_responses,
                "unanswered_prompts": max(
                    rpe_prompts - rpe_prompted_responses, 0
                ),
                "unprompted_responses": rpe_unprompted_responses,
            },
            "signal_family_distribution": signal_distribution,
            "stale_or_missing_required_training_input": {
                "numerator": stale_or_missing_training_days,
                "denominator": day_count,
                "rate": _rate(stale_or_missing_training_days, day_count),
            },
            "recommendation_changes_after_checkin": {
                "numerator": checkin_changed,
                "denominator": checkin_observed,
                "rate": _rate(checkin_changed, checkin_observed),
            },
            "readiness_score_changes_after_checkin": {
                "numerator": checkin_score_changed,
                "denominator": checkin_score_observed,
                "rate": _rate(checkin_score_changed, checkin_score_observed),
            },
            "recommendation_category_changes_after_checkin": {
                "numerator": checkin_category_changed,
                "denominator": checkin_category_observed,
                "rate": _rate(
                    checkin_category_changed,
                    checkin_category_observed,
                ),
            },
            "failures": {
                "ingestion": ingest_failures,
                "delivery": delivery_failures,
                "processing": None,
                "decision": None,
                "presentation": None,
            },
            "duplicate_delivery_rate": {
                "status": "not_measurable",
                "reason": "current idempotency tables store canonical delivery state, not every delivery attempt",
            },
            "api_web_telegram_consistency": {
                "status": "not_measurable",
                "reason": "API and Web read the same current state, but historical presentation observations are not persisted",
            },
        },
        "days": days,
    }


def generate_pilot_report(
    *,
    user_id: str,
    date_from: date,
    date_to: date,
    timezone: str | None = None,
) -> dict[str, Any]:
    report_timezone = timezone or settings.whatte_timezone
    params = (
        date_from,
        date_to,
        report_timezone,
        user_id,
        report_timezone,
        date_from,
        date_to,
        user_id,
        date_from,
        date_to,
        report_timezone,
        user_id,
        report_timezone,
        date_from,
        date_to,
        user_id,
        READINESS_MODEL_VERSION,
        user_id,
        user_id,
        user_id,
        user_id,
    )
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(PILOT_QUERY, params)
            rows = cur.fetchall()
            cur.execute(LOAD_COVERAGE_QUERY, (
                report_timezone, report_timezone, user_id, report_timezone,
                date_from, date_to,
            ))
            coverage_rows = cur.fetchall()
    report = build_pilot_report(
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        timezone=report_timezone,
        rows=rows,
    )
    report["load_coverage"] = build_load_coverage(
        date_from=date_from, date_to=date_to, rows=coverage_rows,
    )
    return report


def render_pilot_report_markdown(report: dict[str, Any]) -> str:
    scope = report["scope"]
    metrics = report["metrics"]
    lines = [
        "# Morning Loop pilot report",
        "",
        f"- Interval: {scope['date_from']} to {scope['date_to']} (inclusive)",
        f"- Timezone: {scope['timezone']}",
        f"- Model version: {scope['model_version']}",
        f"- Calendar rows: {scope['days']}",
        f"- Minimum 14-day interval: {str(scope['minimum_14_consecutive_days_met']).lower()}",
        "",
        "> Fourteen calendar rows do not by themselves prove successful pilot completion.",
        "",
    ]
    coverage = report.get("load_coverage")
    if coverage is not None:
        lines.extend([
            "## Training-load coverage",
            "",
            "Current assessment from stored canonical activities and v1 metrics; "
            "it is not evidence of load inclusion when a historical decision was made.",
            "Unknown means the metrics record is absent. Known not included means "
            "the current load resolver rejects the activity. Neither means measured zero load or rest.",
            "",
            "| Date | State | Canonical | Included | Not included | Unknown | "
            "Deleted / duplicate / user-excluded |",
            "|---|---|---:|---:|---:|---:|---:|",
        ])
        for day in coverage["days"]:
            excluded = day["excluded_records"]
            lines.append(
                f"| {day['date']} | {day['coverage_state']} | "
                f"{day['canonical_activities']} | {day['included']} | "
                f"{day['not_included']} | {day['unknown_assessment']} | "
                f"{excluded['deleted']} / {excluded['duplicate']} / "
                f"{excluded['user_excluded']} |"
            )
        lines.extend([
            "",
            "### Activities without assessed included load",
            "",
            "| Date and time (report timezone) | Activity ID | Sport | Duration (s) | Reason |",
            "|---|---:|---|---:|---|",
        ])
        for day in coverage["days"]:
            for activity in day["not_included_activities"]:
                sport = str(activity["sport"] or "unknown").replace("|", "\\|").replace("\n", " ")
                duration = activity["duration_s"]
                lines.append(
                    f"| {activity['local_start']} | {activity['activity_id']} | "
                    f"{sport} | {duration if duration is not None else 'unknown'} | "
                    f"{activity['reason']} |"
                )
        if not any(day["not_included_activities"] for day in coverage["days"]):
            lines.append("| — | — | — | — | none |")
        lines.append("")
    lines.extend([
        "## Rates",
        "",
        "| Metric | Numerator | Denominator | Rate |",
        "|---|---:|---:|---:|",
    ])
    rate_keys = (
        ("Valid morning recommendations", "valid_morning_recommendations"),
        ("Valid recommendations without physiology", "valid_recommendations_without_physiology"),
        ("Morning recovery response", "morning_recovery_response"),
        ("Post-workout RPE completion", "post_workout_rpe_completion"),
        (
            "Stale or missing required training input",
            "stale_or_missing_required_training_input",
        ),
        ("Combined decision changes after check-in", "recommendation_changes_after_checkin"),
        ("Readiness score changes after check-in", "readiness_score_changes_after_checkin"),
        (
            "Recommendation category changes after check-in",
            "recommendation_category_changes_after_checkin",
        ),
    )
    for label, key in rate_keys:
        metric = metrics[key]
        rate = "unknown" if metric["rate"] is None else f"{metric['rate']:.1%}"
        lines.append(
            f"| {label} | {metric['numerator']} | {metric['denominator']} | {rate} |"
        )

    funnel = metrics["post_workout_rpe_funnel"]
    lines.extend([
        "",
        "## Post-workout RPE funnel",
        "",
        f"- Eligible canonical activities: {funnel['eligible_canonical_activities']}",
        f"- Historical eligibility unknown: {funnel['eligibility_unknown']}",
        f"- Successfully prompted: {funnel['successfully_prompted']}",
        f"- Failed or incomplete prompt records: {funnel['failed_or_incomplete_prompts']}",
        f"- Missing prompt records: {funnel['missing_prompt_records']}",
        f"- Not successfully prompted: {funnel['not_successfully_prompted']}",
        f"- Recorded responses: {funnel['recorded_responses']}",
        f"- Prompted responses: {funnel['prompted_responses']}",
        f"- Unanswered prompts: {funnel['unanswered_prompts']}",
        f"- Unprompted responses: {funnel['unprompted_responses']}",
        "",
        "## Signal-family coverage",
        "",
        "| Family | Available days | Used days |",
        "|---|---:|---:|",
    ])
    for family, counts in metrics["signal_family_distribution"].items():
        lines.append(
            f"| {family} | {counts['available_days']} | {counts['used_days']} |"
        )
    failures = metrics["failures"]
    lines.extend([
        "",
        "## Failures",
        "",
        "| Layer | Count |",
        "|---|---:|",
    ])
    for layer, count in failures.items():
        value = "not measurable" if count is None else count
        lines.append(f"| {layer} | {value} |")
    lines.extend([
        "",
        "## Daily rows",
        "",
        "| Date | Score | Recommendation | Physiology | "
        "RPE eligible/sent/answered | Score delta | Category transition | "
        "Delivery / before / after / current timestamps |",
        "|---|---:|---|---|---:|---:|---|---|",
    ])
    for day in report["days"]:
        states = day["decision_states"]
        delivery_at = states["delivery"]["captured_at"] or "missing"
        comparison = states["checkin_daily_comparison"]
        before_at = comparison["before_captured_at"] or "missing"
        after_at = comparison["after_captured_at"] or "missing"
        current_at = states["current_persisted"]["updated_at"] or "missing"
        transition = day["checkin_category_transition"]
        transition_text = (
            f"{transition['from']} -> {transition['to']}" if transition else "unknown"
        )
        score = "missing" if day["readiness_score"] is None else day["readiness_score"]
        delta = "unknown" if day["checkin_score_delta"] is None else day["checkin_score_delta"]
        physiology = "available"
        if day["readiness_score"] is None:
            physiology = "unknown"
        elif day.get("physiology_available") is False:
            physiology = "not available"
        lines.append(
            f"| {day['date']} | {score} | {day['recommendation'] or 'missing'} | "
            f"{physiology} | {day['rpe_eligible_activities']}/"
            f"{day['rpe_prompts']}/{day['rpe_responses']} | {delta} | "
            f"{transition_text} | {delivery_at} / {before_at} / {after_at} / "
            f"{current_at} |"
        )
    lines.extend([
        "",
        "The check-in comparison is the first before snapshot versus the last "
        "after snapshot for the day; it does not claim individual check-ins "
        "are paired.",
        "A delivery snapshot records decision state captured around delivery, "
        "not proof of rendered message content.",
    ])
    return "\n".join(str(line) for line in lines) + "\n"
