from datetime import date

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


def test_get_readiness_daily_for_date_includes_recommendation(monkeypatch):
    explanation = {
        "fallback_mode": None,
        "freshness_norm": 70.0,
        "recovery_score_simple": 68.0,
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
    assert result["briefing"] == "Сегодня хорошая готовность. Рекомендуется умеренная аэробная тренировка."
    assert result["briefing_text"] == result["briefing"]
