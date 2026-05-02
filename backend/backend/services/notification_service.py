import math
import requests
import json
from datetime import date, datetime, timezone
from typing import Any

from backend.config import settings
from backend.db import get_conn
from backend.services.decision_engine import build_readiness_briefing, build_recommendation


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


def compute_readiness_score(freshness: float | None) -> int | None:
    if freshness is None:
        return None

    score = round(50 + freshness * 5)
    score = max(0, min(100, score))
    return score


def describe_readiness(score: int | None) -> str:
    if score is None:
        return "n/a"
    if score <= 24:
        return "Высокая усталость"
    if score <= 44:
        return "Нагрузка"
    if score <= 64:
        return "Нормальная готовность"
    if score <= 84:
        return "Хорошая готовность"
    return "Очень свежий"


def recommend_training(score: int | None, trend: str = "n/a") -> str:
    if score is None:
        return "Недостаточно данных"

    if score <= 24:
        return "Отдых или очень легкое восстановление"

    if score <= 44:
        if trend == "improving":
            return "Легкая endurance тренировка, без интенсивности"
        return "Легкая тренировка в восстановительном темпе"

    if score <= 64:
        if trend == "declining":
            return "Спокойная endurance тренировка, лучше без интервальной работы"
        if trend == "improving":
            return "Можно делать умеренную тренировку"
        return "Спокойная endurance тренировка"

    if score <= 84:
        if trend == "declining":
            return "Умеренная тренировка, но без максимальной интенсивности"
        if trend == "improving":
            return "Хороший день для качественной тренировки"
        return "Можно делать умеренную или качественную тренировку"

    if trend == "declining":
        return "Можно тренироваться интенсивно, но стоит контролировать самочувствие"

    return "Подходит день для интенсивной тренировки"


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


def describe_training_impact(
    delta_fatigue: float | None,
    delta_freshness: float | None,
) -> str:
    if delta_fatigue is None or delta_freshness is None:
        return "Недостаточно данных для оценки влияния"

    if delta_fatigue >= 8:
        return "Сильная нагрузка, значительный рост усталости"

    if delta_fatigue >= 4:
        return "Заметная тренировочная нагрузка"

    if delta_fatigue >= 1:
        return "Умеренная нагрузка"

    if delta_fatigue < 1:
        return "Легкая нагрузка"

    return "Нагрузка не определена"


def compute_training_impact(
    prev_fatigue: float | None,
    prev_freshness: float | None,
    new_fatigue: float | None,
    new_freshness: float | None,
) -> dict:
    if (
        prev_fatigue is None
        or prev_freshness is None
        or new_fatigue is None
        or new_freshness is None
    ):
        return {
            "delta_fatigue": None,
            "delta_freshness": None,
        }

    return {
        "delta_fatigue": new_fatigue - prev_fatigue,
        "delta_freshness": new_freshness - prev_freshness,
    }


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


def build_briefing_text(
    score: int | None,
    trend: str,
    yesterday_load: float | None,
    last_workout_tss: float | None,
) -> str:
    if score is None:
        return "Недостаточно данных для интерпретации состояния."

    heavy_recent_load = False

    if yesterday_load is not None and yesterday_load >= 60:
        heavy_recent_load = True

    if last_workout_tss is not None and last_workout_tss >= 80:
        heavy_recent_load = True

    if score <= 24:
        if trend == "declining":
            return "Сегодня лучше восстановиться. Свежесть низкая, тренд ухудшается."
        if heavy_recent_load:
            return "Сегодня лучше восстановиться. Недавняя нагрузка была высокой."
        return "Сегодня лучше восстановиться. Организм выглядит утомленным."

    if score <= 44:
        if trend == "improving":
            return "Состояние еще ограничено, но есть признаки восстановления."
        return "Состояние умеренно утомленное. Лучше держать нагрузку легкой."

    if score <= 64:
        if trend == "declining":
            return "Состояние нормальное, но тренд ухудшается. Лучше не форсировать нагрузку."
        if trend == "improving":
            return "Состояние нормальное и улучшается. Подходит день для умеренной тренировки."
        return "Состояние нормальное. Подходит день для спокойной endurance тренировки."

    if score <= 84:
        if trend == "declining":
            return "Состояние хорошее, но тренд не улучшается. Лучше избегать максимальной интенсивности."
        if heavy_recent_load:
            return "Состояние хорошее, но недавняя нагрузка была заметной. Контролируй самочувствие."
        return "Хороший день для качественной работы."

    if trend == "declining":
        return "Состояние очень хорошее, но тренд снижается. Интенсивность допустима, но без лишнего риска."

    return "Очень хороший день для интенсивной тренировки."


