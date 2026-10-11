from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend.today import history_service as diary
from backend.today import service as today
import importlib

router = importlib.import_module('backend.today.router')


@pytest.mark.parametrize('rpe', ['all', 'missing'])
@pytest.mark.parametrize('failure', [False, True])
def test_diary_rpe_filter_uses_effective_score_and_preserves_calendar(monkeypatch, rpe, failure):
    target = date(2026, 8, 30)
    monkeypatch.setattr(today, 'get_local_today', lambda: target)
    users = []

    def activities(user, day):
        users.append((user, day))
        if failure:
            raise RuntimeError('private error')
        return [diary.DiaryActivity(
            ident, name, 'Ride', datetime(2026, 8, 30, 10, tzinfo=today.WHATTE_TZ),
            3600, score, source, web, strava, telegram, conflict)
            for ident, name, score, source, web, strava, telegram, conflict in [
                (1, 'Strava scored', 7, 'strava', None, 7, None, False),
                (2, 'Telegram scored', 6, 'telegram', None, None, 6, False),
                (3, 'Web scored', 5, 'web', 5, None, None, False),
                (4, 'Scored conflict', 7, 'strava', 4, 7, 6, True),
                (5, 'Missing score', None, None, None, None, None, False),
                (6, 'Unresolved Web observation', None, None, 4, None, None, False),
                (7, 'Stored zero', 0, 'strava', None, 0, None, False),
            ]]

    monkeypatch.setattr(diary, 'get_diary_activities', activities)
    monkeypatch.setattr(today, 'get_readiness_daily_calendar_history', lambda *a: [])
    monkeypatch.setattr(today, '_get_recovery_history', lambda *a: {})
    page = TestClient(app_module.app).get('/today/history', params={
        'rpe': rpe, 'user_id': 'someone_else'}).text
    assert users == [(router.settings.daily_readiness_user_id, target)]
    assert page.count('class="diary-day"') == 14
    assert page.count('class="diary-gap"') == 14
    assert f'href="/today/history?rpe={rpe}" aria-current="true"' in page
    assert '<script' not in page
    if failure:
        assert 'Без итогового RPE за 14 дней: количество недоступно' in page
        assert page.count('Не удалось загрузить тренировки') == 14
        assert 'Нет тренировок без RPE' not in page
        assert 'Нет записанных тренировок' not in page
        assert 'private error' not in page
    else:
        assert 'Без итогового RPE за 14 дней: 2' in page
        assert 'Missing score' in page and 'Unresolved Web observation' in page
        assert '/today?activity_id=5&amp;return_day=2026-08-30#rpe' in page
        assert '/today?activity_id=6&amp;return_day=2026-08-30#rpe' in page
        for name in ['Strava scored', 'Telegram scored', 'Web scored', 'Scored conflict', 'Stored zero']:
            assert (name in page) == (rpe == 'all')
        assert page.count('Нет тренировок без RPE' if rpe == 'missing' else 'Нет записанных тренировок') == 13


@pytest.mark.parametrize('raw', ['', 'unknown', 'MISSING', 'https://evil.example', '<script>'])
def test_diary_rejects_unknown_filter_before_read(monkeypatch, raw):
    def unexpected_read(*a):
        pytest.fail('invalid filter must not query diary')
    monkeypatch.setattr(router, 'get_diary_data', unexpected_read)
    response = TestClient(app_module.app).get('/today/history', params={'rpe': raw})
    assert response.status_code == 422


def test_empty_missing_rpe_filter_has_explicit_zero(monkeypatch):
    monkeypatch.setattr(today, 'get_local_today', lambda: date(2026, 8, 30))
    monkeypatch.setattr(diary, 'get_diary_activities', lambda *a: [])
    monkeypatch.setattr(today, 'get_readiness_daily_calendar_history', lambda *a: [])
    monkeypatch.setattr(today, '_get_recovery_history', lambda *a: {})
    page = TestClient(app_module.app).get('/today/history?rpe=missing').text
    assert 'Без итогового RPE за 14 дней: 0' in page
    assert page.count('Нет тренировок без RPE') == 14
    assert 'Не удалось загрузить тренировки' not in page


