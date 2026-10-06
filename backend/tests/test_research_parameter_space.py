import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from backend.services.research_parameter_space import (
    baseline_candidate_config, candidate_config_hash, candidate_config_schema,
    validate_candidate_config,
)


def test_baseline_matches_production_constants_and_recommendation_boundaries():
    from backend.services import readiness_composition as production
    from backend.services.decision_engine import build_recommendation
    from backend.services.daily_feature_vector import DAILY_FEATURE_VECTOR_VERSION
    from backend.services.research_evaluator import EVALUATOR_VERSION
    from backend.services.temporal_dataset import DATASET_VERSION

    config = baseline_candidate_config()
    assert config["baseline_source_model_version"] == production.READINESS_MODEL_VERSION
    assert config["feature_vector_version"] == DAILY_FEATURE_VECTOR_VERSION
    assert config["dataset_version"] == DATASET_VERSION
    assert config["evaluator_version"] == EVALUATOR_VERSION
    assert config["freshness_weight"] == production.FRESHNESS_CONFIGURED_WEIGHT
    assert config["recovery_evidence_weight"] == production.RECOVERY_EVIDENCE_WEIGHT
    assert config["response_max_weight"] == production.RESPONSE_MAX_CONFIGURED_WEIGHT
    assert all(config[name] is True for name in (
        "response_enabled", "feeling_enabled", "historical_physiology_enabled"))
    low, middle, high = (config[name] for name in (
        "recovery_threshold", "endurance_threshold", "moderate_threshold"))
    for score, expected in (
        (low - 0.1, "recovery"), (low, "endurance"),
        (middle - 0.1, "endurance"), (middle, "moderate"),
        (high, "moderate"), (high + 0.1, "high_intensity"),
    ):
        assert build_recommendation(score, {})["recommendation"] == expected


@pytest.mark.parametrize("changes", [
    {"freshness_weight": 0.4, "recovery_evidence_weight": 0.6, "response_max_weight": 0.3},
    {"freshness_weight": 0.8, "recovery_evidence_weight": 0.2, "response_max_weight": 0.2},
    {"response_enabled": False, "response_max_weight": 0.0},
    {"feeling_enabled": False, "historical_physiology_enabled": False},
    {"recovery_threshold": 0, "endurance_threshold": 50, "moderate_threshold": 100},
])
def test_valid_boundaries_and_feature_combinations(changes):
    config = baseline_candidate_config() | changes
    assert validate_candidate_config(config) == config


@pytest.mark.parametrize("changes", [
    {"freshness_weight": 0.39}, {"freshness_weight": 0.81},
    {"recovery_evidence_weight": 0.19}, {"recovery_evidence_weight": 0.61},
    {"response_max_weight": -0.1}, {"response_max_weight": 0.31},
    {"recovery_threshold": -1}, {"moderate_threshold": 101},
    {"freshness_weight": 0.5},
    {"freshness_weight": 0.8, "recovery_evidence_weight": 0.2, "response_max_weight": 0.3},
    {"response_enabled": False},
    {"recovery_threshold": 60}, {"moderate_threshold": 60},
    {"endurance_threshold": 30},
    {"freshness_weight": "0.6"}, {"freshness_weight": True},
    {"response_enabled": 1}, {"feeling_enabled": "true"},
    {"response_max_weight": float("nan")}, {"moderate_threshold": float("inf")},
    {"search_space_version": "future"}, {"candidate_model_version": "arbitrary.module"},
    {"dataset_version": "v2"}, {"evaluator_version": "v2"},
    {"baseline_source_model_version": "v2"}, {"feature_vector_version": "v2"},
    {"baseline_window_days": 14}, {"tau_fitness": 30},
    {"manual_physiology_enabled": True}, {"python_expression": "1 + 1"},
    {"metric_weights": {"mae": 1}},
])
def test_invalid_config_is_rejected(changes):
    with pytest.raises(ValueError):
        validate_candidate_config(baseline_candidate_config() | changes)


@pytest.mark.parametrize("field", list(baseline_candidate_config()))
def test_every_field_is_required(field):
    config = baseline_candidate_config()
    del config[field]
    with pytest.raises(ValueError):
        validate_candidate_config(config)


@pytest.mark.parametrize("value", [None, [], "config", 1])
def test_non_objects_are_rejected(value):
    with pytest.raises(ValueError):
        validate_candidate_config(value)


def test_hash_is_canonical_and_configs_are_detached():
    original = baseline_candidate_config()
    config = deepcopy(original)
    assert candidate_config_hash(config) == candidate_config_hash(dict(reversed(list(config.items()))))
    config["response_max_weight"] = 0.1
    assert candidate_config_hash(config) != candidate_config_hash(original)
    assert baseline_candidate_config() == original
    validated = validate_candidate_config(config)
    validated["recovery_threshold"] = 35.0
    assert config["recovery_threshold"] == 40.0


def test_machine_readable_schema_has_types_bounds_defaults_and_constraints():
    schema = json.loads(json.dumps(candidate_config_schema()))
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(baseline_candidate_config())
    for name, default in baseline_candidate_config().items():
        spec = schema["properties"][name]
        assert spec["default"] == default
        assert spec["description"]
        assert spec["type"] in {"number", "boolean", "string"}
    assert schema["properties"]["freshness_weight"]["minimum"] == 0.4
    assert schema["properties"]["freshness_weight"]["maximum"] == 0.8
    assert len(schema["x-compatibility-constraints"]) == 4


@pytest.mark.parametrize("flag", ["--schema", "--baseline"])
def test_cli_exports_valid_json(flag):
    result = subprocess.run(
        [sys.executable, "-m", "scripts.validate_research_config", flag],
        cwd=Path(__file__).parents[1], text=True, capture_output=True, check=True,
    )
    assert isinstance(json.loads(result.stdout), dict)
