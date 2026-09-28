from datetime import date

import pytest

from backend.services import activity_response_service, rpe_service, strava_auth, strava_client


class _Cursor:
    def __init__(self):
        self.observations = {}
        self.resolution = None
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql, params):
        if "select source, score, scale_version" in sql:
            self.rows = [
                (source, score, "rpe_1_10", "rpe_observation_v1", None, None)
                for source, score in self.observations.items()
            ]
        elif "insert into activity_rpe_observation" in sql:
            self.observations[params[2]] = params[3]
        elif "insert into activity_rpe_resolution" in sql:
            self.resolution = params
        elif "select r.strava_activity_id" in sql:
            self.rows = [(42,)]

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def cursor(self):
        return self.cur

    def commit(self):
        pass


def test_resolution_precedence_and_missing():
    assert rpe_service.resolve_rpe([])["score"] is None
    assert rpe_service.resolve_rpe([
        {"source": "telegram", "score": 6}
    ])["source"] == "telegram"
    assert rpe_service.resolve_rpe([
        {"source": "strava", "score": 7}
    ])["score"] == 7
    both = rpe_service.resolve_rpe([
        {"source": "telegram", "score": 6},
        {"source": "strava", "score": 8},
    ])
    assert (both["score"], both["source"], both["disagreement"]) == (8, "strava", True)
    assert not rpe_service.resolve_rpe([
        {"source": "telegram", "score": 8},
        {"source": "strava", "score": 8},
    ])["disagreement"]


def test_source_coexistence_and_recompute_only_for_effective_change(monkeypatch):
    cur = _Cursor()
    monkeypatch.setattr(rpe_service, "get_conn", lambda: _Conn(cur))
    response_calls = []
    readiness_calls = []
    monkeypatch.setattr(
        activity_response_service, "compute_and_store_activity_response",
        lambda activity_id: response_calls.append(activity_id) or {
            "activity_date": "2026-09-28",
            "activity_type": "Ride",
            "intensity_band": "endurance",
        },
    )
    monkeypatch.setattr(
        activity_response_service, "recompute_later_comparable_responses",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        activity_response_service, "recompute_readiness_for_response_window",
        lambda **kwargs: readiness_calls.append(kwargs) or ["2026-09-28"],
    )
    def write(source, score):
        return rpe_service.upsert_rpe_observation(
            user_id="user-1", canonical_activity_id=42, source=source,
            score=score, source_payload={"score": score},
        )

    assert write("telegram", 6)["effective_changed"]
    assert write("strava", 6)["effective_changed"] is False
    changed = write("strava", 8)
    assert changed["effective_changed"]
    assert changed["disagreement"]
    assert write("telegram", 3)["effective_changed"] is False
    assert cur.observations == {"telegram": 3, "strava": 8}
    assert cur.resolution[2:5] == (8, "strava", True)
    assert response_calls == [42, 42]
    assert len(readiness_calls) == 2


def test_late_strava_import_is_bounded_and_skips_missing_rpe(monkeypatch):
    assert rpe_service.import_strava_rpe(
        user_id="user-1", canonical_activity_id=42, activity={}
    ) is None
    cur = _Cursor()
    monkeypatch.setattr(rpe_service, "get_conn", lambda: _Conn(cur))
    monkeypatch.setattr(
        strava_auth, "refresh_strava_token_if_needed", lambda user_id: ("token", None, None)
    )
    monkeypatch.setattr(
        strava_client, "fetch_activity",
        lambda **kwargs: {"id": 42, "perceived_exertion": 7},
    )
    imported = []
    monkeypatch.setattr(
        rpe_service, "import_strava_rpe",
        lambda **kwargs: imported.append(kwargs) or {"effective_changed": True},
    )
    assert rpe_service.reconcile_recent_strava_rpe("user-1") == {
        "checked": 1, "changed": 1,
    }
    assert imported[0]["canonical_activity_id"] == 42


def test_strava_import_keeps_original_detailed_payload(monkeypatch):
    written = []
    monkeypatch.setattr(
        rpe_service, "upsert_rpe_observation",
        lambda **kwargs: written.append(kwargs) or {"effective_changed": True},
    )
    activity = {"id": 42, "perceived_exertion": 9, "name": "Ride"}
    rpe_service.import_strava_rpe(
        user_id="user-1", canonical_activity_id=42, activity=activity
    )
    assert written[0]["score"] == 9
    assert written[0]["source"] == "strava"
    assert written[0]["source_payload"] == activity
    with pytest.raises(ValueError):
        rpe_service.import_strava_rpe(
            user_id="user-1", canonical_activity_id=42,
            activity={"perceived_exertion": 11},
        )


def test_comparable_baseline_is_scoped_to_new_response_version(monkeypatch):
    class Cursor(_Cursor):
        def execute(self, sql, params):
            self.sql = sql
            self.params = params
            self.rows = []

    cur = Cursor()
    monkeypatch.setattr(activity_response_service, "get_conn", lambda: _Conn(cur))
    activity_response_service._load_comparable_history(
        user_id="user-1",
        activity_id=42,
        activity_type="Ride",
        activity_date=date(2026, 9, 28),
        intensity_band="endurance",
    )
    assert "arm.version = %s" in cur.sql
    assert cur.params[-2] == "v2_rpe_1_10"
