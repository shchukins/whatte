import json

import pytest
from fastapi import HTTPException

from backend.services import readiness_daily


class _FakeCursor:
    def __init__(self, load_row, recovery_row) -> None:
        self._load_row = load_row
        self._recovery_row = recovery_row
        self._last_query = ""
        self.insert_params: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        self._last_query = query
        if "insert into readiness_daily" in query:
            self.insert_params.append(params)

    def fetchone(self):
        if "from load_state_daily_v2" in self._last_query:
            return self._load_row
        if "from health_recovery_daily" in self._last_query:
            return self._recovery_row
        return None


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


def _build_result(monkeypatch, *, load_row, recovery_row):
    fake_cursor = _FakeCursor(load_row=load_row, recovery_row=recovery_row)
    fake_conn = _FakeConn(fake_cursor)

    monkeypatch.setattr(readiness_daily, "get_conn", lambda: fake_conn)

    result = readiness_daily.recompute_readiness_daily_for_date(
        user_id="user-1",
        target_date="2026-04-16",
    )
    explanation_json = json.loads(fake_cursor.insert_params[0][8])
    return result, explanation_json, fake_cursor, fake_conn


def test_recompute_readiness_daily_uses_full_formula_and_propagates_recovery_explanation(monkeypatch):
    recovery_explanation = {"method": "baseline_v2", "sleep_score": 82.8}

    result, explanation_json, fake_cursor, fake_conn = _build_result(
        monkeypatch,
        load_row=(5.0,),
        recovery_row=(70.0, json.dumps(recovery_explanation)),
    )

    assert result["fallback_mode"] is None
    assert result["freshness"] == 5.0
    assert result["freshness_norm"] == 55.0
    assert result["recovery_score_simple"] == 70.0
    assert result["readiness_score_raw"] == 61.0
    assert result["readiness_score"] == 61.0
    assert result["good_day_probability"] == 0.61
    assert result["recommendation"] == "moderate"
    assert "Readiness score is 61/100" in result["reason"]

    assert explanation_json["fallback_mode"] is None
    assert explanation_json["freshness"] == 5.0
    assert explanation_json["freshness_norm"] == 55.0
    assert explanation_json["recovery_score_simple"] == 70.0
    assert explanation_json["recovery_explanation"] == recovery_explanation

    assert len(fake_cursor.insert_params) == 1
    assert fake_conn.committed is True


def test_recompute_readiness_daily_uses_recovery_only_fallback(monkeypatch):
    recovery_explanation = {"method": "baseline_v2", "hrv_score": 61.2}

    result, explanation_json, _, _ = _build_result(
        monkeypatch,
        load_row=None,
        recovery_row=(66.4, recovery_explanation),
    )

    assert result["fallback_mode"] == "recovery_only"
    assert result["readiness_score"] == 66.4
    assert result["good_day_probability"] == 0.664
    assert result["recommendation"] == "moderate"
    assert "Load context is missing" in result["reason"]

    assert explanation_json["fallback_mode"] == "recovery_only"
    assert explanation_json["freshness"] is None
    assert explanation_json["freshness_norm"] is None
    assert explanation_json["recovery_score_simple"] == 66.4
    assert explanation_json["recovery_explanation"] == recovery_explanation


def test_recompute_readiness_daily_uses_load_only_fallback(monkeypatch):
    result, explanation_json, _, _ = _build_result(
        monkeypatch,
        load_row=(12.5,),
        recovery_row=None,
    )

    assert result["fallback_mode"] == "load_only"
    assert result["freshness"] == 12.5
    assert result["freshness_norm"] == 62.5
    assert result["recovery_score_simple"] is None
    assert result["readiness_score"] == 62.5
    assert result["good_day_probability"] == 0.625
    assert result["recommendation"] == "moderate"
    assert "Recovery context is missing" in result["reason"]

    assert explanation_json["fallback_mode"] == "load_only"
    assert explanation_json["freshness"] == 12.5
    assert explanation_json["freshness_norm"] == 62.5
    assert explanation_json["recovery_score_simple"] is None
    assert explanation_json["recovery_explanation"] is None


def test_recompute_readiness_daily_returns_404_without_creating_row(monkeypatch):
    fake_cursor = _FakeCursor(load_row=None, recovery_row=None)
    fake_conn = _FakeConn(fake_cursor)

    monkeypatch.setattr(readiness_daily, "get_conn", lambda: fake_conn)

    with pytest.raises(HTTPException) as exc_info:
        readiness_daily.recompute_readiness_daily_for_date(
            user_id="user-1",
            target_date="2026-04-16",
        )

    assert exc_info.value.status_code == 404
    assert "no load or recovery data found" in exc_info.value.detail
    assert fake_cursor.insert_params == []
    assert fake_conn.committed is False
