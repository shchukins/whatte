from __future__ import annotations

import json
from datetime import date, timedelta
from statistics import median
from typing import Any

from fastapi import HTTPException

from backend.db import get_conn
from backend.services.metrics_service import compute_deltas


RESPONSE_METRICS_VERSION = "v2_rpe_1_10"
RESPONSE_FORMULA_VERSION = "activity_response_v1_rpe_1_10"
BASELINE_MAX_SAMPLES = 20
BASELINE_MIN_SAMPLES = 3
DECOUPLING_MIN_DURATION_S = 30 * 60
DECOUPLING_MAX_VARIABILITY_INDEX = 1.10
DECOUPLING_MIN_PAIRED_COVERAGE = 0.80


def classify_intensity_band(intensity_factor: float | None) -> str | None:
    if intensity_factor is None:
        return None
    value = float(intensity_factor)
    if value < 0.55:
        return "recovery"
    if value < 0.75:
        return "endurance"
    if value < 0.90:
        return "tempo"
    if value < 1.05:
        return "threshold"
    return "high_intensity"


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 6)


def _weighted_average(values: list[float], weights: list[int]) -> float | None:
    total_weight = sum(weights)
    if total_weight <= 0:
        return None
    return sum(value * weight for value, weight in zip(values, weights)) / total_weight


def compute_aerobic_decoupling(
    *,
    time_stream: list[Any],
    watts_stream: list[Any],
    hr_stream: list[Any],
    duration_s: int | None,
    variability_index: float | None,
) -> dict[str, Any]:
    reason_codes: list[str] = []
    if duration_s is None or duration_s < DECOUPLING_MIN_DURATION_S:
        reason_codes.append("duration_below_30_minutes")
    if variability_index is None:
        reason_codes.append("variability_index_unavailable")
    elif variability_index > DECOUPLING_MAX_VARIABILITY_INDEX:
        reason_codes.append("workout_not_steady")
    if not time_stream:
        reason_codes.append("time_stream_unavailable")
    if not watts_stream:
        reason_codes.append("power_stream_unavailable")
    if not hr_stream:
        reason_codes.append("heart_rate_stream_unavailable")
    if reason_codes:
        return {
            "value": None,
            "availability": "unavailable",
            "reason_codes": reason_codes,
            "paired_coverage": 0.0,
        }

    sample_count = min(len(time_stream), len(watts_stream), len(hr_stream))
    times = [int(value) for value in time_stream[:sample_count]]
    deltas = compute_deltas(times)
    total_time = sum(max(0, delta) for delta in deltas)
    midpoint = (times[0] + times[-1]) / 2.0
    halves: dict[str, dict[str, list[Any]]] = {
        "first": {"power": [], "hr": [], "weights": []},
        "second": {"power": [], "hr": [], "weights": []},
    }
    paired_time = 0
    for index in range(sample_count):
        delta = max(0, deltas[index])
        power = watts_stream[index]
        heart_rate = hr_stream[index]
        if (
            delta <= 0
            or power is None
            or heart_rate is None
            or float(power) <= 0
            or float(heart_rate) <= 0
        ):
            continue
        paired_time += delta
        half = "first" if times[index] <= midpoint else "second"
        halves[half]["power"].append(float(power))
        halves[half]["hr"].append(float(heart_rate))
        halves[half]["weights"].append(delta)

    paired_coverage = paired_time / total_time if total_time > 0 else 0.0
    if paired_coverage < DECOUPLING_MIN_PAIRED_COVERAGE:
        return {
            "value": None,
            "availability": "unavailable",
            "reason_codes": ["paired_power_hr_coverage_below_80_percent"],
            "paired_coverage": round(paired_coverage, 4),
        }

    first_power = _weighted_average(halves["first"]["power"], halves["first"]["weights"])
    first_hr = _weighted_average(halves["first"]["hr"], halves["first"]["weights"])
    second_power = _weighted_average(halves["second"]["power"], halves["second"]["weights"])
    second_hr = _weighted_average(halves["second"]["hr"], halves["second"]["weights"])
    first_ratio = _ratio(first_power, first_hr)
    second_ratio = _ratio(second_power, second_hr)
    if first_ratio is None or second_ratio is None:
        return {
            "value": None,
            "availability": "unavailable",
            "reason_codes": ["paired_power_hr_half_unavailable"],
            "paired_coverage": round(paired_coverage, 4),
        }

    value = round((first_ratio / second_ratio - 1.0) * 100.0, 3)
    return {
        "value": value,
        "availability": "available",
        "reason_codes": [],
        "paired_coverage": round(paired_coverage, 4),
        "first_half_power_to_hr": first_ratio,
        "second_half_power_to_hr": second_ratio,
    }


