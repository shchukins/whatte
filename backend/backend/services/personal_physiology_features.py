"""Versioned personal-relative features from manual physiology observations.

The service intentionally has no HealthKit fallback and no readiness side
effect. It is a reproducible derived-data boundary for research consumers.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from backend.config import settings
from backend.db import get_conn


PERSONAL_PHYSIOLOGY_FEATURE_VERSION = "personal_physiology_features_v1"
BASELINE_WINDOW_DAYS = 28
BASELINE_MIN_OBSERVATIONS = 7
_SIGNALS = ("hrv", "resting_hr", "sleep_duration")
_SIGNAL_FIELDS = {
    "hrv": "hrv_ms",
    "resting_hr": "resting_hr_bpm",
    "sleep_duration": "sleep_duration_minutes",
}


def _round(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _source_staleness(
    *, observed_at: datetime | None, local_date: date, timezone: str
) -> str:
    """Describe source timing without changing the value or its eligibility."""
    if observed_at is None:
        return "unknown"
    observed_date = observed_at.astimezone(ZoneInfo(timezone)).date()
    if observed_date == local_date:
        return "current_local_date"
    if observed_date < local_date:
        return "stale"
    return "late"


def _signal_feature(
    *, value: float | None, history: list[float], signal: str
) -> dict[str, Any]:
    count = len(history)
    availability = "available" if value is not None else "unavailable"
    if value is None:
        state = "unavailable"
    elif count >= BASELINE_MIN_OBSERVATIONS:
        state = "mature"
    else:
        state = "immature"
    baseline = (
        _round(float(median(history)))
        if count >= BASELINE_MIN_OBSERVATIONS
        else None
    )
    result: dict[str, Any] = {
        "observation_count": count,
        "availability": availability,
        "baseline_state": state,
        "baseline": baseline,
    }
    if state != "mature" or baseline in (None, 0):
        if signal == "hrv":
            result.update(ratio=None, deviation=None)
        elif signal == "resting_hr":
            result.update(delta=None)
        else:
            result.update(deviation=None, debt=None)
        return result

    assert value is not None
    if signal == "hrv":
        ratio = value / baseline
        result.update(ratio=_round(ratio), deviation=_round(ratio - 1.0))
    elif signal == "resting_hr":
        result.update(delta=_round(value - baseline))
    else:
        deviation = value - baseline
        result.update(deviation=_round(deviation), debt=_round(max(-deviation, 0.0)))
    return result


def build_personal_physiology_features(
    *,
    local_date: date,
    observation: dict[str, Any],
    history: list[dict[str, Any]],
    timezone: str | None = None,
) -> dict[str, Any]:
    """Build one deterministic feature row from target-day raw data and past days.

    ``history`` must already be restricted to the preceding configured calendar
    window; the function never accepts a target-date value as baseline evidence.
    """
    earliest_history_date = local_date - timedelta(days=BASELINE_WINDOW_DAYS)
    if any(
        item["local_date"] >= local_date
        or item["local_date"] < earliest_history_date
        for item in history
    ):
        raise ValueError("history must be inside the preceding baseline window")
    features = {
        signal: _signal_feature(
            value=observation[_SIGNAL_FIELDS[signal]],
            history=[
                float(item[_SIGNAL_FIELDS[signal]])
                for item in history
                if item[_SIGNAL_FIELDS[signal]] is not None
            ],
            signal=signal,
        )
        for signal in _SIGNALS
    }
    return {
        "user_id": observation["user_id"],
        "local_date": local_date,
        "source_observation_id": observation["id"],
        "source_revision": observation["revision"],
        "observed_at": observation["observed_at"],
        "source_updated_at": observation["updated_at"],
        "source_staleness": _source_staleness(
            observed_at=observation["observed_at"],
            local_date=local_date,
            timezone=timezone or settings.whatte_timezone,
        ),
        "feature_version": PERSONAL_PHYSIOLOGY_FEATURE_VERSION,
        "baseline_window_days": BASELINE_WINDOW_DAYS,
        "baseline_min_observations": BASELINE_MIN_OBSERVATIONS,
        **features,
    }


def recompute_personal_physiology_features_for_date(
    *, user_id: str, local_date: date
) -> dict[str, Any] | None:
    """Upsert one feature row using only prior manual-observation calendar days."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id, user_id, local_date, sleep_duration_minutes, hrv_ms,
                       resting_hr_bpm, observed_at, revision, updated_at
                from manual_physiology_observation
                where user_id = %s and local_date = %s;
                """,
                (user_id, local_date),
            )
            row = cur.fetchone()
            if row is None:
                return None
            keys = (
                "id", "user_id", "local_date", "sleep_duration_minutes",
                "hrv_ms", "resting_hr_bpm", "observed_at", "revision",
                "updated_at",
            )
            observation = dict(zip(keys, row))
            cur.execute(
                """
                select local_date, sleep_duration_minutes, hrv_ms, resting_hr_bpm
                from manual_physiology_observation
                where user_id = %s
                  and local_date < %s
                  and local_date >= (%s - %s)
                order by local_date;
                """,
                (user_id, local_date, local_date, BASELINE_WINDOW_DAYS),
            )
            history = [
                dict(
                    zip(
                        (
                            "local_date", "sleep_duration_minutes", "hrv_ms",
                            "resting_hr_bpm",
                        ),
                        item,
                    )
                )
                for item in cur.fetchall()
            ]
            result = build_personal_physiology_features(
                local_date=local_date, observation=observation, history=history,
            )
            _upsert_features(cur, result)
            conn.commit()
    return result


def _upsert_features(cur: Any, result: dict[str, Any]) -> None:
    """Persist the full versioned feature contract; no score is computed here."""
    cur.execute(
        """
        insert into personal_physiology_feature_daily (
            user_id, local_date, source_observation_id, source_revision, observed_at,
            source_updated_at, source_staleness, feature_version, baseline_window_days,
            baseline_min_observations, hrv_observation_count, hrv_availability,
            hrv_baseline_state, hrv_baseline_ms, hrv_ratio, hrv_deviation,
            resting_hr_observation_count, resting_hr_availability,
            resting_hr_baseline_state, resting_hr_baseline_bpm, resting_hr_delta_bpm,
            sleep_duration_observation_count, sleep_duration_availability,
            sleep_duration_baseline_state, sleep_duration_baseline_minutes,
            sleep_duration_deviation_minutes, sleep_duration_debt_minutes, computed_at
        ) values (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
        ) on conflict (user_id, local_date, feature_version) do update set
            source_observation_id = excluded.source_observation_id,
            source_revision = excluded.source_revision, observed_at = excluded.observed_at,
            source_updated_at = excluded.source_updated_at,
            source_staleness = excluded.source_staleness,
            baseline_window_days = excluded.baseline_window_days,
            baseline_min_observations = excluded.baseline_min_observations,
            hrv_observation_count = excluded.hrv_observation_count,
            hrv_availability = excluded.hrv_availability,
            hrv_baseline_state = excluded.hrv_baseline_state,
            hrv_baseline_ms = excluded.hrv_baseline_ms, hrv_ratio = excluded.hrv_ratio,
            hrv_deviation = excluded.hrv_deviation,
            resting_hr_observation_count = excluded.resting_hr_observation_count,
            resting_hr_availability = excluded.resting_hr_availability,
            resting_hr_baseline_state = excluded.resting_hr_baseline_state,
            resting_hr_baseline_bpm = excluded.resting_hr_baseline_bpm,
            resting_hr_delta_bpm = excluded.resting_hr_delta_bpm,
            sleep_duration_observation_count = excluded.sleep_duration_observation_count,
            sleep_duration_availability = excluded.sleep_duration_availability,
            sleep_duration_baseline_state = excluded.sleep_duration_baseline_state,
            sleep_duration_baseline_minutes = excluded.sleep_duration_baseline_minutes,
            sleep_duration_deviation_minutes = excluded.sleep_duration_deviation_minutes,
            sleep_duration_debt_minutes = excluded.sleep_duration_debt_minutes,
            computed_at = now();
        """,
        (
            result["user_id"], result["local_date"],
            result["source_observation_id"], result["source_revision"],
            result["observed_at"], result["source_updated_at"],
            result["source_staleness"], result["feature_version"],
            result["baseline_window_days"], result["baseline_min_observations"],
            result["hrv"]["observation_count"], result["hrv"]["availability"],
            result["hrv"]["baseline_state"], result["hrv"]["baseline"],
            result["hrv"].get("ratio"), result["hrv"].get("deviation"),
            result["resting_hr"]["observation_count"],
            result["resting_hr"]["availability"],
            result["resting_hr"]["baseline_state"],
            result["resting_hr"]["baseline"],
            result["resting_hr"].get("delta"),
            result["sleep_duration"]["observation_count"],
            result["sleep_duration"]["availability"],
            result["sleep_duration"]["baseline_state"],
            result["sleep_duration"]["baseline"],
            result["sleep_duration"].get("deviation"),
            result["sleep_duration"].get("debt"),
        ),
    )
