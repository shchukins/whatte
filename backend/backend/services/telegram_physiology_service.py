"""Telegram-only interaction state for optional manual physiology input.

The state table holds no physiology values. Each accepted value is immediately
saved through the versioned manual-physiology persistence contract.
"""

from __future__ import annotations

import logging
import secrets
from datetime import date
from typing import Any

from backend.config import settings
from backend.core.logging import log_event
from backend.db import get_conn
from backend.services.manual_physiology_service import (
    ManualPhysiologyPatch,
    get_manual_physiology_observation,
    local_today,
    save_manual_physiology_observation,
)
from backend.services.telegram_service import answer_telegram_callback, send_telegram_message


logger = logging.getLogger(__name__)

CALLBACK_PREFIX = "physio"
START_ACTION = "start"
SKIP_ACTION = "skip"
STATUS_ACTIVE = "active"
STATUS_PROCESSING = "processing"
STATUS_SKIPPED = "skipped"
STATUS_COMPLETE = "complete"
FIELDS = (
    "sleep_duration_minutes",
    "sleep_quality",
    "hrv_ms",
    "resting_hr_bpm",
)
FIELD_PROMPTS = {
    "sleep_duration_minutes": "Сон за прошлую ночь, в минутах (например, 450).",
    "sleep_quality": "Качество сна по шкале 1–5.",
    "hrv_ms": "HRV в мс (например, 54.2).",
    "resting_hr_bpm": "Пульс покоя, уд/мин (например, 48).",
}


def _coerce_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _is_configured_chat(chat_id: int | str | None) -> bool:
    return chat_id is not None and str(chat_id) == str(settings.telegram_chat_id)


def build_start_callback_data(target_date: str | date) -> str:
    target = target_date if isinstance(target_date, date) else date.fromisoformat(target_date)
    return f"{CALLBACK_PREFIX}:{START_ACTION}:{target.isoformat()}"


def build_skip_callback_data(session_token: str) -> str:
    return f"{CALLBACK_PREFIX}:{session_token}:{SKIP_ACTION}"


def build_physiology_offer_keyboard(target_date: str | date) -> dict[str, Any]:
    return {
        "inline_keyboard": [[
            {"text": "Добавить показатели", "callback_data": build_start_callback_data(target_date)},
            {"text": "Пропустить", "callback_data": f"{CALLBACK_PREFIX}:{SKIP_ACTION}:{target_date}"},
        ]]
    }


def build_skip_keyboard(session_token: str) -> dict[str, Any]:
    return {"inline_keyboard": [[
        {"text": "Пропустить", "callback_data": build_skip_callback_data(session_token)},
    ]]}


def parse_physiology_callback_data(data: str | None) -> dict[str, str] | None:
    if not data:
        return None
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        return None
    if parts[1] == START_ACTION:
        target_date = _coerce_date(parts[2])
        return {"action": START_ACTION, "target_date": target_date.isoformat()} if target_date else None
    if parts[1] == SKIP_ACTION:
        target_date = _coerce_date(parts[2])
        return {"action": "skip_offer", "target_date": target_date.isoformat()} if target_date else None
    if parts[2] == SKIP_ACTION and parts[1]:
        return {"action": SKIP_ACTION, "session_token": parts[1]}
    return None


def _next_field(current_field: str) -> str | None:
    return FIELDS[FIELDS.index(current_field) + 1] if current_field != FIELDS[-1] else None


def _row_to_session(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "user_id": row[0], "local_date": row[1], "telegram_chat_id": row[2],
        "session_token": row[3], "status": row[4], "current_field": row[5],
    }


