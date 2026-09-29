from datetime import date, datetime, timedelta, timezone

from backend.services.calibration_records import (
    ACTIVITY_QUERY,
    build_calibration_records,
    generate_calibration_records,
)
from backend.services import calibration_records


UTC = timezone.utc


def activity(activity_id=1, start=None, *, metrics_id=11, rpe_id=21,
             recovery_id=31, sport="Ride", current_rpe=None,
             intensity_factor=0.8, recovery_score=3):
    start = start or datetime(2026, 9, 1, 7, tzinfo=UTC)
    local_day = start.astimezone(timezone(timedelta(hours=3))).date()
    return (activity_id, sport, start, local_day, metrics_id,
            52.0 if metrics_id else None, 180.0 if metrics_id else None,
            intensity_factor if metrics_id else None, rpe_id, 4 if rpe_id else None,
            "hard" if rpe_id else None, "v1_extensible" if rpe_id else None,
            start + timedelta(hours=2) if rpe_id else None,
            current_rpe, "strava" if current_rpe else None,
            False if current_rpe else None,
            start + timedelta(hours=2) if current_rpe else None,
            100 + activity_id if current_rpe else None, current_rpe,
            "rpe_1_10" if current_rpe else None,
            "rpe_observation_v1" if current_rpe else None,
            None, start + timedelta(hours=2) if current_rpe else None,
            recovery_id, recovery_score if recovery_id else None,
            {1: "exhausted", 2: "tired", 3: "okay", 4: "fresh", 5: "very_fresh"}[recovery_score] if recovery_id else None,
            "v1_extensible" if recovery_id else None,
            start + timedelta(days=1) if recovery_id else None)


def snapshot(sid=1, captured=None, computed=None, *, day=date(2026, 9, 1),
             version="v2_signal_composition_response_v1", physiology=None):
    captured = captured or datetime(2026, 9, 1, 6, tzinfo=UTC)
    computed = computed or captured - timedelta(minutes=5)
    return (sid, day, "daily_readiness_delivery", f"delivery:{sid}",
            version, 72.0, "moderate",
            {"readiness_computed_at": computed.isoformat(),
             "explanation": {"signal_families": {
                 "physiology": {"availability": physiology}
             }}} if physiology else {"readiness_computed_at": computed.isoformat()},
            captured)


def report(activities, snapshots):
    return build_calibration_records(
        user_id="u", date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 2), timezone="Europe/Moscow",
        activities=activities, snapshots=snapshots,
        generated_at=datetime(2026, 9, 3, tzinfo=UTC),
    )["records"]


def test_latest_eligible_snapshot_and_stable_tie_break():
    start = datetime(2026, 9, 1, 7, tzinfo=UTC)
    records = report([activity()], [
        snapshot(1), snapshot(2),
        snapshot(3, captured=start),
        snapshot(4, captured=start - timedelta(minutes=1), computed=start),
    ])
    assert records[0]["decision"]["source_id"] == 2
    assert records[0]["decision"]["age_seconds"] == 3600
    assert records[0]["decision"]["event_type"] == "daily_readiness_delivery"
    assert records[0]["decision"]["reference_key"] == "delivery:2"


def test_missing_snapshot_reasons_and_model_version():
    assert report([activity()], [])[0]["decision_missing_reason"] == "no_snapshot"
    after = snapshot(captured=datetime(2026, 9, 1, 8, tzinfo=UTC))
    assert report([activity()], [after])[0]["decision_missing_reason"] == "no_snapshot_before_activity"
    invalid = snapshot(computed=datetime(2026, 9, 1, 7, tzinfo=UTC))
    assert report([activity()], [invalid])[0]["decision_missing_reason"] == "missing_or_invalid_pre_activity_computation"
    old = report([activity()], [snapshot(version="legacy")])[0]["decision"]
    assert old["status"] == "incompatible_or_incomplete_decision"
    assert old["model_version"] == "legacy"


