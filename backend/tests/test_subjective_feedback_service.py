import requests
from fastapi.testclient import TestClient

from backend import app as app_module
from backend.services import subjective_feedback_service as feedback_service


class _FakeCursor:
    def __init__(self, fetchone_values=None, fetchall_values=None) -> None:
        self.fetchone_values = list(fetchone_values or [])
        self.fetchall_values = list(fetchall_values or [])
        self.execute_calls: list[tuple[str, tuple | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.execute_calls.append((query, params))

    def fetchone(self):
        if not self.fetchone_values:
            return None
        return self.fetchone_values.pop(0)

    def fetchall(self):
        if not self.fetchall_values:
            return []
        return self.fetchall_values.pop(0)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


def test_map_rpe_score_to_value():
    assert feedback_service.map_rpe_score_to_value(1) == "very_easy"
    assert feedback_service.map_rpe_score_to_value(3) == "moderate"
    assert feedback_service.map_rpe_score_to_value(5) == "very_hard"


def test_map_recovery_score_to_value():
    assert feedback_service.map_recovery_score_to_value(1) == "exhausted"
    assert feedback_service.map_recovery_score_to_value(3) == "okay"
    assert feedback_service.map_recovery_score_to_value(5) == "very_fresh"


def test_parse_rpe_callback_data_valid():
    parsed = feedback_service.parse_rpe_callback_data("rpe:18403528422:4")

    assert parsed == {
        "feedback_type": "post_ride_rpe",
        "activity_id": 18403528422,
        "score": 4,
        "value": "hard",
        "source": "telegram",
    }


def test_parse_rpe_callback_data_invalid_payload():
    assert feedback_service.parse_rpe_callback_data("rpe:bad:4") is None
    assert feedback_service.parse_rpe_callback_data("rpe:18403528422:9") is None
    assert feedback_service.parse_rpe_callback_data("oops") is None


def test_parse_recovery_callback_data_valid():
    parsed = feedback_service.parse_recovery_callback_data("recovery:user-1:2026-05-15:4")

    assert parsed == {
        "feedback_type": "next_day_recovery",
        "user_id": "user-1",
        "activity_id": None,
        "target_date": "2026-05-15",
        "score": 4,
        "value": "fresh",
        "source": "telegram",
    }


def test_parse_recovery_callback_data_invalid_payload():
    assert feedback_service.parse_recovery_callback_data("recovery:user-1:2026-05-15:9") is None
    assert feedback_service.parse_recovery_callback_data("recovery:user-1:not-a-date:3") is None
    assert feedback_service.parse_recovery_callback_data("recovery::2026-05-15:3") is None
    assert feedback_service.parse_recovery_callback_data("oops") is None


def test_build_post_ride_rpe_keyboard_uses_expected_score_mapping():
    keyboard = feedback_service.build_post_ride_rpe_keyboard(42)

    assert keyboard["inline_keyboard"][0][0]["text"] == "😌 Very easy"
    assert keyboard["inline_keyboard"][0][0]["callback_data"] == "rpe:42:1"
    assert keyboard["inline_keyboard"][-1][0]["text"] == "☠️ Very hard"
    assert keyboard["inline_keyboard"][-1][0]["callback_data"] == "rpe:42:5"


def test_build_next_day_recovery_keyboard_uses_expected_score_mapping():
    keyboard = feedback_service.build_next_day_recovery_keyboard("user-1", "2026-05-15")

    assert keyboard["inline_keyboard"][0][0]["text"] == "😴 Exhausted"
    assert keyboard["inline_keyboard"][0][0]["callback_data"] == "recovery:user-1:2026-05-15:1"
    assert keyboard["inline_keyboard"][-1][0]["text"] == "🚀 Very fresh"
    assert keyboard["inline_keyboard"][-1][0]["callback_data"] == "recovery:user-1:2026-05-15:5"


def test_upsert_activity_subjective_feedback_inserts_with_context_snapshot(monkeypatch):
    user_cursor = _FakeCursor([("user-1",)])
    readiness_cursor = _FakeCursor(
        [
            (
                "2026-05-14",
                63.5,
                0.72,
                "Good",
                {
                    "freshness": 4.2,
                    "recovery_score_simple": 71.0,
                    "recovery_explanation": {"sleep_score": 74.0},
                },
            )
        ]
    )
    write_cursor = _FakeCursor(
        [
            None,
            (
                7,
                "user-1",
                17855535922,
                None,
                "post_ride_rpe",
                "hard",
                4,
                "telegram",
                "v1_extensible",
                {},
                {
                    "snapshot_date": "2026-05-14",
                    "readiness_score": 63.5,
                    "good_day_probability": 0.72,
                    "status_text": "Good",
                    "recommendation": "moderate",
                    "freshness": 4.2,
                    "recovery_score": 71.0,
                    "recovery_explanation": {"sleep_score": 74.0},
                },
                "2026-05-14T12:00:00Z",
                "2026-05-14T12:00:00Z",
            ),
        ]
    )

    connections = iter([_FakeConn(user_cursor), _FakeConn(readiness_cursor), _FakeConn(write_cursor)])
    monkeypatch.setattr(feedback_service, "get_conn", lambda: next(connections))

    result = feedback_service.upsert_activity_subjective_feedback(
        activity_id=17855535922,
        score=4,
    )

    assert result["was_update"] is False
    assert result["feedback_value"] == "hard"
    assert result["feedback_score"] == 4
    assert result["activity_date"] is None
    assert result["feedback_schema_version"] == "v1_extensible"
    assert result["feedback_payload"] == {}
    assert result["context"] == {
        "snapshot_date": "2026-05-14",
        "readiness_score": 63.5,
        "good_day_probability": 0.72,
        "status_text": "Good",
        "recommendation": "moderate",
        "freshness": 4.2,
        "recovery_score": 71.0,
        "recovery_explanation": {"sleep_score": 74.0},
    }
    assert write_cursor.execute_calls[1][1][7] == "v1_extensible"
    assert write_cursor.execute_calls[1][1][8] == "{}"
    assert '"snapshot_date": "2026-05-14"' in write_cursor.execute_calls[1][1][9]


def test_upsert_activity_subjective_feedback_persists_payload_and_activity_date(monkeypatch):
    user_cursor = _FakeCursor([("user-1",)])
    readiness_cursor = _FakeCursor(
        [
            (
                "2026-05-14",
                52.0,
                0.51,
                "Normal",
                {
                    "freshness": 1.5,
                    "recovery_score_simple": 66.0,
                },
            )
        ]
    )
    write_cursor = _FakeCursor(
        [
            None,
            (
                11,
                "user-1",
                17855535922,
                "2026-05-14",
                "post_ride_rpe",
                "moderate",
                3,
                "telegram",
                "v1_extensible",
                {"legs_fatigue": 2, "motivation": 4},
                {
                    "snapshot_date": "2026-05-14",
                    "readiness_score": 52.0,
                    "good_day_probability": 0.51,
                    "status_text": "Normal",
                    "recommendation": "endurance",
                    "freshness": 1.5,
                    "recovery_score": 66.0,
                    "recovery_explanation": None,
                },
                "2026-05-14T12:00:00Z",
                "2026-05-14T12:00:00Z",
            ),
        ]
    )

    connections = iter([_FakeConn(user_cursor), _FakeConn(readiness_cursor), _FakeConn(write_cursor)])
    monkeypatch.setattr(feedback_service, "get_conn", lambda: next(connections))

    result = feedback_service.upsert_activity_subjective_feedback(
        activity_id=17855535922,
        score=3,
        payload={"legs_fatigue": 2, "motivation": 4},
        activity_date="2026-05-14",
    )

    assert result["was_update"] is False
    assert result["activity_date"] == "2026-05-14"
    assert result["feedback_payload"] == {"legs_fatigue": 2, "motivation": 4}
    assert write_cursor.execute_calls[1][1][2] == "2026-05-14"
    assert write_cursor.execute_calls[1][1][8] == '{"legs_fatigue": 2, "motivation": 4}'


def test_upsert_activity_subjective_feedback_updates_existing_row(monkeypatch):
    user_cursor = _FakeCursor([("user-1",)])
    readiness_cursor = _FakeCursor(
        [
            (
                "2026-05-14",
                48.0,
                0.42,
                "Load",
                {
                    "freshness": -1.0,
                    "recovery_score_simple": 62.0,
                },
            )
        ]
    )
    write_cursor = _FakeCursor(
        [
            (99,),
            (
                99,
                "user-1",
                17855535922,
                None,
                "post_ride_rpe",
                "easy",
                2,
                "telegram",
                "v1_extensible",
                {},
                {
                    "snapshot_date": "2026-05-14",
                    "readiness_score": 48.0,
                    "good_day_probability": 0.42,
                    "status_text": "Load",
                    "recommendation": "endurance",
                    "freshness": -1.0,
                    "recovery_score": 62.0,
                    "recovery_explanation": None,
                },
                "2026-05-14T12:00:00Z",
                "2026-05-14T12:05:00Z",
            ),
        ]
    )

    connections = iter([_FakeConn(user_cursor), _FakeConn(readiness_cursor), _FakeConn(write_cursor)])
    monkeypatch.setattr(feedback_service, "get_conn", lambda: next(connections))

    result = feedback_service.upsert_activity_subjective_feedback(
        activity_id=17855535922,
        score=2,
    )

    assert result["was_update"] is True
    assert result["feedback_value"] == "easy"
    assert result["feedback_score"] == 2
    assert result["feedback_schema_version"] == "v1_extensible"
    assert result["feedback_payload"] == {}


def test_upsert_next_day_recovery_feedback_uses_date_level_uniqueness(monkeypatch):
    load_cursor = _FakeCursor(fetchone_values=[(2, 85.0)], fetchall_values=[[(17855535922,), (17855535923,)]])
    readiness_cursor = _FakeCursor(
        [
            (
                "2026-05-15",
                58.0,
                0.63,
                "Normal",
                {
                    "freshness": 2.0,
                    "recovery_score_simple": 68.0,
                    "recovery_explanation": {"hrv_score": 61.0},
                },
            )
        ]
    )
    write_cursor = _FakeCursor(
        [
            None,
            (
                19,
                "user-1",
                None,
                "2026-05-15",
                "next_day_recovery",
                "fresh",
                4,
                "telegram",
                "v1_extensible",
                {
                    "target_date": "2026-05-15",
                    "previous_date": "2026-05-14",
                    "previous_training_load": 85.0,
                    "previous_activities_count": 2,
                    "linked_activity_ids": [17855535922, 17855535923],
                },
                {
                    "snapshot_date": "2026-05-15",
                    "readiness_score": 58.0,
                    "good_day_probability": 0.63,
                    "status_text": "Normal",
                    "recommendation": "endurance",
                    "freshness": 2.0,
                    "recovery_score": 68.0,
                    "recovery_explanation": {"hrv_score": 61.0},
                    "target_date": "2026-05-15",
                    "previous_date": "2026-05-14",
                    "previous_training_load": 85.0,
                    "previous_activities_count": 2,
                    "linked_activity_ids": [17855535922, 17855535923],
                },
                "2026-05-15T08:00:00Z",
                "2026-05-15T08:00:00Z",
            ),
        ]
    )

    connections = iter([_FakeConn(load_cursor), _FakeConn(readiness_cursor), _FakeConn(write_cursor)])
    monkeypatch.setattr(feedback_service, "get_conn", lambda: next(connections))

    result = feedback_service.upsert_next_day_recovery_feedback(
        user_id="user-1",
        target_date="2026-05-15",
        score=4,
    )

    assert result["was_update"] is False
    assert result["activity_id"] is None
    assert result["activity_date"] == "2026-05-15"
    assert result["feedback_type"] == "next_day_recovery"
    assert result["feedback_value"] == "fresh"
    assert result["feedback_payload"]["linked_activity_ids"] == [17855535922, 17855535923]
    assert write_cursor.execute_calls[0][1] == ("user-1", "2026-05-15", "next_day_recovery")


def test_upsert_next_day_recovery_feedback_updates_existing_row(monkeypatch):
    load_cursor = _FakeCursor(fetchone_values=[(1, 42.0)], fetchall_values=[[(17855535922,)]])
    readiness_cursor = _FakeCursor(
        [
            (
                "2026-05-15",
                61.0,
                0.68,
                "Good",
                {
                    "freshness": 3.5,
                    "recovery_score_simple": 72.0,
                },
            )
        ]
    )
    write_cursor = _FakeCursor(
        [
            (55,),
            (
                55,
                "user-1",
                None,
                "2026-05-15",
                "next_day_recovery",
                "very_fresh",
                5,
                "telegram",
                "v1_extensible",
                {
                    "target_date": "2026-05-15",
                    "previous_date": "2026-05-14",
                    "previous_training_load": 42.0,
                    "previous_activities_count": 1,
                    "linked_activity_ids": [17855535922],
                },
                {
                    "snapshot_date": "2026-05-15",
                    "readiness_score": 61.0,
                    "good_day_probability": 0.68,
                    "status_text": "Good",
                    "recommendation": "moderate",
                    "freshness": 3.5,
                    "recovery_score": 72.0,
                    "recovery_explanation": None,
                    "target_date": "2026-05-15",
                    "previous_date": "2026-05-14",
                    "previous_training_load": 42.0,
                    "previous_activities_count": 1,
                    "linked_activity_ids": [17855535922],
                },
                "2026-05-15T08:00:00Z",
                "2026-05-15T08:05:00Z",
            ),
        ]
    )

    connections = iter([_FakeConn(load_cursor), _FakeConn(readiness_cursor), _FakeConn(write_cursor)])
    monkeypatch.setattr(feedback_service, "get_conn", lambda: next(connections))

    result = feedback_service.upsert_next_day_recovery_feedback(
        user_id="user-1",
        target_date="2026-05-15",
        score=5,
    )

    assert result["was_update"] is True
    assert result["feedback_value"] == "very_fresh"
    assert result["feedback_score"] == 5


def test_send_next_day_recovery_prompt_skips_when_previous_day_has_no_training(monkeypatch):
    monkeypatch.setattr(
        feedback_service,
        "_load_recovery_prompt_context",
        lambda user_id, recovery_date: {
            "user_id": user_id,
            "target_date": "2026-05-15",
            "previous_date": "2026-05-14",
            "activities_count": 0,
            "previous_training_load": 0.0,
            "linked_activity_ids": [],
            "has_training": False,
        },
    )

    result = feedback_service.send_next_day_recovery_prompt("user-1", "2026-05-15")

    assert result == {
        "ok": True,
        "skipped": True,
        "reason": "no_previous_training_day",
        "prompt_log": None,
        "user_id": "user-1",
        "target_date": "2026-05-15",
        "previous_date": "2026-05-14",
        "activities_count": 0,
        "previous_training_load": 0.0,
        "linked_activity_ids": [],
        "has_training": False,
    }


def test_send_next_day_recovery_prompt_sends_when_previous_day_has_training(monkeypatch):
    claim_calls = []
    sent_messages = []

    monkeypatch.setattr(
        feedback_service,
        "_load_recovery_prompt_context",
        lambda user_id, recovery_date: {
            "user_id": user_id,
            "target_date": "2026-05-15",
            "previous_date": "2026-05-14",
            "activities_count": 1,
            "previous_training_load": 47.0,
            "linked_activity_ids": [17855535922],
            "has_training": True,
        },
    )
    monkeypatch.setattr(feedback_service, "has_next_day_recovery_feedback", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        feedback_service,
        "_claim_recovery_prompt_delivery",
        lambda **kwargs: claim_calls.append(kwargs) or {
            "id": 21,
            "user_id": kwargs["user_id"],
            "prompt_type": "next_day_recovery",
            "target_date": "2026-05-15",
            "sent_at": None,
            "source": kwargs["source"],
            "delivery_status": "pending",
            "telegram_message_id": None,
            "created_at": "2026-05-15T08:00:00Z",
            "updated_at": "2026-05-15T08:00:00Z",
        },
    )
    monkeypatch.setattr(
        feedback_service,
        "send_telegram_message",
        lambda text, reply_markup=None: sent_messages.append((text, reply_markup)) or {"result": {"message_id": 444}},
    )
    monkeypatch.setattr(
        feedback_service,
        "_mark_prompt_delivery_result",
        lambda **kwargs: {
            "id": kwargs["prompt_log_id"],
            "user_id": "user-1",
            "prompt_type": "next_day_recovery",
            "target_date": "2026-05-15",
            "sent_at": "2026-05-15T08:00:03Z",
            "source": "debug",
            "delivery_status": kwargs["delivery_status"],
            "telegram_message_id": kwargs["telegram_message_id"],
            "created_at": "2026-05-15T08:00:00Z",
            "updated_at": "2026-05-15T08:00:03Z",
        },
    )

    result = feedback_service.send_next_day_recovery_prompt("user-1", "2026-05-15")

    assert result["ok"] is True
    assert result["skipped"] is False
    assert result["reason"] is None
    assert result["activities_count"] == 1
    assert result["previous_training_load"] == 47.0
    assert result["prompt_log"]["delivery_status"] == "sent"
    assert result["prompt_log"]["telegram_message_id"] == 444
    assert claim_calls == [
        {
            "user_id": "user-1",
            "target_date": "2026-05-15",
            "source": "debug",
        }
    ]
    assert sent_messages == [
        (
            "Human Engine\n\nHow recovered do you feel today?\n\nThis helps calibrate readiness after yesterday's training.",
            feedback_service.build_next_day_recovery_keyboard("user-1", "2026-05-15"),
        )
    ]


def test_handle_telegram_feedback_callback_rejects_invalid_payload(monkeypatch):
    logged_events: list[tuple[str, dict]] = []
    callback_answers: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        feedback_service,
        "log_event",
        lambda logger, event, **kwargs: logged_events.append((event, kwargs)),
    )
    monkeypatch.setattr(
        feedback_service,
        "answer_telegram_callback",
        lambda callback_query_id, text=None: callback_answers.append((callback_query_id, text)),
    )

    result = feedback_service.handle_telegram_feedback_callback(
        {
            "callback_query": {
                "id": "cb-1",
                "data": "bad-payload",
            }
        }
    )

    assert result == {"ok": False, "reason": "invalid_callback"}
    assert logged_events[0][0] == "feedback_invalid_callback"
    assert callback_answers == [("cb-1", "Invalid feedback payload.")]


def test_handle_telegram_feedback_callback_best_effort_when_telegram_ack_fails(monkeypatch):
    logged_events: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        feedback_service,
        "upsert_activity_subjective_feedback",
        lambda **kwargs: {
            "id": 7,
            "user_id": "user-1",
            "activity_id": kwargs["activity_id"],
            "activity_date": None,
            "feedback_type": "post_ride_rpe",
            "feedback_value": "moderate",
            "feedback_score": kwargs["score"],
            "source": kwargs["source"],
            "feedback_schema_version": "v1_extensible",
            "feedback_payload": {},
            "context": {"readiness_score": 55.0},
            "created_at": "2026-05-14T12:00:00Z",
            "updated_at": "2026-05-14T12:00:01Z",
            "was_update": False,
        },
    )
    monkeypatch.setattr(
        feedback_service,
        "log_event",
        lambda logger, event, **kwargs: logged_events.append((event, kwargs)),
    )

    def raise_http_error(*args, **kwargs):
        response = requests.Response()
        response.status_code = 400
        raise requests.HTTPError("telegram bad request", response=response)

    edit_calls: list[tuple[int, int, str]] = []
    monkeypatch.setattr(feedback_service, "answer_telegram_callback", raise_http_error)
    monkeypatch.setattr(
        feedback_service,
        "edit_telegram_message",
        lambda chat_id, message_id, text: edit_calls.append((chat_id, message_id, text)),
    )

    result = feedback_service.handle_telegram_feedback_callback(
        {
            "callback_query": {
                "id": "fake-callback",
                "data": "rpe:17855535922:3",
                "message": {
                    "message_id": 77,
                    "chat": {"id": 9001},
                },
            }
        }
    )

    assert result["ok"] is True
    assert result["activity_id"] == 17855535922
    assert edit_calls == [(9001, 77, "Feedback recorded ✓")]
    assert logged_events == [
        (
            "telegram_callback_ack_failed",
            {
                "level": 30,
                "callback_query_id": "fake-callback",
                "ack_text": "Feedback recorded.",
                "activity_id": 17855535922,
                "user_id": "user-1",
                "activity_date": None,
                "feedback_type": "post_ride_rpe",
                "source": "telegram",
            },
        )
    ]


