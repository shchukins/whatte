from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import logging
import math
from typing import Any, Iterator, Literal
from zoneinfo import ZoneInfo

from backend.config import settings
from backend.db import get_conn
from backend.services.activity_deduplication_service import (
    DELIVERY_TRAINING_PROCESSED,
    claim_activity_delivery,
    get_activity_deduplication_state,
    mark_activity_delivery_sent,
    release_activity_delivery_claim,
)
from backend.services.activity_load_service import resolve_activity_load
from backend.services.decision_engine import build_persisted_readiness_briefing
from backend.services.decision_context_snapshot import capture_decision_context_snapshot
from backend.services.research_feature_snapshot import capture_research_feature_snapshot
from backend.services.readiness_composition import READINESS_MODEL_VERSION
from backend.services.subjective_feedback_service import send_post_ride_rpe_request
from backend.services.telegram_service import (
    edit_telegram_message,
    send_telegram_message,
)


DAILY_READINESS_STATUS_CLAIMED = "claimed"
DAILY_READINESS_STATUS_SENT = "sent"
DAILY_READINESS_STATUS_UPDATING = "updating"
DAILY_READINESS_STATUS_UPDATED = "updated"
DAILY_READINESS_STATUS_SUPERSEDED = "superseded"
DAILY_READINESS_STATUS_FAILED = "failed"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DailyReadinessDeliveryClaim:
    action: Literal["send", "edit", "send_update"]
    previous_delivery_status: str | None = None
    telegram_chat_id: str | None = None
    telegram_message_id: int | None = None


def _format_duration(seconds: int | None) -> str:
    if not seconds or seconds <= 0:
        return "n/a"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes}:{secs:02d}"


def _fmt(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and math.isnan(value):
        return "n/a"
    return f"{value:.{digits}f}"


def _fmt_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and math.isnan(value):
        return "n/a"
    return f"{round(value * 100)}%"


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _physiology_availability_label(data_freshness: dict[str, Any] | None) -> str:
    state = (data_freshness or {}).get("state", "missing")
    provider = (data_freshness or {}).get("provider")
    if state == "fresh" and provider == "healthkit":
        return "available · historical"
    return {
        "fresh": "available",
        "stale": "unavailable for this date",
        "missing": "unavailable (optional)",
    }.get(state, "unknown")


def classify_workout_type(
    intensity_factor: float | None,
    tss: float | None,
    duration_s: int | None,
) -> str:
    if intensity_factor is None:
        return "unknown"

    # Длинная спокойная тренировка важна как отдельный тип,
    # даже если IF формально попадает в обычный endurance.
    if duration_s is not None and duration_s >= 7200 and intensity_factor < 0.75:
        return "long_endurance"

    if intensity_factor < 0.55 and (tss is None or tss < 30):
        return "recovery"

    if intensity_factor < 0.75:
        return "endurance"

    if intensity_factor < 0.85:
        return "tempo"

    if intensity_factor < 0.95:
        return "threshold"

    return "vo2"


def build_workout_comment(workout_type: str, tss: float | None) -> str:
    if workout_type == "recovery":
        return "Легкая восстановительная сессия"

    if workout_type == "endurance":
        if tss is not None and tss >= 80:
            return "Хорошая аэробная работа с заметной нагрузкой"
        return "Хорошая аэробная работа"

    if workout_type == "long_endurance":
        return "Длинная аэробная сессия"

    if workout_type == "tempo":
        return "Умеренно интенсивная работа"

    if workout_type == "threshold":
        return "Пороговая нагрузка"

    if workout_type == "vo2":
        return "Высокоинтенсивная тренировка"

    return "Тип нагрузки пока не определен"


def build_readiness_briefing_message(
    *,
    notification_date: Any,
    recovery_date: Any,
    readiness_score: float | None,
    status_text: str | None,
    good_day_probability: float | None,
    freshness: float | None,
    recovery_score_simple: float | None,
    recovery_explanation: dict[str, Any] | None,
    briefing: str,
    data_freshness: dict[str, Any] | None = None,
) -> str:
    recovery_explanation = recovery_explanation or {}
    # Historical physiology is evidence only for its exact date. Absence is
    # normal after collection retirement and should not create placeholder rows.
    same_date = recovery_date is not None and str(recovery_date)[:10] == str(notification_date)[:10]
    physiology_available = same_date and (data_freshness or {}).get("state", "fresh") == "fresh"
    if not physiology_available:
        recovery_score_simple = None
        recovery_explanation = {}

    lines = ["WHATTE · Today", "", f"Дата briefing: {notification_date}"]
    physiology_lines = []
    if recovery_score_simple is not None:
        physiology_lines.append(f"Восстановление: {_fmt(recovery_score_simple, 1)}")
    for key, label in (("sleep_score", "Сон"), ("hrv_score", "HRV"), ("rhr_score", "Пульс покоя")):
        value = _float_or_none(recovery_explanation.get(key))
        if value is not None:
            physiology_lines.append(f"• {label}: {_fmt(value, 1)}")
    if physiology_lines:
        lines.extend([f"Дата physiology-данных: {recovery_date}",
                      f"Physiology: {_physiology_availability_label(data_freshness or {'state': 'fresh'})}"])
    lines.append("")
    if readiness_score is not None:
        lines.append(f"Готовность: {_fmt(readiness_score, 1)}")
    else:
        lines.append("Готовность пока не рассчитана")
    if status_text:
        lines.append(f"Статус: {status_text}")
    if good_day_probability is not None:
        lines.append(f"Вероятность хорошего дня: {_fmt_percent(good_day_probability)}")
    if freshness is not None:
        lines.extend(["", f"Свежесть: {_fmt(freshness, 1)}"])
    if physiology_lines:
        lines.extend(["", *physiology_lines])
    lines.extend(["", "Комментарий:", briefing])
    return "\n".join(lines)


def get_physiology_data_freshness(
    user_id: str,
    for_date: date,
) -> dict[str, Any]:
    """Describe exact-date optional physiology without carrying history forward."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select date, updated_at
                from health_recovery_daily
                where user_id = %s
                  and date = %s;
                """,
                (user_id, for_date),
            )
            recovery_row = cur.fetchone()

    if recovery_row is None:
        return {
            "state": "missing",
            "recovery_date": None,
            "provider": None,
            "collection_status": "retired",
        }

    recovery_date, recovery_updated_at = recovery_row
    return {
        "state": "fresh",
        "recovery_date": recovery_date,
        "recovery_updated_at": recovery_updated_at,
        "provider": "healthkit",
        "collection_status": "historical",
    }