def build_readiness_comment(
    freshness: float | None,
    recovery_score_simple: float | None,
    recovery_explanation: dict[str, Any] | None,
) -> str:
    recovery_explanation = recovery_explanation or {}

    sleep_score = _float_or_none(recovery_explanation.get("sleep_score"))
    hrv_score = _float_or_none(recovery_explanation.get("hrv_score"))
    rhr_score = _float_or_none(recovery_explanation.get("rhr_score"))

    scores = {
        "sleep": sleep_score,
        "hrv": hrv_score,
        "rhr": rhr_score,
    }
    available_scores = {
        key: value for key, value in scores.items() if value is not None
    }

    if (
        freshness is not None
        and freshness >= 5
        and recovery_score_simple is not None
        and recovery_score_simple >= 70
    ):
        return "Состояние выглядит хорошим: и свежесть, и восстановление на хорошем уровне."

    if freshness is not None and freshness <= -5:
        return "Есть признаки накопленной усталости, сегодня лучше контролировать нагрузку."

    if not available_scores:
        return "Восстановление выглядит стабильно, но деталей по breakdown пока недостаточно."

    min_score = min(available_scores.values())
    max_score = max(available_scores.values())

    if min_score >= 75:
        return "Восстановление выглядит хорошим по основным сигналам."

    lowest_component = min(
        available_scores,
        key=available_scores.get,
    )

    if lowest_component == "sleep":
        return "Основной ограничивающий фактор сегодня — сон."
    if lowest_component == "hrv":
        return "HRV ниже baseline, восстановление выглядит неполным."
    if lowest_component == "rhr":
        return "Пульс покоя выше обычного, это может указывать на неполное восстановление."

    if max_score >= 75:
        return "Часть recovery signals выглядит хорошо, но есть один ограничивающий фактор."

    return "Состояние смешанное: recovery signals расходятся между собой."


def build_readiness_briefing_message(
    *,
    target_date: Any,
    readiness_score: float | None,
    status_text: str | None,
    good_day_probability: float | None,
    freshness: float | None,
    recovery_score_simple: float | None,
    recovery_explanation: dict[str, Any] | None,
    briefing: str | None = None,
) -> str:
    recovery_explanation = recovery_explanation or {}

    lines = [
        "Human Engine · Today",
        "",
        f"Дата: {target_date}",
        "",
        f"Готовность: {_fmt(readiness_score, 1)}",
        f"Статус: {status_text or 'n/a'}",
        f"Вероятность хорошего дня: {_fmt_percent(good_day_probability)}",
        "",
        f"Свежесть: {_fmt(freshness, 1)}",
        f"Восстановление: {_fmt(recovery_score_simple, 1)}",
        "",
        "Восстановление:",
        f"• Сон: {_fmt(_float_or_none(recovery_explanation.get('sleep_score')), 1)}",
        f"• HRV: {_fmt(_float_or_none(recovery_explanation.get('hrv_score')), 1)}",
        f"• Пульс покоя: {_fmt(_float_or_none(recovery_explanation.get('rhr_score')), 1)}",
        "",
        "Комментарий:",
        briefing
        or build_readiness_comment(
            freshness=freshness,
            recovery_score_simple=recovery_score_simple,
            recovery_explanation=recovery_explanation,
        ),
    ]

    return "\n".join(lines)


def describe_freshness_trend(values: list[float]) -> str:
    if len(values) < 2:
        return "n/a"

    first_value = values[0]
    last_value = values[-1]
    delta = last_value - first_value

    if delta >= 2:
        return "improving"

    if delta <= -2:
        return "declining"

    return "stable"