def test_handle_telegram_recovery_callback_best_effort_when_telegram_edit_fails(monkeypatch):
    logged_events: list[tuple[str, dict]] = []
    callback_answers: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        feedback_service,
        "upsert_next_day_recovery_feedback",
        lambda **kwargs: {
            "id": 8,
            "user_id": kwargs["user_id"],
            "activity_id": None,
            "activity_date": kwargs["target_date"],
            "feedback_type": "next_day_recovery",
            "feedback_value": "fresh",
            "feedback_score": kwargs["score"],
            "source": kwargs["source"],
            "feedback_schema_version": "v1_extensible",
            "feedback_payload": {},
            "context": {"readiness_score": 60.0},
            "created_at": "2026-05-15T08:00:00Z",
            "updated_at": "2026-05-15T08:00:01Z",
            "was_update": False,
        },
    )
    monkeypatch.setattr(
        feedback_service,
        "log_event",
        lambda logger, event, **kwargs: logged_events.append((event, kwargs)),
    )
    monkeypatch.setattr(
        feedback_service,
        "answer_telegram_callback",
        lambda callback_query_id, text=None: callback_answers.append((callback_query_id, text)),
    )

    def raise_http_error(*args, **kwargs):
        response = requests.Response()
        response.status_code = 400
        raise requests.HTTPError("telegram bad request", response=response)

    monkeypatch.setattr(feedback_service, "edit_telegram_message", raise_http_error)

    result = feedback_service.handle_telegram_feedback_callback(
        {
            "callback_query": {
                "id": "recovery-callback",
                "data": "recovery:user-1:2026-05-15:4",
                "message": {
                    "message_id": 88,
                    "chat": {"id": 9001},
                },
            }
        }
    )

    assert result["ok"] is True
    assert result["activity_date"] == "2026-05-15"
    assert callback_answers == [("recovery-callback", "Feedback recorded.")]
    assert logged_events == [
        (
            "telegram_feedback_message_edit_failed",
            {
                "level": 30,
                "chat_id": 9001,
                "message_id": 88,
                "message_text": "Recovery feedback recorded ✓",
                "activity_id": None,
                "user_id": "user-1",
                "activity_date": "2026-05-15",
                "feedback_type": "next_day_recovery",
                "source": "telegram",
            },
        )
    ]


