import importlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import app as app_module
from backend.today import service as today_service

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
today_router_module = importlib.import_module("backend.today.router")


def _readiness(*, physiology_available: bool = False):
    physiology_score = 72.0 if physiology_available else None
    return {
        "ok": True,
        "user_id": "sergey",
        "date": "2026-08-30",
        "readiness_score": 68.0,
        "status_text": "Good readiness",
        "recommendation": "moderate",
        "reason": "Freshness and morning feeling support moderate training.",
        "briefing_text": "Moderate training fits the current backend state.",
        "freshness_state": "fresh",
        "readiness_computed_at": "2026-08-30T06:00:00+00:00",
        "signal_families": {
            "load": {
                "availability": "available",
                "used": False,
                "score": None,
                "contribution": 0.0,
                "reason_codes": ["load_context_exposed_via_freshness"],
            },
            "freshness": {
                "availability": "available",
                "used": True,
                "score": 64.0,
                "contribution": 38.4,
                "reason_codes": [],
            },
            "response": {
                "availability": "unavailable",
                "used": False,
                "score": None,
                "contribution": 0.0,
                "reason_codes": ["response_metrics_unavailable"],
            },
            "feeling": {
                "availability": "available",
                "used": True,
                "score": 75.0,
                "contribution": 30.0,
                "reason_codes": [],
            },
            "physiology": {
                "availability": "available" if physiology_available else "unavailable",
                "used": physiology_available,
                "score": physiology_score,
                "contribution": 14.4 if physiology_available else 0.0,
                "reason_codes": [] if physiology_available else ["physiology_unavailable"],
            },
        },
    }


def _today_data():
    readiness = _readiness()
    return today_service.TodayData(
        user_id="sergey",
        today="2026-08-30",
        readiness=readiness,
        readiness_section=today_service.TodaySection(status="ok", error=None),
        factors=today_service._build_factors(readiness),
        recovery=today_service.TodayFeedback(
            score=4,
            value="fresh",
            updated_at="30 Aug, 09:00",
        ),
        recovery_section=today_service.TodaySection(status="ok", error=None),
        activity=today_service.TodayActivity(
            activity_id=17855535922,
            name="Morning Ride",
            sport_type="Ride",
            start_time="30 Aug, 07:15",
            distance="42.5 km",
            duration="1h 23m",
            rpe_score=None,
            rpe_value=None,
        ),
        activity_section=today_service.TodaySection(status="ok", error=None),
        history_groups=[],
        history_section=today_service.TodaySection(status="ok", error=None),
    )


def test_get_today_data_keeps_missing_physiology_unavailable(monkeypatch):
    monkeypatch.setattr(
        today_service,
        "get_latest_readiness_daily",
        lambda user_id, evaluation_at: _readiness(),
    )
    monkeypatch.setattr(
        today_service,
        "_get_today_recovery",
        lambda user_id, target_date: today_service.TodayFeedback(4, "fresh", "now"),
    )
    monkeypatch.setattr(
        today_service,
        "get_today_activity",
        lambda user_id, preferred_activity_id=None: None,
    )

    result = today_service.get_today_data(
        "sergey",
        now=datetime(2026, 8, 30, 9, tzinfo=MOSCOW_TZ),
    )

    physiology = next(factor for factor in result.factors if factor["key"] == "physiology")
    assert result.today == "2026-08-30"
    assert physiology["availability"] == "unavailable"
    assert physiology["used"] is False
    assert physiology["score"] is None


def test_get_today_data_degrades_sections_independently(monkeypatch):
    monkeypatch.setattr(
        today_service,
        "get_latest_readiness_daily",
        lambda user_id, evaluation_at: (_ for _ in ()).throw(
            HTTPException(status_code=404, detail="missing")
        ),
    )
    monkeypatch.setattr(
        today_service,
        "_get_today_recovery",
        lambda user_id, target_date: (_ for _ in ()).throw(RuntimeError("feedback db failed")),
    )
    monkeypatch.setattr(
        today_service,
        "get_today_activity",
        lambda user_id, preferred_activity_id=None: None,
    )

    result = today_service.get_today_data(
        "sergey",
        now=datetime(2026, 8, 30, 9, tzinfo=MOSCOW_TZ),
    )

    assert result.readiness is None
    assert result.readiness_section.status == "missing"
    assert result.recovery_section.status == "error"
    assert result.recovery_section.error == "feedback db failed"
    assert result.activity_section.status == "ok"


