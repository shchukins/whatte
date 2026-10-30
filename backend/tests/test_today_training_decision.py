"""End-to-end native Today flow with the real adapter and policy, isolated storage."""
from datetime import date, timedelta
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import QueryParams

from backend.app import app
from backend.services import training_context_service as store
from backend.services.activity_load_service import ActivityLoadAssessment
from backend.today import service, training

TODAY = date(2026, 10, 30)


@pytest.fixture
def state(monkeypatch):
    state = {'edit': store.TrainingContextEdit(block_priority='long_z2', plan=store.WeekPlan(
        week_start=store.week_start(TODAY), sessions=(store.SavedSession(id='long', day=TODAY,
        session_type='long_z2', duration_minutes=120, priority='key', minimum_shortened_minutes=40),),
        windows=(store.DailyWindow(day=TODAY, duration_minutes=50, confirmed=True),))),
        'activities': [], 'writes': []}
    monkeypatch.setattr(store, 'local_today', lambda *a: TODAY)
    monkeypatch.setattr(store, 'get_training_context', lambda *a: state['edit'])
    def snapshot(*a, **kw):
        return store.assemble_policy_context(state['edit'], state['activities'], today=TODAY)
    monkeypatch.setattr(store, 'get_policy_context', snapshot)
    def save(user, edit, **kw):
        if edit.revision != state['edit'].revision:
            raise HTTPException(409, 'stale')
        state['writes'].append(edit)
        state['edit'] = edit.model_copy(update={'revision': edit.revision + 1})
    monkeypatch.setattr(store, 'save_training_context', save)
    section = service.TodaySection('ok', None)
    data = service.TodayData('athlete', str(TODAY), None, section, [], None, section,
                             None, section, [], section)
    monkeypatch.setattr(service, 'get_today_data', lambda *a, **kw: data)
    return state


def url(**kw):
    return '/today?' + urlencode(dict(decision_day=str(TODAY), training_allowed='yes', **kw))


def decision(**kw):
    return training.today_decision('athlete', QueryParams(url(**kw).partition('?')[2]))


@pytest.mark.parametrize('minutes,action', [(50, 'SHORTEN'), (120, 'KEEP'), (0, 'SKIP')])
def test_saved_capacity_drives_real_policy_and_repeated_get_is_read_only(state, minutes, action):
    original = state['edit']
    client = TestClient(app)
    response = client.post('/today/training-decision', data=dict(decision_day=str(TODAY), revision='0',
        minutes=str(minutes), training_allowed='yes', session_id='long'), follow_redirects=False)
    assert response.status_code == 303
    location = response.headers['location']
    first = client.get(location)
    second = client.get(location)
    assert first.status_code == 200 and first.text == second.text
    assert first.headers['cache-control'] == 'no-store'
    assert f'>{action}</span>' in first.text
    assert state['edit'].plan.sessions == original.plan.sessions
    assert state['edit'].block_priority == original.block_priority
    assert len(state['writes']) == 1
    assert decision()['decision'].recommendation.action == action
    if action == 'SHORTEN':
        assert '50 мин' in first.text and '70 мин' in first.text


def test_unknown_time_permission_goal_and_plan_are_explicit(state):
    client = TestClient(app)
    assert 'Укажите, допустима ли тренировка сегодня' in client.get('/today').text
    assert client.post('/today/training-decision', data=dict(decision_day=str(TODAY), revision='0',
        minutes='', training_allowed='yes')).status_code == 200
    assert state['edit'].plan.windows[-1].confirmed is False
    assert decision()['decision'] is None
    assert 'Доступное время сегодня неизвестно' in client.get(url()).text
    state['edit'] = store.TrainingContextEdit(plan=store.WeekPlan(week_start=store.week_start(TODAY)))
    page = client.get(url())
    assert page.status_code == 200 and 'Плановое решение не строится' in page.text
    assert 'Не задан приоритет блока' in page.text


def test_reviewed_future_window_required_and_only_proposed(state):
    original = state['edit'].plan
    windows = original.windows + (store.DailyWindow(day=TODAY + timedelta(days=1),
        duration_minutes=150, confirmed=True),)
    state['edit'] = state['edit'].model_copy(update={'plan': original.model_copy(update={'windows': windows})})
    assert decision()['decision'].recommendation.action == 'SHORTEN'
    result = decision(reviewed_window='2026-10-31')
    assert result['decision'].recommendation.action == 'RESCHEDULE'
    assert result['decision'].recommendation.window_id == '2026-10-31'
    page = TestClient(app).get(url(reviewed_window='2026-10-31'))
    assert 'Предлагается перенести' in page.text
    assert state['edit'].plan.sessions == original.sessions and not state['writes']


