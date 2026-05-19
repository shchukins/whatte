from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
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
FEEDBACK_TYPE_NEXT_DAY_RECOVERY = "next_day_recovery"
FEEDBACK_SOURCE_TELEGRAM = "telegram"
FEEDBACK_SCHEMA_VERSION_EXTENSIBLE = "v1_extensible"
PROMPT_TYPE_NEXT_DAY_RECOVERY = "next_day_recovery"
PROMPT_SOURCE_SCHEDULER = "scheduler"
PROMPT_SOURCE_DEBUG = "debug"
PROMPT_STATUS_PENDING = "pending"
PROMPT_STATUS_SENT = "sent"
PROMPT_STATUS_FAILED = "failed"
RPE_CALLBACK_PREFIX = "rpe"
RECOVERY_CALLBACK_PREFIX = "recovery"
RPE_CONFIRMATION_TEXT = "Feedback recorded ✓"
RECOVERY_CONFIRMATION_TEXT = "Recovery feedback recorded ✓"

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

RECOVERY_SCORE_TO_VALUE = {
    1: "exhausted",
    2: "tired",
    3: "okay",
    4: "fresh",
    5: "very_fresh",
}

RECOVERY_BUTTON_LABELS = {
    1: "😴 Exhausted",
    2: "😐 Tired",
    3: "🙂 Okay",
    4: "⚡ Fresh",
    5: "🚀 Very fresh",
}


def _coerce_iso_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_feedback_date(value: str | None) -> date | None:
    if value is None:
        return None

    try:
        return _coerce_iso_date(value)
    except ValueError:
        return None


def map_rpe_score_to_value(score: int) -> str:
    value = RPE_SCORE_TO_VALUE.get(score)
    if value is None:
        raise ValueError(f"unsupported rpe score: {score}")
    return value


def map_recovery_score_to_value(score: int) -> str:
    value = RECOVERY_SCORE_TO_VALUE.get(score)
    if value is None:
        raise ValueError(f"unsupported recovery score: {score}")
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


def build_recovery_callback_data(user_id: str, target_date: str | date, score: int) -> str:
    target_day = _coerce_iso_date(target_date)
    return f"{RECOVERY_CALLBACK_PREFIX}:{user_id}:{target_day.isoformat()}:{score}"


def parse_recovery_callback_data(data: str | None) -> dict[str, Any] | None:
    if not data:
        return None

    parts = data.split(":")
    if len(parts) != 4 or parts[0] != RECOVERY_CALLBACK_PREFIX:
        return None

    user_id = parts[1].strip()
    target_day = _parse_feedback_date(parts[2])
    try:
        score = int(parts[3])
    except ValueError:
        return None

    if not user_id or target_day is None or score not in RECOVERY_SCORE_TO_VALUE:
        return None

    return {
        "feedback_type": FEEDBACK_TYPE_NEXT_DAY_RECOVERY,
        "user_id": user_id,
        "activity_id": None,
        "target_date": target_day.isoformat(),
        "score": score,
        "value": map_recovery_score_to_value(score),
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


def build_next_day_recovery_message() -> str:
    return (
        "Human Engine\n\n"
        "How recovered do you feel today?\n\n"
        "This helps calibrate readiness after yesterday's training."
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


def build_next_day_recovery_keyboard(user_id: str, target_date: str | date) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": RECOVERY_BUTTON_LABELS[score],
                    "callback_data": build_recovery_callback_data(user_id, target_date, score),
                }
            ]
            for score in sorted(RECOVERY_BUTTON_LABELS)
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