def test_handle_telegram_feedback_callback_is_safe_for_duplicate_callbacks(monkeypatch):
    callback_answers: list[tuple[str, str | None]] = []
    edited_messages: list[tuple[int, int, str]] = []
    upsert_calls: list[tuple[int, int, str]] = []

    def fake_upsert(*, activity_id, score, source):
        upsert_calls.append((activity_id, score, source))
        return {
            "user_id": "user-1",
            "activity_id": activity_id,
            "activity_date": None,
            "feedback_type": "post_ride_rpe",
            "feedback_value": "moderate",
            "feedback_score": score,
            "source": source,
            "feedback_schema_version": "v1_extensible",
            "feedback_payload": {},
            "context": {"readiness_score": 55.0},
            "created_at": "2026-05-14T12:00:00Z",
            "updated_at": "2026-05-14T12:00:01Z",
            "was_update": len(upsert_calls) > 1,
        }

    monkeypatch.setattr(feedback_service, "upsert_activity_subjective_feedback", fake_upsert)
    monkeypatch.setattr(
        feedback_service,
        "answer_telegram_callback",
        lambda callback_query_id, text=None: callback_answers.append((callback_query_id, text)),
    )
    monkeypatch.setattr(
        feedback_service,
        "edit_telegram_message",
        lambda chat_id, message_id, text: edited_messages.append((chat_id, message_id, text)),
    )

    payload = {
        "callback_query": {
            "id": "cb-1",
            "data": "rpe:17855535922:3",
            "message": {
                "message_id": 77,
                "chat": {"id": 9001},
            },
        }
    }

    first = feedback_service.handle_telegram_feedback_callback(payload)
    second = feedback_service.handle_telegram_feedback_callback(payload)

    assert first["ok"] is True
    assert second["ok"] is True
    assert upsert_calls == [
        (17855535922, 3, "telegram"),
        (17855535922, 3, "telegram"),
    ]
    assert callback_answers == [
        ("cb-1", "Feedback recorded."),
        ("cb-1", "Feedback recorded."),
    ]
    assert edited_messages == [
        (9001, 77, "Feedback recorded ✓"),
        (9001, 77, "Feedback recorded ✓"),
    ]


