import importlib
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend import app as app_module
from backend.services import user_profile_service as profile
from backend.services.metrics_service import compute_power_metrics, compute_power_zones, compute_hr_zones

router = importlib.import_module('backend.today.router')


@pytest.mark.parametrize('metric,value', [('ftp', 0), ('ftp', float('nan')), ('ftp', float('inf')), ('ftp', 1001), ('weight', 501), ('weight', -3), ('hr_max', 0), ('hr_max', 251), ('hr_max', 190.5), ('hr_max', float('nan')), ('hr_max', float('inf'))])
def test_reject_invalid_values(metric, value):
    with pytest.raises(ValidationError):
        profile.ProfileChange(metric=metric, value=value, effective_from=date(2026, 7, 25))


def test_reject_future_date(monkeypatch):
    monkeypatch.setattr(profile, 'local_today', lambda: date(2026, 9, 5))
    with pytest.raises(ValidationError):
        profile.ProfileChange(metric='ftp', value=222, effective_from=date(2026, 9, 6))


def test_reported_workout_at_updated_ftp():
    result = compute_power_metrics([151.2] * 5406, 151.2, 222, 5406)
    assert result['tss'] == pytest.approx(69.658, abs=0.001)
    assert result['intensity_factor'] == pytest.approx(151.2 / 222)


def test_missing_zone_settings_remain_unavailable():
    assert all(v is None for v in compute_power_zones([150], [1], None, None, None, None, None, None).values())
    assert all(v is None for v in compute_hr_zones([130], [1], None, None, None, None).values())


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(profile, 'get_profile', lambda user: dict(
        current={'ftp': dict(value=222, effective_from=date(2026, 7, 25)),
                 'hr_max': dict(value=190, effective_from=date(2026, 7, 25))},
        history=[dict(metric='ftp', value=222, effective_from=date(2026, 7, 25))],
        today=date(2026, 9, 5), pending_from=date(2026, 7, 25)))
    return TestClient(app_module.app)


def test_profile_page(page):
    response = page.get('/today/profile')
    assert response.status_code == 200
    assert '222' in response.text
    assert '190' in response.text
    assert 'HR max' in response.text
    assert 'уд/мин' in response.text
    assert '2026-07-25' in response.text
    assert 'Не указан' in response.text
    assert '/today/profile/recompute' in response.text


def test_profile_form_uses_configured_user(page, monkeypatch):
    save = MagicMock()
    monkeypatch.setattr(profile, 'save_profile_value', save)
    response = page.post('/today/profile', data=dict(metric='weight', value='73.5', effective_from='2026-07-25'), follow_redirects=False)
    assert response.status_code == 303
    assert save.call_args.args[0] == router.settings.daily_readiness_user_id
    assert save.call_args.args[1].value == 73.5
    assert save.call_args.args[1].metric == 'weight'


@pytest.mark.parametrize('path', ['/today/profile', '/today/profile/recompute'])
def test_profile_cross_site_rejected(page, path):
    assert page.post(path, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert page.post(path, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403


def test_bad_form_does_not_save(page, monkeypatch):
    save = MagicMock()
    monkeypatch.setattr(profile, 'save_profile_value', save)
    response = page.post('/today/profile', data=dict(metric='weight', value='nan', effective_from='2026-07-25'))
    assert response.status_code == 422
    save.assert_not_called()


def test_recompute_failure_is_visible(page, monkeypatch):
    monkeypatch.setattr(profile, 'recompute_profile_history', MagicMock(side_effect=RuntimeError('secret database detail')))
    response = page.post('/today/profile/recompute')
    assert response.status_code == 503
    assert 'Пересчёт не завершён' in response.text
    assert 'secret database detail' not in response.text


def test_recompute_retry_preserves_pending_until_all_stages_finish(monkeypatch):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (date(2026, 7, 25),)
    cur.fetchall.return_value = [(10, True), (20, False)]
    @contextmanager
    def lock(user):
        yield conn
    monkeypatch.setattr(profile, '_profile_lock', lock)
    pipeline = importlib.import_module('backend.services.pipeline_service')
    response = importlib.import_module('backend.services.activity_response_service')
    dedup = importlib.import_module('backend.services.activity_deduplication_service')
    stages = []
    compute = MagicMock(side_effect=[None, RuntimeError('failed')])
    monkeypatch.setattr(pipeline, 'compute_and_store_activity_metrics', compute)
    monkeypatch.setattr(response, 'compute_and_store_activity_response', lambda id: stages.append(('response', id)))
    monkeypatch.setattr(dedup, 'recompute_after_activity_state_change', lambda *args, **kwargs: stages.append(('states', args)))
    with pytest.raises(RuntimeError):
        profile.recompute_profile_history('test')
    assert not any('set needs_recompute = false' in c.args[0] for c in cur.execute.call_args_list)
    conn.commit.assert_not_called()
    monkeypatch.setattr(pipeline, 'compute_and_store_activity_metrics', lambda id: stages.append(('metrics', id)))
    assert profile.recompute_profile_history('test') == 2
    assert [s[0] for s in stages] == ['metrics', 'metrics', 'response', 'states']
    conn.commit.assert_called_once()


@pytest.mark.parametrize('data', [
    'metric=ftp&metric=weight&value=222&effective_from=2026-07-25',
    'metric=ftp&value=222&effective_from=2026-07-25&user_id=other',
])
def test_malformed_form_rejected(page, data):
    assert page.post('/today/profile', content=data,
                     headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 422


@pytest.mark.parametrize('value', [1, 190, 250])
def test_hr_max_accepts_whole_number_limits(value):
    assert profile.ProfileChange(metric='hr_max', value=value, effective_from=date(2026, 7, 25)).value == value


def test_hr_max_form_uses_configured_user(page, monkeypatch):
    save = MagicMock()
    monkeypatch.setattr(profile, 'save_profile_value', save)
    response = page.post('/today/profile', data=dict(metric='hr_max', value='195', effective_from='2026-07-25'), follow_redirects=False)
    assert response.status_code == 303
    assert save.call_args.args[0] == router.settings.daily_readiness_user_id
    assert save.call_args.args[1].metric == 'hr_max'
    assert save.call_args.args[1].value == 195


@pytest.mark.parametrize('value', ['190.5', '251'])
def test_invalid_hr_max_form_does_not_save(page, monkeypatch, value):
    save = MagicMock()
    monkeypatch.setattr(profile, 'save_profile_value', save)
    response = page.post('/today/profile', data=dict(metric='hr_max', value=value, effective_from='2026-07-25'))
    assert response.status_code == 422
    assert 'HR max' in response.text
    save.assert_not_called()


def test_profile_shared_navigation_and_empty_state(page, monkeypatch):
    monkeypatch.setattr(profile, 'get_profile', lambda user: dict(
        current={}, history=[], today=date(2026, 9, 5), pending_from=None))
    response = page.get('/today/profile?saved=true')
    assert '<html lang="ru">' in response.text
    assert 'href="/today">Сегодня</a>' in response.text
    assert 'href="/today/profile" aria-current="page">Профиль</a>' in response.text
    assert 'Пока нет записей.' in response.text
    assert 'Значение сохранено.' in response.text