def compute_response_metrics(
    *,
    duration_s: int | None,
    avg_power: float | None,
    normalized_power: float | None,
    avg_heartrate: float | None,
    intensity_factor: float | None,
    tss: float | None,
    variability_index: float | None,
    rpe_score: int | None,
    time_stream: list[Any],
    watts_stream: list[Any],
    hr_stream: list[Any],
) -> dict[str, Any]:
    avg_power_to_hr = _ratio(avg_power, avg_heartrate)
    normalized_power_to_hr = _ratio(normalized_power, avg_heartrate)
    decoupling = compute_aerobic_decoupling(
        time_stream=time_stream,
        watts_stream=watts_stream,
        hr_stream=hr_stream,
        duration_s=duration_s,
        variability_index=variability_index,
    )
    duration_minutes = duration_s / 60.0 if duration_s is not None and duration_s > 0 else None
    session_rpe_load = (
        round(duration_minutes * rpe_score, 3)
        if duration_minutes is not None and rpe_score is not None
        else None
    )
    rpe_per_intensity_factor = _ratio(rpe_score, intensity_factor)
    session_rpe_load_per_tss = _ratio(session_rpe_load, tss)

    availability = {
        "power": {
            "availability": "available"
            if avg_power is not None or normalized_power is not None
            else "unavailable",
            "reason_codes": []
            if avg_power is not None or normalized_power is not None
            else ["power_unavailable"],
        },
        "heart_rate": {
            "availability": "available" if avg_heartrate is not None else "unavailable",
            "reason_codes": [] if avg_heartrate is not None else ["heart_rate_unavailable"],
        },
        "power_to_hr": {
            "availability": "available"
            if avg_power_to_hr is not None or normalized_power_to_hr is not None
            else "unavailable",
            "reason_codes": []
            if avg_power_to_hr is not None or normalized_power_to_hr is not None
            else ["power_or_heart_rate_unavailable"],
        },
        "aerobic_decoupling": {
            "availability": decoupling["availability"],
            "reason_codes": decoupling["reason_codes"],
        },
        "rpe": {
            "availability": "available" if rpe_score is not None else "unavailable",
            "reason_codes": [] if rpe_score is not None else ["rpe_unavailable"],
        },
        "session_rpe_load": {
            "availability": "available" if session_rpe_load is not None else "unavailable",
            "reason_codes": []
            if session_rpe_load is not None
            else ["rpe_or_duration_unavailable"],
        },
        "rpe_relative_to_objective_load": {
            "availability": "available"
            if rpe_per_intensity_factor is not None or session_rpe_load_per_tss is not None
            else "unavailable",
            "reason_codes": []
            if rpe_per_intensity_factor is not None or session_rpe_load_per_tss is not None
            else ["rpe_or_objective_load_unavailable"],
        },
    }
    return {
        "avg_power_to_hr": avg_power_to_hr,
        "normalized_power_to_hr": normalized_power_to_hr,
        "aerobic_decoupling_pct": decoupling["value"],
        "rpe_score": rpe_score,
        "session_rpe_load": session_rpe_load,
        "rpe_per_intensity_factor": rpe_per_intensity_factor,
        "session_rpe_load_per_tss": session_rpe_load_per_tss,
        "intensity_band": classify_intensity_band(intensity_factor),
        "availability": availability,
        "decoupling_details": decoupling,
    }