def _load_recovery_prompt_context(user_id: str, recovery_date: str | date) -> dict[str, Any]:
    recovery_day = _coerce_iso_date(recovery_date)
    previous_day = recovery_day - timedelta(days=1)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    activities_count,
                    tss
                from daily_training_load
                where user_id = %s
                  and date = %s;
                """,
                (user_id, previous_day),
            )
            load_row = cur.fetchone()

            cur.execute(
                """
                select
                    strava_activity_id
                from strava_activity_raw
                where user_id = %s
                  and date(start_date) = %s
                order by start_date asc;
                """,
                (user_id, previous_day),
            )
            activity_rows = cur.fetchall()

    linked_activity_ids = [int(row[0]) for row in activity_rows]
    activities_count = int(load_row[0]) if load_row and load_row[0] is not None else len(linked_activity_ids)
    previous_training_load = float(load_row[1]) if load_row and load_row[1] is not None else 0.0
    has_training = activities_count > 0 or len(linked_activity_ids) > 0 or previous_training_load > 0

    return {
        "user_id": user_id,
        "target_date": recovery_day.isoformat(),
        "previous_date": previous_day.isoformat(),
        "activities_count": activities_count,
        "previous_training_load": previous_training_load,
        "linked_activity_ids": linked_activity_ids,
        "has_training": has_training,
    }


def build_feedback_context_snapshot(user_id: str, *, target_date: str | date | None = None) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if target_date is not None:
                cur.execute(
                    """
                    select
                        date,
                        readiness_score,
                        good_day_probability,
                        status_text,
                        explanation_json
                    from readiness_daily
                    where user_id = %s
                      and date = %s
                      and version = 'v2'
                    limit 1;
                    """,
                    (user_id, _coerce_iso_date(target_date)),
                )
            else:
                cur.execute(
                    """
                    select
                        date,
                        readiness_score,
                        good_day_probability,
                        status_text,
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
            "snapshot_date": target_date.isoformat() if isinstance(target_date, date) else target_date,
            "readiness_score": None,
            "good_day_probability": None,
            "status_text": None,
            "recommendation": None,
            "freshness": None,
            "recovery_score": None,
            "recovery_explanation": None,
        }

    snapshot_date, readiness_score, good_day_probability, status_text, explanation_json = row
    explanation = explanation_json if isinstance(explanation_json, dict) else {}
    recommendation = None
    if readiness_score is not None:
        recommendation = build_recommendation(
            readiness_score=float(readiness_score),
            explanation=explanation,
        )["recommendation"]

    return {
        "snapshot_date": str(snapshot_date),
        "readiness_score": readiness_score,
        "good_day_probability": good_day_probability,
        "status_text": status_text,
        "recommendation": recommendation,
        "freshness": explanation.get("freshness"),
        "recovery_score": explanation.get("recovery_score_simple"),
        "recovery_explanation": explanation.get("recovery_explanation"),
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


def _build_feedback_row_result(row: tuple[Any, ...], *, was_update: bool) -> dict[str, Any]:
    return {
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


def _build_prompt_log_result(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "user_id": row[1],
        "prompt_type": row[2],
        "target_date": row[3],
        "sent_at": row[4],
        "source": row[5],
        "delivery_status": row[6],
        "telegram_message_id": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


def has_next_day_recovery_feedback(user_id: str, target_date: str | date) -> bool:
    normalized_target_date = _coerce_iso_date(target_date)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select 1
                from activity_subjective_feedback
                where user_id = %s
                  and activity_date = %s
                  and feedback_type = %s
                  and strava_activity_id is null
                limit 1;
                """,
                (user_id, normalized_target_date, FEEDBACK_TYPE_NEXT_DAY_RECOVERY),
            )
            row = cur.fetchone()

    return row is not None


def get_recovery_prompt_log(user_id: str, target_date: str | date) -> dict[str, Any] | None:
    normalized_target_date = _coerce_iso_date(target_date)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    id,
                    user_id,
                    prompt_type,
                    target_date,
                    sent_at,
                    source,
                    delivery_status,
                    telegram_message_id,
                    created_at,
                    updated_at
                from subjective_feedback_prompt_log
                where user_id = %s
                  and prompt_type = %s
                  and target_date = %s
                limit 1;
                """,
                (user_id, PROMPT_TYPE_NEXT_DAY_RECOVERY, normalized_target_date),
            )
            row = cur.fetchone()

    if row is None:
        return None

    return _build_prompt_log_result(row)


def _claim_recovery_prompt_delivery(
    *,
    user_id: str,
    target_date: str | date,
    source: str,
) -> dict[str, Any] | None:
    normalized_target_date = _coerce_iso_date(target_date)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into subjective_feedback_prompt_log (
                    user_id,
                    prompt_type,
                    target_date,
                    source,
                    delivery_status
                )
                values (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                on conflict (user_id, prompt_type, target_date) do nothing
                returning
                    id,
                    user_id,
                    prompt_type,
                    target_date,
                    sent_at,
                    source,
                    delivery_status,
                    telegram_message_id,
                    created_at,
                    updated_at;
                """,
                (
                    user_id,
                    PROMPT_TYPE_NEXT_DAY_RECOVERY,
                    normalized_target_date,
                    source,
                    PROMPT_STATUS_PENDING,
                ),
            )
            row = cur.fetchone()

            if row is None:
                cur.execute(
                    """
                    update subjective_feedback_prompt_log
                    set
                        source = %s,
                        delivery_status = %s,
                        sent_at = null,
                        telegram_message_id = null,
                        updated_at = now()
                    where user_id = %s
                      and prompt_type = %s
                      and target_date = %s
                      and delivery_status = %s
                    returning
                        id,
                        user_id,
                        prompt_type,
                        target_date,
                        sent_at,
                        source,
                        delivery_status,
                        telegram_message_id,
                        created_at,
                        updated_at;
                    """,
                    (
                        source,
                        PROMPT_STATUS_PENDING,
                        user_id,
                        PROMPT_TYPE_NEXT_DAY_RECOVERY,
                        normalized_target_date,
                        PROMPT_STATUS_FAILED,
                    ),
                )
                row = cur.fetchone()

            conn.commit()

    if row is None:
        return None

    return _build_prompt_log_result(row)


def _mark_prompt_delivery_result(
    *,
    prompt_log_id: int,
    delivery_status: str,
    telegram_message_id: int | None = None,
) -> dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update subjective_feedback_prompt_log
                set
                    delivery_status = %s,
                    sent_at = case when %s = %s then now() else sent_at end,
                    telegram_message_id = %s,
                    updated_at = now()
                where id = %s
                returning
                    id,
                    user_id,
                    prompt_type,
                    target_date,
                    sent_at,
                    source,
                    delivery_status,
                    telegram_message_id,
                    created_at,
                    updated_at;
                """,
                (
                    delivery_status,
                    delivery_status,
                    PROMPT_STATUS_SENT,
                    telegram_message_id,
                    prompt_log_id,
                ),
            )
            row = cur.fetchone()
            conn.commit()

    return _build_prompt_log_result(row)


def upsert_subjective_feedback(
    *,
    user_id: str,
    feedback_type: str,
    feedback_value: str,
    score: int,
    activity_id: int | None = None,
    activity_date: str | date | None = None,
    source: str = FEEDBACK_SOURCE_TELEGRAM,
    payload: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    feedback_schema_version: str = FEEDBACK_SCHEMA_VERSION_EXTENSIBLE,
) -> dict[str, Any]:
    feedback_payload = _normalize_feedback_payload(payload)
    context_payload = _normalize_feedback_payload(context)
    normalized_activity_date = (
        _coerce_iso_date(activity_date).isoformat() if activity_date is not None else None
    )

    with get_conn() as conn:
        with conn.cursor() as cur:
            if activity_id is not None:
                cur.execute(
                    """
                    select id
                    from activity_subjective_feedback
                    where strava_activity_id = %s
                      and feedback_type = %s
                    limit 1;
                    """,
                    (activity_id, feedback_type),
                )
            else:
                cur.execute(
                    """
                    select id
                    from activity_subjective_feedback
                    where user_id = %s
                      and activity_date = %s
                      and feedback_type = %s
                      and strava_activity_id is null
                    limit 1;
                    """,
                    (user_id, normalized_activity_date, feedback_type),
                )
            existing_row = cur.fetchone()
            was_update = existing_row is not None

            if activity_id is not None:
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
                    on conflict (strava_activity_id, feedback_type) where strava_activity_id is not null do update set
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
                        normalized_activity_date,
                        feedback_type,
                        feedback_value,
                        score,
                        source,
                        feedback_schema_version,
                        json.dumps(feedback_payload),
                        json.dumps(context_payload),
                    ),
                )
            else:
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
                        null,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s::jsonb,
                        %s::jsonb
                    )
                    on conflict (user_id, activity_date, feedback_type) where strava_activity_id is null do update set
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
                        normalized_activity_date,
                        feedback_type,
                        feedback_value,
                        score,
                        source,
                        feedback_schema_version,
                        json.dumps(feedback_payload),
                        json.dumps(context_payload),
                    ),
                )
            row = cur.fetchone()
            conn.commit()

    result = _build_feedback_row_result(row, was_update=was_update)

    log_event(
        logger,
        "feedback_updated" if was_update else "feedback_received",
        user_id=user_id,
        activity_id=activity_id,
        activity_date=normalized_activity_date,
        score=score,
        feedback_type=feedback_type,
        source=source,
        feedback_schema_version=feedback_schema_version,
    )

    return result


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

    return upsert_subjective_feedback(
        user_id=user_id,
        activity_id=activity_id,
        activity_date=activity_date,
        feedback_type=FEEDBACK_TYPE_POST_RIDE_RPE,
        feedback_value=map_rpe_score_to_value(score),
        score=score,
        source=source,
        payload=payload,
        context=build_feedback_context_snapshot(user_id),
        feedback_schema_version=feedback_schema_version,
    )


