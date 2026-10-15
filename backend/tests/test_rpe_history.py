from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import importlib

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import app as app_module
from backend.services import rpe_history_service as service


def session(activity_id=1, **changes):
    return {"activity_id": activity_id, "user_id": "athlete", "sport": "Ride",
            "started_at": datetime(2026, 10, 10, tzinfo=timezone.utc) - timedelta(days=activity_id),
            "duration_s": 3600, "np_w": 200., "if": .8, "tss": 64., "vi": 1.05,
            "rpe": 7, "source": "web", "scale": "rpe_1_10", **changes}


def test_ranking_summary_and_minimum():
    target = session()
    candidates = [session(i, rpe=i+2) for i in range(2, 8)]
    result = service.build_context(target, list(reversed(candidates)))
    assert result == service.build_context(target, candidates)
    assert result['count'] == 5
    assert [row['activity_id'] for row in result['matches']] == [2, 3, 4, 5, 6]
    assert result['median'] == 6 and result['range'] == [4, 8]
    assert result['matches'][0]['historical_ftp_w'] == 250
    assert result['matches'][0]['match_quality'] == 'reduced'
    assert service.build_context(target, candidates[:2])['matches'] == []


@pytest.mark.parametrize('changes', [
    {'activity_id': 1}, {'user_id': 'other'}, {'sport': 'VirtualRide'},
    {'started_at': session()['started_at']},
    {'started_at': session()['started_at'] + timedelta(days=1)},
    {'rpe': 0}, {'rpe': 11}, {'rpe': True}, {'scale': 'rpe_1_5'},
    {'np_w': None}, {'if': None}, {'duration_s': 0}, {'vi': None},
    {'if': float('nan')}, {'np_w': float('inf')},
    {'duration_s': 4600}, {'if': .94}, {'np_w': 250}, {'vi': 1.2},
    {'np_w': 230., 'if': .7},  # Similar NP/IF separately but incompatible FTP.
    {'duration_s': 4400, 'if': .89},  # Pass individual gates, fail quality.
])
def test_boundary_rejections(changes):
    assert service.compare_sessions(session(), {**session(2), **changes}) is None


def test_tss_does_not_double_count_and_no_power_no_guidance():
    assert service.compare_sessions(session(), session(2, tss=None))['quality'] == 1
    assert service.compare_sessions(session(np_w=None), session(2)) is None


class Cursor:
    def __init__(self, target):
        self.target = target
        self.calls = []
    def execute(self, sql, params):
        self.calls.append((sql, params))
    def fetchone(self):
        return tuple(self.target.values()) if self.target else None
    def fetchall(self):
        return [tuple(session(i).values()) for i in range(2, 5)]


def test_query_bounds_and_owner_on_all_joins(monkeypatch):
    cur = Cursor(session())
    class Conn:
        def cursor(self):
            return nullcontext(cur)
    monkeypatch.setattr(service, 'get_conn', lambda: nullcontext(Conn()))
    assert service.get_rpe_history('athlete', 1)['status'] == 'available'
    sql, params = cur.calls[-1]
    assert params == ('athlete', 1, 'Ride', session()['started_at'], session()['started_at'], 'rpe_1_10', 200)
    for text in ('m.user_id = r.user_id', 'er.user_id = r.user_id',
                 'obs.user_id = r.user_id', 'obs.source = er.effective_source',
                 'obs.score = er.effective_score', "interval '365 days'", 'limit %s',
                 'r.start_date <= now()', 'r.is_deleted = false', 'r.is_excluded = false'):
        assert text in sql
    cur.target = None
    with pytest.raises(HTTPException) as exc:
        service.get_rpe_history('other', 1)
    assert exc.value.status_code == 404


def test_route_requires_selection_and_never_writes(monkeypatch):
    router = importlib.import_module('backend.today.router')
    calls = []
    def history(user_id, activity_id):
        calls.append((user_id, activity_id))
        return service.build_context(session(), [session(i) for i in range(2, 5)])
    monkeypatch.setattr(router, 'get_rpe_history', history)
    client = TestClient(app_module.app)
    for query in ('', '?score=0', '?score=11'):
        assert client.get('/today/rpe-context/1' + query).status_code == 422
    assert not calls
    response = client.get('/today/rpe-context/1?score=6&fragment=true')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert 'Медианная оценка' in response.text
    assert 'https://www.strava.com/activities/2' in response.text
    assert calls == [(router.settings.daily_readiness_user_id, 1)]
    monkeypatch.setattr(router, 'get_rpe_history', lambda *args: (_ for _ in ()).throw(RuntimeError()))
    assert client.get('/today/rpe-context/1?score=6&fragment=true').status_code == 503


def test_same_time_ties_use_id_and_tolerance_is_not_equivalence():
    target = session()
    rows = [session(i, started_at=session(2)['started_at']) for i in (2, 3, 4)]
    result = service.build_context(target, rows)
    assert [row['activity_id'] for row in result['matches']] == [4, 3, 2]
    assert service.compare_sessions(target, session(2, duration_s=4000))['quality'] < 1
    assert service.compare_sessions(target, session(2, sport='Run')) is None


def test_native_preview_and_error_preserve_independent_draft(monkeypatch):
    router = importlib.import_module('backend.today.router')
    captured = []
    from fastapi.responses import HTMLResponse
    def page(request, **kwargs):
        captured.append(kwargs)
        return HTMLResponse('preview')
    monkeypatch.setattr(router, '_today_page', page)
    monkeypatch.setattr(router, 'get_rpe_history', lambda *args: service.build_context(session(), []))
    client = TestClient(app_module.app)
    response = client.get('/today/rpe-context/1?score=8&return_day=2026-10-09')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert captured[-1]['rpe_draft'] == 8
    assert captured[-1]['return_day'] == '2026-10-09'
    assert captured[-1]['rpe_history']['status'] == 'insufficient_data'
    monkeypatch.setattr(router, 'get_rpe_history', lambda *args: (_ for _ in ()).throw(RuntimeError()))
    assert client.get('/today/rpe-context/1?score=9').status_code == 200
    assert captured[-1]['rpe_draft'] == 9
    assert captured[-1]['rpe_history']['status'] == 'error'
