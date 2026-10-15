"""PED robust statistics, temporal guards and the read-only surface."""
from contextlib import nullcontext
from datetime import timedelta
import importlib

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import app as app_module
from backend.services import effort_baseline_service as service
from backend.services import rpe_history_service as history
from test_rpe_history import session

NOW = session()['started_at'] + timedelta(days=1)


def evidence(activity_id=1, **changes):
    row = session(activity_id)
    row.update({key: row['started_at'] + timedelta(hours=2) for key in service.AVAILABILITY_FIELDS})
    return {**row, 'rpe_observed_at': None, **changes}


def calculate(rows=None, target=None):
    return service.build_effort_deviation(
        target or evidence(), rows if rows is not None else [evidence(i) for i in (2, 3, 4)],
        computed_at=NOW)


@pytest.mark.parametrize('actual,ped,comparison', [(8, 2, 'above_median'),
    (4, -2, 'below_median'), (6, 0, 'at_median')])
def test_robust_baseline_outlier_and_neutral_comparison(actual, ped, comparison):
    rows = [evidence(i, rpe=score) for i, score in zip(range(2, 7), [5, 6, 6, 7, 10])]
    result = calculate(rows, evidence(rpe=actual))
    assert result == calculate(list(reversed(rows)), evidence(rpe=actual))
    assert result['expected_rpe'] == 6
    assert result['ped'] == ped and result['comparison'] == comparison
    assert result['dispersion'] == {'method': 'median_absolute_deviation', 'mad': 1, 'range': [5, 10]}
    assert result['reliability'] == 'limited' and not result['as_of_reproducible']
    assert result['actual_reference']['source'] == 'web'
    assert [row['activity_id'] for row in result['source_references']] == [2, 3, 4, 5, 6]


def test_even_sample_median():
    result = calculate([evidence(i, rpe=score) for i, score in zip(range(2, 6), [5, 6, 7, 8])])
    assert result['expected_rpe'] == 6.5 and result['ped'] == .5
    assert result['dispersion']['mad'] == 1


@pytest.mark.parametrize('changes', [
    {'activity_id': 1}, {'started_at': session()['started_at']},
    {'started_at': NOW}, {'started_at': session()['started_at'] - timedelta(days=366)},
    {'user_id': 'other'}, {'sport': 'VirtualRide'}, {'np_w': None},
    {'rpe': 4, 'scale': 'rpe_1_5'}, {'rpe': True}, {'source': 'unknown'},
    *[{key: session()['started_at']} for key in service.AVAILABILITY_FIELDS],
    *[{key: NOW} for key in service.AVAILABILITY_FIELDS],
    *[{key: None} for key in service.AVAILABILITY_FIELDS],
    {'rpe_observed_at': NOW},
])
def test_future_late_edits_unknown_availability_and_incompatible_history(changes):
    result = calculate([evidence(2), evidence(3), {**evidence(4), **changes}])
    assert result['status'] == 'unavailable' and result['sample_count'] == 2
    assert result['expected_rpe'] is None and result['ped'] is None
    assert result['dispersion'] is None and result['reliability'] == 'unavailable'


def test_event_time_is_not_receipt_time_and_window_inclusive():
    old = session()['started_at'] - timedelta(days=365)
    row = evidence(4, started_at=old, rpe_observed_at=old)
    assert calculate([evidence(2), evidence(3), row])['status'] == 'available'
    row['rpe_received_at'] = NOW
    assert calculate([evidence(2), evidence(3), row])['status'] == 'unavailable'


@pytest.mark.parametrize('changes', [{'rpe': None}, {'scale': 'rpe_1_5'}, {'rpe': 0}])
def test_missing_actual_retains_baseline_without_deviation(changes):
    result = calculate(target=evidence(**changes))
    assert result['expected_rpe'] == 7 and result['ped'] is None
    assert result['actual_rpe'] is None and result['status'] == 'unavailable'
    assert result['reason_codes'] == ['actual_rpe_missing_or_incompatible']