def build_training_processed_message(user_id: str, activity_id: int) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select r.name, r.start_date, r.activity_type, m.duration_s,
                       m.tss, m.normalized_power, m.intensity_factor,
                       m.avg_power, m.avg_heartrate, m.raw_json->>'ftp_watts',
                       (r.start_date at time zone 'UTC')::date
                from strava_activity_raw r
                left join activity_metrics m
                  on m.strava_activity_id = r.strava_activity_id and m.version = 'v1'
                where r.strava_activity_id = %s and r.user_id = %s;
                """,
                (activity_id, user_id),
            )
            activity_row = cur.fetchone()
            if not activity_row:
                return f"WHATTE\n\nТренировка не найдена\nactivity_id: {activity_id}"
            (name, start_date, activity_type, duration_s, tss, normalized_power,
             intensity_factor, avg_power, avg_heartrate, ftp_watts, state_date) = activity_row
            # Daily load is currently materialized on UTC dates. Use the exact
            # activity day, never unrelated latest state after a historical ingest.
            cur.execute(
                """select fitness, fatigue_total, freshness from load_state_daily_v2
                   where user_id = %s and date = %s and version = 'v2';""",
                (user_id, state_date),
            )
            state_row = cur.fetchone()
            cur.execute(
                """select readiness_score, good_day_probability, status_text, explanation_json
                   from readiness_daily
                   where user_id = %s and date = %s and version = %s;""",
                (user_id, state_date, READINESS_MODEL_VERSION),
            )
            readiness_row = cur.fetchone()

    load_info = resolve_activity_load(
        activity_type=activity_type, tss=tss, normalized_power=normalized_power,
        intensity_factor=intensity_factor,
    )
    activity_time = (datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                     if isinstance(start_date, str) else start_date)
    if activity_time.tzinfo is None:
        activity_time = activity_time.replace(tzinfo=timezone.utc)
    local_time = activity_time.astimezone(ZoneInfo(settings.whatte_timezone))
    lines = ["WHATTE", "", "✅ Тренировка обработана", name or "Без названия", "",
             f"Дата: {local_time:%d.%m.%Y %H:%M %Z}"]
    if duration_s and duration_s > 0:
        lines.append(f"Длительность: {_format_duration(duration_s)}")
    for label, value, digits, unit in (
        ("TSS", tss, 1, ""), ("NP", normalized_power, 1, " W"),
        ("IF", intensity_factor, 2, ""), ("FTP в расчёте", ftp_watts, 1, " W"),
        ("Avg Power", avg_power, 1, " W"), ("Avg HR", avg_heartrate, 1, ""),
    ):
        value = _float_or_none(value)
        if value is not None:
            lines.append(f"{label}: {_fmt(value, digits)}{unit}")
    if not load_info["load_model_included"]:
        lines.extend(["", "Type: unsupported", f"Load model: {load_info['load_source']}",
                      "Нет надёжной оценки нагрузки: тренировка сохранена, но не включена в расчёт нагрузки и готовности."])
    else:
        workout_type = classify_workout_type(intensity_factor, tss, duration_s)
        lines.extend(["", f"Type: {workout_type}", f"Load model: {load_info['load_source']}",
                      f"Comment: {build_workout_comment(workout_type, tss)}", "",
                      f"Состояние за {state_date} (UTC)"])
        if state_row:
            for label, value in zip(("Fitness", "Fatigue", "Freshness"), state_row):
                if value is not None:
                    lines.append(f"{label}: {_fmt(value, 2)}")
        else:
            lines.append("Состояние нагрузки пока не рассчитано")
        if readiness_row and readiness_row[0] is not None:
            readiness_score, _, status_text, explanation_json = readiness_row
            decision_briefing = build_persisted_readiness_briefing(
                readiness_score=_float_or_none(readiness_score),
                status_text=status_text,
                explanation=_as_dict(explanation_json),
            )
            lines.extend([
                f"Готовность: {_fmt(_float_or_none(readiness_score), 1)}/100",
                f"Рекомендация: {decision_briefing['briefing']}",
            ])
        else:
            lines.append("Готовность пока не рассчитана")
    lines.extend(["", f"activity_id: {activity_id}"])
    return "\n".join(lines)


def build_daily_readiness_message(
    user_id: str,
    *,
    notification_date: date | None = None,
    recovery_date: date | None = None,
    data_freshness: dict[str, Any] | None = None,
) -> str:
    target_recovery_date = notification_date or recovery_date
    with get_conn() as conn:
        with conn.cursor() as cur:
            readiness_date_filter = ""
            params: tuple[Any, ...] = (user_id, READINESS_MODEL_VERSION)
            if target_recovery_date is not None:
                readiness_date_filter = "and date = %s"
                params = (user_id, READINESS_MODEL_VERSION, target_recovery_date)

            cur.execute(
                f"""
                select
                    date,
                    readiness_score,
                    good_day_probability,
                    status_text,
                    explanation_json
                from readiness_daily
                where user_id = %s
                  and version = %s
                  {readiness_date_filter}
                order by date desc
                limit 1;
                """,
                params,
            )
            readiness_row = cur.fetchone()

            if readiness_row:
                (
                    readiness_date,
                    readiness_score,
                    good_day_probability,
                    status_text,
                    explanation_json,
                ) = readiness_row

                explanation = _as_dict(explanation_json)
                source_timestamps = _as_dict(explanation.get("source_timestamps"))
                recovery_explanation = _as_dict(
                    explanation.get("recovery_explanation")
                )
                score = _float_or_none(readiness_score)
                decision_briefing = build_persisted_readiness_briefing(
                    readiness_score=score,
                    status_text=status_text,
                    explanation=explanation,
                )

                return build_readiness_briefing_message(
                    notification_date=notification_date or readiness_date,
                    recovery_date=source_timestamps.get("recovery_source_at"),
                    readiness_score=score,
                    status_text=status_text,
                    good_day_probability=_float_or_none(good_day_probability),
                    freshness=_float_or_none(explanation.get("freshness")),
                    recovery_score_simple=_float_or_none(
                        explanation.get("recovery_score_simple")
                    ),
                    recovery_explanation=recovery_explanation,
                    briefing=decision_briefing["briefing"],
                    data_freshness=data_freshness,
                )

    return "WHATTE · Today\n\nГотовность пока не рассчитана. Нет данных текущей модели за выбранную дату."


def notify_training_processed(user_id: str, activity_id: int) -> bool:
    state = get_activity_deduplication_state(activity_id)
    if state["is_excluded"]:
        return False

    canonical_activity_id = state["canonical_activity_id"]
    claimed = claim_activity_delivery(
        user_id=user_id,
        canonical_activity_id=canonical_activity_id,
        delivery_type=DELIVERY_TRAINING_PROCESSED,
    )
    if not claimed:
        return False

    delivered = False
    try:
        text = build_training_processed_message(
            user_id=user_id,
            activity_id=canonical_activity_id,
        )
        response = send_telegram_message(text)
        delivered = True
        message_id = (
            response.get("result", {}).get("message_id")
            if isinstance(response, dict)
            else None
        )
        mark_activity_delivery_sent(
            canonical_activity_id=canonical_activity_id,
            delivery_type=DELIVERY_TRAINING_PROCESSED,
            telegram_message_id=message_id,
            payload={"message": text, "source_activity_id": activity_id},
        )
        send_post_ride_rpe_request(canonical_activity_id)
    except Exception:
        if not delivered:
            release_activity_delivery_claim(
                canonical_activity_id=canonical_activity_id,
                delivery_type=DELIVERY_TRAINING_PROCESSED,
            )
        raise
    return True


def _daily_readiness_content_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@contextmanager
def _daily_readiness_delivery_lock(
    user_id: str,
    notification_date: date,
) -> Iterator[None]:
    """Serialize competing fallback/sync deliveries for one user's local day."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select pg_advisory_xact_lock(hashtext(%s), hashtext(%s));",
                ("daily_readiness", f"{user_id}:{notification_date.isoformat()}"),
            )
        yield