def test_telegram_webhook_endpoint_routes_callback_updates(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "handle_telegram_feedback_callback",
        lambda payload: {"ok": True, "activity_id": 42},
    )

    client = TestClient(app_module.app)
    response = client.post("/telegram/webhook", json={"callback_query": {"id": "cb-1"}})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "activity_id": 42}


def test_debug_recovery_prompt_endpoint_returns_service_payload(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "send_next_day_recovery_prompt",
        lambda user_id, recovery_date: {
            "ok": True,
            "skipped": False,
            "reason": None,
            "user_id": user_id,
            "target_date": recovery_date,
            "previous_date": "2026-05-14",
            "activities_count": 1,
            "previous_training_load": 47.0,
            "linked_activity_ids": [17855535922],
            "has_training": True,
        },
    )

    client = TestClient(app_module.app)
    response = client.post("/debug/feedback/recovery-prompt/user-1/2026-05-15")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "skipped": False,
        "reason": None,
        "user_id": "user-1",
        "target_date": "2026-05-15",
        "previous_date": "2026-05-14",
        "activities_count": 1,
        "previous_training_load": 47.0,
        "linked_activity_ids": [17855535922],
        "has_training": True,
    }


def test_claim_recovery_prompt_delivery_inserts_pending_row(monkeypatch):
    cursor = _FakeCursor(
        fetchone_values=[
            (
                31,
                "user-1",
                "next_day_recovery",
                "2026-05-15",
                None,
                "scheduler",
                "pending",
                None,
                "2026-05-15T08:00:00Z",
                "2026-05-15T08:00:00Z",
            )
        ]
    )
    monkeypatch.setattr(feedback_service, "get_conn", lambda: _FakeConn(cursor))

    result = feedback_service._claim_recovery_prompt_delivery(
        user_id="user-1",
        target_date="2026-05-15",
        source="scheduler",
    )

    assert result["delivery_status"] == "pending"
    assert result["source"] == "scheduler"
    assert cursor.execute_calls[0][1] == (
        "user-1",
        "next_day_recovery",
        feedback_service._coerce_iso_date("2026-05-15"),
        "scheduler",
        "pending",
    )


