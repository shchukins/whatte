from datetime import datetime, timedelta
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
        if self._last_query == "select count(*) from strava_activity_raw;":
            return
        if "from strava_activity_raw" in self._last_query and "order by start_date desc nulls last" in self._last_query:
            assert params == (10,)
            assert "access_token" not in self._last_query
            assert "refresh_token" not in self._last_query
            assert "client_secret" not in self._last_query
            return
        if "from user_strava_connection" in self._last_query:
            assert "access_token" not in self._last_query
            assert "refresh_token" not in self._last_query
            return
        raise AssertionError(f"unexpected query: {query}")

    def fetchone(self):
        if self._last_query == "select 1;":
            return (1,)
        if "count(*) filter" in self._last_query:
            return (2, 1)
        if self._last_query == "select count(*) from strava_activity_raw;":
            return (12,)
        if "from user_strava_connection" in self._last_query:
            return (
                555777999,
                "activity:read_all",
                datetime.now(MOSCOW_TZ) + timedelta(hours=12),
            )
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
        if "from strava_activity_raw" in self._last_query and "order by start_date desc nulls last" in self._last_query:
            return [
                (
                    777888999,
                    "Morning Ride",
                    "Ride",
                    datetime(2026, 7, 1, 6, 30, tzinfo=ZoneInfo("UTC")),
                    42500.0,
                    4980,
                    5400,
                    datetime(2026, 7, 1, 8, 5, tzinfo=ZoneInfo("UTC")),
                ),
                (
                    777888998,
                    None,
                    None,
                    None,
                    None,
                    None,
                    1200,
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


class _StravaActivitiesFailingConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _StravaActivitiesFailingCursor()


class _StravaActivitiesFailingCursor(_FakeCursor):
    def execute(self, query, params=None):
        normalized = " ".join(query.split()).lower()
        if normalized == "select count(*) from strava_activity_raw;":
            raise RuntimeError("relation strava_activity_raw does not exist")
        return super().execute(query, params)


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
        assert "Connection" in response.text
        assert "Athlete ID:" in response.text
        assert "555777999" in response.text
        assert "activity:read_all" in response.text
        assert "expires_soon" in response.text
        assert "Ingest Jobs" in response.text
        assert "Pending count:" in response.text
        assert "Failed/error count:" in response.text
        assert "webhook_update" in response.text
        assert "987654321" in response.text
        assert "xxxxx" in response.text
        assert "…" in response.text
        assert "Strava Activities" in response.text
        assert "Total count:" in response.text
        assert "12" in response.text
        assert "Morning Ride" in response.text
        assert "42.5" in response.text
        assert "1h 23m" in response.text
        assert "20m" in response.text
        assert "System Info" in response.text
        assert "access_token" not in response.text
        assert "refresh_token" not in response.text


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


def test_dashboard_renders_connection_error_without_failing(monkeypatch):
    monkeypatch.setattr(
        dashboard_service,
        "get_dashboard_data",
        lambda: dashboard_service.DashboardData(
            system=dashboard_service.DashboardSystemStatus(
                backend_status="ok",
                database_status="ok",
                database_error=None,
                server_time_moscow="2026-07-01 12:00:00 MSK",
                process_started_at_moscow="2026-07-01 10:00:00 MSK",
                process_uptime_seconds=7200,
            ),
            ingest_jobs=dashboard_service.DashboardIngestJobsStatus(
                status="ok",
                error=None,
                jobs=[],
                failed_count=0,
                pending_count=0,
            ),
            connection=dashboard_service.DashboardConnectionStatus(
                status="error",
                error="connection query failed",
                athlete_id=None,
                scope=None,
                token_expires_at_moscow="—",
                token_state="unknown",
            ),
            strava_activities=dashboard_service.DashboardStravaActivitiesStatus(
                status="ok",
                error=None,
                activities=[],
                total_count=0,
            ),
        ),
    )

    client = TestClient(app_module.app)
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Connection" in response.text
    assert "Connection status unavailable." in response.text
    assert "connection query failed" in response.text


def test_dashboard_renders_strava_activities_error_without_failing(monkeypatch):
    monkeypatch.setattr(dashboard_service, "get_conn", lambda: _StravaActivitiesFailingConn())

    client = TestClient(app_module.app)
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Strava Activities" in response.text
    assert "Strava activities unavailable." in response.text
    assert "relation strava_activity_raw does not exist" in response.text
