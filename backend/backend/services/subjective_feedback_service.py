from __future__ import annotations

import json
import logging
from typing import Any

import requests

from backend.core.logging import log_event
from backend.db import get_conn
from backend.services.decision_engine import build_recommendation
from backend.services.telegram_service import (
    answer_telegram_callback,
    edit_telegram_message,
    send_telegram_message,
)


logger = logging.getLogger(__name__)

FEEDBACK_TYPE_POST_RIDE_RPE = "post_ride_rpe"
FEEDBACK_SOURCE_TELEGRAM = "telegram"
FEEDBACK_SCHEMA_VERSION_EXTENSIBLE = "v1_extensible"
RPE_CALLBACK_PREFIX = "rpe"
RPE_CONFIRMATION_TEXT = "Feedback recorded ✓"

RPE_SCORE_TO_VALUE = {
    1: "very_easy",
    2: "easy",
    3: "moderate",
    4: "hard",
    5: "very_hard",
}

RPE_BUTTON_LABELS = {
    1: "😌 Very easy",
    2: "🙂 Easy",
    3: "😐 Moderate",
    4: "🥵 Hard",
    5: "☠️ Very hard",
}


def map_rpe_score_to_value(score: int) -> str:
    value = RPE_SCORE_TO_VALUE.get(score)
    if value is None:
        raise ValueError(f"unsupported rpe score: {score}")
    return value


def build_rpe_callback_data(activity_id: int, score: int) -> str:
    return f"{RPE_CALLBACK_PREFIX}:{activity_id}:{score}"


def parse_rpe_callback_data(data: str | None) -> dict[str, Any] | None:
    if not data:
        return None

    parts = data.split(":")
    if len(parts) != 3 or parts[0] != RPE_CALLBACK_PREFIX:
        return None

    try:
        activity_id = int(parts[1])
        score = int(parts[2])
    except ValueError:
        return None

    if activity_id <= 0 or score not in RPE_SCORE_TO_VALUE:
        return None

    return {
        "feedback_type": FEEDBACK_TYPE_POST_RIDE_RPE,
        "activity_id": activity_id,
        "score": score,
        "value": map_rpe_score_to_value(score),
        "source": FEEDBACK_SOURCE_TELEGRAM,
    }


def build_post_ride_rpe_message(activity_id: int) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    m.duration_s,
                    m.tss,
                    m.avg_power
                from strava_activity_raw r
                left join activity_metrics m
                  on m.strava_activity_id = r.strava_activity_id
                 and m.version = 'v1'
                where r.strava_activity_id = %s;
                """,
                (activity_id,),
            )
            row = cur.fetchone()

    if not row:
        return "Ride recorded 🚴\n\nHow did the ride feel?"

    duration_s, tss, avg_power = row

    hours = duration_s // 3600 if duration_s else 0
    minutes = ((duration_s or 0) % 3600) // 60
    duration_text = f"{hours}h {minutes:02d}m" if hours > 0 else f"{minutes}m"
    load_text = "n/a" if tss is None else str(round(float(tss)))
    power_text = "n/a" if avg_power is None else f"{round(float(avg_power))}w"

    return (
        "Ride recorded 🚴\n\n"
        f"Duration: {duration_text}\n"
        f"Load: {load_text}\n"
        f"Avg power: {power_text}\n\n"
        "How did the ride feel?"
    )


def build_post_ride_rpe_keyboard(activity_id: int) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": RPE_BUTTON_LABELS[score],
                    "callback_data": build_rpe_callback_data(activity_id, score),
                }
            ]
            for score in sorted(RPE_BUTTON_LABELS)
        ]
    }


def send_post_ride_rpe_request(activity_id: int) -> None:
    send_telegram_message(
        build_post_ride_rpe_message(activity_id),
        reply_markup=build_post_ride_rpe_keyboard(activity_id),
    )


def _load_activity_user_id(activity_id: int) -> str | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select user_id
                from strava_activity_raw
                where strava_activity_id = %s;
                """,
                (activity_id,),
            )
            row = cur.fetchone()

    return row[0] if row else None


