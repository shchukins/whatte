from __future__ import annotations

import json
import logging
from typing import Any

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


def upsert_activity_subjective_feedback(
    *,
    activity_id: int,
    score: int,
    source: str = FEEDBACK_SOURCE_TELEGRAM,
) -> dict[str, Any]:
    user_id = _load_activity_user_id(activity_id)
    if not user_id:
        raise ValueError(f"activity not found: {activity_id}")

    feedback_value = map_rpe_score_to_value(score)
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
                    feedback_type,
                    feedback_value,
                    feedback_score,
                    source,
                    context_json
                )
                values (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s::jsonb
                )
                on conflict (strava_activity_id, feedback_type) do update set
                    user_id = excluded.user_id,
                    feedback_value = excluded.feedback_value,
                    feedback_score = excluded.feedback_score,
                    source = excluded.source,
                    context_json = excluded.context_json,
                    updated_at = now()
                returning
                    id,
                    user_id,
                    strava_activity_id,
                    feedback_type,
                    feedback_value,
                    feedback_score,
                    source,
                    context_json,
                    created_at,
                    updated_at;
                """,
                (
                    user_id,
                    activity_id,
                    FEEDBACK_TYPE_POST_RIDE_RPE,
                    feedback_value,
                    score,
                    source,
                    json.dumps(context),
                ),
            )
            row = cur.fetchone()
            conn.commit()

    result = {
        "id": row[0],
        "user_id": row[1],
        "activity_id": row[2],
        "feedback_type": row[3],
        "feedback_value": row[4],
        "feedback_score": row[5],
        "source": row[6],
        "context": row[7],
        "created_at": row[8],
        "updated_at": row[9],
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
            answer_telegram_callback(callback_query_id, text="Invalid feedback payload.")
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
            answer_telegram_callback(callback_query_id, text="Activity not found.")
        return {"ok": False, "reason": "activity_not_found"}

    if callback_query_id:
        answer_telegram_callback(callback_query_id, text="Feedback recorded.")
    if chat_id is not None and message_id is not None:
        edit_telegram_message(chat_id, message_id, RPE_CONFIRMATION_TEXT)

    return {"ok": True, **result}
