from datetime import date, datetime, timezone
import importlib

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from backend import app as app_module
from backend.services import training_context_service as service
from backend.services.activity_load_service import ActivityLoadAssessment
from backend.services.training_decision_policy import ActionConstraints

router = importlib.import_module('backend.today.router')
TODAY = date(2026, 10, 30)
MONDAY = date(2026, 10, 26)


def edit(**kwargs):
    plan = dict(week_start=MONDAY, sessions=[dict(id='stable', day=TODAY,
        session_type='long_z2', duration_minutes=120, priority='key', minimum_shortened_minutes=40)],
        windows=[dict(day=TODAY, duration_minutes=50, confirmed=True)])
    plan.update(kwargs)
    return service.TrainingContextEdit(block_priority='long_z2', plan=service.WeekPlan(**plan))


def test_complete_inputs_reach_existing_policy_without_completion_guess():
    activity = dict(activity_id='123', load=ActivityLoadAssessment(True, None), rpe=8)
    result = service.assemble_policy_context(edit(), [activity], today=TODAY,
        constraints=ActionConstraints(training_allowed=True))
    assert result['context'].today_session_id == 'stable'
    assert result['context'].completed[0].confirmed_plan_session_id is None
    assert result['decision'].recommendation.action == 'SHORTEN'
    assert result['decision'].recommendation.duration_minutes == 50
    assert result['activities'][0]['rpe'] == 8
    assert 'optional_physiology_unavailable_no_recovery_assumption' in result['decision'].warnings
    assert 'plan_completion_unconfirmed:123' in result['decision'].warnings
    assert 'future_window_unknown:2026-10-31' in result['missing_context']


@pytest.mark.parametrize('windows', [[], [dict(day=TODAY, duration_minutes=50, confirmed=False)]])
def test_unknown_capacity_never_fabricated_as_zero(windows):
    result = service.assemble_policy_context(edit(windows=windows), [], today=TODAY)
    assert result['context'] is None and result['decision'] is None
    assert 'today_available_minutes_unconfirmed' in result['missing_context']
    assert 'training_permission_unknown' in result['missing_context']


def test_confirmed_zero_and_unreviewed_future_capacity():
    result = service.assemble_policy_context(edit(windows=[
        dict(day=TODAY, duration_minutes=0, confirmed=True),
        dict(day=date(2026, 10, 31), duration_minutes=150, confirmed=True),
    ]), [], today=TODAY, constraints=ActionConstraints(training_allowed=True))
    assert result['decision'].recommendation.action == 'SKIP'
    assert result['context'].future_windows[0].compatible_session_ids is None
    assert any('week_compatibility_unconfirmed' in r for r in result['decision'].rejected['RESCHEDULE'])


@pytest.mark.parametrize('sessions', [None, [], [dict(id='undated', session_type='z2', duration_minutes=60, priority='supporting')]])
def test_absent_empty_and_partial_plan(sessions):
    result = service.assemble_policy_context(edit(sessions=sessions), [], today=TODAY)
    assert result['context'].week_plan == (None if sessions is None else ())
    assert result['decision'].status == 'uncertain'
    assert result['saved_context'].plan.sessions == edit(sessions=sessions).plan.sessions
    if sessions:
        assert 'session_day_unknown:undated' in result['missing_context']


@pytest.mark.parametrize('load', [ActivityLoadAssessment(None, 'unavailable_metrics_record'),
                                  ActivityLoadAssessment(False, 'unsupported_sport')])
def test_missing_unsupported_load_does_not_erase_activity(load):
    result = service.assemble_policy_context(edit(), [dict(activity_id='a', load=load)], today=TODAY)
    assert result['context'].completed[0].load == load
    assert result['decision'].status == 'uncertain'  # permission is never inferred
    assert any(w.startswith('load_not_covered:a:') for w in result['decision'].warnings)


@pytest.mark.parametrize('updates', [dict(week_start=TODAY),
    dict(sessions=[dict(id='bad', day='2026-11-02', session_type='z2', duration_minutes=20, priority='key')]),
    dict(windows=[dict(day=TODAY, confirmed=True)]),
    dict(windows=[dict(day=TODAY), dict(day=TODAY)])])
def test_invalid_week_or_windows_rejected(updates):
    with pytest.raises(ValidationError):
        edit(**updates)


def test_timezone_and_iso_year_boundaries(monkeypatch):
    monkeypatch.setattr(service.settings, 'whatte_timezone', 'Pacific/Auckland')
    assert service.local_today(datetime(2027, 1, 3, 12, tzinfo=timezone.utc)) == date(2027, 1, 4)
    assert service.week_start(date(2027, 1, 3)) == date(2026, 12, 28)
    with pytest.raises(ValueError, match='timezone'):
        service.local_today(datetime(2026, 1, 1))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(service, 'local_today', lambda *args: TODAY)
    monkeypatch.setattr(service, 'get_training_context', lambda *args: edit())
    return TestClient(app_module.app)


def form():
    return dict(week_start=str(MONDAY), revision='0', block_priority='z2', plan_known='1',
        session_0_id='stable', session_0_day=str(TODAY), session_0_session_type='z2',
        session_0_duration_minutes='60', session_0_priority='key', session_0_minimum_shortened_minutes='30',
        **{f'minutes_{TODAY}': '45', f'confirmed_{TODAY}': '1'})


def test_native_form_read_save_and_stable_id(client, monkeypatch):
    page = client.get('/today/plan')
    assert page.status_code == 200
    assert 'План недели' in page.text and 'session_0_id' in page.text
    assert page.headers['cache-control'] == 'no-store'
    saves = []
    monkeypatch.setattr(service, 'save_training_context', lambda user, edit, **kwargs: saves.append(edit))
    response = client.post('/today/plan', data=form(), follow_redirects=False)
    assert response.status_code == 303
    assert saves[0].plan.sessions[0].id == 'stable'
    assert saves[0].plan.windows[0].duration_minutes == 45
    assert saves[0].block_priority == 'z2'


@pytest.mark.parametrize('change', [dict(session_0_duration_minutes='-1'),
    dict(session_0_day='2026-11-02'), dict(session_0_minimum_shortened_minutes='80')])
def test_invalid_form_retains_input_without_saving(client, monkeypatch, change):
    monkeypatch.setattr(service, 'save_training_context', lambda *args, **kwargs: pytest.fail('invalid write'))
    response = client.post('/today/plan', data={**form(), **change})
    assert response.status_code == 422
    assert 'stable' in response.text
    assert str(next(iter(change.values()))) in response.text


def test_form_security_conflict_and_failure(client, monkeypatch):
    assert client.post('/today/plan', data=form(), headers={'origin': 'https://elsewhere.test'}).status_code == 403
    assert client.post('/today/plan', content=b'x' * 65537,
        headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 413
    from fastapi import HTTPException
    def conflict(*args, **kwargs):
        raise HTTPException(409, 'Контекст уже изменён')
    monkeypatch.setattr(service, 'save_training_context', conflict)
    response = client.post('/today/plan', data=form())
    assert response.status_code == 409 and 'stable' in response.text
    def failure(*args, **kwargs):
        raise RuntimeError('db unavailable')
    monkeypatch.setattr(service, 'save_training_context', failure)
    assert client.post('/today/plan', data=form()).status_code == 503