def upsert_next_day_recovery_feedback(
    *,
    user_id: str,
    target_date: str | date,
    score: int,
    source: str = FEEDBACK_SOURCE_TELEGRAM,
    feedback_schema_version: str = FEEDBACK_SCHEMA_VERSION_EXTENSIBLE,
) -> dict[str, Any]:
    recovery_context = _load_recovery_prompt_context(user_id, target_date)
    feedback_payload = {
        "target_date": recovery_context["target_date"],
        "previous_date": recovery_context["previous_date"],
        "previous_training_load": recovery_context["previous_training_load"],
        "previous_activities_count": recovery_context["activities_count"],
        "linked_activity_ids": recovery_context["linked_activity_ids"],
    }
    context_snapshot = build_feedback_context_snapshot(
        user_id,
        target_date=recovery_context["target_date"],
    )
    context_snapshot.update(feedback_payload)

    return upsert_subjective_feedback(
        user_id=user_id,
        activity_date=recovery_context["target_date"],
        feedback_type=FEEDBACK_TYPE_NEXT_DAY_RECOVERY,
        feedback_value=map_recovery_score_to_value(score),
        score=score,
        source=source,
        payload=feedback_payload,
        context=context_snapshot,
        feedback_schema_version=feedback_schema_version,
    )


def send_next_day_recovery_prompt(user_id: str, recovery_date: str | date) -> dict[str, Any]:
    return deliver_next_day_recovery_prompt(
        user_id=user_id,
        recovery_date=recovery_date,
        source=PROMPT_SOURCE_DEBUG,
    )