def test_unknown_future_load_and_physiology_remain_unknown(state):
    state['activities'] = [dict(activity_id='uncovered', load=ActivityLoadAssessment(None, 'unavailable_metrics_record'))]
    result = decision()
    assert result['decision'].recommendation.action == 'SHORTEN'
    assert result['context'].completed[0].confirmed_plan_session_id is None
    assert not result['context'].physiology_available
    assert result['context'].future_windows is None
    page = TestClient(app).get(url())
    assert 'не считается нулевой' in page.text
    assert 'это не означает хорошее восстановление' in page.text
    assert 'Доступность 2026-10-31 неизвестна' in page.text


@pytest.mark.parametrize('patch,status', [({'minutes': '-1'}, 422), ({'minutes': '1.5'}, 422),
    ({'decision_day': '2026-10-29'}, 409), ({'revision': '9'}, 409),
    ({'session_id': 'foreign'}, 422), ({'reviewed_window': '2026-11-02'}, 422)])
def test_invalid_stale_inputs_do_not_write(state, patch, status):
    response = TestClient(app).post('/today/training-decision', data={**dict(decision_day=str(TODAY),
        revision='0', minutes='50', training_allowed='yes'), **patch})
    assert response.status_code == status
    assert not state['writes']


def test_security_storage_failure_and_old_permission(state, monkeypatch):
    client = TestClient(app)
    assert client.post('/today/training-decision', data={}, headers={'origin':'https://other.test'}).status_code == 403
    assert client.post('/today/training-decision', json={}).status_code == 415
    assert client.post('/today/training-decision', content='x'*16385,
        headers={'content-type':'application/x-www-form-urlencoded'}).status_code == 413
    old = training.today_decision('athlete', QueryParams('decision_day=2026-10-29&training_allowed=yes'))
    assert old['decision'].recommendation is None
    def fail(*a, **kw):
        raise RuntimeError('storage offline')
    monkeypatch.setattr(store, 'save_training_context', fail)
    response = client.post('/today/training-decision', data=dict(decision_day=str(TODAY), revision='0',
        minutes='65', training_allowed='yes'))
    assert response.status_code == 503 and 'value="65"' in response.text
    assert not state['writes']


def test_multiple_today_sessions_require_selection_and_substitute_is_policy_owned(state):
    plan = state['edit'].plan
    intensity = store.SavedSession(id='key', day=TODAY, session_type='intensity', duration_minutes=45, priority='key')
    state['edit'] = state['edit'].model_copy(update={'block_priority':'intensity',
        'plan':plan.model_copy(update={'sessions':plan.sessions+(intensity,)})})
    assert decision()['decision'].recommendation is None
    result = decision(session_id='long', intensity_allowed='yes', substitute='key')
    assert result['decision'].recommendation.action == 'SUBSTITUTE'
    assert result['decision'].recommendation.duration_minutes == 45
    assert 'SUBSTITUTE' in TestClient(app).get(url(session_id='long', intensity_allowed='yes', substitute='key')).text
    assert len(state['edit'].plan.sessions) == 2 and not state['writes']


def test_time_patch_preserves_future_windows_and_block_context(state):
    edit = state['edit']
    future = store.DailyWindow(day=TODAY + timedelta(days=1), duration_minutes=150, confirmed=True)
    state['edit'] = edit.model_copy(update={'plan':edit.plan.model_copy(update={'windows':edit.plan.windows+(future,)})})
    store.save_today_availability('athlete', today=TODAY, revision=0, duration_minutes=30)
    saved = state['edit']
    assert future in saved.plan.windows
    assert saved.plan.sessions == edit.plan.sessions and saved.block_priority == edit.block_priority
    assert next(w for w in saved.plan.windows if w.day == TODAY).duration_minutes == 30


def test_planned_decision_is_primary_and_readiness_is_supporting(state, monkeypatch):
    from dataclasses import replace
    base = service.get_today_data('athlete')
    readiness = dict(date=str(TODAY), recommendation='high_intensity', readiness_score=90,
        status_text='Высокая готовность', freshness_state='fresh', briefing_text='Baseline briefing')
    monkeypatch.setattr(service, 'get_today_data', lambda *a, **kw: replace(base, readiness=readiness))
    page = TestClient(app).get(url()).text
    assert '<h2 id="readiness-title">Готовность</h2>' in page
    assert 'Готовность и восстановление · дополнительный контекст</summary>' in page
    assert '<h1 id="readiness-title">' not in page
    assert 'Baseline briefing' in page and '>SHORTEN</span>' in page
    state['edit'] = store.TrainingContextEdit(plan=store.WeekPlan(week_start=store.week_start(TODAY)))
    fallback = TestClient(app).get('/today').text
    assert 'Базовая сводка по состоянию. Планового решения пока нет.' in fallback
    assert '<h1 id="readiness-title">' in fallback