@pytest.mark.parametrize('failure', [None, 'history', 'activities', 'both'])
def test_diary_route_calendar_sections_and_access_boundary(monkeypatch, failure):
    target = date(2026, 8, 30)
    monkeypatch.setattr(today, 'get_local_today', lambda: target)
    users = []

    def activities(user, day):
        users.append(user)
        if failure in ('activities', 'both'):
            raise RuntimeError('private database error')
        return [diary.DiaryActivity(
            101, 'Workout <unsafe>', 'Ride', datetime(2026, 8, 30, 10, tzinfo=today.WHATTE_TZ),
            0, 7, 'strava', 4, 7, 6, True),
            diary.DiaryActivity(
            102, 'Second workout', 'Run', datetime(2026, 8, 30, 9, tzinfo=today.WHATTE_TZ),
            None, None, None, None, None, None, False)]

    def history(user, day):
        if failure in ('history', 'both'):
            raise RuntimeError('private database error')
        rows = [today.TodayHistoryRow(
            (target - diary.timedelta(days=i)).isoformat(),
            0 if i == 0 else 68 if i == 1 else None,
            'moderate' if i == 1 else None, 4 if i == 0 else None,
            'fresh' if i == 0 else None) for i in range(14)]
        return [today.TodayHistoryGroup(today.READINESS_MODEL_VERSION, True, rows),
                today.TodayHistoryGroup('legacy', False, [
                    today.TodayHistoryRow(str(target), 61, 'high_intensity', None, None)])]

    monkeypatch.setattr(diary, 'get_diary_activities', activities)
    monkeypatch.setattr(diary, 'get_today_history', history)
    response = TestClient(app_module.app).get('/today/history?user_id=someone_else')
    page = response.text
    assert response.status_code == 200
    assert users == [router.settings.daily_readiness_user_id]
    assert page.count('class="diary-day"') == 14
    assert '2026-08-17' in page
    assert 'href="/today/history" aria-current="page">Дневник</a>' in page
    assert 'private database error' not in page
    assert 'не неизменяемая история' in page
    assert '<script' not in page and '<form' not in page
    if failure not in ('history', 'both'):
        assert '0/100' in page and 'Нет готовности' in page and 'Нет оценки' in page
        assert '4/5' in page and 'Умеренная аэробная тренировка' in page
        assert page.count('class="diary-plot"') == 1
        assert 'Не определяется для этой версии' in page
        assert 'Высокоинтенсивная' not in page
    else:
        assert 'Готовность и утреннее самочувствие временно недоступны' in page
    if failure not in ('activities', 'both'):
        assert 'Workout &lt;unsafe&gt;' in page and 'Second workout' in page
        assert '0 ч 0 мин 0 с' in page and 'Нет длительности' in page
        assert '7/10 · Strava' in page and 'Web 4/10' in page
        assert '/today?activity_id=101&amp;return_day=2026-08-30#rpe' in page
        assert '/today?activity_id=102&amp;return_day=2026-08-30#rpe' in page
        assert 'Нет записанных тренировок' in page
    else:
        assert 'Не удалось загрузить тренировки' in page
        assert 'Нет записанных тренировок' not in page
    edge = (Path(__file__).parents[2] / 'infra/eu-edge/Caddyfile').read_text()
    assert '@private_surfaces path /dashboard* /today*' in edge
    assert 'basicauth' in edge and 'handle /today*' in edge


def test_today_overview_uses_only_latest_seven_days(monkeypatch):
    from dataclasses import replace
    from test_today import _today_data
    target = date(2026, 8, 30)
    rows = [today.TodayHistoryRow(str(target - diary.timedelta(days=i)),
                                  68, 'moderate', None, None) for i in range(14)]
    data = replace(_today_data(), history_groups=[
        today.TodayHistoryGroup(today.READINESS_MODEL_VERSION, True, rows)])
    monkeypatch.setattr(today, 'get_today_data', lambda *a, **k: data)
    page = TestClient(app_module.app).get('/today').text
    assert '2026-08-24' in page
    assert '2026-08-23' not in page and '2026-08-17' not in page
    assert 'Последние 7 дней' in page and 'Открыть дневник' in page
    assert 'class="history-table"' not in page


def test_empty_diary_has_fourteen_dates_and_explicit_missingness(monkeypatch):
    target = date(2026, 8, 30)
    monkeypatch.setattr(today, 'get_local_today', lambda: target)
    monkeypatch.setattr(diary, 'get_diary_activities', lambda *a: [])
    monkeypatch.setattr(today, 'get_readiness_daily_calendar_history', lambda *a: [])
    monkeypatch.setattr(today, '_get_recovery_history', lambda *a: {})
    page = TestClient(app_module.app).get('/today/history').text
    assert page.count('class="diary-day"') == 14
    assert page.count('class="diary-gap"') == 14
    assert page.count('Нет записанных тренировок') == 14
    assert page.count('Нет готовности') == 14
    assert 'Нет оценки' in page and 'Нет рекомендации' in page
    assert '/100' not in page