def start_session(*, user_id: str, local_date: date, chat_id: int | str) -> dict[str, Any]:
    """Replace a same-day unfinished session so old inline callbacks are stale."""
    session_token = secrets.token_urlsafe(12)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into telegram_physiology_checkin_session (
                    user_id, local_date, telegram_chat_id, session_token, status, current_field
                ) values (%s, %s, %s, %s, %s, %s)
                on conflict (user_id, local_date) do update set
                    telegram_chat_id = excluded.telegram_chat_id,
                    session_token = excluded.session_token,
                    status = excluded.status,
                    current_field = excluded.current_field,
                    updated_at = now()
                returning user_id, local_date, telegram_chat_id, session_token, status, current_field;
                """,
                (user_id, local_date, str(chat_id), session_token, STATUS_ACTIVE, FIELDS[0]),
            )
            row = cur.fetchone()
            conn.commit()
    return _row_to_session(row)


def claim_active_session_for_text(*, user_id: str, chat_id: int | str, target_date: date) -> dict[str, Any] | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select user_id, local_date, telegram_chat_id, session_token, status, current_field
                from telegram_physiology_checkin_session
                where user_id = %s and local_date = %s and telegram_chat_id = %s
                  and status = %s
                for update;
                """,
                (user_id, target_date, str(chat_id), STATUS_ACTIVE),
            )
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return None
            session = _row_to_session(row)
            cur.execute(
                """update telegram_physiology_checkin_session
                   set status = %s, updated_at = now()
                   where session_token = %s and status = %s;""",
                (STATUS_PROCESSING, session["session_token"], STATUS_ACTIVE),
            )
            conn.commit()
    return session


def restore_active_session(session_token: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """update telegram_physiology_checkin_session set status = %s, updated_at = now()
                   where session_token = %s and status = %s;""",
                (STATUS_ACTIVE, session_token, STATUS_PROCESSING),
            )
            conn.commit()


def advance_session(*, session_token: str, current_field: str) -> dict[str, Any] | None:
    next_field = _next_field(current_field)
    next_status = STATUS_ACTIVE if next_field else STATUS_COMPLETE
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update telegram_physiology_checkin_session
                set status = %s, current_field = %s, updated_at = now()
                where session_token = %s and status = %s and current_field = %s
                returning user_id, local_date, telegram_chat_id, session_token, status, current_field;
                """,
                (next_status, next_field, session_token, STATUS_PROCESSING, current_field),
            )
            row = cur.fetchone()
            conn.commit()
    return _row_to_session(row) if row else None


def skip_session_field(
    *, session_token: str, chat_id: int | str, target_date: date
) -> dict[str, Any] | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select user_id, local_date, telegram_chat_id, session_token, status, current_field
                from telegram_physiology_checkin_session
                where session_token = %s and telegram_chat_id = %s and local_date = %s
                  and status = %s
                for update;
                """,
                (session_token, str(chat_id), target_date, STATUS_ACTIVE),
            )
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return None
            current = _row_to_session(row)
            next_field = _next_field(current["current_field"])
            next_status = STATUS_ACTIVE if next_field else STATUS_COMPLETE
            cur.execute(
                """
                update telegram_physiology_checkin_session
                set status = %s, current_field = %s, updated_at = now()
                where session_token = %s
                returning user_id, local_date, telegram_chat_id, session_token, status, current_field;
                """,
                (next_status, next_field, session_token),
            )
            updated = cur.fetchone()
            conn.commit()
    return _row_to_session(updated)


def _format_current_values(user_id: str, target_date: date) -> str:
    observation = get_manual_physiology_observation(user_id=user_id, local_date=target_date)
    if observation is None:
        return "Текущих показателей нет. Пропуск оставит поле незаполненным."
    values = {
        "Сон": f"{observation.sleep_duration_minutes} мин" if observation.sleep_duration_minutes is not None else "нет",
        "Качество": str(observation.sleep_quality) if observation.sleep_quality is not None else "нет",
        "HRV": f"{observation.hrv_ms:g} мс" if observation.hrv_ms is not None else "нет",
        "Пульс": f"{observation.resting_hr_bpm:g}" if observation.resting_hr_bpm is not None else "нет",
    }
    return "Текущие значения: " + " · ".join(f"{name}: {value}" for name, value in values.items()) + ". Пропуск сохранит текущее значение."


def _send_field_prompt(session: dict[str, Any]) -> None:
    send_telegram_message(
        FIELD_PROMPTS[session["current_field"]],
        reply_markup=build_skip_keyboard(session["session_token"]),
        chat_id=session["telegram_chat_id"],
    )


