from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend.today import history_service as diary
from backend.today import service as today
import importlib

router = importlib.import_module('backend.today.router')


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
        assert '/today?activity_id=101#rpe' in page and '/today?activity_id=102#rpe' in page
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
