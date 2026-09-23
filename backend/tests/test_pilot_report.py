from datetime import date, datetime, timezone

from backend.services import pilot_report
from backend.services.pilot_report import (
    LOAD_COVERAGE_QUERY,
    PILOT_QUERY,
    build_load_coverage,
    build_pilot_report,
    generate_pilot_report,
    render_pilot_report_markdown,
)


def _coverage_row(
    day, activity_id, sport="Ride", *, local_start=None, duration_s=3600,
    deleted=False, excluded=False, duplicate_of=None, has_metrics=True,
    tss=50.0, normalized_power=180.0, intensity_factor=0.8,
):
    return (
        day, activity_id, sport, local_start or datetime.combine(day, datetime.min.time()),
        duration_s, deleted, excluded, duplicate_of, has_metrics, tss,
        normalized_power, intensity_factor,
    )


def test_load_coverage_classifies_mixed_activity_and_exclusions():
    first = date(2026, 9, 1)
    second = date(2026, 9, 2)
    rows = [
        _coverage_row(first, 1),
        _coverage_row(first, 2, "Run"),
        _coverage_row(first, 3, tss=None),
        _coverage_row(first, 4, has_metrics=False, tss=None),
        _coverage_row(first, 5, deleted=True),
        _coverage_row(first, 6, excluded=True, duplicate_of=1),
        _coverage_row(first, 7, excluded=True),
        _coverage_row(second, 8, has_metrics=False, tss=None),
    ]

    coverage = build_load_coverage(date_from=first, date_to=date(2026, 9, 3), rows=rows)
    mixed, unknown, empty = coverage["days"]
    assert (mixed["canonical_activities"], mixed["included"],
            mixed["not_included"], mixed["unknown_assessment"]) == (4, 1, 2, 1)
    assert mixed["excluded_records"] == {
        "deleted": 1, "duplicate": 1, "user_excluded": 1,
    }
    assert mixed["coverage_state"] == "mixed_coverage"
    assert [activity["reason"] for activity in mixed["not_included_activities"]] == [
        "unsupported_sport", "missing_required_power_metrics",
        "unavailable_metrics_record",
    ]
    assert unknown["coverage_state"] == "unknown_assessment"
    assert empty["coverage_state"] == "no_recorded_activity"


def test_load_coverage_preserves_local_day_and_zero_tss_resolver_semantics():
    day = date(2026, 9, 2)
    local_start = datetime(2026, 9, 2, 1, 30)
    coverage = build_load_coverage(
        date_from=day, date_to=day,
        rows=[_coverage_row(day, 1, local_start=local_start, tss=0.0)],
    )
    assert coverage["days"][0]["included"] == 1
    assert coverage["days"][0]["coverage_state"] == "supported_measured_load"
    assert "at time zone %s" in LOAD_COVERAGE_QUERY
    assert "m.version = 'v1'" in LOAD_COVERAGE_QUERY
    assert "m.user_id = r.user_id" in LOAD_COVERAGE_QUERY


def test_load_coverage_markdown_explains_unknown_and_historical_limit():
    day = date(2026, 9, 1)
    report = build_pilot_report(
        user_id="user-1", date_from=day, date_to=day,
        timezone="Europe/Moscow", rows=[_row(day)],
    )
    report["load_coverage"] = build_load_coverage(
        date_from=day, date_to=day,
        rows=[_coverage_row(day, 9, "Run|Trail", has_metrics=False)],
    )
    markdown = render_pilot_report_markdown(report)
    assert "## Training-load coverage" in markdown
    assert "Run\\|Trail" in markdown
    assert "unavailable_metrics_record" in markdown
    assert "not evidence of load inclusion when a historical decision was made" in markdown
    assert markdown.index("## Rates") > markdown.index("## Training-load coverage")


def test_generate_report_reads_coverage_without_changing_pilot_rows(monkeypatch):
    day = date(2026, 9, 1)
    pilot_rows = [_row(day)]
    coverage_rows = [_coverage_row(day, 1)]

    class Cursor:
        def __init__(self):
            self.queries = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, params):
            self.queries.append((query, params))

        def fetchall(self):
            return pilot_rows if len(self.queries) == 1 else coverage_rows

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return self.cursor_instance

    connection = Connection()
    monkeypatch.setattr(pilot_report, "get_conn", lambda: connection)
    report = generate_pilot_report(
        user_id="user-1", date_from=day, date_to=day,
        timezone="Europe/Moscow",
    )
    assert report["days"][0]["activities"] == 1
    assert report["load_coverage"]["days"][0]["included"] == 1
    assert [query for query, _ in connection.cursor_instance.queries] == [
        PILOT_QUERY, LOAD_COVERAGE_QUERY,
    ]
    assert connection.cursor_instance.queries[1][1] == (
        "Europe/Moscow", "Europe/Moscow", "user-1", "Europe/Moscow", day, day,
    )


