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
