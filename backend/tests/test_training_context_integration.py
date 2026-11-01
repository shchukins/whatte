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
                      'activity_metrics', 'activity_rpe_resolution', 'health_recovery_daily',
                      'training_decision', 'training_decision_choice', 'training_session_activity',
                      'activity_rpe_observation', 'activity_subjective_feedback', 'activity_delivery_log'):
            conn.execute(f'create temporary table {table} (like public.{table} including all)')
        conn.commit()
        conn.autocommit = True
        @contextmanager
        def connection():
            with conn.transaction():
                yield conn
        from backend.services import training_decision_loop
        monkeypatch.setattr(service, 'get_conn', connection)
        monkeypatch.setattr(training_decision_loop, 'get_conn', connection)
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


def test_today_http_uses_persisted_plan_and_only_patches_capacity(db, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import app
    from backend.today import service as today_service

    monkeypatch.setattr(service, 'local_today', lambda *a: MONDAY)
    monkeypatch.setattr(service.settings, 'daily_readiness_user_id', 'athlete')
    section = today_service.TodaySection('ok', None)
    monkeypatch.setattr(today_service, 'get_today_data', lambda *a, **kw: today_service.TodayData(
        'athlete', str(MONDAY), None, section, [], None, section, None, section, [], section))
    service.save_training_context('athlete', make_edit(sessions=[dict(id='long', day=MONDAY,
        session_type='long_z2', duration_minutes=120, priority='key', minimum_shortened_minutes=40)]), today=MONDAY)
    before = service.get_training_context('athlete', MONDAY)
    client = TestClient(app)
    response = client.post('/today/training-decision', data=dict(decision_day=str(MONDAY),
        revision=str(before.revision), minutes='50', session_id='long', training_allowed='yes'),
        follow_redirects=False)
    assert response.status_code == 303
    first = client.get(response.headers['location'])
    assert first.status_code == 200 and '>SHORTEN</span>' in first.text
    assert first.text == client.get(response.headers['location']).text
    after = service.get_training_context('athlete', MONDAY)
    assert after.plan.sessions == before.plan.sessions
    assert after.block_priority == before.block_priority
    assert after.plan.windows[0].duration_minutes == 50
    assert after.revision == before.revision
    assert service.get_training_context('athlete', MONDAY) == after

# Task 4 exercises the real policy, SQL transactions and native Today forms.
def loop_setup(db, monkeypatch, *, sessions=None, windows=None):
    from backend.services import training_decision_loop as loop
    from backend.today import service as today_service
    from fastapi.testclient import TestClient
    from backend.app import app

    monkeypatch.setattr(service, 'local_today', lambda *a: MONDAY)
    monkeypatch.setattr(service.settings, 'daily_readiness_user_id', 'athlete')
    monkeypatch.setattr(service.settings, 'whatte_timezone', 'Europe/Moscow')
    section = today_service.TodaySection('ok', None)
    monkeypatch.setattr(today_service, 'get_today_data', lambda *a, **kw: today_service.TodayData(
        'athlete', str(MONDAY), None, section, [], None, section, None, section, [], section))
    service.save_training_context('athlete', make_edit(sessions=sessions or [dict(id='long', day=MONDAY,
        session_type='long_z2', duration_minutes=120, priority='key', minimum_shortened_minutes=40)],
        windows=windows or [dict(day=MONDAY, duration_minutes=50, confirmed=True)]
    ).model_copy(update={'block_priority': 'long_z2'}), today=MONDAY)
    return loop, TestClient(app)


def proposal(client, **fields):
    response = client.post('/today/training-decision', data={**dict(decision_day=str(MONDAY),
        revision='1', minutes='50', training_allowed='yes', session_id='long'), **fields}, follow_redirects=False)
    assert response.status_code == 303, response.text


def import_activity(db, id=123, *, day=MONDAY, sport='Ride', user='athlete'):
    # Same canonical ID on replay, as in ingestion; no RPE or metrics required.
    db.execute('''insert into strava_activity_raw
        (strava_activity_id, strava_athlete_id, user_id, start_date, activity_type, moving_time_s, raw_json)
        values (%s,1,%s,%s,%s,3000,'{}') on conflict (strava_activity_id) do update set moving_time_s=3000''',
        (id, user, datetime.combine(day, datetime.min.time(), ZoneInfo('Europe/Moscow')), sport))
    db.commit()


def policy_snapshot(*, now=None, **kwargs):
    return service.get_policy_context('athlete', now=now, constraints=ActionConstraints(training_allowed=True), **kwargs)


def test_full_decision_choice_strava_completion_next_decision(db, monkeypatch):
    tomorrow = MONDAY + timedelta(days=1)
    loop, client = loop_setup(db, monkeypatch, sessions=[
        dict(id='long', day=MONDAY, session_type='long_z2', duration_minutes=120,
             priority='key', minimum_shortened_minutes=40),
        dict(id='support', day=tomorrow, session_type='z2', duration_minutes=60, priority='supporting',
             minimum_shortened_minutes=30)], windows=[dict(day=MONDAY, duration_minutes=50, confirmed=True),
                                                      dict(day=tomorrow, duration_minutes=50, confirmed=True)])
    proposal(client)
    proposal(client)  # Same request produces one row, no acceptance.
    assert db.execute('select count(*) from training_decision').fetchone() == (1,)
    assert db.execute('select count(*) from training_decision_choice').fetchone() == (0,)
    first = client.get('/today')
    assert first.status_code == 200 and 'Принять предложение' in first.text and '50 мин' in first.text
    assert first.text.count('<h1 ') == 1
    assert first.text == client.get('/today').text  # Read-only repeat is stable.
    record = policy_snapshot()['decisions'][0]
    id = record['id']
    assert record['status'] == 'proposed' and record['decision_json']['recommendation']['action'] == 'SHORTEN'
    assert client.post('/today/training-choice', data=dict(decision_id=id, choice='accepted')).status_code == 200
    accepted = policy_snapshot()['decisions'][0]
    assert accepted['choice'] == 'accepted' and not accepted['stale']
    assert accepted['input_json']['context']['week_plan'][0]['duration_minutes'] == 120
    saved = service.get_training_context('athlete', MONDAY)
    assert saved.plan.sessions[0].id == 'long' and saved.plan.sessions[0].duration_minutes == 50
    loop.choose('athlete', id, 'accepted')
    assert service.get_training_context('athlete', MONDAY) == saved
    assert db.execute('select count(*) from training_decision_choice').fetchone() == (1,)
    import_activity(db)
    import_activity(db)  # Reimport never duplicates the canonical activity.
    page = client.get('/today')
    assert 'Тренировка уже записана' in page.text and 'Подтвердить связь' in page.text
    assert 'Принять предложение' not in page.text
    assert 'Сохранить время и получить предложение' not in page.text
    assert db.execute('select count(*) from strava_activity_raw').fetchone() == (1,)
    completion = dict(decision_day=str(MONDAY), revision=str(saved.revision), activity_id='123',
                      session_id='long', correspondence='fulfilled')
    assert client.post('/today/training-completion', data=completion).status_code == 200
    assert client.post('/today/training-completion', data=completion).status_code == 200
    result = policy_snapshot()
    assert result['context'].completed[0].confirmed_plan_session_id == 'long'
    assert result['activities'][0]['rpe'] is None and result['activities'][0]['tss'] is None
    assert not result['context'].physiology_available
    assert result['decision'].recommendation.action == 'SKIP'
    assert result['delivery']['status'] == 'activity_recorded' and not result['delivery']['offer_training']
    assert result['session_statuses']['long'] == dict(status='fulfilled', activity_id='123')
    assert 'pending_key_sessions:' in result['decision'].selection_reasons
    assert db.execute('select count(*), min(decision_id) from training_session_activity').fetchone() == (1, id)
    # Tomorrow's recommendation cannot use already fulfilled long work as a substitute.
    monkeypatch.setattr(service, 'local_today', lambda *a: tomorrow)
    next_result = policy_snapshot(now=datetime.combine(tomorrow, datetime.min.time(), ZoneInfo('Europe/Moscow')),
        today_session_id='support')
    assert next_result['context'].completed[0].confirmed_plan_session_id == 'long'
    assert 'long' not in next_result['decision'].selection_reasons[0]
    assert next_result['decision'].recommendation.action == 'SHORTEN'


def test_declined_and_unanswered_are_separate_from_plan_and_fact(db, monkeypatch):
    loop, client = loop_setup(db, monkeypatch)
    proposal(client)
    before = service.get_training_context('athlete', MONDAY)
    id = policy_snapshot()['decisions'][0]['id']
    assert policy_snapshot()['decisions'][0]['status'] == 'proposed'
    assert service.get_training_context('athlete', MONDAY) == before
    loop.choose('athlete', id, 'declined')
    loop.choose('athlete', id, 'declined')
    assert policy_snapshot()['decisions'][0]['status'] == 'declined'
    assert 'Отказ не означает отдых' in client.get('/today').text
    assert service.get_training_context('athlete', MONDAY) == before
    with pytest.raises(HTTPException) as exc:
        loop.choose('athlete', id, 'accepted')
    assert exc.value.status_code == 409
    assert db.execute('select count(*) from training_session_activity').fetchone() == (0,)


@pytest.mark.parametrize('change', ['capacity', 'plan', 'import', 'midnight', 'rules'])
def test_old_proposals_never_apply_to_changed_context(db, monkeypatch, change):
    loop, client = loop_setup(db, monkeypatch)
    proposal(client)
    id = policy_snapshot()['decisions'][0]['id']
    edit = service.get_training_context('athlete', MONDAY)
    if change == 'capacity':
        service.save_today_availability('athlete', today=MONDAY, revision=edit.revision, duration_minutes=70)
    elif change == 'plan':
        plan = edit.plan.model_copy(update={'sessions': ()})
        service.save_training_context('athlete', edit.model_copy(update={'plan': plan}), today=MONDAY)
    elif change == 'import':
        import_activity(db)
        assert policy_snapshot()['decisions'][0]['stale']
    elif change == 'midnight':
        monkeypatch.setattr(service, 'local_today', lambda *a: MONDAY + timedelta(days=1))
    else:
        original = loop.choose_training_action
        monkeypatch.setattr(loop, 'choose_training_action', lambda context: original(context).model_copy(update={'rule_version': 'changed'}))
    with pytest.raises(HTTPException) as exc:
        loop.choose('athlete', id, 'accepted')
    assert exc.value.status_code == 409
    assert db.execute('select count(*) from training_decision_choice').fetchone() == (0,)


def test_new_explicit_constraints_supersede_older_proposal(db, monkeypatch):
    loop, client = loop_setup(db, monkeypatch)
    proposal(client)
    first = policy_snapshot()['decisions'][0]['id']
    proposal(client, training_allowed='no')
    records = policy_snapshot()['decisions']
    assert records[0]['decision_json']['recommendation']['action'] == 'SKIP'
    assert records[1]['status'] == 'superseded'
    with pytest.raises(HTTPException):
        loop.choose('athlete', first, 'accepted')
    loop.choose('athlete', records[0]['id'], 'accepted')
    assert db.execute('select count(*) from training_decision_choice').fetchone() == (1,)


@pytest.mark.parametrize('relation,sport', [('different', 'Ride'), ('fulfilled', 'Run')])
def test_explicit_correspondence_missing_and_unsupported_metrics(db, monkeypatch, relation, sport):
    loop, client = loop_setup(db, monkeypatch)
    proposal(client)
    loop.choose('athlete', policy_snapshot()['decisions'][0]['id'], 'accepted')
    import_activity(db, sport=sport)
    loop.confirm_activity('athlete', today=MONDAY, revision=2, activity_id=123, session_id='long', correspondence=relation)
    result = policy_snapshot()
    completed = result['context'].completed[0]
    assert completed.confirmed_plan_session_id == ('long' if relation == 'fulfilled' else None)
    assert completed.load.included is not True
    assert result['activities'][0]['rpe'] is None
    if relation == 'different':
        assert 'pending_key_sessions:long' in result['decision'].selection_reasons
        assert 'выполнение не засчитано' in client.get('/today').text


def test_activity_and_assignment_cannot_be_credited_twice(db, monkeypatch):
    loop, client = loop_setup(db, monkeypatch, sessions=[dict(id=id, day=MONDAY, session_type='z2',
        duration_minutes=50, priority='key') for id in ('long', 'other')])
    import_activity(db)
    import_activity(db, id=124)
    loop.confirm_activity('athlete', today=MONDAY, revision=1, activity_id=123, session_id='long', correspondence='fulfilled')
    loop.confirm_activity('athlete', today=MONDAY, revision=1, activity_id=123, session_id='long', correspondence='fulfilled')
    for activity, session in [(123, 'other'), (124, 'long')]:
        with pytest.raises(HTTPException) as exc:
            loop.confirm_activity('athlete', today=MONDAY, revision=2, activity_id=activity,
                                  session_id=session, correspondence='fulfilled')
        assert exc.value.status_code == 409
    assert db.execute('select count(*) from training_session_activity').fetchone() == (1,)
    # Editing a completed ID cannot turn its existing link into proof for new work.
    edit = service.get_training_context('athlete', MONDAY)
    changed = edit.plan.model_dump()
    changed['sessions'][0]['duration_minutes'] = 70
    with pytest.raises(HTTPException):
        service.save_training_context('athlete', edit.model_copy(update={'plan': service.WeekPlan(**changed)}), today=MONDAY)


@pytest.mark.parametrize('action', ['RESCHEDULE', 'SUBSTITUTE'])
def test_move_or_substitution_preserves_identity_without_two_occurrences(db, monkeypatch, action):
    tomorrow = MONDAY + timedelta(days=1)
    sessions = [dict(id='long', day=MONDAY, session_type='long_z2', duration_minutes=120,
                     priority='key', minimum_shortened_minutes=40)]
    if action == 'SUBSTITUTE':
        sessions.append(dict(id='interval', day=tomorrow, session_type='intensity', duration_minutes=45, priority='key'))
    loop, client = loop_setup(db, monkeypatch, sessions=sessions,
        windows=[dict(day=MONDAY, duration_minutes=50, confirmed=True),
                 dict(day=tomorrow, duration_minutes=150, confirmed=True)])
    fields = dict(reviewed_window=str(tomorrow))
    if action == 'SUBSTITUTE':
        edit = service.get_training_context('athlete', MONDAY)
        service.save_training_context('athlete', edit.model_copy(update={'block_priority': 'intensity'}), today=MONDAY)
        fields = dict(revision='2', substitute='interval', intensity_allowed='yes')
    proposal(client, **fields)
    record = policy_snapshot()['decisions'][0]
    assert record['decision_json']['recommendation']['action'] == action
    loop.choose('athlete', record['id'], 'accepted')
    accepted = service.get_training_context('athlete', MONDAY)
    loop.choose('athlete', record['id'], 'accepted')
    assert service.get_training_context('athlete', MONDAY) == accepted
    assert len({s.id for s in accepted.plan.sessions}) == len(sessions)
    if action == 'RESCHEDULE':
        assert accepted.plan.sessions[0].day == tomorrow
    else:
        assert accepted.plan.sessions[0].day is None
        assert accepted.plan.sessions[1].day == MONDAY


def test_completion_date_week_and_owner_boundaries(db, monkeypatch):
    loop, client = loop_setup(db, monkeypatch)
    import_activity(db, id=1, day=MONDAY - timedelta(days=1))
    import_activity(db, id=2, day=MONDAY + timedelta(days=1))
    import_activity(db, id=3, user='other')
    db.execute("insert into strava_activity_raw (strava_activity_id,strava_athlete_id,user_id,raw_json,duplicate_of_activity_id) values (4,1,'athlete','{}',1)")
    db.commit()
    for id in (1, 2, 3, 4, 999):
        with pytest.raises(HTTPException):
            loop.confirm_activity('athlete', today=MONDAY, revision=1, activity_id=id,
                                  session_id='long', correspondence='fulfilled')
    import_activity(db)
    for day, revision, session in [(MONDAY + timedelta(days=1), 1, 'long'), (MONDAY, 0, 'long'), (MONDAY, 1, 'foreign')]:
        with pytest.raises(HTTPException):
            loop.confirm_activity('athlete', today=day, revision=revision, activity_id=123,
                                  session_id=session, correspondence='fulfilled')
    assert db.execute('select count(*) from training_session_activity').fetchone() == (0,)


def test_new_loop_forms_validate_origin_content_and_duplicate_fields(db, monkeypatch):
    loop, client = loop_setup(db, monkeypatch)
    for route in ('training-choice', 'training-completion'):
        url = '/today/' + route
        assert client.post(url, data={}, headers={'origin': 'https://other.example'}).status_code == 403
        assert client.post(url, json={}).status_code == 415
        assert client.post(url, content='a'*16385, headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 413
        assert client.post(url, data=dict(unexpected='x')).status_code == 422
    assert client.post('/today/training-choice', content='decision_id=1&decision_id=2&choice=accepted',
        headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 422
    assert client.post('/today/training-choice', data=dict(decision_id=999, choice='accepted')).status_code == 404


def test_v3_additive_upgrade_preserves_context_and_activity_rows(db):
    db.execute("insert into user_training_context values ('legacy', 'z2', 7)")
    import_activity(db, id=777, user='legacy')
    context_before = db.execute('select row_to_json(c) from user_training_context c').fetchall()
    before = db.execute('select row_to_json(r) from strava_activity_raw r').fetchall()
    with db.transaction():
        db.execute('create schema training_loop_upgrade_probe')
        db.execute('set local search_path = training_loop_upgrade_probe, public, pg_temp')
        # FK refers to existing V2 owner; no old table is modified or backfilled.
        db.execute((Path(__file__).parents[2] / 'migrations/sql/V3__training_decision_loop.sql').read_text(), prepare=False)
        assert db.execute('select row_to_json(r) from pg_temp.strava_activity_raw r').fetchall() == before
        assert db.execute('select row_to_json(c) from pg_temp.user_training_context c').fetchall() == context_before
        db.execute('drop schema training_loop_upgrade_probe cascade')


def test_representing_same_constraints_reuses_snapshot_without_false_supersession(db, monkeypatch):
    loop, client = loop_setup(db, monkeypatch)
    proposal(client)
    first = policy_snapshot()['decisions'][0]['id']
    proposal(client, training_allowed='no')
    proposal(client)
    records = policy_snapshot()['decisions']
    assert records[0]['id'] == first and records[0]['status'] == 'proposed'
    assert len(records) == 2 and records[1]['status'] == 'superseded'
    loop.choose('athlete', first, 'accepted')
    assert service.get_training_context('athlete', MONDAY).plan.sessions[0].duration_minutes == 50


def test_canonical_identity_reselection_transfers_explicit_link(db, monkeypatch):
    from backend.services.activity_deduplication_service import _transfer_canonical_metadata
    loop, client = loop_setup(db, monkeypatch)
    import_activity(db)
    loop.confirm_activity('athlete', today=MONDAY, revision=1, activity_id=123,
                          session_id='long', correspondence='fulfilled')
    import_activity(db, id=124)
    with db.transaction(), db.cursor() as cur:
        cur.execute('update strava_activity_raw set duplicate_of_activity_id=124 where strava_activity_id=123')
        _transfer_canonical_metadata(cur, canonical_activity_id=124, duplicate_activity_id=123)
    result = policy_snapshot()
    assert [a['activity_id'] for a in result['activities']] == ['124']
    assert result['context'].completed[0].confirmed_plan_session_id == 'long'
    assert db.execute('select canonical_activity_id from training_session_activity').fetchone() == (124,)


def test_canonical_merge_refuses_conflicting_assignments(db, monkeypatch):
    from backend.services.activity_deduplication_service import _transfer_canonical_metadata
    loop, client = loop_setup(db, monkeypatch, sessions=[dict(id=id, day=MONDAY, session_type='z2',
        duration_minutes=50, priority='key') for id in ('long', 'other')])
    import_activity(db)
    import_activity(db, id=124)
    loop.confirm_activity('athlete', today=MONDAY, revision=1, activity_id=123, session_id='long', correspondence='fulfilled')
    loop.confirm_activity('athlete', today=MONDAY, revision=2, activity_id=124, session_id='other', correspondence='fulfilled')
    with pytest.raises(ValueError, match='conflicting_training_assignment_links'):
        with db.transaction(), db.cursor() as cur:
            _transfer_canonical_metadata(cur, canonical_activity_id=124, duplicate_activity_id=123)
    assert db.execute('select count(*) from training_session_activity').fetchone() == (2,)


@pytest.mark.parametrize('zone,day', [('Europe/Berlin', date(2026, 10, 25)),
                                    ('Pacific/Auckland', date(2027, 1, 3))])
def test_completion_uses_local_week_at_dst_and_iso_year_boundary(db, monkeypatch, zone, day):
    from backend.services import training_decision_loop as loop
    monkeypatch.setattr(service, 'local_today', lambda *a: day)
    monkeypatch.setattr(service.settings, 'whatte_timezone', zone)
    edit = make_edit(service.week_start(day), sessions=[dict(id='key', day=day, session_type='z2',
        duration_minutes=60, priority='key')], windows=[dict(day=day, duration_minutes=60, confirmed=True)])
    service.save_training_context('athlete', edit, today=day)
    db.execute('''insert into strava_activity_raw
        (strava_activity_id,strava_athlete_id,user_id,start_date,raw_json)
        values (555,1,'athlete',%s,'{}')''', (datetime.combine(day, datetime.max.time(), ZoneInfo(zone)),))
    loop.confirm_activity('athlete', today=day, revision=1, activity_id=555, session_id='key', correspondence='fulfilled')
    result = policy_snapshot(now=datetime.combine(day, datetime.min.time(), ZoneInfo(zone)))
    assert result['context'].completed[0].confirmed_plan_session_id == 'key'
    assert result['decision'].recommendation.action == 'SKIP'
    next_monday = day + timedelta(days=1)
    monkeypatch.setattr(service, 'local_today', lambda *a: next_monday)
    next_result = policy_snapshot(now=datetime.combine(next_monday, datetime.min.time(), ZoneInfo(zone)))
    assert next_result['activities'] == [] and next_result['saved_context'].plan.sessions is None


def test_proposal_storage_failure_does_not_claim_saved_choice(db, monkeypatch):
    loop, client = loop_setup(db, monkeypatch)
    def failed(*args):
        raise RuntimeError('snapshot storage unavailable')
    monkeypatch.setattr(loop, 'propose', failed)
    response = client.post('/today/training-decision', data=dict(decision_day=str(MONDAY),
        revision='1', minutes='70', training_allowed='yes', session_id='long'))
    assert response.status_code == 503 and 'Время сохранено, но предложение не сохранено' in response.text
    assert service.get_training_context('athlete', MONDAY).plan.windows[0].duration_minutes == 70
    assert db.execute('select count(*) from training_decision_choice').fetchone() == (0,)
    assert db.execute('select count(*) from training_decision').fetchone() == (0,)
