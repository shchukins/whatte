from datetime import date

import pytest
from fastapi import HTTPException

from backend.services import readiness_query


class _FakeCursor:
    def __init__(self, row) -> None:
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        pass

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, row) -> None:
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _FakeCursor(self._row)


class _FakeLatestCursor:
    def __init__(self, row) -> None:
        self._row = row
        self.execute_calls: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        self.execute_calls.append((query, params))

    def fetchone(self):
        return self._row


class _FakeLatestConn:
    def __init__(self, cursor: _FakeLatestCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


def test_get_readiness_daily_for_date_includes_recommendation(monkeypatch):
    explanation = {
        "fallback_mode": None,
        "freshness_norm": 70.0,
        "recovery_score_simple": 68.0,
        "recovery_explanation": {
            "sleep_minutes": 460.0,
            "hrv_today": 58.0,
            "rhr_today": 50.0,
        },
    }
    row = (
        "user-1",
        date(2026, 4, 16),
        69.2,
        0.692,
        "Хорошая готовность",
        explanation,
    )

    monkeypatch.setattr(readiness_query, "get_conn", lambda: _FakeConn(row))

    result = readiness_query.get_readiness_daily_for_date(
        user_id="user-1",
        target_date="2026-04-16",
    )

    assert result["recommendation"] == "moderate"
    assert "Readiness score is 69.2/100" in result["reason"]
    assert "Freshness is available at 70/100" in result["reason"]
    assert "Recovery is available at 68/100" in result["reason"]
    assert result["data_quality"] == {
        "sleep": "ok",
        "hrv": "ok",
        "resting_hr": "ok",
        "training": "ok",
    }
    assert result["briefing"] == "Сегодня хорошая готовность. Рекомендуется умеренная аэробная тренировка."
    assert result["briefing_text"] == result["briefing"]


def test_get_latest_readiness_daily_returns_newest_row_with_guidance(monkeypatch):
    explanation = {
        "fallback_mode": None,
        "freshness_norm": 62.0,
        "recovery_score_simple": 65.0,
        "recovery_explanation": {
            "sleep_minutes": 430.0,
            "hrv_today": 54.0,
            "rhr_today": 49.0,
        },
    }
    row = (
        "sergey",
        date(2026, 5, 2),
        63.8,
        0.638,
        "Хорошая готовность",
        explanation,
    )
    fake_cursor = _FakeLatestCursor(row)
    fake_conn = _FakeLatestConn(fake_cursor)

    monkeypatch.setattr(readiness_query, "get_conn", lambda: fake_conn)

    result = readiness_query.get_latest_readiness_daily(user_id="sergey")

    assert result["ok"] is True
    assert result["user_id"] == "sergey"
    assert result["date"] == "2026-05-02"
    assert result["recommendation"] == "moderate"
    assert result["data_quality"] == {
        "sleep": "ok",
        "hrv": "ok",
        "resting_hr": "ok",
        "training": "ok",
    }
    assert result["reason"] == (
        "Readiness score is 63.8/100. "
        "Freshness is available at 62/100. "
        "Recovery is available at 65/100. "
        "Recommendation is moderate."
    )
    assert result["briefing"] == "Сегодня хорошая готовность. Рекомендуется умеренная аэробная тренировка."
    assert result["briefing_text"] == result["briefing"]

    query, params = fake_cursor.execute_calls[0]
    assert "order by date desc" in query
    assert "limit 1" in query
    assert "date = %s" not in query
    assert params == ("sergey",)


def test_get_latest_readiness_daily_returns_404_when_no_rows(monkeypatch):
    fake_cursor = _FakeLatestCursor(None)
    fake_conn = _FakeLatestConn(fake_cursor)

    monkeypatch.setattr(readiness_query, "get_conn", lambda: fake_conn)

    with pytest.raises(HTTPException) as exc:
        readiness_query.get_latest_readiness_daily(user_id="sergey")

    assert exc.value.status_code == 404
    assert exc.value.detail == "latest readiness not found for user_id=sergey"


def test_get_readiness_daily_for_date_marks_missing_hrv(monkeypatch):
    explanation = {
        "fallback_mode": None,
        "freshness_norm": 60.0,
        "recovery_score_simple": 64.0,
        "recovery_explanation": {
            "sleep_minutes": 440.0,
            "hrv_today": None,
            "rhr_today": 51.0,
        },
    }
    row = (
        "user-1",
        date(2026, 4, 17),
        62.4,
        0.624,
        "Нормальная готовность",
        explanation,
    )

    monkeypatch.setattr(readiness_query, "get_conn", lambda: _FakeConn(row))

    result = readiness_query.get_readiness_daily_for_date(
        user_id="user-1",
        target_date="2026-04-17",
    )

    assert result["data_quality"]["sleep"] == "ok"
    assert result["data_quality"]["hrv"] == "missing"
    assert result["data_quality"]["resting_hr"] == "ok"
    assert result["data_quality"]["training"] == "ok"


def test_get_readiness_daily_for_date_marks_missing_sleep(monkeypatch):
    explanation = {
        "fallback_mode": None,
        "freshness_norm": 59.0,
        "recovery_score_simple": 63.0,
        "recovery_explanation": {
            "sleep_minutes": None,
            "hrv_today": 57.0,
            "rhr_today": 52.0,
        },
    }
    row = (
        "user-1",
        date(2026, 4, 18),
        61.4,
        0.614,
        "Нормальная готовность",
        explanation,
    )

    monkeypatch.setattr(readiness_query, "get_conn", lambda: _FakeConn(row))

    result = readiness_query.get_readiness_daily_for_date(
        user_id="user-1",
        target_date="2026-04-18",
    )

    assert result["data_quality"]["sleep"] == "missing"
    assert result["data_quality"]["hrv"] == "ok"
    assert result["data_quality"]["resting_hr"] == "ok"
    assert result["data_quality"]["training"] == "ok"


def test_get_readiness_daily_for_date_marks_training_missing_for_recovery_only(monkeypatch):
    explanation = {
        "fallback_mode": "recovery_only",
        "freshness_norm": None,
        "recovery_score_simple": 66.4,
        "recovery_explanation": {
            "sleep_minutes": 455.0,
            "hrv_today": 61.0,
            "rhr_today": 50.0,
        },
    }
    row = (
        "user-1",
        date(2026, 4, 19),
        66.4,
        0.664,
        "Хорошая готовность",
        explanation,
    )

    monkeypatch.setattr(readiness_query, "get_conn", lambda: _FakeConn(row))

    result = readiness_query.get_readiness_daily_for_date(
        user_id="user-1",
        target_date="2026-04-19",
    )

    assert result["data_quality"] == {
        "sleep": "ok",
        "hrv": "ok",
        "resting_hr": "ok",
        "training": "missing",
    }


def test_get_readiness_daily_for_date_marks_training_ok_for_load_and_recovery(monkeypatch):
    explanation = {
        "fallback_mode": None,
        "freshness_norm": 55.0,
        "recovery_score_simple": 70.0,
        "recovery_explanation": {
            "sleep_minutes": 470.0,
            "hrv_today": 59.0,
            "rhr_today": 49.0,
        },
    }
    row = (
        "user-1",
        date(2026, 4, 20),
        61.0,
        0.61,
        "Нормальная готовность",
        explanation,
    )

    monkeypatch.setattr(readiness_query, "get_conn", lambda: _FakeConn(row))

    result = readiness_query.get_readiness_daily_for_date(
        user_id="user-1",
        target_date="2026-04-20",
    )

    assert result["data_quality"]["training"] == "ok"
