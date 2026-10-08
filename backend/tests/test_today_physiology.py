"""Optional Today collection shares API persistence and keeps the daily loop intact."""
import importlib
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend.config import settings
from backend.services import manual_physiology_service as physiology
from backend.today import service as today_service
from test_today import _today_data, _readiness
from test_manual_physiology_service import Connection, Cursor, observation

today_router = importlib.import_module("backend.today.router")
GET_TODAY_DATA = today_service.get_today_data
DAY = date(2026, 9, 30)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(today_service, "get_today_data", lambda *args, **kwargs: replace(_today_data(), today=DAY.isoformat()))
    monkeypatch.setattr(today_service, "get_local_today", lambda: DAY)
    monkeypatch.setattr(physiology, "local_today", lambda: DAY)
    return TestClient(app_module.app)


def test_missing_and_partial_records_render_independently(client, monkeypatch):
    page = client.get("/today").text
    assert page.index('id="rpe-title"') < page.index('id="manual-physiology-title"')
    assert 'action="/today/physiology"' in page
    assert 'name="local_date" value="2026-09-30"' in page
    assert '<details class="physiology-editor" >' in page
    assert page.count('>unavailable</span>') >= 4
    current = observation(sleep_duration_minutes=0, hrv_ms=None, sleep_quality=None)
    monkeypatch.setattr(today_service, "get_today_data", lambda *args, **kwargs: replace(
        _today_data(), today=DAY.isoformat(), manual_physiology=current.model_dump(),
    ))
    page = client.get("/today").text
    assert 'name="sleep_duration_minutes"' in page
    assert 'value="0"' in page
    assert 'Source telegram' in page
    assert 'name="hrv_ms" type="number" step="any" min="0" max="500" value=""' in page


