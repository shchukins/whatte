import importlib
import re
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import app as app_module
from backend.today import service as today_service

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
today_router_module = importlib.import_module("backend.today.router")


@pytest.fixture(autouse=True)
def no_manual_physiology_database(monkeypatch):
    monkeypatch.setattr(today_service, "get_manual_physiology_observation", lambda **kwargs: None)


def _readiness(*, physiology_available: bool = False):
    physiology_score = 72.0 if physiology_available else None
    return {
        "ok": True,
        "user_id": "sergey",
        "date": "2026-08-30",
        "readiness_score": 68.0,
        "status_text": "Хорошая готовность",
        "recommendation": "moderate",
        "reason": "Freshness and morning feeling support moderate training.",
        "briefing_text": "Сегодня хорошая готовность. Рекомендуется умеренная аэробная тренировка.",
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
            distance="42.5 км",
            duration="1 ч 23 мин",
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
            None,
            None,
            None,
            None,
            None,
        )
    )
    monkeypatch.setattr(today_service, "get_conn", lambda: _ActivityConn(cursor))

    result = today_service.get_today_activity("sergey")

    assert result.activity_id == 17855535922
    assert result.duration == "1 ч 23 мин"
    assert result.distance == "42.5 км"
    assert cursor.params == ("sergey",)
    assert "where r.user_id = %s" in cursor.query
    assert "order by r.start_date desc nulls last" in cursor.query
    assert "case when f.feedback_score is null" not in cursor.query
    assert "r.duplicate_of_activity_id is null" in cursor.query


def test_today_activity_preferred_edit_remains_user_scoped(monkeypatch):
    cursor = _ActivityCursor(None)
    monkeypatch.setattr(today_service, "get_conn", lambda: _ActivityConn(cursor))

    result = today_service.get_today_activity("sergey", preferred_activity_id=123)

    assert result is None
    assert cursor.params == ("sergey", 123)
    assert "and r.strava_activity_id = %s" in cursor.query


def test_today_activity_keeps_telegram_and_web_observations_separate(monkeypatch):
    cursor = _ActivityCursor((
        42, "Ride", "Ride", None, None, None,
        7, "telegram", True, None, 7, 4, 7,
    ))
    monkeypatch.setattr(today_service, "get_conn", lambda: _ActivityConn(cursor))

    activity = today_service.get_today_activity("sergey")

    assert activity.rpe_score == 7
    assert activity.rpe_value == "telegram"
    assert activity.rpe_telegram_score == 7
    assert activity.rpe_web_score == 4


def test_today_page_renders_mobile_working_surface(monkeypatch):
    monkeypatch.setattr(today_service, "get_today_data", lambda *args, **kwargs: _today_data())
    client = TestClient(app_module.app)

    response = client.get("/today")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'name="viewport"' in response.text
    assert "Ответ на 2026-08-30" in response.text
    assert "Хорошая готовность" in response.text
    assert "Как вы себя чувствуете сегодня?" in response.text
    assert "Morning Ride" in response.text
    assert "Физиология" in response.text
    assert "Нет данных" in response.text
    assert "/today/recovery/4" in response.text
    assert "/today/rpe/17855535922/5" in response.text
    assert 'formmethod="post"' in response.text
    assert "X-Requested-With" in response.text


def test_today_editorial_metrics_and_figure_use_persisted_values(monkeypatch):
    data = _today_data()
    data = replace(
        data,
        readiness={**data.readiness, "good_day_probability": 0.73},
        history_groups=[
            today_service.TodayHistoryGroup(
                version=today_service.READINESS_MODEL_VERSION,
                supported=True,
                rows=[
                    today_service.TodayHistoryRow("2026-08-30", 68.0, "moderate", 4, "fresh"),
                    today_service.TodayHistoryRow("2026-08-29", None, None, None, None),
                ],
            )
        ],
    )
    monkeypatch.setattr(today_service, "get_today_data", lambda *args, **kwargs: data)

    response = TestClient(app_module.app).get("/today")

    assert response.status_code == 200
    assert "Вероятность хорошего дня" not in response.text
    assert 'class="score">68.0<span class="unit">/100</span>' in response.text
    assert '--bar-height: 68.0%' in response.text
    assert 'class="plot-missing"' in response.text


