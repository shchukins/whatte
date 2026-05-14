from fastapi.testclient import TestClient

from backend import app as app_module
from backend.services import subjective_feedback_service as feedback_service


class _FakeCursor:
    def __init__(self, fetchone_values=None) -> None:
        self.fetchone_values = list(fetchone_values or [])
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


def test_build_post_ride_rpe_keyboard_uses_expected_score_mapping():
    keyboard = feedback_service.build_post_ride_rpe_keyboard(42)

    assert keyboard["inline_keyboard"][0][0]["text"] == "😌 Very easy"
    assert keyboard["inline_keyboard"][0][0]["callback_data"] == "rpe:42:1"
    assert keyboard["inline_keyboard"][-1][0]["text"] == "☠️ Very hard"
    assert keyboard["inline_keyboard"][-1][0]["callback_data"] == "rpe:42:5"


def test_upsert_activity_subjective_feedback_inserts_with_context_snapshot(monkeypatch):
    user_cursor = _FakeCursor([("user-1",)])
    readiness_cursor = _FakeCursor(
        [
            (
                63.5,
                {
                    "freshness": 4.2,
                    "recovery_score_simple": 71.0,
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
                "post_ride_rpe",
                "hard",
                4,
                "telegram",
                {
                    "readiness_score": 63.5,
                    "recommendation": "moderate",
                    "freshness": 4.2,
                    "recovery_score": 71.0,
                },
                "2026-05-14T12:00:00Z",
                "2026-05-14T12:00:00Z",
            ),
        ]
    )

    user_conn = _FakeConn(user_cursor)
    readiness_conn = _FakeConn(readiness_cursor)
    write_conn = _FakeConn(write_cursor)
    connections = iter([user_conn, readiness_conn, write_conn])

    monkeypatch.setattr(feedback_service, "get_conn", lambda: next(connections))

    result = feedback_service.upsert_activity_subjective_feedback(
        activity_id=17855535922,
        score=4,
    )

    assert result["was_update"] is False
    assert result["feedback_value"] == "hard"
    assert result["feedback_score"] == 4
    assert result["context"] == {
        "readiness_score": 63.5,
        "recommendation": "moderate",
        "freshness": 4.2,
        "recovery_score": 71.0,
    }
    assert write_conn.committed is True
    assert (
        write_cursor.execute_calls[1][1][6]
        == '{"readiness_score": 63.5, "recommendation": "moderate", "freshness": 4.2, "recovery_score": 71.0}'
    )


def test_upsert_activity_subjective_feedback_updates_existing_row(monkeypatch):
    user_cursor = _FakeCursor([("user-1",)])
    readiness_cursor = _FakeCursor(
        [
            (
                48.0,
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
                "post_ride_rpe",
                "easy",
                2,
                "telegram",
                {
                    "readiness_score": 48.0,
                    "recommendation": "endurance",
                    "freshness": -1.0,
                    "recovery_score": 62.0,
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


def test_handle_telegram_feedback_callback_is_safe_for_duplicate_callbacks(monkeypatch):
    callback_answers: list[tuple[str, str | None]] = []
    edited_messages: list[tuple[int, int, str]] = []
    upsert_calls: list[tuple[int, int, str]] = []

    def fake_upsert(*, activity_id, score, source):
        upsert_calls.append((activity_id, score, source))
        return {
            "user_id": "user-1",
            "activity_id": activity_id,
            "feedback_type": "post_ride_rpe",
            "feedback_value": "moderate",
            "feedback_score": score,
            "source": source,
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
