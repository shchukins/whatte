from datetime import date

import pytest
from pydantic import ValidationError

from backend.services.activity_load_service import ActivityLoadAssessment
from backend.services.training_decision_policy import (
    ActionConstraints, CompletedSession, FutureWindow, PlannedSession,
    TrainingDecisionContext, choose_training_action,
)

TODAY = date(2026, 10, 26)


def session(**changes):
    return PlannedSession(**(dict(
        id="long", day=TODAY, session_type="long_z2", duration_minutes=120,
        priority="supporting", minimum_shortened_minutes=30,
    ) | changes))


def context(**changes):
    return TrainingDecisionContext(**(dict(
        today=TODAY, block_priority="intensity", today_session_id="long",
        week_plan=(session(),), completed=(), available_minutes=50,
        constraints=ActionConstraints(training_allowed=True),
    ) | changes))


def window(**changes):
    return FutureWindow(**(dict(
        id="free", day=date(2026, 10, 29), duration_minutes=120,
        confirmed=True, compatible_session_ids=("long",),
    ) | changes))


def key_session(**changes):
    return session(**(dict(
        id="key", day=date(2026, 10, 28), session_type="intensity",
        duration_minutes=45, priority="key", minimum_shortened_minutes=None,
    ) | changes))


def completed(id="key", included=True):
    return CompletedSession(
        activity_id="ride", confirmed_plan_session_id=id,
        load=ActivityLoadAssessment(included, None if included else "missing_required_power_metrics"),
    )


def test_long_z2_120_to_50_preserves_partial_stimulus_and_loses_duration():
    result = choose_training_action(context())
    option = result.recommendation
    assert option.action == "SHORTEN"
    assert (option.session_type, option.duration_minutes) == ("z2", 50)
    assert option.preserved_stimulus == ("long_z2:partial",)
    assert option.lost_stimulus == ("long_z2:duration_reduced_by_70_minutes",)
    assert "other_sessions_unchanged_no_automatic_compensation" in option.week_consequences


@pytest.mark.parametrize("minutes", [120, 150])
def test_original_plan_fits_keep_without_increasing_duration(minutes):
    result = choose_training_action(context(available_minutes=minutes))
    assert result.recommendation.action == "KEEP"
    assert result.recommendation.duration_minutes == 120


def test_zero_time_skip_when_no_move_is_known():
    result = choose_training_action(context(available_minutes=0))
    assert result.recommendation.action == "SKIP"
    assert result.recommendation.duration_minutes is None
    assert result.recommendation.lost_stimulus


def test_pending_key_work_can_replace_supporting_long_ride_when_explicitly_allowed():
    c = context(
        week_plan=(session(), key_session()),
        constraints=ActionConstraints(training_allowed=True, intensity_allowed=True,
                                      substitute_session_ids=("key",)),
    )
    option = choose_training_action(c).recommendation
    assert option.action == "SUBSTITUTE"
    assert (option.session_id, option.duration_minutes) == ("key", 45)
    assert "propose_move_to_today:key:remove_original_occurrence" in option.week_consequences
    assert option.lost_stimulus == ("long_z2:today_planned_session_omitted",)


def test_completed_key_work_is_not_repeated_even_with_unknown_load():
    key = key_session(day=TODAY)
    c = context(
        week_plan=(session(), key), completed=(completed(included=None),),
        constraints=ActionConstraints(training_allowed=True, intensity_allowed=True,
                                      substitute_session_ids=("key",)),
    )
    result = choose_training_action(c)
    assert result.recommendation.action == "SHORTEN"
    assert "SUBSTITUTE" in result.rejected
    assert any(w.startswith("load_not_covered:ride:") for w in result.warnings)


def test_pending_key_long_ride_is_moved_to_reviewed_free_window():
    result = choose_training_action(context(
        block_priority="long_z2", week_plan=(session(priority="key"),),
        future_windows=(window(),),
    ))
    assert result.recommendation.action == "RESCHEDULE"
    assert result.recommendation.window_id == "free"
    assert result.recommendation.duration_minutes == 120
    assert result.recommendation.lost_stimulus == ()
    assert "propose_move:long:2026-10-29:free" in result.recommendation.week_consequences


def test_zero_time_can_reschedule():
    assert choose_training_action(context(available_minutes=0, future_windows=(window(),))).recommendation.action == "RESCHEDULE"


@pytest.mark.parametrize("changes", [
    {"confirmed": False}, {"duration_minutes": 119},
    {"compatible_session_ids": None}, {"compatible_session_ids": ()},
])
def test_move_requires_confirmed_capacity_and_explicit_compatibility(changes):
    result = choose_training_action(context(future_windows=(window(**changes),)))
    assert "RESCHEDULE" in result.rejected
    assert all(o.action != "RESCHEDULE" for o in result.alternatives)


def test_occupied_date_is_not_a_free_window():
    c = context(week_plan=(session(), key_session(day=window().day)), future_windows=(window(),))
    assert "window:free:occupied_date" in choose_training_action(c).rejected["RESCHEDULE"]


def test_unknown_windows_are_not_invented_and_do_not_prevent_shortening():
    result = choose_training_action(context())
    assert result.recommendation.action == "SHORTEN"
    assert "future_windows_unknown_no_move_assumed" in result.warnings


@pytest.mark.parametrize("changes,reason", [
    ({"block_priority": None}, "block_priority_unknown"),
    ({"week_plan": None}, "today_plan_unknown"),
    ({"week_plan": ()}, "today_plan_unknown"),
    ({"today_session_id": None}, "today_plan_unknown"),
    ({"completed": None}, "completed_work_unknown"),
    ({"constraints": ActionConstraints()}, "training_permission_unknown"),
])
def test_missing_context_returns_uncertainty_and_admissible_alternatives(changes, reason):
    result = choose_training_action(context(**changes))
    assert result.status == "uncertain"
    assert result.recommendation is None
    assert reason in result.missing_context
    assert any(o.action == "SKIP" for o in result.alternatives)