def test_today_history_keeps_calendar_gaps_and_missing_feedback(monkeypatch):
    target = date(2026, 8, 30)
    version = today_service.READINESS_MODEL_VERSION
    calls = []

    def history(user_id, start_date, end_date):
        calls.append((user_id, start_date, end_date))
        return [{"date": target, "version": version, "readiness_score": 68.0,
                 "recommendation": "moderate"}]

    monkeypatch.setattr(today_service, "get_readiness_daily_calendar_history", history)
    monkeypatch.setattr(today_service, "_get_recovery_history",
                        lambda *args: {target: (4, "fresh")})

    groups = today_service.get_today_history("sergey", target)

    assert calls == [("sergey", date(2026, 8, 17), target)]
    assert len(groups) == 1
    assert len(groups[0].rows) == 14
    assert groups[0].rows[0].date == "2026-08-30"
    assert groups[0].rows[0].recommendation == "moderate"
    assert groups[0].rows[0].recovery_score == 4
    assert groups[0].rows[1].date == "2026-08-29"
    assert groups[0].rows[1].readiness_score is None
    assert groups[0].rows[1].recovery_score is None


def test_today_history_empty_and_older_version_separate(monkeypatch):
    target = date(2026, 8, 30)
    monkeypatch.setattr(today_service, "_get_recovery_history", lambda *args: {})
    monkeypatch.setattr(today_service, "get_readiness_daily_calendar_history", lambda *args: [])

    groups = today_service.get_today_history("sergey", target)
    assert len(groups) == 1
    assert groups[0].supported is True
    assert all(row.readiness_score is None for row in groups[0].rows)

    monkeypatch.setattr(today_service, "get_readiness_daily_calendar_history",
                        lambda *args: [{"date": target, "version": "v2", "readiness_score": 65.0,
                                        "recommendation": None}])
    groups = today_service.get_today_history("sergey", target)
    assert len(groups) == 2
    assert groups[0].supported is True
    assert groups[1].version == "v2"
    assert groups[1].supported is False
    assert groups[1].rows[0].readiness_score == 65.0
    assert groups[1].rows[0].recommendation is None


def test_history_failure_does_not_break_today_sections(monkeypatch):
    monkeypatch.setattr(today_service, "get_latest_readiness_daily",
                        lambda user_id, evaluation_at: _readiness())
    monkeypatch.setattr(today_service, "_get_today_recovery", lambda *args: None)
    monkeypatch.setattr(today_service, "get_today_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(today_service, "get_today_history",
                        lambda *args: (_ for _ in ()).throw(RuntimeError("history failed")))

    result = today_service.get_today_data(
        "sergey", now=datetime(2026, 8, 30, 9, tzinfo=MOSCOW_TZ))

    assert result.readiness_section.status == "ok"
    assert result.readiness["readiness_score"] == 68.0
    assert result.recovery_section.status == "ok"
    assert result.activity_section.status == "ok"
    assert result.history_section.status == "error"
    assert result.history_groups == []


class _ActivityCursor:
    def __init__(self, row):
        self.row = row
        self.query = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.query = " ".join(query.split()).lower()
        self.params = params

    def fetchone(self):
        return self.row


class _ActivityConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


def test_today_activity_query_selects_latest_and_scopes_user(monkeypatch):
    cursor = _ActivityCursor(
        (
            17855535922,
            "Morning Ride",
            "Ride",
            datetime(2026, 8, 30, 6, tzinfo=ZoneInfo("UTC")),
            42500.0,
            4980,
            None,
            None,
        )
    )
    monkeypatch.setattr(today_service, "get_conn", lambda: _ActivityConn(cursor))

    result = today_service.get_today_activity("sergey")

    assert result.activity_id == 17855535922
    assert result.duration == "1h 23m"
    assert result.distance == "42.5 km"
    assert cursor.params == ("post_ride_rpe", "sergey")
    assert "where r.user_id = %s" in cursor.query
    assert "order by r.start_date desc nulls last" in cursor.query
    assert "case when f.feedback_score is null" not in cursor.query
    assert "r.duplicate_of_activity_id is null" in cursor.query