def test_today_rpe_scale_is_numeric_and_shows_source_resolution(monkeypatch):
    data = _today_data()
    activity = replace(
        data.activity,
        rpe_score=8,
        rpe_value="strava",
        rpe_disagreement=True,
        rpe_strava_score=8,
        rpe_telegram_score=6,
        rpe_web_score=5,
    )
    monkeypatch.setattr(today_service, "get_today_data", lambda *args, **kwargs: replace(data, activity=activity))

    response = TestClient(app_module.app).get("/today")

    assert response.status_code == 200
    assert re.findall(r'<button class="rpe-button"[^>]*>(\d+)</button>', response.text) == [
        str(score) for score in range(1, 11)
    ]
    assert 'aria-label="RPE 5: Умеренно" aria-pressed="true"' in response.text
    assert 'aria-label="RPE 8: Очень тяжело" aria-pressed="false"' in response.text
    assert "RPE 8/10 · Strava" in response.text
    assert "Strava 8/10" in response.text
    assert "Telegram 6/10" in response.text
    assert "Web 5/10" in response.text
    assert "сначала используется Strava, затем Telegram, затем Web" in response.text
    assert "Ваша оценка в Web: 5/10" in response.text


def test_today_rpe_telegram_fallback_is_identified(monkeypatch):
    data = _today_data()
    activity = replace(data.activity, rpe_score=7, rpe_value="telegram", rpe_telegram_score=7)
    monkeypatch.setattr(today_service, "get_today_data", lambda *args, **kwargs: replace(data, activity=activity))

    response = TestClient(app_module.app).get("/today")

    assert "RPE 7/10 · Telegram · резервный источник" in response.text
    assert "Оценки RPE из разных источников различаются" not in response.text


def test_today_rpe_disagreement_without_strava_shows_both_manual_sources(monkeypatch):
    data = _today_data()
    activity = replace(
        data.activity,
        rpe_score=7,
        rpe_value="telegram",
        rpe_disagreement=True,
        rpe_telegram_score=7,
        rpe_web_score=4,
    )
    monkeypatch.setattr(today_service, "get_today_data", lambda *args, **kwargs: replace(data, activity=activity))

    response = TestClient(app_module.app).get("/today")

    assert "Telegram 7/10, Web 4/10" in response.text
    assert "RPE 7/10 · Telegram · резервный источник" in response.text


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
    assert "Текущая сохранённая история по дням" in response.text
    assert "Нет готовности" in response.text
    assert "Нет оценки" in response.text
    assert "Не определяется" in response.text
    assert "Умеренная аэробная тренировка" in response.text
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