def _freshness_rank(value: str | None) -> int:
    return {"missing": 0, "stale": 1, "fresh": 2}.get(value or "missing", 0)


def _incoming_daily_readiness_is_newer(
    *,
    current_recovery_date: date | None,
    current_freshness_status: str | None,
    current_content_fingerprint: str | None,
    incoming_recovery_date: date | None,
    incoming_freshness_status: str,
    incoming_content_fingerprint: str,
) -> bool:
    """Compare delivered briefing versions without changing readiness semantics."""
    if current_recovery_date is not None and incoming_recovery_date is not None:
        if incoming_recovery_date < current_recovery_date:
            return False
        if incoming_recovery_date > current_recovery_date:
            return True

    current_rank = _freshness_rank(current_freshness_status)
    incoming_rank = _freshness_rank(incoming_freshness_status)
    if incoming_rank < current_rank:
        return False
    if incoming_rank > current_rank:
        return True

    return incoming_content_fingerprint != current_content_fingerprint


def claim_daily_readiness(
    user_id: str,
    notification_date: date,
    *,
    recovery_date: date | None,
    freshness_status: str,
    content_fingerprint: str,
    message: str,
    data_freshness: dict[str, Any],
) -> DailyReadinessDeliveryClaim | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_log (
                    user_id,
                    notification_type,
                    notification_date,
                    recovery_date,
                    freshness_status,
                    delivery_status,
                    content_fingerprint,
                    payload_json
                )
                values (
                    %s,
                    'daily_readiness',
                    %s,
                    %s,
                    %s,
                    'claimed',
                    %s,
                    %s::jsonb
                )
                on conflict (user_id, notification_type, notification_date) do nothing
                returning id;
                """,
                (
                    user_id,
                    notification_date,
                    recovery_date,
                    freshness_status,
                    content_fingerprint,
                    json.dumps(
                        {
                            "delivery_state": "claimed",
                            "data_freshness": data_freshness,
                        },
                        default=str,
                    ),
                ),
            )
            inserted = cur.fetchone()
            if inserted is not None:
                conn.commit()
                return DailyReadinessDeliveryClaim(action="send")

            cur.execute(
                """
                select
                    recovery_date,
                    freshness_status,
                    delivery_status,
                    content_fingerprint,
                    telegram_chat_id,
                    telegram_message_id,
                    payload_json->>'message'
                from notification_log
                where user_id = %s
                  and notification_type = 'daily_readiness'
                  and notification_date = %s
                for update;
                """,
                (user_id, notification_date),
            )
            row = cur.fetchone()
            if row is None:
                conn.commit()
                return None

            (
                current_recovery_date,
                current_freshness_status,
                delivery_status,
                current_content_fingerprint,
                telegram_chat_id,
                telegram_message_id,
                current_message,
            ) = row

            if delivery_status == DAILY_READINESS_STATUS_FAILED:
                cur.execute(
                    """
                    update notification_log
                    set recovery_date = %s,
                        freshness_status = %s,
                        delivery_status = 'claimed',
                        content_fingerprint = %s,
                        updated_at = now()
                    where user_id = %s
                      and notification_type = 'daily_readiness'
                      and notification_date = %s;
                    """,
                    (
                        recovery_date,
                        freshness_status,
                        content_fingerprint,
                        user_id,
                        notification_date,
                    ),
                )
                conn.commit()
                return DailyReadinessDeliveryClaim(action="send")

            if delivery_status in {
                DAILY_READINESS_STATUS_CLAIMED,
                DAILY_READINESS_STATUS_UPDATING,
            }:
                conn.commit()
                return None

            # Rows created before the lifecycle migration have no SHA-256
            # fingerprint or Telegram coordinates. Exact content equality keeps
            # those historical deliveries idempotent after deployment.
            if current_message == message:
                conn.commit()
                return None

            if not _incoming_daily_readiness_is_newer(
                current_recovery_date=current_recovery_date,
                current_freshness_status=current_freshness_status,
                current_content_fingerprint=current_content_fingerprint,
                incoming_recovery_date=recovery_date,
                incoming_freshness_status=freshness_status,
                incoming_content_fingerprint=content_fingerprint,
            ):
                conn.commit()
                return None

            cur.execute(
                """
                update notification_log
                set delivery_status = 'updating',
                    updated_at = now()
                where user_id = %s
                  and notification_type = 'daily_readiness'
                  and notification_date = %s;
                """,
                (user_id, notification_date),
            )
            conn.commit()

    action: Literal["edit", "send_update"] = (
        "edit"
        if telegram_chat_id is not None and telegram_message_id is not None
        else "send_update"
    )
    return DailyReadinessDeliveryClaim(
        action=action,
        previous_delivery_status=delivery_status,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=telegram_message_id,
    )


def mark_daily_readiness_sent(
    user_id: str,
    notification_date: date,
    *,
    payload: str,
    recovery_date: date | None,
    freshness_status: str,
    delivery_status: str,
    content_fingerprint: str,
    telegram_chat_id: str | int | None,
    telegram_message_id: int | None,
    data_freshness: dict[str, Any],
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update notification_log
                set recovery_date = %s,
                    freshness_status = %s,
                    delivery_status = %s,
                    telegram_chat_id = %s,
                    telegram_message_id = %s,
                    sent_at = coalesce(sent_at, now()),
                    updated_at = now(),
                    content_fingerprint = %s,
                    payload_json = %s::jsonb
                where user_id = %s
                  and notification_type = 'daily_readiness'
                  and notification_date = %s;
                """,
                (
                    recovery_date,
                    freshness_status,
                    delivery_status,
                    str(telegram_chat_id) if telegram_chat_id is not None else None,
                    telegram_message_id,
                    content_fingerprint,
                    json.dumps(
                        {
                            "delivery_state": delivery_status,
                            "message": payload,
                            "data_freshness": data_freshness,
                        },
                        default=str,
                    ),
                    user_id,
                    notification_date,
                ),
            )
            conn.commit()