def test_today_activity_preferred_edit_remains_user_scoped(monkeypatch):
    cursor = _ActivityCursor(None)
    monkeypatch.setattr(today_service, "get_conn", lambda: _ActivityConn(cursor))

    result = today_service.get_today_activity("sergey", preferred_activity_id=123)

    assert result is None
    assert cursor.params == ("post_ride_rpe", "sergey", 123)
    assert "and r.strava_activity_id = %s" in cursor.query


def test_today_page_renders_mobile_working_surface(monkeypatch):
    monkeypatch.setattr(today_service, "get_today_data", lambda *args, **kwargs: _today_data())
    client = TestClient(app_module.app)

    response = client.get("/today")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'name="viewport"' in response.text
    assert "Today’s readiness" in response.text
    assert "Good readiness" in response.text
    assert "How do you feel today?" in response.text
    assert "Morning Ride" in response.text
    assert "Physiology" in response.text
    assert "unavailable" in response.text
    assert "/today/recovery/4" in response.text
    assert "/today/rpe/17855535922/5" in response.text
    assert 'formmethod="post"' in response.text
    assert "X-Requested-With" in response.text


def test_today_history_table_renders_versions_and_missing_values(monkeypatch):
    data = _today_data()
    data = today_service.TodayData(
        **{**data.__dict__, "history_groups": [
            today_service.TodayHistoryGroup(
                version=today_service.READINESS_MODEL_VERSION,
                supported=True,
                rows=[today_service.TodayHistoryRow("2026-08-30", 68.0, "moderate", 4, "fresh"),
                      today_service.TodayHistoryRow("2026-08-29", None, None, None, None)],
            ),
            today_service.TodayHistoryGroup(
                version="v2", supported=False,
                rows=[today_service.TodayHistoryRow("2026-08-30", 60.0, None, 4, "fresh")],
            ),
        ]})
    monkeypatch.setattr(today_service, "get_today_data", lambda *args, **kwargs: data)

    response = TestClient(app_module.app).get("/today")

    assert response.status_code == 200
    assert "Current persisted daily history" in response.text
    assert "No readiness" in response.text
    assert "No feedback" in response.text
    assert "Not mapped" in response.text
    assert "moderate" in response.text
    assert 'scope="col"' in response.text
    assert 'tabindex="0"' in response.text


def test_today_recovery_submission_uses_web_source_and_redirects(monkeypatch):
    calls = []
    monkeypatch.setattr(today_service, "get_local_today", lambda: date(2026, 8, 30))
    monkeypatch.setattr(
        today_router_module,
        "upsert_next_day_recovery_feedback",
        lambda **kwargs: calls.append(kwargs),
    )
    client = TestClient(app_module.app)

    response = client.post("/today/recovery/4", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/today?saved=recovery"
    assert calls == [
        {
            "user_id": "sergey",
            "target_date": date(2026, 8, 30),
            "score": 4,
            "source": "web",
        }
    ]


def test_today_rpe_submission_validates_activity_owner_and_redirects(monkeypatch):
    calls = []
    monkeypatch.setattr(
        today_service,
        "get_today_activity",
        lambda user_id, preferred_activity_id: _today_data().activity,
    )
    monkeypatch.setattr(
        today_router_module,
        "upsert_activity_subjective_feedback",
        lambda **kwargs: calls.append(kwargs),
    )
    client = TestClient(app_module.app)

    response = client.post("/today/rpe/17855535922/3", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/today?saved=rpe&activity_id=17855535922"
    assert calls == [{"activity_id": 17855535922, "score": 3, "source": "web"}]


def test_today_rpe_submission_rejects_unowned_activity(monkeypatch):
    monkeypatch.setattr(
        today_service,
        "get_today_activity",
        lambda user_id, preferred_activity_id: None,
    )
    client = TestClient(app_module.app)

    response = client.post("/today/rpe/999/3")

    assert response.status_code == 404


def test_today_writes_reject_cross_site_forms(monkeypatch):
    client = TestClient(app_module.app)

    response = client.post(
        "/today/recovery/3",
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403


def test_today_writes_reject_mismatched_origin():
    client = TestClient(app_module.app)

    response = client.post(
        "/today/recovery/3",
        headers={"Origin": "https://example.test"},
    )

    assert response.status_code == 403


def test_today_scores_are_limited_to_documented_scale():
    client = TestClient(app_module.app)

    assert client.post("/today/recovery/0").status_code == 422
    assert client.post("/today/recovery/6").status_code == 422