@pytest.mark.parametrize("available", [True, False])
def test_optional_physiology_does_not_decide_workout(available):
    result = choose_training_action(context(physiology_available=available))
    assert result.recommendation.action == "SHORTEN"
    assert bool(result.warnings.count("optional_physiology_unavailable_no_recovery_assumption")) is not available


@pytest.mark.parametrize("included", [False, None])
def test_unknown_or_unsupported_load_is_visible_and_does_not_count_as_completion(included):
    activity = completed(id=None, included=included)
    c = context(completed=(activity,))
    result = choose_training_action(c)
    assert result.recommendation.action == "SHORTEN"
    assert any(w.startswith("load_not_covered:") for w in result.warnings)
    assert "plan_completion_unconfirmed:ride" in result.warnings


def test_training_prohibition_prevents_training_today():
    result = choose_training_action(context(constraints=ActionConstraints(training_allowed=False)))
    assert result.recommendation.action == "SKIP"
    assert all(o.action not in ("KEEP", "SHORTEN", "SUBSTITUTE") for o in result.alternatives)


@pytest.mark.parametrize("permission", [False, None])
def test_intensity_requires_explicit_permission_even_if_it_is_key(permission):
    c = context(
        week_plan=(session(), key_session()),
        constraints=ActionConstraints(training_allowed=True, intensity_allowed=permission,
                                      substitute_session_ids=("key",)),
    )
    assert choose_training_action(c).recommendation.action == "SHORTEN"


def test_all_actions_disallowed_returns_uncertainty_without_forcing_skip():
    c = context(constraints=ActionConstraints(training_allowed=False, allow_skip=False, allow_reschedule=False))
    result = choose_training_action(c)
    assert result.recommendation is None
    assert result.alternatives == ()


def test_completed_today_session_is_not_repeated():
    result = choose_training_action(context(completed=(completed(id="long"),)))
    assert result.recommendation.action == "SKIP"


def test_multiple_substitutes_do_not_create_an_arbitrary_sporting_preference():
    c = context(
        week_plan=(session(), key_session(), key_session(id="key2")),
        constraints=ActionConstraints(training_allowed=True, intensity_allowed=True,
                                      substitute_session_ids=("key", "key2")),
    )
    result = choose_training_action(c)
    assert result.status == "uncertain"
    assert "multiple_substitutes_no_preference" in result.missing_context
    assert sum(o.action == "SUBSTITUTE" for o in result.alternatives) == 2


def test_earliest_reviewed_window_is_reproducible_independent_of_input_order():
    c = context(block_priority="long_z2", week_plan=(session(priority="key"),),
                future_windows=(window(id="later", day=date(2026, 10, 30)), window()))
    before = c.model_dump_json()
    first = choose_training_action(c)
    assert first.recommendation.window_id == "free"
    assert all(choose_training_action(c).model_dump_json() == first.model_dump_json() for _ in range(10))
    assert c.model_dump_json() == before
    reverse = c.model_copy(update={"future_windows": tuple(reversed(c.future_windows))})
    assert choose_training_action(reverse) == first


@pytest.mark.parametrize("changes", [
    {"available_minutes": -1}, {"available_minutes": 1.5}, {"available_minutes": True},
    {"week_plan": (session(), session())},
    {"today_session_id": "missing"},
    {"week_plan": (session(day=date(2026, 11, 2)),)},
    {"future_windows": (window(day=TODAY),)},
    {"future_windows": (window(day=date(2026, 11, 2)),)},
    {"completed": (completed(id="missing"),)},
    {"week_plan": (session(), key_session()), "completed": (completed(),)},
    {"constraints": ActionConstraints(substitute_session_ids=("missing",))},
])
def test_invalid_context_is_rejected(changes):
    with pytest.raises(ValidationError):
        context(**changes)


def test_no_unverified_intensity_shortening_or_invalid_minimum():
    with pytest.raises(ValidationError):
        key_session(minimum_shortened_minutes=30)
    with pytest.raises(ValidationError):
        session(minimum_shortened_minutes=120)


def test_same_120_to_50_can_skip_when_training_and_moves_are_disallowed():
    c = context(constraints=ActionConstraints(training_allowed=False, allow_reschedule=False))
    assert choose_training_action(c).recommendation.action == "SKIP"


def test_completed_session_is_not_reported_as_lost():
    result = choose_training_action(context(completed=(completed(id="long"),)))
    assert result.recommendation.lost_stimulus == ()
    assert "today_session_already_completed_do_not_repeat" in result.selection_reasons


def test_unfinished_key_work_is_not_automatically_prescribed_without_permission():
    c = context(week_plan=(session(), key_session()))
    result = choose_training_action(c)
    assert result.recommendation.action == "SHORTEN"
    assert result.selection_reasons[0] == "pending_key_sessions:key"


def test_missing_intensity_permission_does_not_make_skip_a_supported_preference():
    target = key_session(id="long", day=TODAY)
    result = choose_training_action(context(week_plan=(target,)))
    assert result.status == "uncertain"
    assert "intensity_permission_unknown" in result.missing_context
    assert result.recommendation is None


def test_missing_plan_with_known_completion_references_still_returns_uncertainty():
    result = choose_training_action(context(week_plan=None, completed=(completed(),)))
    assert result.status == "uncertain"
    assert "today_plan_unknown" in result.missing_context
