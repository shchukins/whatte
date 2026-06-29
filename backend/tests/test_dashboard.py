from fastapi.testclient import TestClient

from backend import app as app_module


def test_dashboard_endpoints_render_html():
    client = TestClient(app_module.app)

    for path in ("/dashboard", "/dashboard/"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "Internal Dashboard" in response.text
        assert "Backend status:" in response.text
        assert "OK" in response.text
        assert "Europe/Moscow" in response.text
        assert "Strava" in response.text
        assert "Ingest Jobs" in response.text
        assert "Connection" in response.text
        assert "System Info" in response.text
