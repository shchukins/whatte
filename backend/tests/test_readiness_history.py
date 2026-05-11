from datetime import date

from fastapi.testclient import TestClient

from backend import app as app_module
from backend.services import readiness_query


class _FakeHistoryCursor:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params):
        self.execute_calls.append((query, params))

    def fetchall(self):
        return [
            (date(2026, 5, 2), 61.5, 0.615, "Хорошая готовность", {"src": "latest"}),
            (date(2026, 5, 1), 58.2, 0.582, "Нормальная готовность", {"src": "mid"}),
            (date(2026, 4, 30), 55.0, 0.55, "Нормальная готовность", {"src": "oldest"}),
        ]


class _FakeHistoryConn:
    def __init__(self, cursor: _FakeHistoryCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


def test_get_readiness_daily_history_reads_last_n_rows_in_ascending_order(monkeypatch):
    fake_cursor = _FakeHistoryCursor()
    fake_conn = _FakeHistoryConn(fake_cursor)

    monkeypatch.setattr(readiness_query, "get_conn", lambda: fake_conn)

    result = readiness_query.get_readiness_daily_history(user_id="sergey", days=3)

    assert result["ok"] is True
    assert result["user_id"] == "sergey"
    assert result["days"] == 3
    assert len(result["points"]) == 3
    assert [point["date"] for point in result["points"]] == [
        "2026-04-30",
        "2026-05-01",
        "2026-05-02",
    ]

    query, params = fake_cursor.execute_calls[0]
    assert "order by date desc" in query
    assert "limit %s" in query
    assert "interval" not in query.lower()
    assert params == ("sergey", 3)


def test_readiness_history_endpoint_returns_ascending_points(monkeypatch):
    def fake_get_readiness_daily_history(*, user_id, days):
        assert user_id == "sergey"
        assert days == 2
        return {
            "ok": True,
            "user_id": user_id,
            "days": days,
            "points": [
                {
                    "date": "2026-05-01",
                    "readiness_score": 58.2,
                    "good_day_probability": 0.582,
                    "status_text": "Нормальная готовность",
                    "explanation": {"fallback_mode": None},
                },
                {
                    "date": "2026-05-02",
                    "readiness_score": 61.5,
                    "good_day_probability": 0.615,
                    "status_text": "Хорошая готовность",
                    "explanation": {"fallback_mode": None},
                },
            ],
        }

    monkeypatch.setattr(
        app_module,
        "get_readiness_daily_history",
        fake_get_readiness_daily_history,
    )

    client = TestClient(app_module.app)
    response = client.get("/api/v1/model/readiness-daily/sergey/history?days=2")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["points"]) == 2
    assert [point["date"] for point in data["points"]] == [
        "2026-05-01",
        "2026-05-02",
    ]


def test_latest_readiness_endpoint_returns_latest_row(monkeypatch):
    def fake_get_latest_readiness_daily(*, user_id):
        assert user_id == "sergey"
        return {
            "ok": True,
            "user_id": user_id,
            "date": "2026-05-02",
            "readiness_score": 61.5,
            "good_day_probability": 0.615,
            "status_text": "Хорошая готовность",
            "data_quality": {
                "sleep": "ok",
                "hrv": "ok",
                "resting_hr": "ok",
                "training": "ok",
            },
            "explanation": {"fallback_mode": None},
            "recommendation": "moderate",
            "reason": "Readiness score is 61.5/100. Recommendation is moderate.",
            "briefing": "Сегодня хорошая готовность. Рекомендуется умеренная аэробная тренировка.",
            "briefing_text": "Сегодня хорошая готовность. Рекомендуется умеренная аэробная тренировка.",
        }

    monkeypatch.setattr(
        app_module,
        "get_latest_readiness_daily",
        fake_get_latest_readiness_daily,
    )

    client = TestClient(app_module.app)
    response = client.get("/api/v1/model/readiness-daily/sergey/latest")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["date"] == "2026-05-02"
    assert data["data_quality"]["training"] == "ok"
    assert data["recommendation"] == "moderate"
    assert data["briefing"] == data["briefing_text"]