@pytest.mark.parametrize("save_fails", [False, True])
def test_historical_rpe_keeps_owned_activity_and_day_through_native_post(monkeypatch, save_fails):
    from dataclasses import replace
    from test_today import _today_data
    data = _today_data()
    activity = replace(data.activity, local_date="2026-08-27")
    selected = []
    writes = []
    monkeypatch.setattr(today, 'get_local_today', lambda: date(2026, 8, 30))
    def read(*args, preferred_activity_id=None):
        selected.append(preferred_activity_id)
        return replace(data, activity=activity)
    monkeypatch.setattr(today, 'get_today_data', read)
    monkeypatch.setattr(today, 'get_today_activity', lambda *a, **k: activity)
    def save(**kwargs):
        nonlocal activity
        writes.append(kwargs)
        if save_fails:
            raise RuntimeError('private save error')
        activity = replace(activity, rpe_web_score=6)
    monkeypatch.setattr(router, 'upsert_activity_rpe_v2', save)
    client = TestClient(app_module.app)
    url = f"/today?activity_id={activity.activity_id}&return_day=2026-08-27"
    page = client.get(url).text
    assert 'Оценка тренировки за 2026-08-27' in page
    assert 'Последняя подходящая тренировка' not in page
    assert 'Готовность выше относится к сегодняшнему дню' in page
    action = f"/today/rpe/{activity.activity_id}/6?return_day=2026-08-27"
    assert f'action="{action}"' in page
    response = client.post(action, follow_redirects=False)
    if save_fails:
        assert response.status_code == 503
        assert 'Не удалось сохранить RPE' in response.text
        assert 'private save error' not in response.text
        page = response.text
    else:
        assert response.status_code == 303
        assert response.headers['location'] == f"/today?saved=rpe&activity_id={activity.activity_id}&return_day=2026-08-27#rpe"
        page = client.get(response.headers['location']).text
        assert 'RPE сохранён в Web.' in page
    assert 'href="/today/history#day-2026-08-27"' in page
    assert set(selected) == {activity.activity_id}
    assert writes == [dict(activity_id=activity.activity_id, score=6, source='web')]


@pytest.mark.parametrize('raw', ['https://evil.example', '//evil.example', '2026-08-27#evil',
                                '2026-02-30', '2026-08-26', '2026-09-01', '2026-08-01', ''])
def test_invalid_return_context_never_becomes_a_link_or_redirect(monkeypatch, raw):
    from dataclasses import replace
    from test_today import _today_data
    data = _today_data()
    activity = replace(data.activity, local_date=raw if raw in ['2026-09-01', '2026-08-01'] else '2026-08-27')
    monkeypatch.setattr(today, 'get_local_today', lambda: date(2026, 8, 30))
    monkeypatch.setattr(today, 'get_today_data', lambda *a, **k: replace(data, activity=activity))
    monkeypatch.setattr(today, 'get_today_activity', lambda *a, **k: activity)
    monkeypatch.setattr(router, 'upsert_activity_rpe_v2', lambda **k: None)
    client = TestClient(app_module.app)
    page = client.get('/today', params={'activity_id': activity.activity_id, 'return_day': raw}).text
    assert 'Вернуться к дню в дневнике' not in page
    response = client.post(f'/today/rpe/{activity.activity_id}/6', params={'return_day': raw}, follow_redirects=False)
    assert response.headers['location'] == f'/today?saved=rpe&activity_id={activity.activity_id}#rpe'


def test_diary_and_today_figure_links_include_missing_days(monkeypatch):
    from dataclasses import replace
    from test_today import _today_data
    monkeypatch.setattr(today, 'get_local_today', lambda: date(2026, 8, 30))
    monkeypatch.setattr(diary, 'get_diary_activities', lambda *a: [])
    monkeypatch.setattr(today, 'get_readiness_daily_calendar_history', lambda *a: [])
    monkeypatch.setattr(today, '_get_recovery_history', lambda *a: {})
    client = TestClient(app_module.app)
    page = client.get('/today/history').text
    for i in range(14):
        day = str(date(2026, 8, 30) - diary.timedelta(days=i))
        assert f'id="day-{day}"' in page
        assert f'href="/today/history#day-{day}" aria-label="{day}: нет готовности' in page
    assert 'role="img"' not in page
    data = replace(_today_data(), history_groups=diary.get_diary_data('test', date(2026, 8, 30)).history_groups)
    monkeypatch.setattr(today, 'get_today_data', lambda *a, **k: data)
    page = client.get('/today').text
    assert 'Последняя подходящая тренировка' in page
    assert page.count('class="diary-point" href=') == 7
    assert 'href="/today/history#day-2026-08-24"' in page
