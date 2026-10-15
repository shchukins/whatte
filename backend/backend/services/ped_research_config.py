"""Explicit non-production PED study recipe for existing experiment audit records."""
from typing import Literal
from pydantic import Field
from backend.services.recovery_prediction_config import RecoveryPredictionConfig, baseline_prediction_config


class PedResearchConfig(RecoveryPredictionConfig):
    search_space_version: Literal["ped_research_parameter_space_v1"]
    candidate_model_version: Literal["ped_research_v1"]
    evidence_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")


def study_config(state_hash, evidence_hash):
    config = baseline_prediction_config(state_hash)
    config.update(search_space_version="ped_research_parameter_space_v1",
                  candidate_model_version="ped_research_v1", evidence_hash=evidence_hash)
    return validate_ped_config(config)


def validate_ped_config(config):
    result = PedResearchConfig.model_validate(config).model_dump(mode="json")
    expected = baseline_prediction_config(result["learned_state_hash"])
    # Study ablations live in the frozen protocol, not an unbounded weight search.
    if any(result[k] != v for k, v in expected.items()
           if k not in ("search_space_version", "candidate_model_version")):
        raise ValueError("ped_baseline_recipe_fixed")
    return result
