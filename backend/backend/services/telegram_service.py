from __future__ import annotations

from typing import Any

import requests

from backend.config import settings


def telegram_is_configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def send_telegram_request(method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if not settings.telegram_bot_token:
        return None

    response = requests.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}",
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def send_telegram_message(
    text: str,
    reply_markup: dict[str, Any] | None = None,
    chat_id: str | int | None = None,
) -> dict[str, Any] | None:
    target_chat_id = chat_id if chat_id is not None else settings.telegram_chat_id
    if not settings.telegram_bot_token or not target_chat_id:
        return None

    payload: dict[str, Any] = {
        "chat_id": target_chat_id,
        "text": text,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    return send_telegram_request("sendMessage", payload)


def edit_telegram_message(
    chat_id: str | int,
    message_id: int,
    text: str,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    return send_telegram_request("editMessageText", payload)


def answer_telegram_callback(
    callback_query_id: str,
    text: str | None = None,
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {
        "callback_query_id": callback_query_id,
    }
    if text:
        payload["text"] = text

    return send_telegram_request("answerCallbackQuery", payload)