def test_local_day_multiple_activities_and_shared_recovery():
    first = activity(1, datetime(2026, 8, 31, 22, 30, tzinfo=UTC))
    second = activity(2, datetime(2026, 9, 1, 9, tzinfo=UTC))
    records = report([first, second], [
        snapshot(1, captured=datetime(2026, 8, 31, 22, tzinfo=UTC)),
        snapshot(2, captured=datetime(2026, 9, 1, 8, tzinfo=UTC)),
    ])
    assert [r["activity_local_date"] for r in records] == [date(2026, 9, 1)] * 2
    assert [r["decision"]["source_id"] for r in records] == [1, 2]
    assert records[0]["next_day_recovery"]["source_id"] == records[1]["next_day_recovery"]["source_id"]
    assert records[0]["next_day_recovery"]["target_local_date"] == date(2026, 9, 2)
    assert records[0]["outcome"]["targets"]["next_day_recovery"]["unit"] == "training_day"
    assert records[0]["outcome"]["targets"]["next_day_recovery"]["source_id"] == records[1]["outcome"]["targets"]["next_day_recovery"]["source_id"]


def test_missing_and_incompatible_feedback_and_load():
    records = report([
        activity(1, metrics_id=None, rpe_id=None, recovery_id=None),
        activity(2, sport="Run"),
    ], [snapshot()])
    assert records[0]["load"]["inclusion_state"] == "missing_metrics"
    assert records[0]["post_ride_rpe"]["status"] == "missing"
    assert records[0]["next_day_recovery"]["status"] == "missing"
    assert records[1]["load"]["inclusion_state"] == "unsupported_sport"
    bad = list(activity())
    bad[11] = "v2"
    assert report([tuple(bad)], [snapshot()])[0]["post_ride_rpe"]["status"] == "incompatible_scale_or_version"
    assert "r.duplicate_of_activity_id is null" in ACTIVITY_QUERY


def test_unchanged_inputs_produce_equivalent_records():
    rows = [activity()]
    snapshots = [snapshot()]
    assert report(rows, snapshots) == report(rows, snapshots)


def test_query_uses_read_only_consistent_transaction(monkeypatch):
    commands = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, params=None):
            commands.append((query, params))

        def fetchall(self):
            return []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(calibration_records, "get_conn", Connection)
    result = generate_calibration_records(
        user_id="u", date_from=date(2026, 9, 1), date_to=date(2026, 9, 2),
    )
    assert commands[0][0] == "set transaction isolation level repeatable read, read only"
    assert commands[1][0] == ACTIVITY_QUERY
    assert result["records"] == []


def test_current_rpe_precedes_legacy_without_mixing_scales():
    result = report([activity(current_rpe=8)], [snapshot()])[0]
    assert result["post_ride_rpe"]["scale"] == "1-10"
    assert result["post_ride_rpe"]["source"] == "strava"
    assert result["legacy_post_ride_rpe"]["scale"] == "1-5"
    assert result["post_ride_rpe"]["source_id"] == 101
    assert result["outcome"]["contract_version"] == "workout_outcome_v1"
    assert result["outcome"]["targets"]["post_workout_rpe"]["scale"] == "1-10"


def test_outcome_targets_remain_independent_when_feedback_is_missing_or_edited():
    original = report([activity(rpe_id=None, recovery_id=None)], [snapshot()])[0]
    targets = original["outcome"]["targets"]
    assert targets["post_workout_rpe"]["status"] == "missing"
    assert targets["next_day_recovery"]["status"] == "missing"
    assert targets["subjective_result"] == {
        "unit": "activity", "status": "not_collected", "value": None,
    }
    assert targets["completion_ratio"]["status"] == "no_plan_source"
    edited = report([activity(current_rpe=9, recovery_score=4)], [snapshot()])[0]
    assert edited["outcome"]["targets"]["post_workout_rpe"]["score"] == 9
    assert edited["outcome"]["targets"]["next_day_recovery"]["score"] == 4
    assert edited["outcome"]["targets"]["completion_state"]["status"] == "not_collected"


def test_outcome_evaluation_counts_recovery_once_per_training_day():
    result = build_calibration_records(
        user_id="u", date_from=date(2026, 9, 1), date_to=date(2026, 9, 2),
        timezone="Europe/Moscow",
        activities=[activity(1, current_rpe=8),
                    activity(2, start=datetime(2026, 9, 1, 9, tzinfo=UTC),
                             rpe_id=None, current_rpe=None)],
        snapshots=[snapshot()], generated_at=datetime(2026, 9, 3, tzinfo=UTC),
    )
    counts = result["outcome_evaluation"]
    assert counts["contract_version"] == "workout_outcome_v1"
    assert counts["activity_target_states"]["post_workout_rpe"] == {
        "available": 1, "missing": 1,
    }
    assert counts["activity_target_states"]["subjective_result"] == {
        "not_collected": 2,
    }
    assert counts["training_day_count"] == 1
    assert counts["next_day_recovery_states"] == {"available": 1}


