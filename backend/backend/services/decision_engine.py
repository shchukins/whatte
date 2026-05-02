from __future__ import annotations

from typing import Any


def _zone_for_readiness(readiness_score: float) -> str:
    if readiness_score < 40:
        return "recovery"
    if readiness_score < 60:
        return "endurance"
    if readiness_score <= 75:
        return "moderate"
    return "high_intensity"


def _fmt_score(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def build_recommendation(readiness_score: float, explanation: dict[str, Any]) -> dict[str, str]:
    recommendation = _zone_for_readiness(readiness_score)

    reason_parts = [f"Readiness score is {_fmt_score(readiness_score)}/100."]

    fallback_mode = explanation.get("fallback_mode")
    freshness_norm = explanation.get("freshness_norm")
    recovery_score = explanation.get("recovery_score_simple")

    if freshness_norm is not None:
        reason_parts.append(f"Freshness is available at {_fmt_score(float(freshness_norm))}/100.")
    if recovery_score is not None:
        reason_parts.append(f"Recovery is available at {_fmt_score(float(recovery_score))}/100.")

    if fallback_mode == "recovery_only":
        reason_parts.append("Load context is missing, so the recommendation is conservative.")
    elif fallback_mode == "load_only":
        reason_parts.append("Recovery context is missing, so freshness should not be over-interpreted.")

    reason_parts.append(f"Recommendation is {recommendation}.")

    return {
        "recommendation": recommendation,
        "reason": " ".join(reason_parts),
    }


def _status_phrase(status_text: str | None) -> str:
    phrases = {
        "Высокая усталость": "выраженная усталость",
        "Нагрузка": "сниженная готовность после нагрузки",
        "Нормальная готовность": "нормальная готовность",
        "Хорошая готовность": "хорошая готовность",
        "Очень свежий": "очень хорошая готовность",
    }

    if not status_text or status_text == "n/a":
        return "недостаточно данных по готовности"

    return phrases.get(status_text, status_text[:1].lower() + status_text[1:])


def build_readiness_briefing(
    readiness_score: float | None,
    status_text: str | None,
    recommendation: str | None,
    reason: str | None,
    explanation: dict[str, Any] | None,
) -> dict[str, str]:
    """Build a short deterministic user-facing briefing from readiness decision output."""
    if readiness_score is None or not recommendation:
        fallback_reason = reason or "Readiness data is missing, so the recommendation is conservative."
        return {
            "briefing": (
                "Сегодня недостаточно данных для уверенной рекомендации. "
                "Лучше выбрать легкую нагрузку или отдых."
            ),
            "recommendation": recommendation or "insufficient_data",
            "reason": fallback_reason,
        }

    status = _status_phrase(status_text)
    recommendation_text = {
        "recovery": "Лучше выбрать восстановление или очень легкую нагрузку.",
        "endurance": "Рекомендуется спокойная аэробная тренировка.",
        "moderate": "Рекомендуется умеренная аэробная тренировка.",
        "high_intensity": "Интенсивная работа допустима, если она есть в плане.",
    }.get(
        recommendation,
        "Лучше выбрать контролируемую тренировку без лишнего риска.",
    )

    fallback_mode = (explanation or {}).get("fallback_mode")
    caution = ""
    if fallback_mode == "recovery_only":
        caution = " Контекст нагрузки неполный, поэтому лучше не форсировать."
    elif fallback_mode == "load_only":
        caution = " Контекст восстановления неполный, поэтому лучше не форсировать."

    return {
        "briefing": f"Сегодня {status}. {recommendation_text}{caution}",
        "recommendation": recommendation,
        "reason": reason or "",
    }