def _deviation_pct(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None or baseline == 0:
        return None
    return round((current / baseline - 1.0) * 100.0, 3)


def build_baseline_snapshot(
    current_metrics: dict[str, float | None],
    history_rows: list[tuple[Any, ...]],
) -> dict[str, Any]:
    metric_names = (
        "normalized_power_to_hr",
        "aerobic_decoupling_pct",
        "rpe_per_intensity_factor",
        "session_rpe_load_per_tss",
    )
    result: dict[str, Any] = {
        "minimum_samples": BASELINE_MIN_SAMPLES,
        "maximum_samples": BASELINE_MAX_SAMPLES,
        "metrics": {},
    }
    for index, name in enumerate(metric_names):
        values = [float(row[index]) for row in history_rows if row[index] is not None]
        baseline_value = (
            round(float(median(values)), 6)
            if len(values) >= BASELINE_MIN_SAMPLES
            else None
        )
        current_value = current_metrics.get(name)
        result["metrics"][name] = {
            "availability": "available" if baseline_value is not None else "unavailable",
            "sample_count": len(values),
            "median": baseline_value,
            "current": current_value,
            "deviation_pct": _deviation_pct(current_value, baseline_value),
            "reason_codes": []
            if baseline_value is not None
            else ["comparable_baseline_insufficient_samples"],
        }
    return result


def _load_comparable_history(
    *,
    user_id: str,
    activity_id: int,
    activity_type: str | None,
    activity_date: date | None,
    intensity_band: str | None,
) -> list[tuple[Any, ...]]:
    if activity_type is None or activity_date is None or intensity_band is None:
        return []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    arm.normalized_power_to_hr,
                    arm.aerobic_decoupling_pct,
                    arm.rpe_per_intensity_factor,
                    arm.session_rpe_load_per_tss
                from activity_response_metrics arm
                join strava_activity_raw r
                  on r.strava_activity_id = arm.strava_activity_id
                where arm.user_id = %s
                  and arm.strava_activity_id <> %s
                  and arm.activity_type = %s
                  and arm.activity_date < %s
                  and arm.intensity_band = %s
                  and arm.version = %s
                  and r.is_deleted = false
                  and r.is_excluded = false
                  and r.duplicate_of_activity_id is null
                order by arm.activity_date desc, arm.strava_activity_id desc
                limit %s;
                """,
                (
                    user_id,
                    activity_id,
                    activity_type,
                    activity_date,
                    intensity_band,
                    RESPONSE_METRICS_VERSION,
                    BASELINE_MAX_SAMPLES,
                ),
            )
            return cur.fetchall()


def compute_and_store_activity_response(activity_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    r.user_id,
                    r.strava_activity_id,
                    r.activity_type,
                    date(r.start_date),
                    coalesce(m.moving_time_s, m.duration_s),
                    m.avg_power,
                    m.normalized_power,
                    m.avg_heartrate,
                    m.intensity_factor,
                    m.tss,
                    m.variability_index,
                    er.effective_score
                from strava_activity_raw r
                join activity_metrics m
                  on m.strava_activity_id = r.strava_activity_id
                 and m.version = 'v1'
                left join activity_rpe_resolution er
                  on er.canonical_activity_id = r.strava_activity_id
                where r.strava_activity_id = %s
                  and r.is_deleted = false
                  and r.is_excluded = false
                  and r.duplicate_of_activity_id is null
                limit 1;
                """,
                (activity_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"canonical activity metrics not found for activity_id={activity_id}",
                )
            cur.execute(
                """
                select stream_type, data_json
                from strava_activity_stream_raw
                where strava_activity_id = %s
                  and stream_type in ('time', 'watts', 'heartrate');
                """,
                (activity_id,),
            )
            stream_rows = cur.fetchall()

    (
        user_id,
        strava_activity_id,
        activity_type,
        activity_date,
        duration_s,
        avg_power,
        normalized_power,
        avg_heartrate,
        intensity_factor,
        tss,
        variability_index,
        rpe_score,
    ) = row
    streams = {
        stream_type: data_json if isinstance(data_json, dict) else json.loads(data_json)
        for stream_type, data_json in stream_rows
    }
    metrics = compute_response_metrics(
        duration_s=duration_s,
        avg_power=avg_power,
        normalized_power=normalized_power,
        avg_heartrate=avg_heartrate,
        intensity_factor=intensity_factor,
        tss=tss,
        variability_index=variability_index,
        rpe_score=rpe_score,
        time_stream=streams.get("time", {}).get("data", []),
        watts_stream=streams.get("watts", {}).get("data", []),
        hr_stream=streams.get("heartrate", {}).get("data", []),
    )
    history_rows = _load_comparable_history(
        user_id=user_id,
        activity_id=strava_activity_id,
        activity_type=activity_type,
        activity_date=activity_date,
        intensity_band=metrics["intensity_band"],
    )
    baseline = build_baseline_snapshot(metrics, history_rows)
    explanation = {
        "model": {
            "name": "activity_response_metrics",
            "version": RESPONSE_METRICS_VERSION,
            "formula_version": RESPONSE_FORMULA_VERSION,
        },
        "decoupling": metrics["decoupling_details"],
        "rpe_scale_version": "rpe_1_10",
        "thresholds": {
            "decoupling_min_duration_s": DECOUPLING_MIN_DURATION_S,
            "decoupling_max_variability_index": DECOUPLING_MAX_VARIABILITY_INDEX,
            "decoupling_min_paired_coverage": DECOUPLING_MIN_PAIRED_COVERAGE,
        },
    }

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into activity_response_metrics (
                    user_id,
                    strava_activity_id,
                    version,
                    activity_type,
                    activity_date,
                    duration_s,
                    intensity_factor,
                    intensity_band,
                    avg_power_w,
                    normalized_power_w,
                    avg_hr_bpm,
                    avg_power_to_hr,
                    normalized_power_to_hr,
                    aerobic_decoupling_pct,
                    rpe_score,
                    session_rpe_load,
                    rpe_per_intensity_factor,
                    session_rpe_load_per_tss,
                    availability_json,
                    baseline_json,
                    explanation_json,
                    computed_at
                )
                values (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb, now()
                )
                on conflict (strava_activity_id, version) do update set
                    user_id = excluded.user_id,
                    activity_type = excluded.activity_type,
                    activity_date = excluded.activity_date,
                    duration_s = excluded.duration_s,
                    intensity_factor = excluded.intensity_factor,
                    intensity_band = excluded.intensity_band,
                    avg_power_w = excluded.avg_power_w,
                    normalized_power_w = excluded.normalized_power_w,
                    avg_hr_bpm = excluded.avg_hr_bpm,
                    avg_power_to_hr = excluded.avg_power_to_hr,
                    normalized_power_to_hr = excluded.normalized_power_to_hr,
                    aerobic_decoupling_pct = excluded.aerobic_decoupling_pct,
                    rpe_score = excluded.rpe_score,
                    session_rpe_load = excluded.session_rpe_load,
                    rpe_per_intensity_factor = excluded.rpe_per_intensity_factor,
                    session_rpe_load_per_tss = excluded.session_rpe_load_per_tss,
                    availability_json = excluded.availability_json,
                    baseline_json = excluded.baseline_json,
                    explanation_json = excluded.explanation_json,
                    computed_at = now();
                """,
                (
                    user_id,
                    strava_activity_id,
                    RESPONSE_METRICS_VERSION,
                    activity_type,
                    activity_date,
                    duration_s,
                    intensity_factor,
                    metrics["intensity_band"],
                    avg_power,
                    normalized_power,
                    avg_heartrate,
                    metrics["avg_power_to_hr"],
                    metrics["normalized_power_to_hr"],
                    metrics["aerobic_decoupling_pct"],
                    rpe_score,
                    metrics["session_rpe_load"],
                    metrics["rpe_per_intensity_factor"],
                    metrics["session_rpe_load_per_tss"],
                    json.dumps(metrics["availability"]),
                    json.dumps(baseline),
                    json.dumps(explanation),
                ),
            )
            conn.commit()

    return {
        "ok": True,
        "user_id": user_id,
        "activity_id": strava_activity_id,
        "activity_date": activity_date.isoformat() if activity_date else None,
        "activity_type": activity_type,
        "version": RESPONSE_METRICS_VERSION,
        **{key: value for key, value in metrics.items() if key != "decoupling_details"},
        "baseline": baseline,
        "explanation": explanation,
    }


def recompute_readiness_for_response_window(
    *,
    user_id: str,
    activity_date: str | date,
) -> list[str]:
    from backend.services.readiness_daily import recompute_readiness_daily_for_date

    start_date = (
        activity_date
        if isinstance(activity_date, date)
        else date.fromisoformat(activity_date)
    )
    end_date = start_date + timedelta(days=7)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select date
                from load_state_daily_v2
                where user_id = %s
                  and date between %s and %s
                  and version = 'v2'
                order by date;
                """,
                (user_id, start_date, end_date),
            )
            dates = [row[0] for row in cur.fetchall()]
    for target_date in dates:
        recompute_readiness_daily_for_date(user_id, str(target_date))
    return [str(target_date) for target_date in dates]


