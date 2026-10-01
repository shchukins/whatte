from datetime import date

from backend import app as app_module
from backend.config import settings
from backend.services import subjective_feedback_service as feedback_service
from backend.services import telegram_physiology_service as physiology_telegram


TODAY = date(2026, 10, 1)


def _session(*, field="sleep_duration_minutes", status="active"):
    return {
        "user_id": "sergey",
        "local_date": TODAY,
        "telegram_chat_id": "9001",
        "session_token": "current-token",
        "status": status,
        "current_field": field,
    }


def test_parse_physiology_callbacks_distinguishes_offer_and_session_actions():
    assert physiology_telegram.parse_physiology_callback_data("physio:start:2026-10-01") == {
        "action": "start", "target_date": "2026-10-01"
    }
    assert physiology_telegram.parse_physiology_callback_data("physio:skip:2026-10-01") == {
        "action": "skip_offer", "target_date": "2026-10-01"
    }
    assert physiology_telegram.parse_physiology_callback_data("physio:token:skip") == {
        "action": "skip", "session_token": "token"
    }
    assert physiology_telegram.parse_physiology_callback_data("physio:start:not-a-date") is None


def test_start_callback_shows_current_values_then_first_field(monkeypatch):
    sent = []
    answers = []
    monkeypatch.setattr(physiology_telegram, "local_today", lambda: TODAY)
    monkeypatch.setattr(physiology_telegram, "_is_configured_chat", lambda chat_id: True)
    monkeypatch.setattr(physiology_telegram, "start_session", lambda **kwargs: _session())
    monkeypatch.setattr(physiology_telegram, "_format_current_values", lambda *args: "Текущих показателей нет.")
    monkeypatch.setattr(physiology_telegram, "answer_telegram_callback", lambda callback_id, text=None: answers.append((callback_id, text)))
    monkeypatch.setattr(physiology_telegram, "send_telegram_message", lambda text, **kwargs: sent.append((text, kwargs)))

    result = physiology_telegram.handle_telegram_physiology_callback({
        "callback_query": {
            "id": "start-1", "data": "physio:start:2026-10-01",
            "message": {"chat": {"id": 9001}},
        }
    })

    assert result == {"ok": True, "session_token": "current-token", "current_field": "sleep_duration_minutes"}
    assert answers == [("start-1", "Optional physiology check-in started.")]
    assert sent[0][0] == "Текущих показателей нет."
    assert sent[1][0].startswith("Сон за прошлую ночь")
    assert sent[1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "physio:current-token:skip"


def test_message_saves_partial_value_and_moves_to_next_field(monkeypatch):
    saved = []
    sent = []
    monkeypatch.setattr(physiology_telegram, "_is_configured_chat", lambda chat_id: True)
    monkeypatch.setattr(physiology_telegram, "local_today", lambda: TODAY)
    monkeypatch.setattr(physiology_telegram, "claim_active_session_for_text", lambda **kwargs: _session())
    monkeypatch.setattr(physiology_telegram, "save_manual_physiology_observation", lambda **kwargs: saved.append(kwargs))
    monkeypatch.setattr(physiology_telegram, "advance_session", lambda **kwargs: _session(field="sleep_quality"))
    monkeypatch.setattr(physiology_telegram, "send_telegram_message", lambda text, **kwargs: sent.append((text, kwargs)))

    result = physiology_telegram.handle_telegram_physiology_message({
        "message": {"chat": {"id": 9001}, "text": "450"}
    })

    assert result == {"ok": True, "current_field": "sleep_quality", "complete": False}
    assert saved[0]["user_id"] == "sergey"
    assert saved[0]["patch"].sleep_duration_minutes == 450
    assert saved[0]["patch"].source == "telegram"
    assert sent[0][0].startswith("Качество сна")


def test_invalid_message_keeps_session_active_and_offers_retry(monkeypatch):
    restored = []
    sent = []
    monkeypatch.setattr(physiology_telegram, "_is_configured_chat", lambda chat_id: True)
    monkeypatch.setattr(physiology_telegram, "local_today", lambda: TODAY)
    monkeypatch.setattr(physiology_telegram, "claim_active_session_for_text", lambda **kwargs: _session(field="hrv_ms"))
    monkeypatch.setattr(physiology_telegram, "restore_active_session", lambda token: restored.append(token))
    monkeypatch.setattr(physiology_telegram, "send_telegram_message", lambda text, **kwargs: sent.append((text, kwargs)))

    result = physiology_telegram.handle_telegram_physiology_message({
        "message": {"chat": {"id": 9001}, "text": "0"}
    })

    assert result == {"ok": False, "reason": "invalid_value", "current_field": "hrv_ms"}
    assert restored == ["current-token"]
    assert "Введите число" in sent[0][0]


def test_stale_skip_callback_cannot_change_observation(monkeypatch):
    answers = []
    monkeypatch.setattr(physiology_telegram, "_is_configured_chat", lambda chat_id: True)
    monkeypatch.setattr(physiology_telegram, "local_today", lambda: TODAY)
    monkeypatch.setattr(physiology_telegram, "skip_session_field", lambda **kwargs: None)
    monkeypatch.setattr(physiology_telegram, "answer_telegram_callback", lambda callback_id, text=None: answers.append((callback_id, text)))

    result = physiology_telegram.handle_telegram_physiology_callback({
        "callback_query": {
            "id": "old-1", "data": "physio:old-token:skip",
            "message": {"chat": {"id": 9001}},
        }
    })

    assert result == {"ok": False, "reason": "stale_callback"}
    assert answers == [("old-1", "This check-in has expired.")]


def test_webhook_routes_ordinary_messages_to_physiology_handler(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        app_module, "handle_telegram_physiology_message", lambda payload: {"ok": True, "current_field": "hrv_ms"}
    )
    client = TestClient(app_module.app)

    response = client.post("/telegram/webhook", json={"message": {"text": "54"}})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "current_field": "hrv_ms"}


def test_recovery_callback_offers_optional_physiology_once(monkeypatch):
    offers = []
    monkeypatch.setattr(settings, "daily_readiness_user_id", "sergey")
    monkeypatch.setattr(feedback_service, "handle_telegram_physiology_callback", lambda payload: None)
    monkeypatch.setattr(
        feedback_service,
        "upsert_next_day_recovery_feedback",
        lambda **kwargs: {
            "user_id": "sergey", "activity_id": None, "activity_date": "2026-10-01",
            "feedback_type": "next_day_recovery", "source": "telegram", "was_update": False,
        },
    )
    monkeypatch.setattr(feedback_service, "answer_telegram_callback", lambda *args, **kwargs: None)
    monkeypatch.setattr(feedback_service, "edit_telegram_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        feedback_service, "send_telegram_message", lambda text, **kwargs: offers.append((text, kwargs))
    )

    result = feedback_service.handle_telegram_feedback_callback({
        "callback_query": {
            "id": "recovery-1", "data": "recovery:sergey:2026-10-01:4",
            "message": {"message_id": 7, "chat": {"id": 9001}},
        }
    })

    assert result["ok"] is True
    assert offers == [
        (
            "Дополнительно можно записать сон, HRV и пульс. Это необязательно.",
            {
                "reply_markup": feedback_service.build_physiology_offer_keyboard("2026-10-01"),
                "chat_id": 9001,
            },
        )
    ]
