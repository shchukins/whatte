"""Persist explicit training choices and correspondence; never infer completion."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from backend.db import get_conn
from backend.services import training_context_service as store
from backend.services.training_decision_policy import TrainingDecisionContext, TrainingOption, choose_training_action


def lock_user(cur, user_id: str) -> None:
    # Serialize plan edits, consent and links, including an athlete's first write.
    cur.execute("select pg_advisory_xact_lock(hashtextextended(%s, 93))", (user_id,))


def evidence(result: dict) -> dict:
    context = result['context']
    return dict(revision=result['saved_context'].revision,
                rule_version=result['decision'].rule_version if result['decision'] else None,
                context=context.model_dump(mode='json') if context else None)


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_decisions(cur, user_id: str, today: date, edit: store.TrainingContextEdit, activities: list[dict]) -> list[dict]:
    cur.execute("""select d.id, d.target_session_id, d.input_json, d.decision_json,
                          d.proposed_at, c.choice, c.chosen_at, coalesce(c.applied_revision, d.context_revision)
                   from training_decision d left join training_decision_choice c on c.decision_id = d.id
                   where d.user_id = %s and d.decision_day = %s order by d.presented_at desc, d.id desc""", (user_id, today))
    rows = [dict(id=id, target_session_id=target, input_json=inputs, decision_json=decision,
                 proposed_at=at, choice=choice, chosen_at=chosen_at,
                 status=choice or ('proposed' if rev == edit.revision else 'stale'),
                 stale=rev != edit.revision)
            for id, target, inputs, decision, at, choice, chosen_at, rev in cur.fetchall()]
    seen = set()
    for row in rows:
        if not row['choice'] and not row['stale']:
            context = TrainingDecisionContext.model_validate(row['input_json']['context'])
            result = store.assemble_policy_context(edit, activities, today=today,
                today_session_id=context.today_session_id if any(
                    s.id == context.today_session_id and s.day == today for s in edit.plan.sessions or ()) else None,
                constraints=context.constraints,
                reviewed_window_ids=tuple(w.id for w in context.future_windows or () if w.compatible_session_ids),
                physiology_available=context.physiology_available)
            row['stale'] = row['stale'] or evidence(result) != row['input_json']
        if not row['choice']:
            if row['target_session_id'] in seen:
                row['status'] = 'superseded'
                row['stale'] = True
            elif row['stale']:
                row['status'] = 'stale'
        seen.add(row['target_session_id'])
    return rows


def propose(user_id: str, result: dict) -> int | None:
    """Explicit preview POST saves one immutable snapshot per exact policy input."""
    decision = result['decision']
    if not decision or not decision.recommendation or any(
            a.get('local_date') == result['today'] for a in result['activities']):
        return None
    inputs = evidence(result)
    context = result['context']
    with get_conn() as conn, conn.cursor() as cur:
        lock_user(cur, user_id)
        edit = store._read(cur, user_id, store.week_start(result['today']))
        if store.local_today() != result['today'] or edit.revision != inputs['revision']:
            raise HTTPException(409, 'Контекст изменился. Получите новое предложение.')
        cur.execute("""insert into training_decision
            (user_id, decision_day, week_start, target_session_id, context_revision,
             input_json, decision_json, content_fingerprint)
            values (%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict (user_id, decision_day, content_fingerprint) do update
            set presented_at = now() returning id""",
            (user_id, result['today'], edit.plan.week_start, context.today_session_id,
             edit.revision, Jsonb(inputs), Jsonb(decision.model_dump(mode='json')), fingerprint(inputs)))
        return cur.fetchone()[0]


def apply_option(edit: store.TrainingContextEdit, context: TrainingDecisionContext, option: TrainingOption) -> store.WeekPlan:
    """Keep assignment identity when accepting a shortening, replacement or move."""
    target = context.today_session_id
    sessions = []
    for s in edit.plan.sessions or ():
        patch = {}
        if option.action == 'SHORTEN' and s.id == target:
            patch = dict(duration_minutes=option.duration_minutes, session_type=option.session_type,
                         minimum_shortened_minutes=None)
        elif option.action == 'RESCHEDULE' and s.id == target:
            patch = dict(day=date.fromisoformat(option.window_id))
        elif option.action == 'SUBSTITUTE':
            if s.id == target:
                patch = dict(day=None)
            elif s.id == option.session_id:
                patch = dict(day=context.today)
        sessions.append({**s.model_dump(), **patch})
    return store.WeekPlan.model_validate({**edit.plan.model_dump(), 'sessions': sessions})


def choose(user_id: str, decision_id: int, choice: str) -> None:
    if choice not in ('accepted', 'declined'):
        raise HTTPException(422, 'Неизвестный ответ')
    stale = False
    with get_conn() as conn, conn.cursor() as cur:
        lock_user(cur, user_id)
        cur.execute("""select decision_day, input_json, decision_json from training_decision
                       where id = %s and user_id = %s""", (decision_id, user_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, 'Предложение не найдено')
        day, inputs, saved = row
        cur.execute('select choice from training_decision_choice where decision_id = %s', (decision_id,))
        previous = cur.fetchone()
        if previous:
            if previous[0] != choice:
                raise HTTPException(409, 'Ответ уже сохранён. Получите новое предложение.')
            return  # Idempotent retry never reapplies a move or replacement.
        edit = store._read(cur, user_id, store.week_start(day))
        context = TrainingDecisionContext.model_validate(inputs['context'])
        if day != store.local_today() or edit.revision != inputs['revision']:
            raise HTTPException(409, 'Предложение устарело. Обновите Сегодня и проверьте план.')
        activities = store._activities(cur, user_id, day, ZoneInfo(store.settings.whatte_timezone))
        current = store.assemble_policy_context(edit, activities, today=day,
            today_session_id=context.today_session_id, constraints=context.constraints,
            reviewed_window_ids=tuple(w.id for w in context.future_windows or () if w.compatible_session_ids),
            physiology_available=context.physiology_available)
        cur.execute('''select 1 from training_decision where user_id = %s and decision_day = %s
                       and target_session_id = %s and (presented_at, id) >
                           (select presented_at, id from training_decision where id = %s) limit 1''',
                    (user_id, day, context.today_session_id, decision_id))
        superseded = cur.fetchone() is not None
        stale = (superseded or day != store.local_today() or evidence(current) != inputs
                 or any(a['local_date'] == day for a in activities))
        if not stale:
            # Reconstruct the exact backend-owned option; client sends no workout fields.
            decision = choose_training_action(context)
            if decision.model_dump(mode='json') != saved:
                stale = True
            else:
                revision = edit.revision
                if choice == 'accepted':
                    plan = apply_option(edit, context, decision.recommendation)
                    cur.execute('update training_week_plan set plan = %s where user_id = %s and week_start = %s',
                                (Jsonb(plan.model_dump(mode='json')), user_id, plan.week_start))
                    cur.execute('update user_training_context set revision = revision + 1 where user_id = %s returning revision',
                                (user_id,))
                    revision = cur.fetchone()[0]
                cur.execute('''insert into training_decision_choice (decision_id, choice, applied_revision)
                               values (%s,%s,%s)''', (decision_id, choice, revision))
    if stale:
        raise HTTPException(409, 'Предложение устарело. Обновите Сегодня и проверьте план.')


def confirm_activity(user_id: str, *, today: date, revision: int, activity_id: int,
                     session_id: str, correspondence: str) -> None:
    if correspondence not in ('fulfilled', 'different'):
        raise HTTPException(422, 'Укажите соответствие занятию')
    with get_conn() as conn, conn.cursor() as cur:
        lock_user(cur, user_id)
        # Lock canonical identity against a concurrent deduplication/metadata change.
        cur.execute('''select start_date from strava_activity_raw where user_id = %s
                       and strava_activity_id = %s and not is_deleted and not is_excluded
                       and duplicate_of_activity_id is null and start_date is not null for update''', (user_id, activity_id))
        raw = cur.fetchone()
        if not raw:
            raise HTTPException(409, 'Активность недоступна или её идентичность изменилась')
        cur.execute('''select week_start, session_id, correspondence from training_session_activity
                       where user_id = %s and canonical_activity_id = %s''', (user_id, activity_id))
        previous = cur.fetchone()
        monday = store.week_start(today)
        if previous:
            if previous == (monday, session_id, correspondence):
                return
            raise HTTPException(409, 'Активность уже связана с другим назначением или ответом')
        edit = store._read(cur, user_id, monday)
        local_day = raw[0].astimezone(ZoneInfo(store.settings.whatte_timezone)).date()
        session = next((s for s in edit.plan.sessions or () if s.id == session_id), None)
        if (today != store.local_today() or revision != edit.revision or not session
                or session.day is None or session.day > today
                or not monday <= local_day <= today):
            raise HTTPException(409, 'План или дата изменились. Обновите Сегодня.')
        cur.execute('''select 1 from training_session_activity where user_id = %s and week_start = %s
                       and session_id = %s and correspondence = 'fulfilled' ''', (user_id, monday, session_id))
        if cur.fetchone():
            raise HTTPException(409, 'Выполнение этого назначения уже подтверждено')
        # Association records the choice actually applied to this assignment, if any.
        cur.execute('''select d.id from training_decision d join training_decision_choice c on c.decision_id = d.id
                       where d.user_id = %s and d.week_start = %s and c.choice = 'accepted'
                       and d.decision_json->'recommendation'->>'session_id' = %s
                       and d.decision_json->'recommendation'->>'session_type' = %s
                       and (d.decision_json->'recommendation'->>'duration_minutes')::int = %s
                       and case when d.decision_json->'recommendation'->>'action' = 'RESCHEDULE'
                           then (d.decision_json->'recommendation'->>'window_id')::date
                           else d.decision_day end = %s
                       order by c.chosen_at desc, d.id desc limit 1''', (user_id, monday, session_id, session.session_type, session.duration_minutes, session.day))
        accepted = cur.fetchone()
        cur.execute('''insert into training_session_activity
                       (user_id, week_start, session_id, canonical_activity_id, decision_id, correspondence)
                       values (%s,%s,%s,%s,%s,%s)''',
                    (user_id, monday, session_id, activity_id, accepted[0] if accepted else None, correspondence))
        cur.execute('update user_training_context set revision = revision + 1 where user_id = %s', (user_id,))
