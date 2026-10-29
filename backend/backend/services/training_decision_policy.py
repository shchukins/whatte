"""Pure, proposal-only time adaptation. No readiness calculation or plan writes."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.services.activity_load_service import ActivityLoadAssessment

RULE_VERSION = "training_time_policy_v1"
SessionType = Literal["long_z2", "z2", "intensity", "recovery"]
Action = Literal["KEEP", "SHORTEN", "SUBSTITUTE", "RESCHEDULE", "SKIP"]


class PolicyInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PlannedSession(PolicyInput):
    id: str = Field(min_length=1)
    day: date
    session_type: SessionType
    duration_minutes: int = Field(gt=0, strict=True)
    priority: Literal["key", "supporting"]
    # Explicit plan-specific minimum, including warm-up/cool-down; never inferred.
    minimum_shortened_minutes: int | None = Field(default=None, gt=0, strict=True)

    @model_validator(mode="after")
    def validate_shortening(self):
        if self.minimum_shortened_minutes is not None:
            if self.minimum_shortened_minutes >= self.duration_minutes:
                raise ValueError("Shortened minimum must be below planned duration")
            if self.session_type not in ("long_z2", "z2", "recovery"):
                raise ValueError("Intensity shortening requires a separate verified template")
        return self


class CompletedSession(PolicyInput):
    activity_id: str = Field(min_length=1)
    # Only caller-confirmed correspondence counts, never a type/TSS match.
    confirmed_plan_session_id: str | None = None
    load: ActivityLoadAssessment


class FutureWindow(PolicyInput):
    id: str = Field(min_length=1)
    day: date
    duration_minutes: int = Field(gt=0, strict=True)
    confirmed: bool = False
    # Caller reviewed neighboring sessions, recovery and weekly budget for these IDs.
    compatible_session_ids: tuple[str, ...] | None = None


class ActionConstraints(PolicyInput):
    training_allowed: bool | None = None
    intensity_allowed: bool | None = None
    allow_shorten: bool = True
    allow_reschedule: bool = True
    allow_skip: bool = True
    # Only full, already supplied pending plan sessions can be substituted.
    substitute_session_ids: tuple[str, ...] = ()


class TrainingDecisionContext(PolicyInput):
    today: date
    block_priority: SessionType | None = None
    today_session_id: str | None = None
    week_plan: tuple[PlannedSession, ...] | None = None
    completed: tuple[CompletedSession, ...] | None = None
    available_minutes: int = Field(ge=0, strict=True)
    future_windows: tuple[FutureWindow, ...] | None = None
    constraints: ActionConstraints = ActionConstraints()
    physiology_available: bool = False

    @model_validator(mode="after")
    def validate_context(self):
        plan = self.week_plan or ()
        ids = [s.id for s in plan]
        if len(ids) != len(set(ids)):
            raise ValueError("Plan session IDs must be unique")
        week = self.today.isocalendar()[:2]
        if any(s.day.isocalendar()[:2] != week for s in plan):
            raise ValueError("Plan must belong to today's ISO week")
        if self.today_session_id is not None and plan:
            matches = [s for s in plan if s.id == self.today_session_id]
            if not matches or matches[0].day != self.today:
                raise ValueError("Today's session must exist on today's date")
        for activity in self.completed or ():
            if plan and activity.confirmed_plan_session_id is not None:
                matched = next((s for s in plan if s.id == activity.confirmed_plan_session_id), None)
                if matched is None or matched.day > self.today:
                    raise ValueError("Confirmed completion must reference a non-future plan session")
        windows = self.future_windows or ()
        if len({w.id for w in windows}) != len(windows):
            raise ValueError("Window IDs must be unique")
        if any(w.day <= self.today or w.day.isocalendar()[:2] != week for w in windows):
            raise ValueError("Windows must be later in the current week")
        if plan and any(id not in ids for id in self.constraints.substitute_session_ids):
            raise ValueError("Substitutes must reference supplied plan sessions")
        return self


class TrainingOption(PolicyInput):
    action: Action
    session_id: str | None = None
    session_type: SessionType | None = None
    duration_minutes: int | None = None
    window_id: str | None = None
    reasons: tuple[str, ...]
    preserved_stimulus: tuple[str, ...]
    lost_stimulus: tuple[str, ...]
    week_consequences: tuple[str, ...]


class TrainingDecision(PolicyInput):
    rule_version: str = RULE_VERSION
    status: Literal["recommended", "uncertain"]
    recommendation: TrainingOption | None
    alternatives: tuple[TrainingOption, ...]
    rejected: dict[Action, tuple[str, ...]]
    selection_reasons: tuple[str, ...]
    missing_context: tuple[str, ...]
    warnings: tuple[str, ...]


def choose_training_action(context: TrainingDecisionContext) -> TrainingDecision:
    """Rank feasible supplied options, not physiological benefit.

    Prefer an unchanged feasible plan; otherwise protect unfinished block-key work.
    Missing goal/history/permission prevents ranking, not fabrication of context.
    Unknown load is disclosed and never converted to rest or stimulus completion.
    """
    c = context
    limits = c.constraints
    plan = c.week_plan or ()
    target = next((s for s in plan if s.id == c.today_session_id), None)
    completed = {a.confirmed_plan_session_id for a in c.completed or ()}
    missing = []
    warnings = []
    if c.block_priority is None:
        missing.append("block_priority_unknown")
    if target is None:
        missing.append("today_plan_unknown")
    if c.completed is None:
        missing.append("completed_work_unknown")
    if limits.training_allowed is None:
        missing.append("training_permission_unknown")
    if (target is not None and target.session_type == "intensity"
            and limits.training_allowed is True and limits.intensity_allowed is None):
        missing.append("intensity_permission_unknown")
    if c.future_windows is None:
        warnings.append("future_windows_unknown_no_move_assumed")
    if not c.physiology_available:
        warnings.append("optional_physiology_unavailable_no_recovery_assumption")
    for a in sorted(c.completed or (), key=lambda a: a.activity_id):
        if a.load.included is not True:
            warnings.append(f"load_not_covered:{a.activity_id}:{a.load.reason or 'unknown'}")
        if a.confirmed_plan_session_id is None:
            warnings.append(f"plan_completion_unconfirmed:{a.activity_id}")

    options = []
    rejected = {}

    def add(
        action: Action, session: PlannedSession | None = None,
        duration: int | None = None, window: FutureWindow | None = None,
        reason: str = "",
    ) -> None:
        stimulus = session.session_type if session else None
        lost = ()
        consequences = []
        if target:
            if action == "SHORTEN":
                lost = (f"{target.session_type}:duration_reduced_by_{target.duration_minutes - duration}_minutes",)
            elif action in ("SUBSTITUTE", "SKIP") and target.id not in completed:
                lost = (f"{target.session_type}:today_planned_session_omitted",)
            if action == "RESCHEDULE":
                consequences.append(f"propose_move:{target.id}:{window.day.isoformat()}:{window.id}")
            if action == "SUBSTITUTE":
                consequences.append(f"propose_move_to_today:{session.id}:remove_original_occurrence")
        consequences.append("other_sessions_unchanged_no_automatic_compensation")
        options.append(TrainingOption(
            action=action, session_id=session.id if session else None,
            session_type="z2" if action == "SHORTEN" and stimulus == "long_z2" else stimulus,
            duration_minutes=duration, window_id=window.id if window else None,
            reasons=(reason,), preserved_stimulus=(f"{stimulus}:partial" if action == "SHORTEN" else stimulus,) if stimulus else (),
            lost_stimulus=lost, week_consequences=tuple(consequences),
        ))

    def permitted(session: PlannedSession) -> bool:
        if limits.training_allowed is not True:
            return False
        if session.session_type == "intensity" and limits.intensity_allowed is not True:
            if limits.intensity_allowed is None and "intensity_permission_unknown" not in warnings:
                warnings.append("intensity_permission_unknown")
            return False
        return True

    if target is not None and target.id not in completed:
        if permitted(target) and target.duration_minutes <= c.available_minutes:
            add("KEEP", target, target.duration_minutes, reason="original_plan_fits_available_time")
        else:
            rejected["KEEP"] = ("original_plan_exceeds_time_or_current_permission",)
        if (limits.allow_shorten and permitted(target) and target.minimum_shortened_minutes is not None
                and target.minimum_shortened_minutes <= c.available_minutes < target.duration_minutes):
            add("SHORTEN", target, c.available_minutes, reason="preserve_partial_planned_stimulus_without_intensity_compensation")
        else:
            rejected["SHORTEN"] = ("shortening_disallowed_or_no_valid_plan_specific_duration",)
        for s in sorted(plan, key=lambda s: s.id):
            if (s.id in limits.substitute_session_ids and s.id != target.id and s.id not in completed
                    and s.day >= c.today and s.priority == "key" and s.session_type == c.block_priority
                    and s.duration_minutes <= c.available_minutes and permitted(s)):
                add("SUBSTITUTE", s, s.duration_minutes, reason="unfinished_block_priority_session_explicitly_allowed_today")
        if not any(o.action == "SUBSTITUTE" for o in options):
            rejected["SUBSTITUTE"] = ("no_permitted_fitting_unfinished_block_key_session",)
        move_rejections = []
        for w in sorted(c.future_windows or (), key=lambda w: (w.day, w.id)):
            # A free date is deliberately conservative: no within-day scheduler here.
            occupied = any(s.day == w.day and s.id not in completed for s in plan)
            problems = []
            if not limits.allow_reschedule:
                problems.append("move_disallowed")
            if not w.confirmed:
                problems.append("unconfirmed")
            if occupied:
                problems.append("occupied_date")
            if target.id not in (w.compatible_session_ids or ()):
                problems.append("week_compatibility_unconfirmed")
            if w.duration_minutes < target.duration_minutes:
                problems.append("insufficient_duration")
            move_rejections.extend(f"window:{w.id}:{problem}" for problem in problems)
            if not problems:
                add("RESCHEDULE", target, target.duration_minutes, w,
                    reason="confirmed_free_window_with_explicit_week_compatibility")
        if not any(o.action == "RESCHEDULE" for o in options):
            rejected["RESCHEDULE"] = tuple(move_rejections) or ("no_confirmed_free_compatible_window_or_move_disallowed",)
    else:
        for action in ("KEEP", "SHORTEN", "SUBSTITUTE", "RESCHEDULE"):
            rejected[action] = ("today_plan_missing_or_already_completed",)
    if limits.allow_skip:
        add("SKIP", reason="no_training_today_no_compensation_debt")
    else:
        rejected["SKIP"] = ("skip_disallowed",)

    recommendation = None
    selection_reasons = []
    pending = sorted(s.id for s in plan if s.id not in completed and s.priority == "key")
    selection_reasons.append(
        "pending_key_sessions_unknown" if c.completed is None or c.week_plan is None
        else "pending_key_sessions:" + ",".join(pending)
    )
    if not missing:
        if target.id in completed:
            order = ("SKIP",)
            selection_reasons.append("today_session_already_completed_do_not_repeat")
        elif limits.training_allowed is False:
            # Today's prohibition does not assert future tolerance: only reviewed windows qualify.
            order = ("RESCHEDULE", "SKIP")
            selection_reasons.append("training_today_prohibited_only_reviewed_move_or_skip")
        elif target.priority == "key" and target.session_type == c.block_priority:
            order = ("KEEP", "RESCHEDULE", "SHORTEN", "SUBSTITUTE", "SKIP")
            selection_reasons.append("protect_full_unfinished_block_key_stimulus_before_partial_work")
        else:
            order = ("KEEP", "SUBSTITUTE", "SHORTEN", "RESCHEDULE", "SKIP")
            selection_reasons.append("keep_fitting_plan_else_unfinished_block_key_before_supporting_work")
        for action in order:
            candidates = [o for o in options if o.action == action]
            if candidates:
                # Earliest reviewed move is a logistical tie-break; distinct substitute
                # stimuli/templates have no justified preference in this first policy.
                if action == "SUBSTITUTE" and len(candidates) > 1:
                    missing.append("multiple_substitutes_no_preference")
                else:
                    recommendation = candidates[0]
                break
    if recommendation is None and not missing:
        missing.append("no_admissible_action")
    return TrainingDecision(
        status="recommended" if recommendation else "uncertain", recommendation=recommendation,
        alternatives=tuple(o for o in options if o != recommendation), rejected=rejected,
        selection_reasons=tuple(selection_reasons),
        missing_context=tuple(missing), warnings=tuple(warnings),
    )