def test_mark_prompt_delivery_result_updates_sent_metadata(monkeypatch):
    cursor = _FakeCursor(
        fetchone_values=[
            (
                31,
                "user-1",
                "next_day_recovery",
                "2026-05-15",
                "2026-05-15T08:00:03Z",
                "scheduler",
                "sent",
                444,
                "2026-05-15T08:00:00Z",
                "2026-05-15T08:00:03Z",
            )
        ]
    )
    monkeypatch.setattr(feedback_service, "get_conn", lambda: _FakeConn(cursor))

    result = feedback_service._mark_prompt_delivery_result(
        prompt_log_id=31,
        delivery_status="sent",
        telegram_message_id=444,
    )

    assert result["delivery_status"] == "sent"
    assert result["telegram_message_id"] == 444
    assert cursor.execute_calls[0][1] == ("sent", "sent", "sent", 444, 31)


def test_deliver_next_day_recovery_prompt_skips_when_feedback_already_exists(monkeypatch):
    monkeypatch.setattr(
        feedback_service,
        "_load_recovery_prompt_context",
        lambda user_id, recovery_date: {
            "user_id": user_id,
            "target_date": "2026-05-15",
            "previous_date": "2026-05-14",
            "activities_count": 1,
            "previous_training_load": 47.0,
            "linked_activity_ids": [17855535922],
            "has_training": True,
        },
    )
    monkeypatch.setattr(feedback_service, "has_next_day_recovery_feedback", lambda *args, **kwargs: True)

    result = feedback_service.deliver_next_day_recovery_prompt(
        user_id="user-1",
        recovery_date="2026-05-15",
    )

    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["reason"] == "feedback_already_exists"
    assert result["prompt_log"] is None


