from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from backend import app as app_module
from backend.dashboard import service as dashboard_service

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


class _FakeCursor:
    def __init__(self):
        self._last_query = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self._last_query = " ".join(query.split()).lower()
        if self._last_query == "select 1;":
            return
        if "count(*) filter" in self._last_query:
            assert "from strava_activity_ingest_job" in self._last_query
            return
        if "from strava_activity_ingest_job" in self._last_query and "order by id desc" in self._last_query:
            assert params == (10,)
            return
        raise AssertionError(f"unexpected query: {query}")

    def fetchone(self):
        if self._last_query == "select 1;":
            return (1,)
        if "count(*) filter" in self._last_query:
            return (2, 1)
        raise AssertionError(f"unexpected fetchone query: {self._last_query}")

    def fetchall(self):
        if "from strava_activity_ingest_job" in self._last_query and "order by id desc" in self._last_query:
            return [
                (
                    42,
                    "failed",
                    "webhook_update",
                    987654321,
                    datetime(2026, 7, 1, 10, 15, tzinfo=MOSCOW_TZ),
                    None,
                    "x" * 260,
                ),
                (
                    41,
                    "pending",
                    "webhook_create",
                    123456789,
                    None,
                    None,
                    None,
                ),
            ]
        raise AssertionError(f"unexpected fetchall query: {self._last_query}")


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _FakeCursor()


class _DatabaseOnlyFailingConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _DatabaseOnlyFailingCursor()


class _DatabaseOnlyFailingCursor:
    def __init__(self):
        self._last_query = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self._last_query = " ".join(query.split()).lower()
        if self._last_query == "select 1;":
            return
        raise RuntimeError("relation strava_activity_ingest_job does not exist")

    def fetchone(self):
        if self._last_query == "select 1;":
            return (1,)
        raise AssertionError(f"unexpected fetchone query: {self._last_query}")


def test_dashboard_endpoints_render_html(monkeypatch):
    monkeypatch.setattr(dashboard_service, "get_conn", lambda: _FakeConn())

    client = TestClient(app_module.app)

    for path in ("/dashboard", "/dashboard/"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "Internal Dashboard" in response.text
        assert "Backend status:" in response.text
        assert "Database status:" in response.text
        assert "ok" in response.text
        assert "Process started:" in response.text
        assert "Uptime:" in response.text
        assert "Ingest Jobs" in response.text
        assert "Pending count:" in response.text
        assert "Failed/error count:" in response.text
        assert "webhook_update" in response.text
        assert "987654321" in response.text
        assert "xxxxx" in response.text
        assert "…" in response.text
        assert "Strava" in response.text
        assert "Connection" in response.text
        assert "System Info" in response.text


def test_dashboard_renders_ingest_error_without_failing(monkeypatch):
    monkeypatch.setattr(dashboard_service, "get_conn", lambda: _DatabaseOnlyFailingConn())

    client = TestClient(app_module.app)
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Database status:" in response.text
    assert "Ingest Jobs" in response.text
    assert "Status:" in response.text
    assert "Error:" in response.text
    assert "relation strava_activity_ingest_job does not exist" in response.text
