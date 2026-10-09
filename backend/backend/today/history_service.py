from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from backend.db import get_conn
from backend.today.service import (
    HISTORY_DAYS,
    WHATTE_TZ,
    TodayHistoryGroup,
    TodaySection,
    _bounded_error,
    get_today_history,
)


@dataclass(frozen=True)
class DiaryActivity:
    activity_id: int
    name: str
    sport_type: str
    start_time: datetime
    duration_s: int | None
    rpe_score: int | None
    rpe_source: str | None
    rpe_web_score: int | None
    rpe_strava_score: int | None
    rpe_telegram_score: int | None
    rpe_disagreement: bool


@dataclass(frozen=True)
class DiaryDay:
    date: str
    # None means the activity read failed; [] is a successful empty day.
    activities: list[DiaryActivity] | None

    @property
    def activity_message(self) -> str | None:
        if self.activities is None:
            return "Не удалось загрузить тренировки"
        if not self.activities:
            return "Нет записанных тренировок"
        return None


@dataclass(frozen=True)
class DiaryData:
    user_id: str
    target_date: str
    days: list[DiaryDay]
    activity_section: TodaySection
    history_groups: list[TodayHistoryGroup]
    history_section: TodaySection


def get_diary_activities(user_id: str, target_date: date) -> list[DiaryActivity]:
    """Read eligible workouts and persisted RPE resolution in one bounded query."""
    start_date = target_date - timedelta(days=HISTORY_DAYS - 1)
    # Construct both local midnights independently: a DST window need not be
    # 14 * 24 elapsed hours. PostgreSQL compares these aware bounds to start_date.
    start_at = datetime.combine(start_date, time.min, tzinfo=WHATTE_TZ)
    end_at = datetime.combine(target_date + timedelta(days=1), time.min, tzinfo=WHATTE_TZ)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    r.strava_activity_id,
                    coalesce(nullif(trim(r.name), ''), 'Activity'),
                    coalesce(nullif(trim(r.activity_type), ''), 'Workout'),
                    r.start_date,
                    coalesce(r.moving_time_s, r.elapsed_time_s),
                    er.effective_score, er.effective_source, er.disagreement,
                    wr.score, sr.score, tr.score
                from strava_activity_raw r
                left join activity_rpe_resolution er
                  on er.canonical_activity_id = r.strava_activity_id
                  and er.user_id = r.user_id
                left join activity_rpe_observation wr
                  on wr.canonical_activity_id = r.strava_activity_id
                  and wr.user_id = r.user_id and wr.source = 'web'
                left join activity_rpe_observation sr
                  on sr.canonical_activity_id = r.strava_activity_id
                  and sr.user_id = r.user_id and sr.source = 'strava'
                left join activity_rpe_observation tr
                  on tr.canonical_activity_id = r.strava_activity_id
                  and tr.user_id = r.user_id and tr.source = 'telegram'
                where r.user_id = %s
                  and r.is_deleted = false
                  and r.is_excluded = false
                  and r.duplicate_of_activity_id is null
                  and r.start_date >= %s
                  and r.start_date < %s
                order by r.start_date desc, r.strava_activity_id desc;
                """,
                (user_id, start_at, end_at),
            )
            rows = cur.fetchall()

    return [
        DiaryActivity(
            activity_id=activity_id,
            name=name,
            sport_type=sport_type,
            start_time=start_at.astimezone(WHATTE_TZ),
            duration_s=duration,
            rpe_score=score,
            rpe_source=source,
            rpe_web_score=web_score,
            rpe_strava_score=strava_score,
            rpe_telegram_score=telegram_score,
            rpe_disagreement=bool(disagreement),
        )
        for (
            activity_id, name, sport_type, start_at, duration, score, source,
            disagreement, web_score, strava_score, telegram_score,
        ) in rows
    ]


def get_diary_data(user_id: str, target_date: date) -> DiaryData:
    """Build 14 newest-first local days without writes or model recomputation.

    Readiness/recovery reuse Today's version-separated calendar contract.
    Activity failure does not discard that history, and vice versa.
    """
    dates = [target_date - timedelta(days=offset) for offset in range(HISTORY_DAYS)]
    by_day: dict[date, list[DiaryActivity]] = {day: [] for day in dates}
    activity_section = TodaySection(status="ok", error=None)
    try:
        for activity in get_diary_activities(user_id, target_date):
            by_day[activity.start_time.date()].append(activity)
    except Exception as exc:
        activity_section = TodaySection(status="error", error=_bounded_error(exc))

    history_groups: list[TodayHistoryGroup] = []
    history_section = TodaySection(status="ok", error=None)
    try:
        history_groups = get_today_history(user_id, target_date)
    except Exception as exc:
        history_section = TodaySection(status="error", error=_bounded_error(exc))

    return DiaryData(
        user_id=user_id,
        target_date=target_date.isoformat(),
        days=[DiaryDay(
            date=day.isoformat(),
            activities=by_day[day] if activity_section.status == "ok" else None,
        ) for day in dates],
        activity_section=activity_section,
        history_groups=history_groups,
        history_section=history_section,
    )