def _row(day: date, **overrides):
    values = {
        "readiness_score": 70.0,
        "good_day_probability": 0.7,
        "status_text": "Good",
        "explanation": {"source_timestamps": {"training_source_at": day.isoformat()},
                        "signal_families": {
            "load": {"availability": "available", "used": False},
            "freshness": {"availability": "available", "used": True},
            "response": {"availability": "unavailable", "used": False},
            "feeling": {"availability": "unavailable", "used": False},
            "physiology": {"availability": "unavailable", "used": False},
        }},
        "computed_at": datetime(2026, 9, 1, 5, tzinfo=timezone.utc),
        "notification_status": "sent", "previous_activities": 1,
        "previous_tss": 50.0, "prompt_status": "sent",
        "recovery_feedback": True, "activities": 1, "rpe_eligible": 1,
        "rpe_eligibility_unknown": 0, "rpe_prompts": 1,
        "rpe_failed_or_incomplete_prompts": 0, "rpe_missing_prompts": 0,
        "rpe_prompted_responses": 1, "rpe_recorded_responses": 1,
        "rpe_unprompted_responses": 0,
        "before": {"snapshot": {
            "readiness_score": 60.0, "recommendation": "moderate",
        }, "captured_at": "2026-09-01T06:00:00+00:00"},
        "after": {"snapshot": {
            "readiness_score": 70.0, "recommendation": "moderate",
        }, "captured_at": "2026-09-01T06:05:00+00:00"},
        "delivery": {"snapshot": {"readiness_score": 70.0},
                     "captured_at": "2026-09-01T05:00:00+00:00"},
        "ingest_failures": 0,
        "delivery_failures": 0,
    }
    values.update(overrides)
    return (
        day, values["readiness_score"], values["good_day_probability"],
        values["status_text"], values["explanation"], values["computed_at"],
        values["notification_status"], values["previous_activities"],
        values["previous_tss"], values["prompt_status"],
        values["recovery_feedback"], values["activities"],
        values["rpe_eligible"], values["rpe_eligibility_unknown"],
        values["rpe_prompts"],
        values["rpe_failed_or_incomplete_prompts"],
        values["rpe_missing_prompts"],
        values["rpe_prompted_responses"], values["rpe_recorded_responses"],
        values["rpe_unprompted_responses"], values["before"], values["after"],
        values["delivery"], values["ingest_failures"], values["delivery_failures"],
    )


def test_report_uses_explicit_denominators_and_signal_availability():
    rows = [
        _row(date(2026, 9, 1)),
        _row(date(2026, 9, 2), readiness_score=None, good_day_probability=None,
             status_text=None, explanation={}, previous_activities=0,
             previous_tss=0, prompt_status=None, recovery_feedback=False,
             activities=0, rpe_eligible=0, rpe_prompts=0,
             rpe_prompted_responses=0, rpe_recorded_responses=0, before=None,
             after=None, delivery=None, ingest_failures=1, delivery_failures=1),
    ]
    report = build_pilot_report(user_id="user-1", date_from=date(2026, 9, 1),
                                date_to=date(2026, 9, 2), timezone="Europe/Moscow",
                                rows=rows)
    metrics = report["metrics"]
    assert metrics["valid_morning_recommendations"] == {
        "numerator": 1, "denominator": 2, "rate": 0.5,
    }
    assert metrics["valid_recommendations_without_physiology"]["rate"] == 1.0
    assert metrics["morning_recovery_response"]["rate"] == 1.0
    assert metrics["post_workout_rpe_completion"]["rate"] == 1.0
    assert metrics["signal_family_distribution"]["freshness"] == {
        "available_days": 1, "used_days": 1,
    }
    assert metrics["recommendation_changes_after_checkin"]["rate"] == 1.0
    assert metrics["stale_or_missing_required_training_input"]["rate"] == 0.5
    assert metrics["failures"]["ingestion"] == 1
    assert metrics["failures"]["delivery"] == 1


def test_report_does_not_claim_rates_without_denominators():
    row = _row(date(2026, 9, 1), readiness_score=None, previous_activities=0,
               previous_tss=0, recovery_feedback=False, rpe_eligible=0,
               rpe_prompts=0, rpe_prompted_responses=0,
               rpe_recorded_responses=0, before=None, after=None, delivery=None)
    report = build_pilot_report(user_id="user-1", date_from=date(2026, 9, 1),
                                date_to=date(2026, 9, 1), timezone="Europe/Moscow",
                                rows=[row])
    metrics = report["metrics"]
    assert metrics["valid_recommendations_without_physiology"]["rate"] is None
    assert metrics["morning_recovery_response"]["rate"] is None
    assert metrics["post_workout_rpe_completion"]["rate"] is None
    assert metrics["recommendation_changes_after_checkin"]["rate"] is None
    assert report["days"][0]["decision_states"]["delivery"]["snapshot"] is None
    assert report["days"][0]["decision_states"]["current_persisted"][
        "readiness_score"
    ] is None


def test_query_uses_first_before_and_last_after_for_daily_comparison():
    assert "order by captured_at\n" in PILOT_QUERY
    assert "order by captured_at desc\n" in PILOT_QUERY
    assert "filter (where event_type = 'recovery_checkin_before')" in PILOT_QUERY
    assert "filter (where event_type = 'recovery_checkin_after')" in PILOT_QUERY


