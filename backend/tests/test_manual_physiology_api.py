from datetime import datetime, timezone
import importlib

from fastapi.testclient import TestClient

from backend import app as app_module
from backend.config import settings
from backend.services.manual_physiology_service import (
    ManualPhysiologyObservation,
    ManualPhysiologySaveResult,
)


physiology_router = importlib.import_module("backend.physiology.router")


TOKEN = "manual-physiology-test-token"
DATE = "2026-10-01"


def _observation(**overrides) -> ManualPhysiologyObservation:
    values = {
        "id": 1,
        "user_id": "sergey",
        "local_date": DATE,
        "sleep_duration_minutes": 450,
        "sleep_quality": None,
        "hrv_ms": None,
        "resting_hr_bpm": 48.0,
        "source": "web",
        "observed_at": datetime(2026, 10, 1, 6, tzinfo=timezone.utc),
        "schema_version": "manual_physiology_observation_v1",
        "revision": 1,
        "created_at": datetime(2026, 10, 1, 6, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 1, 6, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return ManualPhysiologyObservation(**values)


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "manual_physiology_api_token", TOKEN)
    return TestClient(app_module.app)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_manual_physiology_api_requires_dedicated_token(monkeypatch):
    client = _client(monkeypatch)

    response = client.get(f"/api/v1/manual-physiology/{DATE}")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_manual_physiology_api_is_disabled_when_token_is_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "manual_physiology_api_token", None)
    client = TestClient(app_module.app)

    response = client.get(f"/api/v1/manual-physiology/{DATE}")

    assert response.status_code == 503


def test_get_missing_manual_physiology_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        physiology_router,
        "get_manual_physiology_observation",
        lambda **kwargs: None,
    )
    client = _client(monkeypatch)

    response = client.get(f"/api/v1/manual-physiology/{DATE}", headers=_headers())

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "local_date": DATE,
        "fields": {
            "sleep_duration_minutes": {"availability": "unavailable", "value": None},
            "sleep_quality": {"availability": "unavailable", "value": None},
            "hrv_ms": {"availability": "unavailable", "value": None},
            "resting_hr_bpm": {"availability": "unavailable", "value": None},
        },
        "source": None,
        "observed_at": None,
        "schema_version": None,
        "revision": None,
        "created_at": None,
        "updated_at": None,
        "changed": None,
        "changed_fields": None,
    }


def test_get_manual_physiology_returns_values_and_provenance(monkeypatch):
    observed = _observation()
    monkeypatch.setattr(
        physiology_router,
        "get_manual_physiology_observation",
        lambda **kwargs: observed,
    )
    client = _client(monkeypatch)

    response = client.get(f"/api/v1/manual-physiology/{DATE}", headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["fields"]["sleep_duration_minutes"] == {
        "availability": "available", "value": 450
    }
    assert payload["fields"]["hrv_ms"]["availability"] == "unavailable"
    assert payload["source"] == "web"
    assert payload["revision"] == 1
    assert payload["updated_at"] == "2026-10-01T06:00:00Z"


def test_patch_builds_partial_service_patch_and_returns_change(monkeypatch):
    calls = []
    observed = _observation(sleep_duration_minutes=None, hrv_ms=54.2, revision=2)

    def save(**kwargs):
        calls.append(kwargs)
        return ManualPhysiologySaveResult(
            observation=observed,
            changed=True,
            changed_fields=["hrv_ms"],
        )

    monkeypatch.setattr(physiology_router, "save_manual_physiology_observation", save)
    client = _client(monkeypatch)

    response = client.patch(
        f"/api/v1/manual-physiology/{DATE}",
        headers=_headers(),
        json={"source": "telegram", "hrv_ms": 54.2},
    )

    assert response.status_code == 200
    patch = calls[0]["patch"]
    assert calls[0]["user_id"] == "sergey"
    assert patch.local_date.isoformat() == DATE
    assert patch.source == "telegram"
    assert patch.model_fields_set == {"local_date", "source", "hrv_ms"}
    assert response.json()["changed_fields"] == ["hrv_ms"]
    assert response.json()["fields"]["sleep_duration_minutes"]["availability"] == "unavailable"


def test_patch_preserves_explicit_null_for_service_merge(monkeypatch):
    captured = []
    observed = _observation(sleep_duration_minutes=None, revision=2)

    def save(**kwargs):
        captured.append(kwargs["patch"])
        return ManualPhysiologySaveResult(
            observation=observed,
            changed=True,
            changed_fields=["sleep_duration_minutes"],
        )

    monkeypatch.setattr(physiology_router, "save_manual_physiology_observation", save)
    client = _client(monkeypatch)

    response = client.patch(
        f"/api/v1/manual-physiology/{DATE}",
        headers=_headers(),
        json={"source": "web", "sleep_duration_minutes": None},
    )

    assert response.status_code == 200
    assert captured[0].model_fields_set == {
        "local_date", "source", "sleep_duration_minutes"
    }


def test_patch_rejects_invalid_values_and_unknown_fields(monkeypatch):
    client = _client(monkeypatch)

    invalid = client.patch(
        f"/api/v1/manual-physiology/{DATE}",
        headers=_headers(),
        json={"source": "web", "hrv_ms": 0},
    )
    unknown = client.patch(
        f"/api/v1/manual-physiology/{DATE}",
        headers=_headers(),
        json={"source": "web", "surprise": 1},
    )
    naive_timestamp = client.patch(
        f"/api/v1/manual-physiology/{DATE}",
        headers=_headers(),
        json={"source": "web", "observed_at": "2026-10-01T06:00:00"},
    )

    assert invalid.status_code == 422
    assert invalid.json()["detail"][0]["loc"] == ["body", "hrv_ms"]
    assert unknown.status_code == 422
    assert unknown.json()["detail"][0]["loc"] == ["body", "surprise"]
    assert naive_timestamp.status_code == 422
    assert naive_timestamp.json()["detail"][0]["loc"] == ["body"]


def test_patch_rejects_future_local_date_before_persistence(monkeypatch):
    client = _client(monkeypatch)

    response = client.patch(
        "/api/v1/manual-physiology/2999-01-01",
        headers=_headers(),
        json={"source": "web", "hrv_ms": 54.2},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "future local dates are not supported"


def test_patch_returns_idempotent_service_result(monkeypatch):
    observed = _observation()
    monkeypatch.setattr(
        physiology_router,
        "save_manual_physiology_observation",
        lambda **kwargs: ManualPhysiologySaveResult(
            observation=observed, changed=False, changed_fields=[]
        ),
    )
    client = _client(monkeypatch)

    response = client.patch(
        f"/api/v1/manual-physiology/{DATE}",
        headers=_headers(),
        json={"source": "web", "sleep_duration_minutes": 450},
    )

    assert response.status_code == 200
    assert response.json()["changed"] is False
    assert response.json()["changed_fields"] == []