def test_form_partial_clear_and_repeat_use_real_persistence(client, monkeypatch):
    current = observation(user_id=settings.daily_readiness_user_id, source="web")
    saved = current.model_copy(update={"sleep_quality": 5, "hrv_ms": None, "revision": 2})
    cursor = Cursor(current=current, saved=saved)
    monkeypatch.setattr(physiology, "get_conn", lambda: Connection(cursor))
    response = client.post("/today/physiology", data={
        "local_date": DAY.isoformat(), "sleep_quality": "5",
        "sleep_duration_minutes": "", "hrv_ms": "58", "clear_hrv_ms": "1",
    }, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/today?saved=physiology"
    update = next(params for sql, params in cursor.calls if "update manual_physiology_observation set" in sql)
    assert update[:5] == (450, 5, None, 49.0, "web")
    assert any("insert into manual_physiology_observation_revision" in sql for sql, _ in cursor.calls)
    repeat_cursor = Cursor(current=saved)
    monkeypatch.setattr(physiology, "get_conn", lambda: Connection(repeat_cursor))
    assert client.post("/today/physiology", data={
        "local_date": DAY.isoformat(), "sleep_quality": "5", "clear_hrv_ms": "1",
    }, follow_redirects=False).status_code == 303
    assert not any("insert" in sql or "update manual_physiology_observation set" in sql for sql, _ in repeat_cursor.calls)


def test_api_and_today_read_the_same_record(client, monkeypatch):
    current = observation(user_id=settings.daily_readiness_user_id)
    saved = current.model_copy(update={"hrv_ms": 62.5, "source": "web", "revision": 2})
    cursor = Cursor(current=current, saved=saved)
    monkeypatch.setattr(physiology, "get_conn", lambda: Connection(cursor))
    assert client.post("/today/physiology", data={
        "local_date": DAY.isoformat(), "hrv_ms": "62.5",
    }, follow_redirects=False).status_code == 303
    # Use the shared read service for both HTTP surfaces with a database row.
    class ReadCursor(Cursor):
        def execute(self, sql, params):
            self.calls.append((sql, params))
            self.fetchone_values.append(self.saved)
    monkeypatch.setattr(physiology, "get_conn", lambda: Connection(ReadCursor(saved=saved)))
    monkeypatch.setattr(settings, "manual_physiology_api_token", "test-token")
    api = client.get(f"/api/v1/manual-physiology/{DAY}", headers={"Authorization": "Bearer test-token"}).json()
    monkeypatch.setattr(today_service, "get_latest_readiness_daily", lambda *args, **kwargs: _readiness())
    monkeypatch.setattr(today_service, "_get_today_recovery", lambda *args: None)
    monkeypatch.setattr(today_service, "get_today_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(today_service, "get_today_history", lambda *args: [])
    data = GET_TODAY_DATA(settings.daily_readiness_user_id,
        now=datetime(2026, 9, 30, 9, tzinfo=ZoneInfo("Europe/Moscow")))
    assert data.manual_physiology["hrv_ms"] == api["fields"]["hrv_ms"]["value"] == 62.5
    assert data.manual_physiology["source"] == api["source"] == "web"


@pytest.mark.parametrize("field,value", [
    ("sleep_duration_minutes", "1441"), ("sleep_duration_minutes", "1.5"),
    ("sleep_quality", "6"), ("hrv_ms", "0"), ("hrv_ms", "nan"),
    ("resting_hr_bpm", "19"), ("resting_hr_bpm", "inf"),
])
def test_invalid_field_preserves_input_without_write(client, monkeypatch, field, value):
    monkeypatch.setattr(today_router, "save_manual_physiology_observation", lambda **kwargs: pytest.fail("invalid write"))
    response = client.post("/today/physiology", data={"local_date": DAY.isoformat(), field: value})
    assert response.status_code == 422
    assert 'aria-invalid="true"' in response.text
    assert f'value="{value}"' in response.text
    assert 'role="alert"' in response.text
    assert 'class="physiology-editor" open' in response.text


@pytest.mark.parametrize("payload,status", [
    ({"local_date": "2026-09-29", "hrv_ms": "60"}, 409),
    ({"local_date": "2026-10-01", "hrv_ms": "60"}, 409),
    ({"local_date": "invalid", "hrv_ms": "60"}, 422),
    ({"local_date": DAY.isoformat(), "hrv_ms": ""}, 422),
    ({"local_date": DAY.isoformat(), "user_id": "other", "hrv_ms": "60"}, 422),
    ({"local_date": DAY.isoformat(), "clear_hrv_ms": "invalid"}, 422),
])
def test_invalid_or_empty_forms_do_not_write(client, monkeypatch, payload, status):
    monkeypatch.setattr(today_router, "save_manual_physiology_observation", lambda **kwargs: pytest.fail("invalid write"))
    assert client.post("/today/physiology", data=payload).status_code == status


def test_duplicate_fields_and_cross_site_requests_rejected(client, monkeypatch):
    monkeypatch.setattr(today_router, "save_manual_physiology_observation", lambda **kwargs: pytest.fail("invalid write"))
    payload = urlencode([("local_date", DAY.isoformat()), ("hrv_ms", "60"), ("hrv_ms", "61")])
    assert client.post("/today/physiology", content=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 422
    for headers in ({"Sec-Fetch-Site": "cross-site"}, {"Origin": "https://other.example"}):
        assert client.post("/today/physiology", data={"hrv_ms": "60"}, headers=headers).status_code == 403
    assert client.post("/today/physiology", json={"hrv_ms": 60}).status_code == 415


def test_write_failure_preserves_input_and_never_claims_success(client, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("internal database detail")
    monkeypatch.setattr(today_router, "save_manual_physiology_observation", fail)
    response = client.post("/today/physiology", data={"local_date": DAY.isoformat(), "hrv_ms": "60"})
    assert response.status_code == 503
    assert 'value="60"' in response.text
    assert "Physiology could not be saved" in response.text
    assert "Physiology saved." not in response.text
    assert "internal database detail" not in response.text


def test_read_failure_does_not_break_primary_sections(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("internal database detail")
    monkeypatch.setattr(today_service, "get_manual_physiology_observation", fail)
    monkeypatch.setattr(today_service, "get_latest_readiness_daily", lambda *args, **kwargs: _readiness())
    monkeypatch.setattr(today_service, "_get_today_recovery", lambda *args: None)
    monkeypatch.setattr(today_service, "get_today_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(today_service, "get_today_history", lambda *args: [])
    data = today_service.get_today_data("sergey")
    assert data.readiness_section.status == "ok"
    assert data.manual_physiology_section.status == "error"
    monkeypatch.setattr(today_service, "get_today_data", lambda *args, **kwargs: data)
    response = TestClient(app_module.app).get("/today")
    assert response.status_code == 200
    assert "Manual physiology is temporarily unavailable" in response.text
    assert "internal database detail" not in response.text
    assert "How do you feel today?" in response.text
    assert "How did the workout feel?" in response.text


def test_full_entry_creates_shared_observation_with_configured_user(client, monkeypatch):
    saved = observation(user_id=settings.daily_readiness_user_id, source="web", observed_at=None)
    cursor = Cursor(saved=saved)
    monkeypatch.setattr(physiology, "get_conn", lambda: Connection(cursor))
    response = client.post("/today/physiology", data={
        "local_date": DAY.isoformat(), "sleep_duration_minutes": "450",
        "sleep_quality": "4", "hrv_ms": "58", "resting_hr_bpm": "49",
    }, follow_redirects=False)
    assert response.status_code == 303
    params = next(params for sql, params in cursor.calls
                  if "insert into manual_physiology_observation (" in sql)
    assert params[:7] == (settings.daily_readiness_user_id, DAY, 450, 4, 58.0, 49.0, "web")
    assert any("insert into manual_physiology_observation_revision" in sql for sql, _ in cursor.calls)
