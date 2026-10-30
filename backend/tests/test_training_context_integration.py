"""Real migrated storage and ISO-week queries; only disposable PostgreSQL."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from backend.db import get_conn
from backend.services import training_context_service as service
from backend.services.training_decision_policy import ActionConstraints

pytestmark = pytest.mark.skipif(not os.getenv('RUN_DB_TESTS'), reason='Requires isolated migrated PostgreSQL')
MONDAY = date(2026, 10, 26)


@pytest.fixture
def db(monkeypatch):
    with get_conn() as conn:
        for table in ('user_training_context', 'training_week_plan', 'strava_activity_raw',
                      'activity_metrics', 'activity_rpe_resolution', 'health_recovery_daily'):
            conn.execute(f'create temporary table {table} (like public.{table} including all)')
        conn.commit()
        @contextmanager
        def connection():
            with conn.transaction():
                yield conn
        monkeypatch.setattr(service, 'get_conn', connection)
        yield conn


def make_edit(monday=MONDAY, revision=0, **kwargs):
    data = dict(week_start=monday, sessions=[dict(id='stable', day=monday, session_type='z2',
        duration_minutes=60, priority='key')], windows=[dict(day=monday, duration_minutes=50, confirmed=True)])
    data.update(kwargs)
    return service.TrainingContextEdit(block_priority='z2', revision=revision, plan=service.WeekPlan(**data))


def test_create_update_goal_windows_sessions_and_conflicts(db):
    absent = service.get_training_context('athlete', MONDAY)
    assert absent.block_priority is None and absent.plan.sessions is None and absent.revision == 0
    service.save_training_context('athlete', make_edit(), today=MONDAY)
    saved = service.get_training_context('athlete', MONDAY)
    assert saved.revision == 1 and saved.block_priority == 'z2'
    changed = make_edit(revision=1, windows=[dict(day=MONDAY, duration_minutes=0, confirmed=True)],
        sessions=[dict(id='stable', session_type='recovery', duration_minutes=25, priority='supporting')])
    changed = changed.model_copy(update={'block_priority': 'recovery'})
    service.save_training_context('athlete', changed, today=MONDAY)
    read = service.get_training_context('athlete', MONDAY)
    assert read.plan.windows[0].duration_minutes == 0
    assert read.plan.sessions[0].id == 'stable' and read.plan.sessions[0].day is None
    assert read.block_priority == 'recovery' and read.revision == 2
    with pytest.raises(HTTPException) as exc:
        service.save_training_context('athlete', make_edit(revision=1), today=MONDAY)
    assert exc.value.status_code == 409
    assert service.get_training_context('athlete', MONDAY) == read
    with pytest.raises(HTTPException):
        service.save_training_context('athlete', changed, today=MONDAY + timedelta(days=7))
    next_week = service.get_training_context('athlete', MONDAY + timedelta(days=7))
    assert next_week.block_priority == 'recovery' and next_week.plan.sessions is None
    assert service.get_training_context('other', MONDAY).block_priority is None
    with pytest.raises(HTTPException):
        service.save_training_context('new', make_edit(revision=5), today=MONDAY)
    assert service.get_training_context('new', MONDAY).revision == 0


@pytest.mark.parametrize('monday,zone', [(date(2026, 3, 23), 'Europe/Berlin'),
    (date(2026, 10, 19), 'Europe/Berlin'), (date(2026, 12, 28), 'Pacific/Auckland')])
def test_week_to_date_identity_load_rpe_and_boundaries(db, monkeypatch, monday, zone):
    monkeypatch.setattr(service.settings, 'whatte_timezone', zone)
    tz = ZoneInfo(zone)
    sunday = monday + timedelta(days=6)
    start = datetime.combine(monday, datetime.min.time(), tz).astimezone(timezone.utc)
    end = datetime.combine(monday + timedelta(days=7), datetime.min.time(), tz).astimezone(timezone.utc)
    for id, started, user, deleted, excluded, duplicate in [
        (1, start, 'athlete', False, False, None),
        (2, end - timedelta(seconds=1), 'athlete', False, False, None),
        (3, start + timedelta(days=1), 'athlete', False, False, None),
        (4, start - timedelta(seconds=1), 'athlete', False, False, None),
        (5, end, 'athlete', False, False, None), (6, start, 'other', False, False, None),
        (7, start, 'athlete', True, False, None), (8, start, 'athlete', False, True, None),
        (9, start, 'athlete', False, False, 1),
    ]:
        db.execute("""insert into strava_activity_raw
            (id, strava_activity_id, strava_athlete_id, user_id, start_date, raw_json,
             activity_type, is_deleted, is_excluded, duplicate_of_activity_id)
            values (%s,%s,1,%s,%s,'{}',%s,%s,%s,%s)""",
            (id, id, user, started, 'Run' if id == 3 else 'Ride', deleted, excluded, duplicate))
    db.execute("""insert into activity_metrics
        (id, user_id, strava_activity_id, version, tss, normalized_power, intensity_factor)
        values (1,'athlete',1,'v1',40,180,0.8), (2,'athlete',3,'v1',40,180,0.8),
        (3,'other',2,'v1',40,180,0.8)""")
    db.execute("""insert into activity_rpe_resolution
        (canonical_activity_id, user_id, effective_score, effective_source, disagreement)
        values (1,'athlete',8,'web',true), (2,'other',10,'web',false)""")
    db.commit()
    service.save_training_context('athlete', make_edit(monday, sessions=[dict(id='sunday', day=sunday,
        session_type='z2', duration_minutes=60, priority='key')], windows=[dict(day=sunday,
        duration_minutes=50, confirmed=True)]), today=sunday)
    result = service.get_policy_context('athlete', now=datetime.combine(sunday, datetime.min.time(), tz),
        constraints=ActionConstraints(training_allowed=True))
    assert [a['activity_id'] for a in result['activities']] == ['1', '3', '2']
    assert [a['load'].included for a in result['activities']] == [True, False, None]
    assert result['activities'][0]['rpe'] == 8 and result['activities'][0]['rpe_disagreement']
    assert result['activities'][-1]['rpe'] is None
    assert not result['context'].physiology_available
    assert all(a.confirmed_plan_session_id is None for a in result['context'].completed)
    assert result['context'].today == sunday
    midweek = service.get_policy_context('athlete', now=datetime.combine(monday + timedelta(days=2), datetime.min.time(), tz))
    assert [a['activity_id'] for a in midweek['activities']] == ['1', '3']


def test_v2_upgrade_preserves_existing_activity(db):
    db.execute("""insert into strava_activity_raw
        (id,strava_activity_id,strava_athlete_id,user_id,raw_json) values (55,55,1,'legacy','{"preserved":true}')""")
    before = db.execute('select row_to_json(r) from strava_activity_raw r').fetchall()
    db.commit()
    # Isolated namespace rehearses additive DDL without touching public schema.
    with db.transaction():
        db.execute('create schema training_context_upgrade_probe')
        db.execute('set local search_path = training_context_upgrade_probe, public, pg_temp')
        db.execute((Path(__file__).parents[2] / 'migrations/sql/V2__training_context.sql').read_text(), prepare=False)
        assert db.execute('select row_to_json(r) from pg_temp.strava_activity_raw r').fetchall() == before
        db.execute('drop schema training_context_upgrade_probe cascade')
