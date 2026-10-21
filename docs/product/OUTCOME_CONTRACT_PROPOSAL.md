# Workout outcome contract proposal (#132)

> Priority update, 2026-10-21: further work on this research/calibration
> direction is **paused** under [current priorities](../ai/CURRENT_PRIORITIES.md).
> This document preserves its technical contract, dated evidence and acceptance
> gates; internal “next steps” apply only if the workstream is explicitly resumed.
> This does not disable existing runtime or change GitHub issue status.
> It is not a prerequisite for the [training decision MVP](TRAINING_DECISION_MVP.md).

Version `workout_outcome_v1` extends the existing read-only decision-to-outcome
report. One activity record is emitted for each current canonical, nondeleted,
nonexcluded Strava activity. The record contains independent targets; absence of
one target never invalidates another. Next-day recovery is a training-day target
referenced by each activity on that date and counted once in day-level summaries.

The first implementation exposes observed RPE and next-day recovery from the
existing sources. Subjective result, completion state/ratio, and planned versus
actual duration/load remain explicitly unavailable until their source and
eligibility contracts exist. A recorded activity does not prove that a plan was
completed, and Strava metrics do not supply a planned value.

RPE keeps the observed scale and source version. Historical 1-5 and current
1-10 observations are separate series; the current resolved 1-10 observation
takes precedence without transforming the legacy value. Inconsistent current
resolution is incompatible even when a legacy observation exists.

The relevant decision is the latest valid snapshot before the activity start on
the same local date. The next-day recovery target uses the following local
calendar date and is contextual for all activities on the training date. This
contract describes associations, not causal effects or a success score. It is
read-only and does not change readiness or production decisions.
