from datetime import date, datetime, timedelta, timezone

from backend.services.calibration_records import (
    ACTIVITY_QUERY,
    build_calibration_records,
    generate_calibration_records,
)
from backend.services import calibration_records


UTC = timezone.utc


def activity(activity_id=1, start=None, *, metrics_id=11, rpe_id=21,
             recovery_id=31, sport="Ride"):
    start = start or datetime(2026, 9, 1, 7, tzinfo=UTC)
    local_day = start.astimezone(timezone(timedelta(hours=3))).date()
    return (activity_id, sport, start, local_day, metrics_id,
            52.0 if metrics_id else None, 180.0 if metrics_id else None,
            0.8 if metrics_id else None, rpe_id, 4 if rpe_id else None,
            "hard" if rpe_id else None, "v1_extensible" if rpe_id else None,
            start + timedelta(hours=2) if rpe_id else None,
            recovery_id, 3 if recovery_id else None,
            "okay" if recovery_id else None,
            "v1_extensible" if recovery_id else None,
            start + timedelta(days=1) if recovery_id else None)


def snapshot(sid=1, captured=None, computed=None, *, day=date(2026, 9, 1),
             version="v2_signal_composition_response_v1"):
    captured = captured or datetime(2026, 9, 1, 6, tzinfo=UTC)
    computed = computed or captured - timedelta(minutes=5)
    return (sid, day, "daily_readiness_delivery", f"delivery:{sid}",
            version, 72.0, "moderate",
            {"readiness_computed_at": computed.isoformat()}, captured)


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