def test_report_separates_score_and_category_changes():
    rows = [
        _row(date(2026, 9, 1)),
        _row(
            date(2026, 9, 2),
            before={"readiness_score": 70.0, "recommendation": "moderate"},
            after={"readiness_score": 70.0, "recommendation": "high_intensity"},
        ),
        _row(
            date(2026, 9, 3),
            before={"readiness_score": 70.0, "recommendation": "moderate"},
            after={"readiness_score": 70.0, "recommendation": "moderate"},
        ),
    ]
    report = build_pilot_report(
        user_id="user-1",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 3),
        timezone="Europe/Moscow",
        rows=rows,
    )

    assert report["metrics"]["recommendation_changes_after_checkin"] == {
        "numerator": 2, "denominator": 3, "rate": 0.6667,
    }
    assert report["metrics"]["readiness_score_changes_after_checkin"] == {
        "numerator": 1, "denominator": 3, "rate": 0.3333,
    }
    assert report["metrics"]["recommendation_category_changes_after_checkin"] == {
        "numerator": 1, "denominator": 3, "rate": 0.3333,
    }
    assert report["days"][0]["checkin_score_delta"] == 10.0
    assert report["days"][1]["checkin_category_transition"] == {
        "from": "moderate", "to": "high_intensity",
    }
    assert report["days"][2]["checkin_decision_changed"] is False


def test_report_uses_field_specific_denominators_for_incomplete_snapshots():
    rows = [
        _row(
            date(2026, 9, 1),
            before={"readiness_score": 60.0},
            after={"readiness_score": 65.0},
        ),
        _row(
            date(2026, 9, 2),
            before={"recommendation": "endurance"},
            after={"recommendation": "moderate"},
        ),
        _row(date(2026, 9, 3), before={"status_text": "Good"}, after={}),
    ]
    report = build_pilot_report(
        user_id="user-1",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 3),
        timezone="Europe/Moscow",
        rows=rows,
    )

    assert report["metrics"]["recommendation_changes_after_checkin"] == {
        "numerator": 2, "denominator": 2, "rate": 1.0,
    }
    assert report["metrics"]["readiness_score_changes_after_checkin"] == {
        "numerator": 1, "denominator": 1, "rate": 1.0,
    }
    assert report["metrics"]["recommendation_category_changes_after_checkin"] == {
        "numerator": 1, "denominator": 1, "rate": 1.0,
    }
    assert report["days"][0]["checkin_category_transition"] is None
    assert report["days"][2]["checkin_decision_changed"] is None


def test_report_exposes_rpe_funnel_and_unknown_unprompted_feedback():
    row = _row(
        date(2026, 9, 1),
        activities=4,
        rpe_eligible=3,
        rpe_eligibility_unknown=1,
        rpe_prompts=2,
        rpe_failed_or_incomplete_prompts=0,
        rpe_missing_prompts=1,
        rpe_prompted_responses=1,
        rpe_recorded_responses=2,
        rpe_unprompted_responses=1,
    )
    report = build_pilot_report(
        user_id="user-1",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 1),
        timezone="Europe/Moscow",
        rows=[row],
    )

    assert report["metrics"]["post_workout_rpe_funnel"] == {
        "eligible_canonical_activities": 3,
        "eligibility_unknown": 1,
        "successfully_prompted": 2,
        "failed_or_incomplete_prompts": 0,
        "missing_prompt_records": 1,
        "not_successfully_prompted": 1,
        "recorded_responses": 2,
        "prompted_responses": 1,
        "unanswered_prompts": 1,
        "unprompted_responses": 1,
    }
    assert report["metrics"]["post_workout_rpe_completion"]["rate"] == 0.5


def test_report_keeps_snapshots_and_current_state_separate():
    report = build_pilot_report(
        user_id="user-1",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 1),
        timezone="Europe/Moscow",
        rows=[_row(date(2026, 9, 1))],
    )
    states = report["days"][0]["decision_states"]

    assert states["delivery"]["captured_at"] == "2026-09-01T05:00:00+00:00"
    assert states["checkin_daily_comparison"]["semantics"] == (
        "first_before_to_last_after_not_individually_paired"
    )
    assert states["current_persisted"]["readiness_score"] == 70.0
    assert states["delivery"]["snapshot"] is not states["current_persisted"]


def test_markdown_output_includes_scope_funnel_daily_rows_and_limitations():
    report = build_pilot_report(
        user_id="user-1",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 1),
        timezone="Europe/Moscow",
        rows=[_row(date(2026, 9, 1))],
    )

    markdown = render_pilot_report_markdown(report)

    assert "# Morning Loop pilot report" in markdown
    assert "Timezone: Europe/Moscow" in markdown
    assert "## Post-workout RPE funnel" in markdown
    assert "| 2026-09-01 | 70.0 | moderate | not available |" in markdown
    assert "does not claim individual check-ins are paired" in markdown