def build_training_processed_message(user_id: str, activity_id: int) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select
                    r.name,
                    r.start_date,
                    m.duration_s,
                    m.tss,
                    m.normalized_power,
                    m.intensity_factor,
                    m.avg_power,
                    m.avg_heartrate
                from strava_activity_raw r
                left join activity_metrics m
                  on m.strava_activity_id = r.strava_activity_id
                 and m.version = 'v1'
                where r.strava_activity_id = %s;
                """,
                (activity_id,),
            )
            activity_row = cur.fetchone()

            cur.execute(
                """
                select
                    fitness_signal,
                    fatigue_signal,
                    freshness_signal
                from daily_fitness_state
                where user_id = %s
                order by date desc
                limit 2;
                """,
                (user_id,),
            )
            state_rows = cur.fetchall()
            
            cur.execute(
                """
                select
                    fitness_signal,
                    fatigue_signal,
                    freshness_signal
                from daily_fitness_state
                where user_id = %s
                order by date desc
                limit 1;
                """,
                (user_id,),
            )
            state_row = cur.fetchone()

    if not activity_row:
        return f"Human Engine\n\nТренировка обработана\nactivity_id={activity_id}"

    (
        name,
        start_date,
        duration_s,
        tss,
        normalized_power,
        intensity_factor,
        avg_power,
        avg_heartrate,
    ) = activity_row

    fitness = None
    fatigue = None
    freshness = None

    prev_fatigue = None
    prev_freshness = None

    if state_rows:
        # текущее состояние
        fitness, fatigue, freshness = state_rows[0]

        # предыдущее состояние
        if len(state_rows) > 1:
            _, prev_fatigue, prev_freshness = state_rows[1]

    readiness_score = compute_readiness_score(freshness)
    readiness_text = describe_readiness(readiness_score)

    impact = compute_training_impact(
        prev_fatigue,
        prev_freshness,
        fatigue,
        freshness,
    )

    impact_text = describe_training_impact(
        impact["delta_fatigue"],
        impact["delta_freshness"],
    )

    workout_type = classify_workout_type(
        intensity_factor=intensity_factor,
        tss=tss,
        duration_s=duration_s,
    )
    workout_comment = build_workout_comment(workout_type, tss)

    lines = [
        "Human Engine",
        "",
        "✅ Тренировка обработана",
        f"{name or 'Без названия'}",
        "",
        f"Дата: {start_date}",
        f"Длительность: {_format_duration(duration_s)}",
        f"TSS: {_fmt(tss, 1)}",
        f"NP: {_fmt(normalized_power, 1)} W",
        f"IF: {_fmt(intensity_factor, 2)}",
        f"Avg Power: {_fmt(avg_power, 1)} W",
        f"Avg HR: {_fmt(avg_heartrate, 1)}",
        "",
        f"Type: {workout_type}",
        f"Comment: {workout_comment}",
        "",
        "Impact",
        f"Fatigue Δ: {_fmt(impact['delta_fatigue'], 2)}",
        f"Freshness Δ: {_fmt(impact['delta_freshness'], 2)}",
        f"{impact_text}",
        "",
        "Состояние после обновления",
        f"Fitness: {_fmt(fitness, 2)}",
        f"Fatigue: {_fmt(fatigue, 2)}",
        f"Freshness: {_fmt(freshness, 2)}",
        "",
        f"Readiness: {readiness_score if readiness_score is not None else 'n/a'}/100",
        f"Статус: {readiness_text}",
        "",
        f"activity_id: {activity_id}",
    ]

    return "\n".join(lines)


def build_daily_readiness_message(user_id: str) -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
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
                recovery_explanation = _as_dict(
                    explanation.get("recovery_explanation")
                )
                score = _float_or_none(readiness_score)
                decision = (
                    build_recommendation(
                        readiness_score=score,
                        explanation=explanation,
                    )
                    if score is not None
                    else {
                        "recommendation": "insufficient_data",
                        "reason": "Readiness data is missing, so the recommendation is conservative.",
                    }
                )
                readiness_briefing = build_readiness_briefing(
                    readiness_score=score,
                    status_text=status_text,
                    recommendation=decision["recommendation"],
                    reason=decision["reason"],
                    explanation=explanation,
                )

                return build_readiness_briefing_message(
                    target_date=readiness_date,
                    readiness_score=score,
                    status_text=status_text,
                    good_day_probability=_float_or_none(good_day_probability),
                    freshness=_float_or_none(explanation.get("freshness")),
                    recovery_score_simple=_float_or_none(
                        explanation.get("recovery_score_simple")
                    ),
                    recovery_explanation=recovery_explanation,
                    briefing=readiness_briefing["briefing"],
                )

            cur.execute(
                """
                select
                    date,
                    fitness_signal,
                    fatigue_signal,
                    freshness_signal
                from daily_fitness_state
                where user_id = %s
                order by date desc
                limit 1;
                """,
                (user_id,),
            )
            row = cur.fetchone()

            cur.execute(
                """
                select freshness_signal
                from daily_fitness_state
                where user_id = %s
                order by date desc
                limit 3;
                """,
                (user_id,),
            )
            trend_rows = cur.fetchall()

            cur.execute(
                """
                select
                    coalesce(tss, 0)
                from daily_training_load
                where user_id = %s
                  and date = (
                      select max(date) - interval '1 day'
                      from daily_fitness_state
                      where user_id = %s
                  );
                """,
                (user_id, user_id),
            )
            yesterday_load_row = cur.fetchone()

            cur.execute(
                """
                select count(*)
                from daily_training_load
                where user_id = %s
                  and date >= (
                      select max(date) - interval '2 day'
                      from daily_fitness_state
                      where user_id = %s
                  )
                  and tss > 0;
                """,
                (user_id, user_id),
            )
            recent_training_days_row = cur.fetchone()

            cur.execute(
                """
                select
                    date,
                    tss
                from daily_training_load
                where user_id = %s
                  and tss > 0
                order by date desc
                limit 1;
                """,
                (user_id,),
            )
            last_workout_row = cur.fetchone()

    if not row:
        return (
            "Human Engine\n\n"
            "📅 Daily Readiness Summary\n"
            "Недостаточно данных для расчета состояния"
        )

    date, fitness, fatigue, freshness = row

    # В БД значения идут от новых к старым, а для тренда нам удобнее старые -> новые
    trend_values = [r[0] for r in reversed(trend_rows)] if trend_rows else []
    trend = describe_freshness_trend(trend_values)

    yesterday_load = yesterday_load_row[0] if yesterday_load_row else 0
    recent_training_days = recent_training_days_row[0] if recent_training_days_row else 0

    last_workout_date = None
    last_workout_tss = None

    if last_workout_row:
        last_workout_date, last_workout_tss = last_workout_row

    readiness_score = compute_readiness_score(freshness)
    readiness_text = describe_readiness(readiness_score)
    recommendation = recommend_training(readiness_score, trend)

    briefing = build_briefing_text(
        readiness_score,
        trend,
        yesterday_load,
        last_workout_tss,
    )

    lines = [
        "Human Engine",
        "",
        "📅 Daily Readiness Summary",
        f"Дата: {date}",
        "",
        f"Fitness: {_fmt(fitness, 2)}",
        f"Fatigue: {_fmt(fatigue, 2)}",
        f"Freshness: {_fmt(freshness, 2)}",
        f"Trend: {trend}",
        "",
        f"Yesterday load: {_fmt(yesterday_load, 1)} TSS",
        f"Training days (3d): {recent_training_days}",
        "",
        f"Last workout: {_fmt(last_workout_tss, 1)} TSS",
        f"Last workout date: {last_workout_date or 'n/a'}",
        f"Readiness: {readiness_score if readiness_score is not None else 'n/a'}/100",
        f"Статус: {readiness_text}",
        "",
        f"Briefing: {briefing}",
        "",
        f"Рекомендация: {recommendation}",
    ]

    return "\n".join(lines)


def send_telegram_message(text: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return

    response = requests.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
        json={
            "chat_id": settings.telegram_chat_id,
            "text": text,
        },
        timeout=30,
    )
    response.raise_for_status()


def notify_training_processed(user_id: str, activity_id: int) -> None:
    text = build_training_processed_message(user_id=user_id, activity_id=activity_id)
    send_telegram_message(text)

def was_daily_readiness_sent(user_id: str, for_date: date) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select 1
                from notification_log
                where user_id = %s
                  and notification_type = 'daily_readiness'
                  and notification_date = %s
                limit 1;
                """,
                (user_id, for_date),
            )
            row = cur.fetchone()

    return row is not None


