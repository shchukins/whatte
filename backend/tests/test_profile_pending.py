from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from backend import app as app_module
from backend.services import user_profile_service as profile
from backend.today import service as today
from backend.today import history_service as diary


@pytest.mark.parametrize('rows', [[], [('ftp', date(2026, 7, 25))], [('hr_max', date(2026, 8, 1))], [('ftp', date(2026, 7, 25)), ('hr_max', date(2026, 8, 1))]])
def test_pending_query_scoped_aggregate_read_only(monkeypatch, rows):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = rows
    @contextmanager
    def connection():
        yield conn
    monkeypatch.setattr(profile, 'get_conn', connection)
    assert profile.get_pending_profile_recompute('test-user') == dict(rows)
    query, params = cur.execute.call_args.args
    assert params == ('test-user',)
    assert 'min(effective_from)' in query and 'group by metric' in query
    assert "metric in ('ftp', 'hr_max')" in query and 'needs_recompute' in query
    assert query.strip().startswith('select')
    cur.execute.assert_called_once()
    conn.commit.assert_not_called()


@pytest.mark.parametrize('path', ['/today', '/today/history'])
@pytest.mark.parametrize('state', ['empty', 'ftp', 'hr_max', 'mixed', 'error'])
def test_notice_states_and_failure_isolation(monkeypatch, path, state):
    from test_today import _readiness
    monkeypatch.setattr(today, 'get_latest_readiness_daily', lambda *a, **k: _readiness())
    monkeypatch.setattr(today, '_get_today_recovery', lambda *a: None)
    monkeypatch.setattr(today, 'get_today_activity', lambda *a, **k: None)
    monkeypatch.setattr(today, 'get_today_history', lambda *a: [])
    monkeypatch.setattr(today, 'get_manual_physiology_observation', lambda **k: None)
    monkeypatch.setattr(diary, 'get_diary_activities', lambda *a: [])
    monkeypatch.setattr(diary, 'get_today_history', lambda *a: [])
    pending = {}
    if state in ('ftp', 'mixed'):
        pending['ftp'] = date(2026, 7, 25)
    if state in ('hr_max', 'mixed'):
        pending['hr_max'] = date(2026, 8, 1)
    read = MagicMock(return_value=pending)
    if state == 'error':
        read.side_effect = RuntimeError('private database detail')
    monkeypatch.setattr(today, 'get_pending_profile_recompute', read)
    recompute, save = MagicMock(), MagicMock()
    monkeypatch.setattr(profile, 'recompute_profile_history', recompute)
    monkeypatch.setattr(profile, 'save_profile_value', save)
    page = TestClient(app_module.app).get(path + '?user_id=other')
    assert page.status_code == 200
    read.assert_called_once_with(today.settings.daily_readiness_user_id)
    recompute.assert_not_called()
    save.assert_not_called()
    assert 'private database detail' not in page.text
    assert ('FTP изменён с 2026-07-25' in page.text) == ('ftp' in pending)
    assert ('HR max изменён с 2026-08-01' in page.text) == ('hr_max' in pending)
    if 'ftp' in pending:
        assert 'Связанные расчёты TSS, отклика на тренировки и готовности ожидают обновления' in page.text
    if 'hr_max' in pending:
        assert 'Метаданные тренировок ожидают обновления; HR max не меняет TSS или готовность' in page.text
    if state == 'error':
        assert 'Актуальность связанных расчётов не подтверждена' in page.text
    assert ('href="/today/profile#profile-pending-title"' in page.text) == (state != 'empty')
    assert ('Утренний отчёт' if path == '/today' else 'Последние 14 дней') in page.text


@pytest.mark.parametrize('path', ['/today', '/today/history'])
def test_notice_disappears_after_successful_recompute(monkeypatch, path):
    from dataclasses import replace
    from test_today import _today_data
    pending = {'ftp': date(2026, 7, 25)}
    monkeypatch.setattr(today, 'get_pending_profile_recompute', lambda *a: pending.copy())
    def data(*a, **k):
        state, section = today.get_profile_pending('test')
        return replace(_today_data(), profile_pending=state, profile_pending_section=section)
    monkeypatch.setattr(today, 'get_today_data', data)
    monkeypatch.setattr(diary, 'get_diary_activities', lambda *a: [])
    monkeypatch.setattr(diary, 'get_today_history', lambda *a: [])
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (date(2026, 7, 25),)
    cur.fetchall.return_value = []
    @contextmanager
    def lock(user):
        yield conn
    monkeypatch.setattr(profile, '_profile_lock', lock)
    def execute(query, params):
        if 'set needs_recompute = false' in query:
            pending.clear()
    cur.execute.side_effect = execute
    monkeypatch.setattr(profile, 'get_profile', lambda *a: dict(current={}, history=[], today=date(2026, 8, 30), pending_from=None))
    client = TestClient(app_module.app)
    assert 'FTP изменён' in client.get(path).text
    assert client.post('/today/profile/recompute', follow_redirects=False).status_code == 200
    conn.commit.assert_called_once()
    assert 'FTP изменён' not in client.get(path).text
