from __future__ import annotations

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