def mark_daily_readiness_sent(user_id: str, for_date: date, payload: str | None = None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_log (
                    user_id,
                    notification_type,
                    notification_date,
                    payload_json
                )
                values (
                    %s,
                    'daily_readiness',
                    %s,
                    %s::jsonb
                )
                on conflict (user_id, notification_type, notification_date) do nothing;
                """,
                (
                    user_id,
                    for_date,
                    json.dumps({"message": payload}) if payload else None,
                ),
            )
            conn.commit()


def was_daily_readiness_sent(user_id: str, for_date: date) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select 1
                from notification_log
                where user_id = %s
                  and notification_type = 'daily_readiness'
                  and notification_date = %s
                limit 1;
                """,
                (user_id, for_date),
            )
            row = cur.fetchone()

    return row is not None


def mark_daily_readiness_sent(user_id: str, for_date: date, payload: str | None = None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into notification_log (
                    user_id,
                    notification_type,
                    notification_date,
                    payload_json
                )
                values (
                    %s,
                    'daily_readiness',
                    %s,
                    %s::jsonb
                )
                on conflict (user_id, notification_type, notification_date) do nothing;
                """,
                (
                    user_id,
                    for_date,
                    json.dumps({"message": payload}) if payload else None,
                ),
            )
            conn.commit()


def send_daily_readiness(user_id: str, for_date: date | None = None) -> bool:
    if for_date is None:
        for_date = datetime.now(timezone.utc).date()

    if was_daily_readiness_sent(user_id=user_id, for_date=for_date):
        return False

    text = build_daily_readiness_message(user_id=user_id)
    send_telegram_message(text)
    mark_daily_readiness_sent(user_id=user_id, for_date=for_date, payload=text)

    return True
