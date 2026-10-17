from datetime import date, datetime, timedelta, timezone
import json
import sys
from zoneinfo import ZoneInfo

import pytest
from psycopg import OperationalError

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


def completeness_report(rows, *, now=datetime(2026, 9, 3, tzinfo=UTC),
                        zone="Europe/Moscow", gap_limit=20):
    return build_calibration_records(
        user_id="synthetic", date_from=date(2026, 9, 1), date_to=date(2026, 9, 2),
        timezone=zone, activities=rows, snapshots=[], generated_at=now,
        gap_limit=gap_limit,
    )


def test_completeness_empty_period_has_unavailable_fractions():
    result = completeness_report([])["feedback_completeness"]
    assert result["status"] == "ok"
    assert result["canonical_workout_count"] == result["training_day_count"] == 0
    for rate in (result["rpe"]["current_coverage"], result["next_day_recovery"]["coverage"]):
        assert rate == {"numerator": 0, "denominator": 0, "fraction": None}
    assert result["gaps"]["activities"] == result["gaps"]["training_days"] == []


def test_completeness_denominators_ignore_snapshot_sport_and_power():
    no_power = list(activity(2, current_rpe=6))
    no_power[6] = None
    result = completeness_report([
        activity(1, current_rpe=7, sport="Run", metrics_id=None), tuple(no_power),
        activity(3, rpe_id=None, recovery_id=31),
    ])["feedback_completeness"]
    assert result["canonical_workout_count"] == 3
    assert result["rpe"]["current_coverage"] == {
        "numerator": 2, "denominator": 3, "fraction": 2 / 3,
    }
    assert result["training_day_count"] == 1
    assert result["next_day_recovery"]["coverage"] == {
        "numerator": 1, "denominator": 1, "fraction": 1.0,
    }


def test_completeness_preserves_effective_source_and_separate_legacy():
    conflict = list(activity(1, current_rpe=8))
    conflict[15] = True
    incompatible = list(activity(2, current_rpe=9))
    incompatible[18] = 2  # Selected observation differs from persisted resolution.
    bad_scale = list(activity(3, current_rpe=7))
    bad_scale[19] = "legacy_scale"
    bad_legacy = list(activity(4))
    bad_legacy[11] = "future"
    result = completeness_report([
        tuple(conflict), tuple(incompatible), tuple(bad_scale), tuple(bad_legacy),
        activity(5), activity(6, rpe_id=None),
    ])
    counts = result["feedback_completeness"]["rpe"]
    assert (counts["usable_current"], counts["incompatible"],
            counts["legacy_only"], counts["missing"]) == (1, 3, 1, 1)
    assert counts["compatible_legacy_observation_count"] == 4
    assert counts["source_disagreement_count"] == 1
    assert result["records"][0]["post_ride_rpe"]["score"] == 8
    assert result["records"][0]["post_ride_rpe"]["source"] == "strava"
    assert [gap["reason_code"] for gap in result["feedback_completeness"]["gaps"]["activities"]] == [
        "incompatible_scale_or_resolution", "incompatible_scale_or_resolution",
        "incompatible_scale_or_version", "legacy_rpe_only", "missing_rpe",
    ]


@pytest.mark.parametrize("now,expected", [
    (datetime(2026, 9, 2, 20, 59, 59, tzinfo=UTC), "window_open"),
    (datetime(2026, 9, 2, 21, tzinfo=UTC), "missing"),
])
def test_completeness_window_closes_exactly_at_local_d_plus_2(now, expected):
    result = completeness_report([activity(recovery_id=None)], now=now)["feedback_completeness"]
    assert result["next_day_recovery"][expected] == 1
    assert result["gaps"]["training_days"][0]["window_closes_at"] == "2026-09-03T00:00:00+03:00"


@pytest.mark.parametrize("column,value", [(25, "fresh"), (26, "future_schema")])
def test_completeness_recovery_incompatibility_is_not_missing_or_pending(column, value):
    bad = list(activity())
    bad[column] = value
    result = completeness_report([tuple(bad)], now=datetime(2026, 9, 1, tzinfo=UTC))
    recovery = result["feedback_completeness"]["next_day_recovery"]
    assert (recovery["incompatible"], recovery["missing"], recovery["window_open"]) == (1, 0, 0)
    assert result["feedback_completeness"]["gaps"]["training_days"][0]["reason_code"] == "incompatible_scale_or_version"