def deliver_next_day_recovery_prompt(
    *,
    user_id: str,
    recovery_date: str | date,
    source: str = PROMPT_SOURCE_SCHEDULER,
) -> dict[str, Any]:
    recovery_context = _load_recovery_prompt_context(user_id, recovery_date)

    if not recovery_context["has_training"]:
        result = {
            "ok": True,
            "skipped": True,
            "reason": "no_previous_training_day",
            "prompt_log": None,
            **recovery_context,
        }
        log_event(logger, "recovery_prompt_skipped", reason=result["reason"], **recovery_context)
        return result

    if has_next_day_recovery_feedback(user_id, recovery_context["target_date"]):
        result = {
            "ok": True,
            "skipped": True,
            "reason": "feedback_already_exists",
            "prompt_log": None,
            **recovery_context,
        }
        log_event(logger, "recovery_prompt_skipped", reason=result["reason"], **recovery_context)
        return result

    prompt_log = _claim_recovery_prompt_delivery(
        user_id=user_id,
        target_date=recovery_context["target_date"],
        source=source,
    )
    if prompt_log is None:
        existing_prompt_log = get_recovery_prompt_log(user_id, recovery_context["target_date"])
        reason = "prompt_already_sent"
        if existing_prompt_log and existing_prompt_log["delivery_status"] == PROMPT_STATUS_PENDING:
            reason = "prompt_delivery_in_progress"
        result = {
            "ok": True,
            "skipped": True,
            "reason": reason,
            "prompt_log": existing_prompt_log,
            **recovery_context,
        }
        log_event(logger, "recovery_prompt_skipped", reason=reason, **recovery_context)
        return result

    telegram_response = None
    try:
        telegram_response = send_telegram_message(
            build_next_day_recovery_message(),
            reply_markup=build_next_day_recovery_keyboard(user_id, recovery_context["target_date"]),
        )
    except requests.RequestException:
        failed_prompt_log = _mark_prompt_delivery_result(
            prompt_log_id=prompt_log["id"],
            delivery_status=PROMPT_STATUS_FAILED,
        )
        log_event(
            logger,
            "recovery_prompt_delivery_failed",
            level=logging.ERROR,
            source=source,
            prompt_log_id=failed_prompt_log["id"],
            **recovery_context,
        )
        raise

    telegram_message_id = None
    if isinstance(telegram_response, dict):
        result_payload = telegram_response.get("result") or {}
        if isinstance(result_payload, dict):
            telegram_message_id = result_payload.get("message_id")

    if telegram_response is None:
        final_prompt_log = _mark_prompt_delivery_result(
            prompt_log_id=prompt_log["id"],
            delivery_status=PROMPT_STATUS_FAILED,
        )
        result = {
            "ok": False,
            "skipped": False,
            "reason": "telegram_not_configured",
            "prompt_log": final_prompt_log,
            **recovery_context,
        }
        log_event(
            logger,
            "recovery_prompt_delivery_failed",
            level=logging.ERROR,
            source=source,
            reason=result["reason"],
            prompt_log_id=final_prompt_log["id"],
            **recovery_context,
        )
        return result

    final_prompt_log = _mark_prompt_delivery_result(
        prompt_log_id=prompt_log["id"],
        delivery_status=PROMPT_STATUS_SENT,
        telegram_message_id=telegram_message_id,
    )
    result = {
        "ok": True,
        "skipped": False,
        "reason": None,
        "prompt_log": final_prompt_log,
        **recovery_context,
    }
    log_event(
        logger,
        "recovery_prompt_sent",
        source=source,
        prompt_log_id=final_prompt_log["id"],
        telegram_message_id=telegram_message_id,
        **recovery_context,
    )
    return result