def build_feedback_context_snapshot(user_id: str) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    readiness_score,
                    explanation_json
                from readiness_daily
                where user_id = %s
                  and version = 'v2'
                order by date desc
                limit 1;
                """,
                (user_id,),
            )
            row = cur.fetchone()

    if not row:
        return {
            "readiness_score": None,
            "recommendation": None,
            "freshness": None,
            "recovery_score": None,
        }

    readiness_score, explanation_json = row
    explanation = explanation_json if isinstance(explanation_json, dict) else {}
    recommendation = None
    if readiness_score is not None:
        recommendation = build_recommendation(
            readiness_score=float(readiness_score),
            explanation=explanation,
        )["recommendation"]

    return {
        "readiness_score": readiness_score,
        "recommendation": recommendation,
        "freshness": explanation.get("freshness"),
        "recovery_score": explanation.get("recovery_score_simple"),
    }


def _normalize_feedback_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("feedback payload must be a json object")
    return payload


def _safe_answer_telegram_callback(callback_query_id: str, text: str, **log_context: Any) -> None:
    try:
        answer_telegram_callback(callback_query_id, text=text)
    except requests.HTTPError:
        log_event(
            logger,
            "telegram_callback_ack_failed",
            level=logging.WARNING,
            callback_query_id=callback_query_id,
            ack_text=text,
            **log_context,
        )


def _safe_edit_telegram_message(chat_id: int | str, message_id: int, text: str, **log_context: Any) -> None:
    try:
        edit_telegram_message(chat_id, message_id, text)
    except requests.HTTPError:
        log_event(
            logger,
            "telegram_feedback_message_edit_failed",
            level=logging.WARNING,
            chat_id=chat_id,
            message_id=message_id,
            message_text=text,
            **log_context,
        )


def upsert_activity_subjective_feedback(
    *,
    activity_id: int,
    score: int,
    source: str = FEEDBACK_SOURCE_TELEGRAM,
    payload: dict[str, Any] | None = None,
    feedback_schema_version: str = FEEDBACK_SCHEMA_VERSION_EXTENSIBLE,
    activity_date: str | None = None,
) -> dict[str, Any]:
    user_id = _load_activity_user_id(activity_id)
    if not user_id:
        raise ValueError(f"activity not found: {activity_id}")

    feedback_value = map_rpe_score_to_value(score)
    feedback_payload = _normalize_feedback_payload(payload)
    context = build_feedback_context_snapshot(user_id)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id
                from activity_subjective_feedback
                where strava_activity_id = %s
                  and feedback_type = %s
                limit 1;
                """,
                (activity_id, FEEDBACK_TYPE_POST_RIDE_RPE),
            )
            existing_row = cur.fetchone()
            was_update = existing_row is not None

            cur.execute(
                """
                insert into activity_subjective_feedback (
                    user_id,
                    strava_activity_id,
                    activity_date,
                    feedback_type,
                    feedback_value,
                    feedback_score,
                    source,
                    feedback_schema_version,
                    feedback_payload,
                    context_json
                )
                values (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s::jsonb,
                    %s::jsonb
                )
                on conflict (strava_activity_id, feedback_type) do update set
                    user_id = excluded.user_id,
                    activity_date = coalesce(excluded.activity_date, activity_subjective_feedback.activity_date),
                    feedback_value = excluded.feedback_value,
                    feedback_score = excluded.feedback_score,
                    source = excluded.source,
                    feedback_schema_version = excluded.feedback_schema_version,
                    feedback_payload = excluded.feedback_payload,
                    context_json = excluded.context_json,
                    updated_at = now()
                returning
                    id,
                    user_id,
                    strava_activity_id,
                    activity_date,
                    feedback_type,
                    feedback_value,
                    feedback_score,
                    source,
                    feedback_schema_version,
                    feedback_payload,
                    context_json,
                    created_at,
                    updated_at;
                """,
                (
                    user_id,
                    activity_id,
                    activity_date,
                    FEEDBACK_TYPE_POST_RIDE_RPE,
                    feedback_value,
                    score,
                    source,
                    feedback_schema_version,
                    json.dumps(feedback_payload),
                    json.dumps(context),
                ),
            )
            row = cur.fetchone()
            conn.commit()

    result = {
        "id": row[0],
        "user_id": row[1],
        "activity_id": row[2],
        "activity_date": row[3],
        "feedback_type": row[4],
        "feedback_value": row[5],
        "feedback_score": row[6],
        "source": row[7],
        "feedback_schema_version": row[8],
        "feedback_payload": row[9],
        "context": row[10],
        "created_at": row[11],
        "updated_at": row[12],
        "was_update": was_update,
    }

    log_event(
        logger,
        "feedback_updated" if was_update else "feedback_received",
        user_id=user_id,
        activity_id=activity_id,
        score=score,
        feedback_type=FEEDBACK_TYPE_POST_RIDE_RPE,
        source=source,
        feedback_schema_version=feedback_schema_version,
    )

    return result


def handle_telegram_feedback_callback(payload: dict[str, Any]) -> dict[str, Any]:
    callback_query = payload.get("callback_query") or {}
    callback_query_id = callback_query.get("id")
    callback_data = callback_query.get("data")
    callback_message = callback_query.get("message") or {}
    chat = callback_message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = callback_message.get("message_id")

    parsed = parse_rpe_callback_data(callback_data)
    if not parsed:
        log_event(
            logger,
            "feedback_invalid_callback",
            source=FEEDBACK_SOURCE_TELEGRAM,
            raw_callback_data=callback_data,
        )
        if callback_query_id:
            _safe_answer_telegram_callback(
                callback_query_id,
                text="Invalid feedback payload.",
                source=FEEDBACK_SOURCE_TELEGRAM,
                raw_callback_data=callback_data,
            )
        return {"ok": False, "reason": "invalid_callback"}

    try:
        result = upsert_activity_subjective_feedback(
            activity_id=parsed["activity_id"],
            score=parsed["score"],
            source=parsed["source"],
        )
    except ValueError:
        log_event(
            logger,
            "feedback_invalid_callback",
            activity_id=parsed["activity_id"],
            score=parsed["score"],
            feedback_type=parsed["feedback_type"],
            source=parsed["source"],
        )
        if callback_query_id:
            _safe_answer_telegram_callback(
                callback_query_id,
                text="Activity not found.",
                activity_id=parsed["activity_id"],
                score=parsed["score"],
                feedback_type=parsed["feedback_type"],
                source=parsed["source"],
            )
        return {"ok": False, "reason": "activity_not_found"}

    if callback_query_id:
        _safe_answer_telegram_callback(
            callback_query_id,
            text="Feedback recorded.",
            activity_id=result["activity_id"],
            feedback_type=result["feedback_type"],
            source=result["source"],
        )
    if chat_id is not None and message_id is not None:
        _safe_edit_telegram_message(
            chat_id,
            message_id,
            RPE_CONFIRMATION_TEXT,
            activity_id=result["activity_id"],
            feedback_type=result["feedback_type"],
            source=result["source"],
        )

    return {"ok": True, **result}