def test_completeness_compatible_feedback_counts_before_window_closure():
    result = completeness_report([activity()], now=datetime(2026, 9, 2, 10, tzinfo=UTC))
    assert result["feedback_completeness"]["next_day_recovery"]["usable"] == 1


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 28), 23), (date(2026, 10, 24), 25)])
def test_completeness_dst_uses_calendar_dates_and_local_midnight(day, hours):
    zone = ZoneInfo("Europe/Berlin")
    start = datetime.combine(day, datetime.min.time(), tzinfo=zone).astimezone(UTC)
    row = list(activity(start=start, recovery_id=None))
    row[3] = day  # Local-date column is produced by PostgreSQL in production.
    closes = datetime.combine(day + timedelta(days=2), datetime.min.time(), tzinfo=zone)
    target_start = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=zone)
    assert (closes.astimezone(UTC) - target_start.astimezone(UTC)).total_seconds() == hours * 3600
    for offset, state in ((-1, "window_open"), (0, "missing")):
        result = completeness_report([tuple(row)], zone="Europe/Berlin",
                                     now=closes.astimezone(UTC) + timedelta(seconds=offset))
        gap = result["feedback_completeness"]["gaps"]["training_days"][0]
        assert gap["state"] == state
        assert gap["target_local_date"] == day + timedelta(days=1)
        assert gap["window_closes_at"] == closes.isoformat()


def test_completeness_bounded_gaps_do_not_limit_counts_and_are_deterministic():
    rows = [activity(i, start=datetime(2026, 9, i, 7, tzinfo=UTC),
                     rpe_id=None, recovery_id=None) for i in (1, 2)]
    result = completeness_report(rows, gap_limit=1)["feedback_completeness"]
    assert result == completeness_report(list(reversed(rows)), gap_limit=1)["feedback_completeness"]
    assert result["rpe"]["missing"] == 2
    assert result["next_day_recovery"]["missing"] == 1
    assert result["next_day_recovery"]["window_open"] == 1
    assert len(result["gaps"]["activities"]) == len(result["gaps"]["training_days"]) == 1
    assert result["gaps"]["activity_gaps_truncated"] is True
    assert result["gaps"]["training_day_gaps_truncated"] is True
    assert completeness_report(rows) == completeness_report(rows)
    assert completeness_report(rows, gap_limit=0)["feedback_completeness"]["gaps"]["activities"] == []


@pytest.mark.parametrize("options", [
    {"gap_limit": -1}, {"gap_limit": 101}, {"generated_at": datetime(2026, 9, 1)},
    {"date_to": date(2026, 8, 31)}, {"timezone": "Unknown/Zone"},
])
def test_completeness_invalid_options_fail_before_database_read(monkeypatch, options):
    def forbidden():
        pytest.fail("invalid options must not read database")
    monkeypatch.setattr(calibration_records, "get_conn", forbidden)
    kwargs = dict(user_id="synthetic", date_from=date(2026, 9, 1),
                  date_to=date(2026, 9, 2), timezone="Europe/Moscow")
    kwargs.update(options)
    with pytest.raises((ValueError, KeyError)):
        generate_calibration_records(**kwargs)


@pytest.mark.parametrize("mode", ["calibration", "feedback-completeness"])
def test_cli_read_error_is_json_failure_without_false_zero_counts(monkeypatch, capsys, mode):
    from scripts import calibration_records as cli

    def failed_read():
        raise OperationalError("private connection information")

    monkeypatch.setattr(calibration_records, "get_conn", failed_read)
    monkeypatch.setattr(sys, "argv", ["calibration_records", "--user-id", "synthetic",
                        "--date-from", "2026-09-01", "--date-to", "2026-09-02", "--report", mode])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "read_error", "reason_code": "database_read_failed",
    }


def test_cli_completeness_projection_and_metadata(monkeypatch, capsys):
    from scripts import calibration_records as cli

    monkeypatch.setattr(cli, "generate_calibration_records", lambda **kwargs: completeness_report([]))
    monkeypatch.setattr(sys, "argv", ["calibration_records", "--user-id", "synthetic",
                        "--date-from", "2026-09-01", "--date-to", "2026-09-02",
                        "--report", "feedback-completeness"])
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["date_from"] == "2026-09-01"
    assert result["date_to"] == "2026-09-02"
    assert result["timezone"] == "Europe/Moscow"
    assert result["generated_at"] == "2026-09-03 00:00:00+00:00"
    assert result["contract_version"] == "feedback_completeness_v1"
    assert "records" not in result


@pytest.mark.parametrize("failed_fetch", [1, 2])
def test_completeness_query_failure_never_returns_partial_report(monkeypatch, failed_fetch):
    class Cursor:
        reads = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *args):
            pass

        def fetchall(self):
            self.reads += 1
            if self.reads == failed_fetch:
                raise OperationalError("synthetic read failure")
            return [activity()]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(calibration_records, "get_conn", Connection)
    with pytest.raises(OperationalError, match="synthetic read failure"):
        generate_calibration_records(user_id="synthetic", date_from=date(2026, 9, 1),
                                     date_to=date(2026, 9, 2))
