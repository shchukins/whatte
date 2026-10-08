"""Complete reviewed offline predictor config; legacy recipes remain unchanged."""

from typing import Literal
from pydantic import Field, model_validator
from backend.services.research_parameter_space import CandidateConfig, baseline_candidate_config

SPACE_VERSION = "recovery_prediction_parameter_space_v1"
MODEL_VERSION = "recovery_prediction_candidate_v1"


class RecoveryPredictionConfig(CandidateConfig):
    search_space_version: Literal["recovery_prediction_parameter_space_v1"]
    candidate_model_version: Literal["recovery_prediction_candidate_v1"]
    feature_vector_version: Literal["daily_feature_vector_v2"]
    dataset_version: Literal["temporal_dataset_v2"]
    evaluator_version: Literal["baseline_evaluator_v2"]
    learned_state_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def fixed_thresholds(self):
        # These thresholds cannot affect the recovery target and are not searchable.
        if (self.recovery_threshold, self.endurance_threshold, self.moderate_threshold) != (40, 60, 75):
            raise ValueError("recovery_prediction_thresholds_fixed")
        return self


def validate_recovery_config(value):
    return RecoveryPredictionConfig.model_validate(value).model_dump(mode="json")


def baseline_prediction_config(state_hash):
    value = baseline_candidate_config()
    value.update(search_space_version=SPACE_VERSION, candidate_model_version=MODEL_VERSION,
                 feature_vector_version="daily_feature_vector_v2", dataset_version="temporal_dataset_v2",
                 evaluator_version="baseline_evaluator_v2", learned_state_hash=state_hash)
    return validate_recovery_config(value)