def test_evaluation_uses_distinct_activity_and_recovery_day_units():
    first = activity(1, current_rpe=8, intensity_factor=0.6, recovery_score=2)
    second = activity(2, start=datetime(2026, 9, 1, 9, tzinfo=UTC),
                      current_rpe=2, intensity_factor=1.1, recovery_score=2)
    evaluation = calibration_records.build_evaluation(report([first, second], [snapshot()]))
    assert evaluation["activity_count"] == 2
    assert evaluation["training_day_count"] == 1
    assert evaluation["recovery_distributions"][0]["day_count"] == 1
    assert evaluation["rpe_distributions"][0]["scale"] == "1-10"
    assert {case["type"] for case in evaluation["review_cases"]} == {
        "low_intensity_high_rpe", "high_intensity_low_rpe",
    }
    assert evaluation["model_error"]["status"] == "not_measurable"


def test_review_case_needs_comparable_evidence():
    missing = activity(1, current_rpe=9, metrics_id=None)
    incompatible = list(activity(2, current_rpe=9))
    incompatible[19] = "unexpected_scale"
    evaluation = calibration_records.build_evaluation(
        report([missing, tuple(incompatible)], [snapshot()])
    )
    assert evaluation["review_cases"] == []
    assert evaluation["activity_states"]["rpe:incompatible_scale_or_resolution:unknown"] == 1


def test_legacy_and_current_rpe_have_separate_denominators():
    evaluation = calibration_records.build_evaluation(report([
        activity(1), activity(2, current_rpe=8),
    ], [snapshot()]))
    assert [(group["scale"], group["count"]) for group in evaluation["rpe_distributions"]] == [
        ("1-10", 1), ("1-5", 1),
    ]
    assert evaluation["activity_states"]["rpe:available:1-10"] == 1
    assert evaluation["activity_states"]["rpe:available:1-5"] == 1


def test_day_review_case_uses_one_recovery_for_multiple_activities():
    first = activity(1, recovery_score=2)
    second = activity(2, start=datetime(2026, 9, 1, 9, tzinfo=UTC), recovery_score=2)
    decision = list(snapshot())
    decision[6] = "high_intensity"
    evaluation = calibration_records.build_evaluation(
        report([first, second], [tuple(decision)])
    )
    cases = [case for case in evaluation["review_cases"]
             if case["type"] == "high_intensity_advice_low_next_day_recovery"]
    assert len(cases) == 1
    assert cases[0]["activity_ids"] == [1, 2]
    assert evaluation["recovery_distributions"][0]["day_count"] == 1


def test_partial_load_day_remains_visible_without_day_review_verdict():
    first = activity(1, recovery_score=2)
    second = activity(2, start=datetime(2026, 9, 1, 9, tzinfo=UTC),
                      sport="Run", recovery_score=2)
    decision = list(snapshot())
    decision[6] = "high_intensity"
    evaluation = calibration_records.build_evaluation(
        report([first, second], [tuple(decision)])
    )
    day = evaluation["recovery_days"][0]
    assert day["load_coverage"] == "partially_included"
    assert evaluation["recovery_distributions"][0]["load_coverage"] == "partially_included"
    assert not any(case["type"] == "high_intensity_advice_low_next_day_recovery"
                   for case in evaluation["review_cases"])


def test_snapshot_physio_availability_is_preserved_as_stratum():
    record = report([activity(current_rpe=7)], [
        snapshot(physiology="unavailable")
    ])[0]
    assert record["decision"]["signal_availability"]["physiology"] == "unavailable"
    evaluation = calibration_records.build_evaluation([record])
    assert evaluation["rpe_distributions"][0]["physiology_availability"] == "unavailable"
    assert evaluation["recovery_distributions"][0]["physiology_availability"] == "unavailable"
