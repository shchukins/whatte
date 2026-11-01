"""Manual weekly inputs and a read-only adapter to the existing pure policy."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from pydantic import Field, model_validator

from backend.config import settings
from backend.db import get_conn
from backend.services.activity_load_service import assess_stored_activity_load
from backend.services.physiology_signal import load_physiology_signal
from backend.services.training_decision_policy import (
    ActionConstraints, CompletedSession, FutureWindow, PlannedSession, PolicyInput,
    SessionType, TrainingDecisionContext, choose_training_action,
)


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def local_today(now: datetime | None = None) -> date:
    zone = ZoneInfo(settings.whatte_timezone)
    current = now or datetime.now(zone)
    if current.tzinfo is None:
        raise ValueError("now must include timezone")
    return current.astimezone(zone).date()


class SavedSession(PlannedSession):
    # Undated work is stored, but cannot be allocated by the dated policy yet.
    day: date | None = None


class DailyWindow(PolicyInput):
    day: date
    duration_minutes: int | None = Field(default=None, ge=0, strict=True)
    confirmed: bool = False

    @model_validator(mode="after")
    def confirmed_capacity(self):
        if self.confirmed and self.duration_minutes is None:
            raise ValueError("Confirmed window requires duration (zero means unavailable)")
        return self


class WeekPlan(PolicyInput):
    week_start: date
    sessions: tuple[SavedSession, ...] | None = None
    windows: tuple[DailyWindow, ...] = ()

    @model_validator(mode="after")
    def validate_week(self):
        if self.week_start.weekday() != 0:
            raise ValueError("Week starts on Monday")
        sessions = self.sessions or ()
        if len({s.id for s in sessions}) != len(sessions):
            raise ValueError("Session IDs must be unique")
        if len({w.day for w in self.windows}) != len(self.windows):
            raise ValueError("One total training window per day")
        if any(week_start(day) != self.week_start for day in (
            *(s.day for s in sessions if s.day is not None), *(w.day for w in self.windows),
        )):
            raise ValueError("Dates must belong to the selected week")
        return self


class TrainingContextEdit(PolicyInput):
    block_priority: SessionType | None = None
    plan: WeekPlan
    revision: int = Field(default=0, ge=0, strict=True)


def _read(cur, user_id: str, monday: date) -> TrainingContextEdit:
    cur.execute("select block_priority, revision from user_training_context where user_id = %s", (user_id,))
    goal = cur.fetchone()
    cur.execute("select plan from training_week_plan where user_id = %s and week_start = %s", (user_id, monday))
    row = cur.fetchone()
    return TrainingContextEdit(
        block_priority=goal[0] if goal else None, revision=goal[1] if goal else 0,
        plan=WeekPlan.model_validate(row[0]) if row else WeekPlan(week_start=monday),
    )


def get_training_context(user_id: str, today: date) -> TrainingContextEdit:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("set transaction isolation level repeatable read read only")
        return _read(cur, user_id, week_start(today))


def save_training_context(user_id: str, edit: TrainingContextEdit, *, today: date) -> None:
    if edit.plan.week_start != week_start(today):
        raise HTTPException(409, "Неделя изменилась. Обновите страницу перед сохранением.")
    with get_conn() as conn, conn.cursor() as cur:
        from backend.services.training_decision_loop import lock_user
        lock_user(cur, user_id)
        before = _read(cur, user_id, edit.plan.week_start)
        cur.execute("""select session_id from training_session_activity
                       where user_id = %s and week_start = %s and correspondence = 'fulfilled'""",
                    (user_id, edit.plan.week_start))
        completed = {row[0] for row in cur.fetchall()}
        old = {s.id: s for s in before.plan.sessions or ()}
        new = {s.id: s for s in edit.plan.sessions or ()}
        if any(old.get(id) != new.get(id) for id in completed):
            raise HTTPException(409, 'Выполненное назначение нельзя заменить или удалить. Добавьте новое занятие с новым ID.')
        # Conditional revision protects both the persistent block goal and weekly
        # document from stale tabs. The whole save rolls back on any conflict.
        cur.execute("""insert into user_training_context (user_id, block_priority, revision)
                       values (%s, %s, 1) on conflict (user_id) do update
                       set block_priority = excluded.block_priority, revision = user_training_context.revision + 1
                       where user_training_context.revision = %s
                       returning revision""", (user_id, edit.block_priority, edit.revision))
        if cur.fetchone() != (edit.revision + 1,):
            raise HTTPException(409, "Контекст уже изменён. Обновите страницу; сохраните свой ввод отдельно.")
        cur.execute("""insert into training_week_plan (user_id, week_start, plan) values (%s, %s, %s)
                       on conflict (user_id, week_start) do update set plan = excluded.plan""",
                    (user_id, edit.plan.week_start, Jsonb(edit.plan.model_dump(mode="json"))))


def _activities(cur, user_id: str, today: date, zone: ZoneInfo) -> list[dict]:
    # Independent local midnights handle DST and ISO-year boundaries. This is
    # week-to-date, never a rolling seven-day load sum. Missing metrics survive.
    start = datetime.combine(week_start(today), time.min, zone)
    end = datetime.combine(today + timedelta(days=1), time.min, zone)
    cur.execute("""select r.strava_activity_id, r.start_date, r.activity_type,
                          coalesce(r.moving_time_s, r.elapsed_time_s),
                          m.id is not null, m.tss, m.normalized_power, m.intensity_factor,
                          er.effective_score, er.effective_source, er.disagreement
                   from strava_activity_raw r
                   left join activity_metrics m on m.strava_activity_id = r.strava_activity_id
                     and m.user_id = r.user_id and m.version = 'v1'
                   left join activity_rpe_resolution er on er.canonical_activity_id = r.strava_activity_id
                     and er.user_id = r.user_id
                   where r.user_id = %s and not r.is_deleted and not r.is_excluded
                     and r.duplicate_of_activity_id is null and r.start_date >= %s and r.start_date < %s
                   order by r.start_date, r.strava_activity_id""", (user_id, start, end))
    activities = [dict(activity_id=str(id), local_date=started.astimezone(zone).date(),
                 activity_type=sport, duration_s=duration, tss=tss,
                 normalized_power=np, intensity_factor=ifactor,
                 load=assess_stored_activity_load(has_metrics=has_metrics, activity_type=sport,
                     tss=tss, normalized_power=np, intensity_factor=ifactor),
                 rpe=score, rpe_source=source, rpe_disagreement=bool(disagreement))
            for id, started, sport, duration, has_metrics, tss, np, ifactor, score, source, disagreement
            in cur.fetchall()]
    cur.execute("""select canonical_activity_id, session_id, correspondence, decision_id
                   from training_session_activity where user_id = %s and week_start = %s""",
                (user_id, week_start(today)))
    links = {str(id): dict(session_id=session, correspondence=match, decision_id=decision)
             for id, session, match, decision in cur.fetchall()}
    for activity in activities:
        activity['plan_link'] = links.get(activity['activity_id'])
    return activities


def assemble_policy_context(edit: TrainingContextEdit, activities: list[dict], *, today: date,
                            today_session_id: str | None = None,
                            constraints: ActionConstraints | None = None,
                            physiology_available: bool = False,
                            reviewed_window_ids: tuple[str, ...] = ()) -> dict:
    """No invented capacity, completion matching or permissions from readiness.

    V1 requires numeric today's capacity: until confirmed, return context=None
    and explicit missingness rather than fabricate zero. Undated work remains in
    saved_context; the policy only receives the dated subset with a disclosure.
    """
    missing = []
    if (constraints or ActionConstraints()).training_allowed is None:
        missing.append("training_permission_unknown")
    if edit.block_priority is None:
        missing.append("block_priority_unknown")
    if edit.plan.sessions is None:
        missing.append("week_plan_unknown")
    for s in edit.plan.sessions or ():
        if s.day is None:
            missing.append(f"session_day_unknown:{s.id}")
    windows = {w.day: w for w in edit.plan.windows}
    current = windows.get(today)
    if current is None or not current.confirmed:
        missing.append("today_available_minutes_unconfirmed")
    for offset in range(1, 7 - today.weekday()):
        day = today + timedelta(days=offset)
        if day not in windows or not windows[day].confirmed:
            missing.append(f"future_window_unknown:{day}")
    dated = tuple(PlannedSession.model_validate(s.model_dump()) for s in edit.plan.sessions or () if s.day)
    targets = [s.id for s in dated if s.day == today]
    if today_session_id is None and len(targets) == 1:
        today_session_id = targets[0]
    if today_session_id is None:
        missing.append("today_session_unknown_or_ambiguous")
    future_confirmed = [w for w in edit.plan.windows if w.day > today and w.confirmed]
    future_windows = tuple(FutureWindow(id=w.day.isoformat(), day=w.day,
        duration_minutes=w.duration_minutes, confirmed=True,
        compatible_session_ids=(today_session_id,) if w.day.isoformat() in reviewed_window_ids and today_session_id else None)
        for w in future_confirmed if w.duration_minutes > 0)
    if not future_confirmed and today.weekday() < 6:
        future_windows = None
    confirmed = {a['plan_link']['session_id']: a['activity_id'] for a in activities
                 if a.get('plan_link') and a['plan_link']['correspondence'] == 'fulfilled'
                 and any(s.id == a['plan_link']['session_id'] and s.day <= today for s in dated)}
    context = None
    decision = None
    if current is not None and current.confirmed:
        context = TrainingDecisionContext(
            today=today, block_priority=edit.block_priority, today_session_id=today_session_id,
            week_plan=None if edit.plan.sessions is None else dated,
            completed=tuple(CompletedSession(activity_id=a["activity_id"], load=a["load"],
                confirmed_plan_session_id=(a['plan_link']['session_id']
                    if a.get('plan_link') and a['plan_link']['session_id'] in confirmed
                    and a['plan_link']['correspondence'] == 'fulfilled'
                    else None)) for a in activities),
            available_minutes=current.duration_minutes,
            future_windows=future_windows,
            constraints=constraints or ActionConstraints(), physiology_available=physiology_available,
        )
        decision = choose_training_action(context)
        missing.extend(decision.missing_context)
    return dict(today=today, saved_context=edit, activities=activities, context=context, decision=decision,
                session_statuses={s.id: dict(status='fulfilled' if s.id in confirmed else 'pending',
                                            activity_id=confirmed.get(s.id)) for s in edit.plan.sessions or ()},
                missing_context=tuple(dict.fromkeys(missing)),
                history_scope="locally_stored_strava_week_to_date",
                limitations=("strava_sync_completeness_unverified", "plan_completion_not_linked",
                             "future_session_compatibility_unreviewed"))


def get_policy_context(user_id: str, *, now: datetime | None = None,
                       today_session_id: str | None = None,
                       constraints: ActionConstraints | None = None,
                       reviewed_window_ids: tuple[str, ...] = ()) -> dict:
    today = local_today(now)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("set transaction isolation level repeatable read read only")
        edit = _read(cur, user_id, week_start(today))
        activities = _activities(cur, user_id, today, ZoneInfo(settings.whatte_timezone))
        physiology = load_physiology_signal(cur, user_id=user_id, target_date=str(today))
        from backend.services.training_decision_loop import read_decisions
        decisions = read_decisions(cur, user_id, today, edit, activities)
    result = assemble_policy_context(edit, activities, today=today,
        today_session_id=today_session_id, constraints=constraints,
        physiology_available=physiology["availability"] == "available",
        reviewed_window_ids=reviewed_window_ids)
    result['decisions'] = decisions
    # Delivery state is distinct from the pure policy candidate. Recorded work
    # never automatically creates a second training prescription on any consumer.
    recorded_today = any(a['local_date'] == today for a in activities)
    latest = decisions[0] if decisions else None
    result['delivery'] = dict(
        status=('activity_recorded' if recorded_today else
                latest['status'] if latest and not latest['stale'] else
                'stale' if latest else 'preview'),
        decision_id=latest['id'] if latest else None,
        offer_training=not recorded_today and not (latest and latest['choice'] and not latest['stale']))
    return result


def save_today_availability(user_id: str, *, today: date, revision: int,
                            duration_minutes: int | None) -> None:
    """Patch only today's window through the existing atomic revisioned store."""
    if today != local_today():
        raise HTTPException(409, "Наступил новый день. Обновите Сегодня перед сохранением.")
    edit = get_training_context(user_id, today)
    if edit.revision != revision:
        raise HTTPException(409, "Контекст уже изменён. Обновите страницу перед сохранением.")
    existing = next((w for w in edit.plan.windows if w.day == today), None)
    window = DailyWindow(day=today, duration_minutes=duration_minutes,
                         confirmed=duration_minutes is not None)
    windows = tuple(w for w in edit.plan.windows if w.day != today) + (window,)
    plan = WeekPlan.model_validate({**edit.plan.model_dump(), "windows": windows})
    # The read can straddle midnight within the same ISO week; the weekly store
    # alone cannot detect that today's narrow patch has become yesterday's.
    current_day = local_today()
    if today != current_day:
        raise HTTPException(409, "Наступил новый день. Обновите Сегодня перед сохранением.")
    if existing and existing.duration_minutes == duration_minutes and existing.confirmed == (duration_minutes is not None):
        return
    save_training_context(user_id, edit.model_copy(update={"plan": plan}), today=current_day)