def recompute_later_comparable_responses(
    *, user_id: str, activity_id: int, activity_date: str, activity_type: str | None,
    intensity_band: str | None,
) -> list[dict[str, Any]]:
    """Refresh baseline snapshots that can include the changed activity.

    A comparable baseline uses at most the 20 preceding sessions, so only the
    next 20 comparable rows can depend on this observation.
    """
    if not activity_type or not intensity_band:
        return []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select arm.strava_activity_id
                from activity_response_metrics arm
                join strava_activity_raw r
                  on r.strava_activity_id = arm.strava_activity_id
                where arm.user_id = %s
                  and arm.strava_activity_id <> %s
                  and arm.activity_date > %s
                  and arm.activity_type = %s
                  and arm.intensity_band = %s
                  and arm.version = %s
                  and r.is_deleted = false
                  and r.is_excluded = false
                  and r.duplicate_of_activity_id is null
                order by arm.activity_date, arm.strava_activity_id
                limit %s;
                """,
                (
                    user_id, activity_id, activity_date, activity_type,
                    intensity_band, RESPONSE_METRICS_VERSION, BASELINE_MAX_SAMPLES,
                ),
            )
            activity_ids = [row[0] for row in cur.fetchall()]
    return [compute_and_store_activity_response(next_id) for next_id in activity_ids]


def load_recent_response_context(
    cur: Any,
    *,
    user_id: str,
    target_date: str,
) -> dict[str, Any] | None:
    cur.execute(
        """
        select
            arm.strava_activity_id,
            arm.activity_date,
            arm.version,
            arm.intensity_band,
            arm.normalized_power_to_hr,
            arm.aerobic_decoupling_pct,
            arm.rpe_score,
            arm.session_rpe_load,
            arm.rpe_per_intensity_factor,
            arm.session_rpe_load_per_tss,
            arm.availability_json,
            arm.baseline_json,
            arm.explanation_json
        from activity_response_metrics arm
        join strava_activity_raw r
          on r.strava_activity_id = arm.strava_activity_id
        where arm.user_id = %s
          and arm.activity_date between (%s::date - interval '7 days') and %s::date
          and arm.version in (%s, 'v1')
          and r.is_deleted = false
          and r.is_excluded = false
          and r.duplicate_of_activity_id is null
        order by arm.activity_date desc, arm.strava_activity_id desc,
                 case when arm.version = %s then 0 else 1 end
        limit 1;
        """,
        (
            user_id, target_date, target_date, RESPONSE_METRICS_VERSION,
            RESPONSE_METRICS_VERSION,
        ),
    )
    row = cur.fetchone()
    if row is None:
        return None
    availability, baseline, explanation = row[10], row[11], row[12]
    for name, value in (
        ("availability", availability),
        ("baseline", baseline),
        ("explanation", explanation),
    ):
        if isinstance(value, str):
            parsed = json.loads(value)
            if name == "availability":
                availability = parsed
            elif name == "baseline":
                baseline = parsed
            else:
                explanation = parsed
    return {
        "activity_id": row[0],
        "activity_date": str(row[1]),
        "version": row[2],
        "intensity_band": row[3],
        "normalized_power_to_hr": row[4],
        "aerobic_decoupling_pct": row[5],
        "rpe_score": row[6],
        "session_rpe_load": row[7],
        "rpe_per_intensity_factor": row[8],
        "session_rpe_load_per_tss": row[9],
        "availability": availability,
        "baseline": baseline,
        "explanation": explanation,
    }
