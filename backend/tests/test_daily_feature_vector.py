from datetime import date, datetime, timedelta, timezone

import pytest

from backend.services.daily_feature_vector import (
    DAILY_FEATURE_VECTOR_VERSION,
    build_daily_feature_vector_from_sources,
)


UTC = timezone.utc
TARGET = date(2026, 10, 1)
CUTOFF = datetime(2026, 10, 1, 9, tzinfo=UTC)


def response(activity_id, start, *, available_at=None, computed_at=None, rpe=6):
    return {
        "activity_id": activity_id, "activity_start_at": start,
        "source_available_at": available_at or start + timedelta(minutes=5),
        "computed_at": computed_at or start + timedelta(minutes=10),
        "normalized_power_to_hr": 2.5, "aerobic_decoupling_pct": 3.0,
        "rpe_score": rpe, "session_rpe_load": 360.0,
        "rpe_per_intensity_factor": 8.0, "session_rpe_load_per_tss": 3.0,
        "intensity_band": "endurance",
    }


def build(**overrides):
    inputs = {
        "user_id": "u", "local_date": TARGET, "cutoff_at": CUTOFF,
        "timezone_name": "Europe/Moscow",
        "load": {"tss": 55.0, "fitness": 40.0, "fatigue_fast": 22.0,
                 "fatigue_slow": 30.0, "fatigue_total": 24.8, "freshness": 15.2,
                 "updated_at": CUTOFF - timedelta(minutes=1)},
        "responses": [], "feeling": None, "manual_physiology": None,
        "historical_physiology": None,
    }
    inputs.update(overrides)
    return build_daily_feature_vector_from_sources(**inputs)


def test_contract_is_versioned_and_missing_signals_are_not_zero_filled():
    result = build()
    assert result["feature_vector_version"] == DAILY_FEATURE_VECTOR_VERSION
    assert result["features"]["physiology.manual.hrv_ms"] == {
        "value": None, "availability": "unavailable",
        "reason_codes": ["manual_physiology_unavailable_as_of_cutoff"],
    }
    assert result["features"]["training_response.latest.rpe_score"]["value"] is None


def test_multiple_activities_are_kept_and_latest_eligible_one_is_explicit():
    first = response(1, CUTOFF - timedelta(hours=3), rpe=4)
    second = response(2, CUTOFF - timedelta(hours=1), rpe=7)
    result = build(responses=[first, second])
    assert result["features"]["training_response.recent_activity_count"]["value"] == 2
    assert result["features"]["training_response.latest.activity_id"]["value"] == 2
    assert [row["activity_id"] for row in result["recent_response_activities"]] == [2, 1]


def test_post_cutoff_source_is_excluded_instead_of_leaking_future_information():
    late = response(1, CUTOFF - timedelta(hours=1), computed_at=CUTOFF + timedelta(seconds=1))
    result = build(responses=[late])
    assert result["source_metadata"]["training_response"]["activity_count"] == 0
    assert result["features"]["training_response.latest.rpe_score"]["availability"] == "unavailable"


def test_timezone_boundary_is_preserved_in_contract_and_requires_aware_cutoff():
    result = build(responses=[response(1, datetime(2026, 9, 30, 21, 30, tzinfo=UTC))])
    assert result["local_date"] == "2026-10-01"
    assert result["timezone"] == "Europe/Moscow"
    with pytest.raises(ValueError, match="timezone-aware"):
        build(cutoff_at=datetime(2026, 10, 1, 9))


def test_feeling_and_physiology_require_current_state_to_precede_cutoff():
    result = build(
        feeling={"score": 4, "created_at": CUTOFF - timedelta(hours=1), "updated_at": CUTOFF + timedelta(seconds=1)},
        manual_physiology={"hrv_ms": 60.0, "updated_at": CUTOFF + timedelta(seconds=1), "computed_at": CUTOFF - timedelta(minutes=1)},
    )
    assert result["features"]["feeling.next_day_recovery_score"]["availability"] == "unavailable"
    assert result["features"]["physiology.manual.hrv_ms"]["availability"] == "unavailable"