def test_future_target_and_no_power():
    assert calculate(target=evidence(started_at=NOW + timedelta(days=1)))['expected_rpe'] is None
    assert calculate(target=evidence(np_w=None))['expected_rpe'] is None


def test_sql_filters_availability_before_limit_and_keeps_effective_source(monkeypatch):
    class Cursor:
        calls = []
        def execute(self, sql, params):
            self.calls.append((sql, params))
        def fetchone(self):
            return tuple(evidence().get(key) for key in history.FIELDS)
        def fetchall(self):
            return [tuple(evidence(i).get(key) for key in history.FIELDS) for i in (2, 3, 4)]
    cur = Cursor()
    class Conn:
        def cursor(self):
            return nullcontext(cur)
    monkeypatch.setattr(history, 'get_conn', lambda: nullcontext(Conn()))
    assert service.get_effort_deviation('athlete', 1)['status'] == 'available'
    sql, params = cur.calls[-1]
    for field in ('r.updated_at', 'm.computed_at', 'obs.received_at', 'er.resolved_at', 'obs.observed_at'):
        assert sql.index(field + ' < %s') < sql.index('limit %s')
    assert 'obs.source = er.effective_source' in sql
    assert params[-6:] == (session()['started_at'],) * 5 + (200,)
    assert params[0] == 'athlete'


def test_json_route_owned_read_only_and_failure(monkeypatch):
    router = importlib.import_module('backend.today.router')
    calls = []
    def get(user_id, activity_id):
        calls.append((user_id, activity_id))
        return calculate()
    monkeypatch.setattr(router, 'get_effort_deviation', get)
    client = TestClient(app_module.app)
    response = client.get('/today/effort-deviation/1?user_id=other')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['version'] == service.VERSION
    assert response.json()['computed_at'] == NOW.isoformat()
    assert calls == [(router.settings.daily_readiness_user_id, 1)]
    assert client.post('/today/effort-deviation/1').status_code == 405
    def missing(*args):
        raise HTTPException(404, 'missing')
    monkeypatch.setattr(router, 'get_effort_deviation', missing)
    assert client.get('/today/effort-deviation/1').status_code == 404
    def failure(*args):
        raise RuntimeError('database')
    monkeypatch.setattr(router, 'get_effort_deviation', failure)
    assert client.get('/today/effort-deviation/1').status_code == 503


@pytest.mark.parametrize('result', [calculate(), calculate([]), calculate(target=evidence(rpe=None)), {'status': 'error'}])
def test_presentation_states_and_stored_score_label(result):
    router = importlib.import_module('backend.today.router')
    html = router.templates.env.get_template('today/rpe_history.html').render(
        rpe_history={'status': 'insufficient_data', 'ped': result})
    assert 'PED' in html and 'не вывод об усталости' in html
    if result['status'] == 'available':
        assert 'Сохранённый RPE' in html and 'Черновик выбора сюда не входит' in html
        assert 'Надёжность ограничена' in html
    else:
        assert 'недоступ' in html


def test_history_fragment_saved_actual_and_ped_failure_isolation(monkeypatch):
    router = importlib.import_module('backend.today.router')
    monkeypatch.setattr(router, 'get_rpe_history', lambda *args: history.build_context(
        evidence(), [evidence(i) for i in (2, 3, 4)]))
    monkeypatch.setattr(router, 'get_effort_deviation', lambda *args: calculate(target=evidence(rpe=8)))
    client = TestClient(app_module.app)
    response = client.get('/today/rpe-context/1?score=3&fragment=true')
    assert response.status_code == 200
    assert 'Сохранённый RPE: <strong>8/10' in response.text
    assert 'Разница PED: <strong>+1' in response.text
    def failure(*args):
        raise RuntimeError('database')
    monkeypatch.setattr(router, 'get_effort_deviation', failure)
    response = client.get('/today/rpe-context/1?score=3&fragment=true')
    assert response.status_code == 200
    assert 'Медианная оценка' in response.text
    assert 'Сравнение усилия временно недоступно' in response.text