def test_deliver_next_day_recovery_prompt_prevents_duplicate_prompt(monkeypatch):
    monkeypatch.setattr(
        feedback_service,
        "_load_recovery_prompt_context",
        lambda user_id, recovery_date: {
            "user_id": user_id,
            "target_date": "2026-05-15",
            "previous_date": "2026-05-14",
            "activities_count": 1,
            "previous_training_load": 47.0,
            "linked_activity_ids": [17855535922],
            "has_training": True,
        },
    )
    monkeypatch.setattr(feedback_service, "has_next_day_recovery_feedback", lambda *args, **kwargs: False)
    monkeypatch.setattr(feedback_service, "_claim_recovery_prompt_delivery", lambda **kwargs: None)
    monkeypatch.setattr(
        feedback_service,
        "get_recovery_prompt_log",
        lambda *args, **kwargs: {
            "id": 21,
            "user_id": "user-1",
            "prompt_type": "next_day_recovery",
            "target_date": "2026-05-15",
            "sent_at": "2026-05-15T08:00:03Z",
            "source": "scheduler",
            "delivery_status": "sent",
            "telegram_message_id": 444,
            "created_at": "2026-05-15T08:00:00Z",
            "updated_at": "2026-05-15T08:00:03Z",
        },
    )

    result = feedback_service.deliver_next_day_recovery_prompt(
        user_id="user-1",
        recovery_date="2026-05-15",
    )

    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["reason"] == "prompt_already_sent"
    assert result["prompt_log"]["delivery_status"] == "sent"