def release_daily_readiness_claim(
    user_id: str,
    notification_date: date,
    *,
    previous_delivery_status: str | None = None,
) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                update notification_log
                set delivery_status = %s,
                    updated_at = now()
                where user_id = %s
                  and notification_type = 'daily_readiness'
                  and notification_date = %s
                  and delivery_status in ('claimed', 'updating');
                """,
                (
                    previous_delivery_status or DAILY_READINESS_STATUS_FAILED,
                    user_id,
                    notification_date,
                ),
            )
            conn.commit()


def _send_daily_readiness_locked(
    user_id: str,
    notification_date: date,
    *,
    recovery_date: date | None = None,
    data_freshness: dict[str, Any] | None = None,
) -> bool:
    if data_freshness is None:
        data_freshness = get_physiology_data_freshness(
            user_id=user_id,
            for_date=notification_date,
        )
    if recovery_date is None and data_freshness.get("recovery_date") is not None:
        recovery_date = date.fromisoformat(str(data_freshness["recovery_date"]))

    freshness_status = str(data_freshness.get("state") or "missing")
    text = build_daily_readiness_message(
        user_id=user_id,
        notification_date=notification_date,
        recovery_date=recovery_date,
        data_freshness=data_freshness,
    )
    content_fingerprint = _daily_readiness_content_fingerprint(text)
    claim = claim_daily_readiness(
        user_id=user_id,
        notification_date=notification_date,
        recovery_date=recovery_date,
        freshness_status=freshness_status,
        content_fingerprint=content_fingerprint,
        message=text,
        data_freshness=data_freshness,
    )
    if claim is None:
        return False

    delivered = False
    try:
        response: dict[str, Any] | None
        delivery_status = DAILY_READINESS_STATUS_SENT
        if claim.action == "edit":
            try:
                response = edit_telegram_message(
                    claim.telegram_chat_id,
                    claim.telegram_message_id,
                    text,
                )
                delivery_status = DAILY_READINESS_STATUS_UPDATED
            except Exception:
                response = send_telegram_message(f"ОБНОВЛЕНИЕ\n\n{text}")
                delivery_status = DAILY_READINESS_STATUS_SUPERSEDED
        else:
            delivery_text = (
                f"ОБНОВЛЕНИЕ\n\n{text}"
                if claim.action == "send_update"
                else text
            )
            response = send_telegram_message(delivery_text)
            if claim.action == "send_update":
                delivery_status = DAILY_READINESS_STATUS_SUPERSEDED
        delivered = True
        result = response.get("result", {}) if isinstance(response, dict) else {}
        response_chat = result.get("chat", {}) if isinstance(result, dict) else {}
        telegram_chat_id = response_chat.get("id") or claim.telegram_chat_id
        telegram_message_id = result.get("message_id") or claim.telegram_message_id
        mark_daily_readiness_sent(
            user_id=user_id,
            notification_date=notification_date,
            payload=text,
            recovery_date=recovery_date,
            freshness_status=freshness_status,
            delivery_status=delivery_status,
            content_fingerprint=content_fingerprint,
            telegram_chat_id=telegram_chat_id or settings.telegram_chat_id,
            telegram_message_id=telegram_message_id,
            data_freshness=data_freshness,
        )
        capture_decision_context_snapshot(
            user_id=user_id,
            snapshot_date=notification_date,
            event_type="daily_readiness_delivery",
            reference_key=f"daily_readiness:{user_id}:{notification_date.isoformat()}",
        )
        try:
            capture_research_feature_snapshot(
                user_id=user_id,
                local_date=notification_date,
                reference_key=f"daily_readiness:{user_id}:{notification_date.isoformat()}",
            )
        except Exception:
            # Delivery already succeeded. Research evidence must never retry a
            # user-visible Telegram message or change the delivery lifecycle.
            logger.exception("Unable to capture research feature snapshot")
    except Exception:
        # Once Telegram accepted the message, keep the claim even if persisting
        # the final payload failed: at-most-once delivery is more important than
        # retrying into a duplicate morning briefing.
        if not delivered:
            release_daily_readiness_claim(
                user_id=user_id,
                notification_date=notification_date,
                previous_delivery_status=claim.previous_delivery_status,
            )
        raise

    return True


def send_daily_readiness(
    user_id: str,
    notification_date: date | None = None,
    *,
    recovery_date: date | None = None,
    data_freshness: dict[str, Any] | None = None,
) -> bool:
    if notification_date is None:
        notification_date = datetime.now(timezone.utc).date()

    # The lock spans Telegram I/O intentionally. Daily briefing delivery is
    # low-frequency, and serializing the lifecycle prevents duplicate sends.
    with _daily_readiness_delivery_lock(user_id, notification_date):
        return _send_daily_readiness_locked(
            user_id=user_id,
            notification_date=notification_date,
            recovery_date=recovery_date,
            data_freshness=data_freshness,
        )
