"""Read-only personal PED surface; shared pure computation."""
from backend.services.rpe_history_service import load_rpe_sessions
from backend.services.effort_deviation_core import (
    VERSION, WINDOW_DAYS, AVAILABILITY_FIELDS, LIMITATIONS, build_effort_deviation,
)


def get_effort_deviation(user_id: str, activity_id: int) -> dict:
    target, candidates, computed_at = load_rpe_sessions(user_id, activity_id, prior_evidence=True)
    return build_effort_deviation(target, candidates, computed_at=computed_at)