@pytest.mark.parametrize("score", [1, 3, 10])
def test_today_rpe_submission_validates_activity_owner_and_redirects(monkeypatch, score):
    calls = []
    monkeypatch.setattr(
        today_service,
        "get_today_activity",
        lambda user_id, preferred_activity_id: _today_data().activity,
    )
    monkeypatch.setattr(
        today_router_module,
        "upsert_activity_rpe_v2",
        lambda **kwargs: calls.append(kwargs),
    )
    client = TestClient(app_module.app)

    response = client.post(f"/today/rpe/17855535922/{score}", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/today?saved=rpe&activity_id=17855535922"
    assert calls == [{"activity_id": 17855535922, "score": score, "source": "web"}]


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
    assert client.post("/today/rpe/123/0").status_code == 422
    assert client.post("/today/rpe/123/11").status_code == 422


@pytest.mark.parametrize("state,label", [("fresh", "Актуальны"), ("stale", "Устарели"), ("partial", "Неполные"), ("missing", "Нет данных"), ("future_state", "Неизвестное состояние")])
def test_today_labels_preserve_backend_contract(monkeypatch, state, label):
    data = _today_data()
    readiness = {**data.readiness, "freshness_state": state,
                 "recommendation": "future_zone", "status_text": "future_status"}
    monkeypatch.setattr(today_service, "get_today_data", lambda *args, **kwargs: replace(data, readiness=readiness))
    page = TestClient(app_module.app).get("/today").text
    assert f"<strong>{label}</strong>" in page
    assert '<h1 id="readiness-title">Неизвестное состояние</h1>' in page
    assert 'id="decision-title"' not in page
    assert readiness["readiness_score"] == 68.0
    assert readiness["recommendation"] == "future_zone"
    assert data.readiness["briefing_text"] in page
    assert data.readiness["reason"] in page


@pytest.mark.parametrize("status", ["missing", "error"])
def test_today_empty_and_error_states_have_russian_navigation(monkeypatch, status):
    data = replace(_today_data(), readiness=None, recovery=None, activity=None,
                   factors=[], history_groups=[],
                   readiness_section=today_service.TodaySection(status, "technical failure" if status == "error" else None))
    monkeypatch.setattr(today_service, "get_today_data", lambda *args, **kwargs: data)
    page = TestClient(app_module.app).get("/today").text
    assert '<html lang="ru">' in page
    assert 'href="/today" aria-current="page">Сегодня</a>' in page
    assert 'href="/today/profile">Профиль</a>' in page
    assert '/today/history' not in page
    assert "Пока нет подходящей тренировки для оценки." in page
    assert ("Готовность недоступна." if status == "error" else "Готовность ещё не рассчитана.") in page


@pytest.mark.parametrize("saved,message", [("recovery", "Самочувствие сохранено. Готовность на сегодня пересчитана."), ("rpe", "RPE сохранён."), ("physiology", "Наблюдения сохранены.")])
def test_today_saved_messages_remain_russian(monkeypatch, saved, message):
    monkeypatch.setattr(today_service, "get_today_data", lambda *args, **kwargs: _today_data())
    page = TestClient(app_module.app).get(f"/today?saved={saved}").text
    assert message in page
    assert 'role="status"' in page


def test_today_answer_disclosure_and_feedback_order(monkeypatch):
    data = _today_data()
    readiness = {**data.readiness, "training_source_at": "2026-08-30T05:00:00Z",
                 "recovery_source_at": "2026-08-30T06:05:00+00:00"}
    monkeypatch.setattr(today_service, "get_today_data", lambda *a, **k: replace(data, readiness=readiness))
    page = TestClient(app_module.app).get("/today").text
    assert page.count('<h1 id="readiness-title">Умеренная аэробная тренировка</h1>') == 1
    assert 'class="card decision"' not in page
    assert 'class="positive"' not in page
    assert '<details class="readiness-explanation">' in page
    assert '<summary>Почему такая рекомендация</summary>' in page
    assert page.index('id="readiness-title"') < page.index('Почему такая рекомендация') < page.index('id="recovery-title"')
    assert '30.08.2026, 09:00 MSK' in page
    assert '30.08.2026, 08:00 MSK' in page
    assert '30.08.2026, 09:05 MSK' in page
    assert 'Отклик на тренировку' in page and 'Нет данных' in page
    assert '/today/rpe/17855535922/5' in page
    assert 'action="/today/physiology"' in page
    assert 'id="history-title"' in page


@pytest.mark.parametrize("result_date,state", [("2026-08-29", "stale"), ("2026-08-30", "stale"), ("2026-08-29", "fresh")])
def test_today_stale_warning_is_outside_disclosure(monkeypatch, result_date, state):
    data = _today_data()
    monkeypatch.setattr(today_service, "get_today_data", lambda *a, **k: replace(
        data, readiness={**data.readiness, "date": result_date, "freshness_state": state}))
    page = TestClient(app_module.app).get("/today").text
    assert f'Ответ на {result_date}' in page
    assert f'Рекомендация относится к {result_date}' in page
    assert page.index('Результат устарел.') < page.index('<details class="readiness-explanation">')
    if result_date != data.today:
        assert f'Сохранённая сводка за {result_date}:' in page


@pytest.mark.parametrize("status", ["missing", "error"])
def test_today_missing_and_error_have_no_score_or_answer(monkeypatch, status):
    data = replace(_today_data(), readiness=None, factors=[],
                   readiness_section=today_service.TodaySection(status, "failed"))
    monkeypatch.setattr(today_service, "get_today_data", lambda *a, **k: data)
    page = TestClient(app_module.app).get("/today").text
    assert '<p class="score">' not in page
    assert '<h1 id="readiness-title">Умеренная аэробная тренировка</h1>' not in page
    assert 'class="positive"' not in page
    assert 'class="readiness-explanation"' not in page
    assert 'Готовность недоступна.' in page if status == "error" else 'Готовность ещё не рассчитана.' in page


def test_today_null_score_does_not_fall_back_to_probability(monkeypatch):
    data = _today_data()
    monkeypatch.setattr(today_service, "get_today_data", lambda *a, **k: replace(
        data, readiness={**data.readiness, "readiness_score": None, "good_day_probability": 0.73}))
    page = TestClient(app_module.app).get("/today").text
    assert 'Оценка недоступна' in page
    assert '<p class="score">' not in page


@pytest.mark.parametrize("timestamp", [None, "invalid", "2026-08-30T06:00:00", datetime(2026, 8, 30, 6)])
def test_readiness_timestamp_missing_invalid_or_naive_is_unavailable(timestamp):
    assert today_service.format_readiness_timestamp(timestamp) == "—"


def test_readiness_timestamp_uses_configured_timezone(monkeypatch):
    monkeypatch.setattr(today_service, "WHATTE_TZ", ZoneInfo("Europe/Berlin"))
    assert today_service.format_readiness_timestamp("2026-08-30T23:00:00Z") == "31.08.2026, 01:00 CEST"


@pytest.mark.parametrize("web_score", [None, 1, 10])
def test_today_rpe_web_selection_is_independent_of_effective_source(monkeypatch, web_score):
    data = _today_data()
    activity = replace(data.activity, rpe_score=8, rpe_value="strava",
                       rpe_strava_score=8, rpe_web_score=web_score,
                       rpe_disagreement=web_score is not None)
    monkeypatch.setattr(today_service, "get_today_data",
                        lambda *a, **k: replace(data, activity=activity))
    page = TestClient(app_module.app).get("/today").text
    buttons = re.findall(r'<button class="rpe-button"[^>]*>', page)
    assert len(buttons) == 10
    for score, button in enumerate(buttons, 1):
        assert f'aria-pressed="{str(score == web_score).lower()}"' in button
        assert f'aria-label="RPE {score}:' in button
        assert f'action="/today/rpe/{activity.activity_id}/{score}"' in page
    assert 'Итоговый RPE 8/10 · Strava' in page
    assert f'Ваша оценка в Web: {str(web_score) + "/10" if web_score else "не выбрана"}.' in page
    assert len(re.findall(r'<span class="rpe-anchor" aria-hidden="true">', page)) == 10
    assert 'Прокрутите или используйте стрелки' not in page
    assert 'прокрутите шкалу вбок' not in page


def test_today_recovery_buttons_keep_numeric_accessible_names(monkeypatch):
    monkeypatch.setattr(today_service, "get_today_data", lambda *a, **k: _today_data())
    page = TestClient(app_module.app).get("/today").text
    names = re.findall(r'aria-label="Самочувствие (\d): ([^"]+)"', page)
    assert names == [("1", "Без сил"), ("2", "Усталость"), ("3", "Нормально"),
                     ("4", "Бодро"), ("5", "Полон сил")]
