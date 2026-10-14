from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from backend.db import get_conn
from backend.services.activity_load_service import ActivityLoadAssessment, assess_stored_activity_load
from backend.today.service import (
    HISTORY_DAYS,
    WHATTE_TZ,
    TodayHistoryGroup,
    TodaySection,
    _bounded_error,
    activity_load_status,
    get_today_history,
    get_profile_pending,
)

DIARY_SUMMARY_DAYS = 7
LOAD_EXCLUSION_LABELS = {
    "unsupported_sport": "Вид спорта пока не поддерживается",
    "missing_required_power_metrics": "Нет необходимых данных мощности",
}


@dataclass(frozen=True)
class DiaryLoadExclusion:
    reason: str
    label: str
    count: int


@dataclass(frozen=True)
class DiarySummary:
    start_date: str
    end_date: str
    activity_count: int
    known_duration_s: int
    missing_duration_count: int
    rpe_count: int
    load_included_count: int | None
    load_unknown_count: int
    load_exclusions: tuple[DiaryLoadExclusion, ...]


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
    load_status: str = "Статус недоступен"
    load_assessment: ActivityLoadAssessment | None = None


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
    profile_pending: dict[str, date] | None = None
    profile_pending_section: TodaySection = TodaySection(status="ok", error=None)

    @property
    def summary_start_date(self) -> str:
        return (date.fromisoformat(self.target_date) - timedelta(days=DIARY_SUMMARY_DAYS - 1)).isoformat()

    @property
    def summary(self) -> DiarySummary | None:
        """Aggregate the unfiltered read over seven local dates, not elapsed hours.

        A failed activity read is unavailable; known zero durations and effective
        RPE zero remain recorded values. No observations resolve RPE here.
        """
        if self.activity_section.status != "ok":
            return None
        days = [day for day in self.days
                if self.summary_start_date <= day.date <= self.target_date]
        if any(day.activities is None for day in days):
            return None
        activities = [
            activity for day in days
            for activity in day.activities or []
        ]
        # Only typed backend assessments count; display labels are not evidence.
        unknown = sum(a.load_assessment is None or a.load_assessment.included is None
                      for a in activities)
        included = sum(a.load_assessment is not None and a.load_assessment.included is True
                       for a in activities)
        exclusions = tuple(
            DiaryLoadExclusion(reason, label, count)
            for reason, label in LOAD_EXCLUSION_LABELS.items()
            if (count := sum(a.load_assessment is not None
                             and a.load_assessment.included is False
                             and a.load_assessment.reason == reason for a in activities))
        )
        return DiarySummary(
            start_date=self.summary_start_date,
            end_date=self.target_date,
            activity_count=len(activities),
            known_duration_s=sum(a.duration_s for a in activities if a.duration_s is not None),
            missing_duration_count=sum(a.duration_s is None for a in activities),
            rpe_count=sum(a.rpe_score is not None for a in activities),
            load_included_count=None if activities and unknown == len(activities) else included,
            load_unknown_count=unknown,
            load_exclusions=exclusions,
        )


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
                    wr.score, sr.score, tr.score,
                    m.tss, m.normalized_power, m.intensity_factor, m.id is not null
                from strava_activity_raw r
                left join activity_metrics m
                  on m.strava_activity_id = r.strava_activity_id
                  and m.user_id = r.user_id and m.version = 'v1'
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
            load_assessment=assess_stored_activity_load(
                has_metrics=has_metrics, activity_type=sport_type, tss=tss,
                normalized_power=normalized_power, intensity_factor=intensity_factor,
            ),
            load_status=activity_load_status(sport_type, tss, normalized_power, intensity_factor),
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
            tss, normalized_power, intensity_factor, has_metrics,
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

    profile_pending, profile_pending_section = get_profile_pending(user_id)

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
        profile_pending=profile_pending,
        profile_pending_section=profile_pending_section,
    )
