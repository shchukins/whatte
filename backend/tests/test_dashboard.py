from fastapi.testclient import TestClient

from backend import app as app_module
from backend.dashboard import service as dashboard_service


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query):
        assert query == "SELECT 1;"

    def fetchone(self):
        return (1,)


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _FakeCursor()


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
        assert "Strava" in response.text
        assert "Ingest Jobs" in response.text
        assert "Connection" in response.text
        assert "System Info" in response.text


def test_dashboard_renders_database_error_without_failing(monkeypatch):
    monkeypatch.setattr(
        dashboard_service,
        "get_conn",
        lambda: (_ for _ in ()).throw(RuntimeError("db unavailable for dashboard test")),
    )

    client = TestClient(app_module.app)
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Database status:" in response.text
    assert "error" in response.text
    assert "Database error:" in response.text
    assert "db unavailable for dashboard test" in response.text