def test_schedule_next_day_recovery_prompts_sends_prompt_after_training_day(monkeypatch):
    monkeypatch.setattr(
        feedback_service,
        "list_recovery_prompt_candidate_users",
        lambda target_date: ["user-1"],
    )
    monkeypatch.setattr(
        feedback_service,
        "deliver_next_day_recovery_prompt",
        lambda **kwargs: {"ok": True, "skipped": False, "reason": None},
    )

    result = feedback_service.schedule_next_day_recovery_prompts(target_date="2026-05-15")

    assert result == {
        "ok": True,
        "target_date": "2026-05-15",
        "candidate_users": ["user-1"],
        "processed_users": 1,
        "sent_count": 1,
        "skipped_count": 0,
        "failed_count": 0,
        "results": [{"user_id": "user-1", "ok": True, "skipped": False, "reason": None}],
    }


def test_schedule_next_day_recovery_prompts_skips_users_without_load_activity(monkeypatch):
    monkeypatch.setattr(
        feedback_service,
        "list_recovery_prompt_candidate_users",
        lambda target_date: [],
    )

    result = feedback_service.schedule_next_day_recovery_prompts(target_date="2026-05-15")

    assert result == {
        "ok": True,
        "target_date": "2026-05-15",
        "candidate_users": [],
        "processed_users": 0,
        "sent_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "results": [],
    }


