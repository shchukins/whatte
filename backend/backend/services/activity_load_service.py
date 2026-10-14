from __future__ import annotations

from dataclasses import dataclass
from typing import Any


CYCLING_ACTIVITY_TYPES = {
    "ride",
    "virtualride",
    "ebikeride",
    "mountainbikeride",
    "gravelride",
    "handcycle",
    "velomobile",
}


def normalize_activity_type(activity_type: Any) -> str | None:
    if activity_type is None:
        return None

    normalized = str(activity_type).strip().lower()
    return normalized or None


def is_supported_cycling_activity(activity_type: Any) -> bool:
    normalized = normalize_activity_type(activity_type)
    if normalized is None:
        return False
    return normalized in CYCLING_ACTIVITY_TYPES


def resolve_activity_load(
    *,
    activity_type: Any,
    tss: float | None,
    normalized_power: float | None,
    intensity_factor: float | None,
) -> dict[str, Any]:
    # MVP: only cycling activities with valid power-based TSS participate in the load model.
    power_metrics_available = (
        tss is not None
        and normalized_power is not None
        and intensity_factor is not None
    )
    load_model_included = (
        is_supported_cycling_activity(activity_type)
        and power_metrics_available
    )

    return {
        "load_source": "power_tss" if load_model_included else "unsupported",
        "load_model_included": load_model_included,
        "power_metrics_available": power_metrics_available,
        "activity_type_normalized": normalize_activity_type(activity_type),
    }


@dataclass(frozen=True)
class ActivityLoadAssessment:
    included: bool | None
    reason: str | None


def assess_stored_activity_load(
    *, has_metrics: bool, activity_type: Any, tss: float | None,
    normalized_power: float | None, intensity_factor: float | None,
) -> ActivityLoadAssessment:
    """Current stored coverage, not evidence of a historical readiness decision.

    Preserve the pilot coverage contract: absent v1 rows are unknown. For an
    available row, use the load resolver and one reason per rejected workout;
    unsupported sport takes precedence over missing required power metrics.
    """
    if not has_metrics:
        return ActivityLoadAssessment(None, "unavailable_metrics_record")
    load = resolve_activity_load(
        activity_type=activity_type, tss=tss, normalized_power=normalized_power,
        intensity_factor=intensity_factor,
    )
    if load["load_model_included"]:
        return ActivityLoadAssessment(True, None)
    reason = (
        "unsupported_sport"
        if not is_supported_cycling_activity(load["activity_type_normalized"])
        else "missing_required_power_metrics"
    )
    return ActivityLoadAssessment(False, reason)