def list_recovery_prompt_candidate_users(target_date: str | date) -> list[str]:
    recovery_day = _coerce_iso_date(target_date)
    previous_day = recovery_day - timedelta(days=1)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                with candidate_users as (
                    select distinct user_id
                    from daily_training_load
                    where date = %s
                      and (
                        coalesce(activities_count, 0) > 0
                        or coalesce(tss, 0) > 0
                      )
                    union
                    select distinct user_id
                    from strava_activity_raw
                    where date(start_date) = %s
                )
                select user_id
                from candidate_users
                order by user_id asc;
                """,
                (previous_day, previous_day),
            )
            rows = cur.fetchall()

    return [str(row[0]) for row in rows]


def schedule_next_day_recovery_prompts(
    *,
    target_date: str | date,
    source: str = PROMPT_SOURCE_SCHEDULER,
) -> dict[str, Any]:
    recovery_day = _coerce_iso_date(target_date)
    candidate_users = list_recovery_prompt_candidate_users(recovery_day)
    results: list[dict[str, Any]] = []

    for user_id in candidate_users:
        try:
            result = deliver_next_day_recovery_prompt(
                user_id=user_id,
                recovery_date=recovery_day,
                source=source,
            )
        except requests.RequestException as exc:
            log_event(
                logger,
                "recovery_prompt_scheduler_user_failed",
                level=logging.ERROR,
                user_id=user_id,
                target_date=recovery_day.isoformat(),
                source=source,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            result = {
                "ok": False,
                "skipped": False,
                "reason": "telegram_delivery_failed",
            }
        results.append(
            {
                "user_id": user_id,
                "ok": result["ok"],
                "skipped": result["skipped"],
                "reason": result["reason"],
            }
        )

    sent_count = sum(1 for result in results if not result["skipped"] and result["ok"])
    skipped_count = sum(1 for result in results if result["skipped"])
    failed_count = sum(1 for result in results if not result["ok"])

    summary = {
        "ok": True,
        "target_date": recovery_day.isoformat(),
        "candidate_users": candidate_users,
        "processed_users": len(results),
        "sent_count": sent_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "results": results,
    }

    log_event(
        logger,
        "recovery_prompt_scheduler_completed",
        target_date=summary["target_date"],
        processed_users=summary["processed_users"],
        sent_count=sent_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
    )
    return summary


def handle_telegram_feedback_callback(payload: dict[str, Any]) -> dict[str, Any]:
    callback_query = payload.get("callback_query") or {}
    callback_query_id = callback_query.get("id")
    callback_data = callback_query.get("data")
    callback_message = callback_query.get("message") or {}
    chat = callback_message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = callback_message.get("message_id")

    parsed = parse_rpe_callback_data(callback_data) or parse_recovery_callback_data(callback_data)
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
        if parsed["feedback_type"] == FEEDBACK_TYPE_POST_RIDE_RPE:
            result = upsert_activity_subjective_feedback(
                activity_id=parsed["activity_id"],
                score=parsed["score"],
                source=parsed["source"],
            )
        else:
            result = upsert_next_day_recovery_feedback(
                user_id=parsed["user_id"],
                target_date=parsed["target_date"],
                score=parsed["score"],
                source=parsed["source"],
            )
    except ValueError:
        log_event(
            logger,
            "feedback_invalid_callback",
            activity_id=parsed.get("activity_id"),
            user_id=parsed.get("user_id"),
            target_date=parsed.get("target_date"),
            score=parsed["score"],
            feedback_type=parsed["feedback_type"],
            source=parsed["source"],
        )
        if callback_query_id:
            _safe_answer_telegram_callback(
                callback_query_id,
                text="Feedback target not found.",
                activity_id=parsed.get("activity_id"),
                user_id=parsed.get("user_id"),
                target_date=parsed.get("target_date"),
                score=parsed["score"],
                feedback_type=parsed["feedback_type"],
                source=parsed["source"],
            )
        return {"ok": False, "reason": "feedback_target_not_found"}

    if callback_query_id:
        _safe_answer_telegram_callback(
            callback_query_id,
            text="Feedback recorded.",
            activity_id=result["activity_id"],
            user_id=result["user_id"],
            activity_date=result["activity_date"],
            feedback_type=result["feedback_type"],
            source=result["source"],
        )
    if chat_id is not None and message_id is not None:
        confirmation_text = (
            RPE_CONFIRMATION_TEXT
            if result["feedback_type"] == FEEDBACK_TYPE_POST_RIDE_RPE
            else RECOVERY_CONFIRMATION_TEXT
        )
        _safe_edit_telegram_message(
            chat_id,
            message_id,
            confirmation_text,
            activity_id=result["activity_id"],
            user_id=result["user_id"],
            activity_date=result["activity_date"],
            feedback_type=result["feedback_type"],
            source=result["source"],
        )

    return {"ok": True, **result}
