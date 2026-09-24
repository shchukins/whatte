from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from backend.config import settings
from backend.db import get_conn
from backend.services.readiness_composition import READINESS_MODEL_VERSION
from backend.services.readiness_query import (
    get_latest_readiness_daily,
    get_readiness_daily_calendar_history,
)
from backend.services.subjective_feedback_service import (
    FEEDBACK_TYPE_NEXT_DAY_RECOVERY,
    FEEDBACK_TYPE_POST_RIDE_RPE,
)

WHATTE_TZ = ZoneInfo(settings.whatte_timezone)
SIGNAL_FAMILY_ORDER = ("freshness", "feeling", "physiology", "response", "load")
SIGNAL_FAMILY_LABELS = {
    "freshness": "Freshness",
    "feeling": "How you feel",
    "physiology": "Physiology",
    "response": "Training response",
    "load": "Training load",
}
MAX_SECTION_ERROR_LENGTH = 220
HISTORY_DAYS = 14


@dataclass(frozen=True)
class TodayFeedback:
    score: int
    value: str
    updated_at: str


@dataclass(frozen=True)
class TodayActivity:
    activity_id: int
    name: str
    sport_type: str
    start_time: str
    distance: str
    duration: str
    rpe_score: int | None
    rpe_value: str | None


@dataclass(frozen=True)
class TodaySection:
    status: str
    error: str | None


@dataclass(frozen=True)
class TodayHistoryRow:
    date: str
    readiness_score: float | None
    recommendation: str | None
    recovery_score: int | None
    recovery_value: str | None


@dataclass(frozen=True)
class TodayHistoryGroup:
    version: str
    supported: bool
    rows: list[TodayHistoryRow]


@dataclass(frozen=True)
class TodayData:
    user_id: str
    today: str
    readiness: dict[str, Any] | None
    readiness_section: TodaySection
    factors: list[dict[str, Any]]
    recovery: TodayFeedback | None
    recovery_section: TodaySection
    activity: TodayActivity | None
    activity_section: TodaySection
    history_groups: list[TodayHistoryGroup]
    history_section: TodaySection


def _bounded_error(exc: Exception) -> str:
    message = str(exc).strip() or type(exc).__name__
    return message[:MAX_SECTION_ERROR_LENGTH]


def _format_timestamp(value: Any) -> str:
    if not isinstance(value, datetime):
        return "—"
    return value.astimezone(WHATTE_TZ).strftime("%d %b, %H:%M")