def _parse_value(field: str, text: str | None) -> int | float | None:
    if text is None:
        return None
    normalized = text.strip().replace(",", ".")
    try:
        if field in {"sleep_duration_minutes", "sleep_quality"}:
            if not normalized.isdigit():
                return None
            value: int | float = int(normalized)
        else:
            value = float(normalized)
    except ValueError:
        return None
    bounds = {
        "sleep_duration_minutes": (0, 1440), "sleep_quality": (1, 5),
        "hrv_ms": (0, 500), "resting_hr_bpm": (20, 250),
    }
    low, high = bounds[field]
    if not low <= value <= high or (field == "hrv_ms" and value == 0):
        return None
    return value


def _complete_message(user_id: str, target_date: date) -> str:
    return "Показатели сохранены ✓\n" + _format_current_values(user_id, target_date)


def handle_telegram_physiology_callback(payload: dict[str, Any]) -> dict[str, Any] | None:
    callback = payload.get("callback_query") or {}
    parsed = parse_physiology_callback_data(callback.get("data"))
    if parsed is None:
        return None
    callback_id = callback.get("id")
    message = callback.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    if not _is_configured_chat(chat_id):
        if callback_id:
            answer_telegram_callback(callback_id, "This check-in is not available in this chat.")
        return {"ok": False, "reason": "unconfigured_chat"}
    target_date = _coerce_date(parsed.get("target_date", ""))
    if parsed["action"] in {START_ACTION, "skip_offer"}:
        if target_date != local_today():
            if callback_id:
                answer_telegram_callback(callback_id, "This check-in has expired.")
            return {"ok": False, "reason": "stale_callback"}
        if parsed["action"] == "skip_offer":
            if callback_id:
                answer_telegram_callback(callback_id, "Optional physiology skipped.")
            return {"ok": True, "skipped": True}
        session = start_session(user_id=settings.daily_readiness_user_id, local_date=target_date, chat_id=chat_id)
        if callback_id:
            answer_telegram_callback(callback_id, "Optional physiology check-in started.")
        send_telegram_message(_format_current_values(session["user_id"], session["local_date"]), chat_id=chat_id)
        _send_field_prompt(session)
        return {"ok": True, "session_token": session["session_token"], "current_field": session["current_field"]}
    session = skip_session_field(
        session_token=parsed["session_token"], chat_id=chat_id, target_date=local_today()
    )
    if session is None:
        if callback_id:
            answer_telegram_callback(callback_id, "This check-in has expired.")
        return {"ok": False, "reason": "stale_callback"}
    if callback_id:
        answer_telegram_callback(callback_id, "Skipped.")
    if session["status"] == STATUS_COMPLETE:
        send_telegram_message(_complete_message(session["user_id"], session["local_date"]), chat_id=chat_id)
    else:
        _send_field_prompt(session)
    return {"ok": True, "skipped": True, "current_field": session["current_field"]}


def handle_telegram_physiology_message(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    if not _is_configured_chat(chat_id):
        return {"ok": True, "ignored": True}
    today = local_today()
    session = claim_active_session_for_text(
        user_id=settings.daily_readiness_user_id, chat_id=chat_id, target_date=today
    )
    if session is None:
        return {"ok": True, "ignored": True}
    value = _parse_value(session["current_field"], message.get("text"))
    if value is None:
        restore_active_session(session["session_token"])
        send_telegram_message("Введите число в допустимом диапазоне. " + FIELD_PROMPTS[session["current_field"]], reply_markup=build_skip_keyboard(session["session_token"]), chat_id=chat_id)
        return {"ok": False, "reason": "invalid_value", "current_field": session["current_field"]}
    try:
        save_manual_physiology_observation(
            user_id=session["user_id"],
            patch=ManualPhysiologyPatch(
                local_date=session["local_date"], source="telegram", **{session["current_field"]: value}
            ),
        )
    except Exception:
        restore_active_session(session["session_token"])
        raise
    next_session = advance_session(session_token=session["session_token"], current_field=session["current_field"])
    if next_session is None:
        log_event(logger, "telegram_physiology_session_advance_rejected", session_token=session["session_token"])
        return {"ok": False, "reason": "stale_session"}
    if next_session["status"] == STATUS_COMPLETE:
        send_telegram_message(_complete_message(next_session["user_id"], next_session["local_date"]), chat_id=chat_id)
    else:
        _send_field_prompt(next_session)
    return {"ok": True, "current_field": next_session["current_field"], "complete": next_session["status"] == STATUS_COMPLETE}