def test_schedule_next_day_recovery_prompts_is_idempotent_across_repeated_runs(monkeypatch):
    calls = []

    monkeypatch.setattr(
        feedback_service,
        "list_recovery_prompt_candidate_users",
        lambda target_date: ["user-1"],
    )

    def fake_deliver(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return {"ok": True, "skipped": False, "reason": None}
        return {"ok": True, "skipped": True, "reason": "prompt_already_sent"}

    monkeypatch.setattr(feedback_service, "deliver_next_day_recovery_prompt", fake_deliver)

    first = feedback_service.schedule_next_day_recovery_prompts(target_date="2026-05-15")
    second = feedback_service.schedule_next_day_recovery_prompts(target_date="2026-05-15")

    assert first["sent_count"] == 1
    assert first["skipped_count"] == 0
    assert second["sent_count"] == 0
    assert second["skipped_count"] == 1
    assert second["results"] == [
        {"user_id": "user-1", "ok": True, "skipped": True, "reason": "prompt_already_sent"}
    ]


def test_handle_telegram_recovery_callback_is_safe_for_duplicate_callbacks(monkeypatch):
    callback_answers = []
    edited_messages = []
    upsert_calls = []

    def fake_upsert(*, user_id, target_date, score, source):
        upsert_calls.append((user_id, target_date, score, source))
        return {
            "user_id": user_id,
            "activity_id": None,
            "activity_date": target_date,
            "feedback_type": "next_day_recovery",
            "feedback_value": "fresh",
            "feedback_score": score,
            "source": source,
            "feedback_schema_version": "v1_extensible",
            "feedback_payload": {},
            "context": {"readiness_score": 60.0},
            "created_at": "2026-05-15T08:00:00Z",
            "updated_at": "2026-05-15T08:00:01Z",
            "was_update": len(upsert_calls) > 1,
        }

    monkeypatch.setattr(feedback_service, "upsert_next_day_recovery_feedback", fake_upsert)
    monkeypatch.setattr(
        feedback_service,
        "answer_telegram_callback",
        lambda callback_query_id, text=None: callback_answers.append((callback_query_id, text)),
    )
    monkeypatch.setattr(
        feedback_service,
        "edit_telegram_message",
        lambda chat_id, message_id, text: edited_messages.append((chat_id, message_id, text)),
    )

    payload = {
        "callback_query": {
            "id": "cb-1",
            "data": "recovery:user-1:2026-05-15:4",
            "message": {
                "message_id": 88,
                "chat": {"id": 9001},
            },
        }
    }

    first = feedback_service.handle_telegram_feedback_callback(payload)
    second = feedback_service.handle_telegram_feedback_callback(payload)

    assert first["ok"] is True
    assert second["ok"] is True
    assert upsert_calls == [
        ("user-1", "2026-05-15", 4, "telegram"),
        ("user-1", "2026-05-15", 4, "telegram"),
    ]
    assert callback_answers == [
        ("cb-1", "Feedback recorded."),
        ("cb-1", "Feedback recorded."),
    ]
    assert edited_messages == [
        (9001, 88, "Recovery feedback recorded ✓"),
        (9001, 88, "Recovery feedback recorded ✓"),
    ]


def test_debug_recovery_prompt_batch_endpoint_returns_scheduler_payload(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "schedule_next_day_recovery_prompts",
        lambda target_date, source: {
            "ok": True,
            "target_date": target_date,
            "candidate_users": ["user-1"],
            "processed_users": 1,
            "sent_count": 1,
            "skipped_count": 0,
            "failed_count": 0,
            "results": [{"user_id": "user-1", "ok": True, "skipped": False, "reason": None}],
        },
    )

    client = TestClient(app_module.app)
    response = client.post("/debug/feedback/recovery-prompts/2026-05-15")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "target_date": "2026-05-15",
        "candidate_users": ["user-1"],
        "processed_users": 1,
        "sent_count": 1,
        "skipped_count": 0,
        "failed_count": 0,
        "results": [{"user_id": "user-1", "ok": True, "skipped": False, "reason": None}],
    }