def _format_duration(value: int | None) -> str:
    if value is None or value < 0:
        return "—"
    hours, remainder = divmod(value, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _format_distance(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value / 1000:.1f} km"


def get_local_today() -> date:
    return datetime.now(WHATTE_TZ).date()


def _build_factors(readiness: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not readiness:
        return []
    signal_families = readiness.get("signal_families")
    if not isinstance(signal_families, dict):
        return []

    factors: list[dict[str, Any]] = []
    for key in SIGNAL_FAMILY_ORDER:
        raw_family = signal_families.get(key)
        family = raw_family if isinstance(raw_family, dict) else {}
        availability = str(family.get("availability") or "unavailable")
        factors.append(
            {
                "key": key,
                "label": SIGNAL_FAMILY_LABELS[key],
                "availability": availability,
                "used": bool(family.get("used")),
                "score": family.get("score"),
                "contribution": family.get("contribution"),
                "reason_codes": family.get("reason_codes") or [],
            }
        )
    return factors


def _get_today_recovery(user_id: str, target_date: date) -> TodayFeedback | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select feedback_score, feedback_value, updated_at
                from activity_subjective_feedback
                where user_id = %s
                  and activity_date = %s
                  and feedback_type = %s
                  and strava_activity_id is null
                limit 1;
                """,
                (user_id, target_date.isoformat(), FEEDBACK_TYPE_NEXT_DAY_RECOVERY),
            )
            row = cur.fetchone()

    if row is None:
        return None
    return TodayFeedback(
        score=int(row[0]),
        value=str(row[1]),
        updated_at=_format_timestamp(row[2]),
    )


def _get_recovery_history(
    user_id: str, start_date: date, end_date: date
) -> dict[date, tuple[int, str]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select activity_date, feedback_score, feedback_value
                from activity_subjective_feedback
                where user_id = %s
                  and activity_date >= %s
                  and activity_date <= %s
                  and feedback_type = %s
                  and strava_activity_id is null;
                """,
                (user_id, start_date, end_date, FEEDBACK_TYPE_NEXT_DAY_RECOVERY),
            )
            rows = cur.fetchall()
    return {row_date: (int(score), str(value)) for row_date, score, value in rows}


def get_today_history(user_id: str, target_date: date) -> list[TodayHistoryGroup]:
    start_date = target_date - timedelta(days=HISTORY_DAYS - 1)
    points = get_readiness_daily_calendar_history(user_id, start_date, target_date)
    feedback = _get_recovery_history(user_id, start_date, target_date)
    by_version = {
        (point["version"], point["date"]): point for point in points
    }
    versions = [READINESS_MODEL_VERSION, *sorted({
        point["version"] for point in points
        if point["version"] != READINESS_MODEL_VERSION
    })]
    days = [target_date - timedelta(days=offset) for offset in range(HISTORY_DAYS)]
    groups = []
    for version in versions:
        rows = []
        for day in days:
            point = by_version.get((version, day))
            recovery = feedback.get(day)
            rows.append(TodayHistoryRow(
                date=day.isoformat(),
                readiness_score=point["readiness_score"] if point else None,
                recommendation=point["recommendation"] if point else None,
                recovery_score=recovery[0] if recovery else None,
                recovery_value=recovery[1] if recovery else None,
            ))
        groups.append(TodayHistoryGroup(
            version=version,
            supported=version == READINESS_MODEL_VERSION,
            rows=rows,
        ))
    return groups


def _activity_where(preferred_activity_id: int | None) -> tuple[str, tuple[Any, ...]]:
    if preferred_activity_id is None:
        return "", ()
    return " and r.strava_activity_id = %s", (preferred_activity_id,)


def get_today_activity(
    user_id: str,
    *,
    preferred_activity_id: int | None = None,
) -> TodayActivity | None:
    preferred_filter, preferred_params = _activity_where(preferred_activity_id)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                select
                    r.strava_activity_id,
                    coalesce(nullif(trim(r.name), ''), 'Activity'),
                    coalesce(nullif(trim(r.activity_type), ''), 'Workout'),
                    r.start_date,
                    r.distance_m,
                    coalesce(r.moving_time_s, r.elapsed_time_s),
                    f.feedback_score,
                    f.feedback_value
                from strava_activity_raw r
                left join activity_subjective_feedback f
                  on (
                       f.canonical_activity_id = r.strava_activity_id
                       or (
                           f.canonical_activity_id is null
                           and f.strava_activity_id = r.strava_activity_id
                       )
                  )
                 and f.feedback_type = %s
                where r.user_id = %s
                  and r.is_deleted = false
                  and r.is_excluded = false
                  and r.duplicate_of_activity_id is null
                  {preferred_filter}
                order by
                    r.start_date desc nulls last,
                    r.strava_activity_id desc
                limit 1;
                """,
                (FEEDBACK_TYPE_POST_RIDE_RPE, user_id, *preferred_params),
            )
            row = cur.fetchone()

    if row is None:
        return None
    return TodayActivity(
        activity_id=int(row[0]),
        name=str(row[1]),
        sport_type=str(row[2]),
        start_time=_format_timestamp(row[3]),
        distance=_format_distance(row[4]),
        duration=_format_duration(row[5]),
        rpe_score=int(row[6]) if row[6] is not None else None,
        rpe_value=str(row[7]) if row[7] is not None else None,
    )


def get_today_data(
    user_id: str,
    *,
    preferred_activity_id: int | None = None,
    now: datetime | None = None,
) -> TodayData:
    evaluation_at = now or datetime.now(WHATTE_TZ)
    target_date = evaluation_at.astimezone(WHATTE_TZ).date()

    readiness: dict[str, Any] | None = None
    readiness_section = TodaySection(status="ok", error=None)
    try:
        readiness = get_latest_readiness_daily(user_id, evaluation_at=evaluation_at)
    except HTTPException as exc:
        if exc.status_code == 404:
            readiness_section = TodaySection(status="missing", error=None)
        else:
            readiness_section = TodaySection(status="error", error=_bounded_error(exc))
    except Exception as exc:
        readiness_section = TodaySection(status="error", error=_bounded_error(exc))

    recovery: TodayFeedback | None = None
    recovery_section = TodaySection(status="ok", error=None)
    try:
        recovery = _get_today_recovery(user_id, target_date)
    except Exception as exc:
        recovery_section = TodaySection(status="error", error=_bounded_error(exc))

    activity: TodayActivity | None = None
    activity_section = TodaySection(status="ok", error=None)
    try:
        activity = get_today_activity(
            user_id,
            preferred_activity_id=preferred_activity_id,
        )
    except Exception as exc:
        activity_section = TodaySection(status="error", error=_bounded_error(exc))

    history_groups: list[TodayHistoryGroup] = []
    history_section = TodaySection(status="ok", error=None)
    try:
        history_groups = get_today_history(user_id, target_date)
    except Exception as exc:
        history_section = TodaySection(status="error", error=_bounded_error(exc))

    return TodayData(
        user_id=user_id,
        today=target_date.isoformat(),
        readiness=readiness,
        readiness_section=readiness_section,
        factors=_build_factors(readiness),
        recovery=recovery,
        recovery_section=recovery_section,
        activity=activity,
        activity_section=activity_section,
        history_groups=history_groups,
        history_section=history_section,
    )
