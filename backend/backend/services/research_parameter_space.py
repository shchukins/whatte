"""Strict, data-only search-space contract; never executes or changes a model."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator


SEARCH_SPACE_VERSION = "readiness_parameter_space_v1"
CANDIDATE_MODEL_VERSION = "readiness_parameter_candidate_v1"

# Bounds are conservative engineering search limits, not physiological claims.
# Keep a substantial freshness contribution; response borrows only from
# recovery evidence. Changing bounds or semantics requires a new space version.
_BASELINE = {
    "search_space_version": SEARCH_SPACE_VERSION,
    "candidate_model_version": CANDIDATE_MODEL_VERSION,
    "baseline_source_model_version": "v2_signal_composition_response_v1",
    "feature_vector_version": "daily_feature_vector_v1",
    "dataset_version": "temporal_dataset_v1",
    "evaluator_version": "baseline_evaluator_v1",
    "freshness_weight": 0.6,
    "recovery_evidence_weight": 0.4,
    "response_max_weight": 0.2,
    "response_enabled": True,
    "feeling_enabled": True,
    "historical_physiology_enabled": True,
    "recovery_threshold": 40.0,
    "endurance_threshold": 60.0,
    "moderate_threshold": 75.0,
}


def _field(name: str, description: str, **bounds: Any) -> Any:
    # Defaults are schema annotations, not implicit filling of partial configs.
    return Field(..., description=description,
                 json_schema_extra={"default": _BASELINE[name]}, **bounds)


class CandidateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    search_space_version: Literal["readiness_parameter_space_v1"] = _field(
        "search_space_version", "Exact version of allowed parameters and constraints.")
    candidate_model_version: Literal["readiness_parameter_candidate_v1"] = _field(
        "candidate_model_version", "Parameter recipe identity; not a production model write version.")
    baseline_source_model_version: Literal["v2_signal_composition_response_v1"] = _field(
        "baseline_source_model_version", "Production formula whose defaults are represented exactly.")
    feature_vector_version: Literal["daily_feature_vector_v1"] = _field(
        "feature_vector_version", "Pinned immutable feature-vector contract.")
    dataset_version: Literal["temporal_dataset_v1"] = _field(
        "dataset_version", "Pinned chronological dataset contract.")
    evaluator_version: Literal["baseline_evaluator_v1"] = _field(
        "evaluator_version", "Pinned metric contract; candidate cannot configure metrics.")
    freshness_weight: float = _field(
        "freshness_weight", "Configured freshness weight before missing-signal renormalization.",
        ge=0.4, le=0.8)
    recovery_evidence_weight: float = _field(
        "recovery_evidence_weight", "Total evidence budget before subtracting response weight.",
        ge=0.2, le=0.6)
    response_max_weight: float = _field(
        "response_max_weight", "Maximum current response weight, capped by recovery evidence budget.",
        ge=0.0, le=0.3)
    response_enabled: bool = _field(
        "response_enabled", "Allow baseline-backed response with fixed production scoring/recency rules.")
    feeling_enabled: bool = _field(
        "feeling_enabled", "Allow available 1-5 morning recovery evidence; never impute missing values.")
    historical_physiology_enabled: bool = _field(
        "historical_physiology_enabled", "Allow exact-date historical recovery score; no manual substitution.")
    recovery_threshold: float = _field(
        "recovery_threshold", "Score below this value maps to recovery (exclusive upper boundary).",
        ge=0.0, le=100.0)
    endurance_threshold: float = _field(
        "endurance_threshold", "Score below this value, after recovery, maps to endurance.",
        ge=0.0, le=100.0)
    moderate_threshold: float = _field(
        "moderate_threshold", "Inclusive upper boundary for moderate; higher scores map to high_intensity.",
        ge=0.0, le=100.0)

    @model_validator(mode="after")
    def compatible(self) -> "CandidateConfig":
        # An absolute tolerance handles binary float sums; it is not a hidden
        # normalization or rounding step. Accepted weights remain unchanged.
        if abs(self.freshness_weight + self.recovery_evidence_weight - 1.0) > 1e-12:
            raise ValueError("freshness_weight + recovery_evidence_weight must equal 1")
        if self.response_max_weight > self.recovery_evidence_weight:
            raise ValueError("response_max_weight must not exceed recovery_evidence_weight")
        if not self.response_enabled and self.response_max_weight != 0.0:
            raise ValueError("disabled response requires response_max_weight = 0")
        if not self.recovery_threshold < self.endurance_threshold < self.moderate_threshold:
            raise ValueError("recommendation thresholds must be strictly increasing")
        return self


def validate_candidate_config(value: Mapping[str, Any]) -> dict[str, Any]:
    """Reject partial/unknown/coerced configs and return a detached JSON object."""
    if not isinstance(value, Mapping):
        raise ValueError("candidate config must be an object")
    return CandidateConfig.model_validate(dict(value)).model_dump(mode="json")


def baseline_candidate_config() -> dict[str, Any]:
    return validate_candidate_config(deepcopy(_BASELINE))


def candidate_config_hash(value: Mapping[str, Any]) -> str:
    normalized = validate_candidate_config(value)
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def candidate_config_schema() -> dict[str, Any]:
    """Export JSON Schema plus explicit cross-field validation requirements."""
    schema = CandidateConfig.model_json_schema()
    # JSON Schema describes individual types/ranges; comparisons of sibling
    # numbers require this authoritative validator, also used by persistence.
    schema["x-compatibility-constraints"] = [
        "abs(freshness_weight + recovery_evidence_weight - 1) <= 1e-12",
        "response_max_weight <= recovery_evidence_weight",
        "response_enabled == false implies response_max_weight == 0",
        "recovery_threshold < endurance_threshold < moderate_threshold",
    ]
    schema["x-fixed-semantics"] = {
        "missingness": "exclude unavailable signals and renormalize; no imputation",
        "load": "context only; scored through freshness, never counted twice",
        "freshness": "clamp(50 + freshness, 0, 100)",
        "feeling": "round((score_1_5 - 1) * 25, 1)",
        "response": "production ratio/drift scoring, channel means, seven-day recency",
        "evidence": "subtract response weight; split remainder equally among enabled available recovery signals",
        "physiology": "historical exact-date recovery score only; manual features are not readiness scores",
        "upstream": "load and physiology baseline parameters are fixed in immutable input snapshots",
        "probability": "readiness / 100 presentation only; no outcome probability mapping",
    }
    return schema
