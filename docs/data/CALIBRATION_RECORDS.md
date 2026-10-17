# Decision-to-outcome records and evaluation (#77)

## Feedback completeness: first bounded stage of #80

Use the existing CLI from `backend/`, with the normal backend environment:

```bash
python -m scripts.calibration_records --report feedback-completeness --user-id USER --date-from 2026-09-01 --date-to 2026-09-14 --timezone Europe/Moscow --gap-limit 20
```

The inclusive range selects **training local dates**. Timezone defaults to
`WHATTE_TIMEZONE`. Output includes `user_id`, `date_from`, `date_to`, `timezone`,
`generated_at`, `contract_version = feedback_completeness_v1`, and `status = ok`.
The default calibration mode also includes this same summary under
`feedback_completeness`; there is no separate SQL selection or source resolver.
The compact mode omits raw records and the existing descriptive review cases.
Both modes remain repeatable-read/read-only and perform no backfill/recompute.

| Field | Counting contract |
| --- | --- |
| `canonical_workout_count` | All current nondeleted, nonexcluded, nonduplicate canonical activities selected by #77. No snapshot, sport, load, or power eligibility filter. |
| `rpe.usable_current` | Effective compatible RPE 1–10 from the persisted backend resolution and its selected observation. Source disagreement alone does not invalidate the selected score. |
| `rpe.legacy_only` | Compatible effective historical 1–5 feedback, with no current RPE. Kept outside current coverage. |
| `rpe.missing` | No effective current or legacy RPE. |
| `rpe.incompatible` | Present effective observation fails the existing scale/version/resolution checks. Never replaced with a lower-priority or legacy observation to improve coverage. |
| `rpe.compatible_legacy_observation_count` | Compatible 1–5 rows, including legacy stored alongside current RPE. Overlaps other counts; never added to usable current RPE. |
| `rpe.source_disagreement_count` | Persisted disagreement on effective current resolution, including incompatible resolution. Diagnostic count, not an additional partition. |
| `training_day_count` | Unique local training dates, regardless of number of activities. |
| `next_day_recovery.usable` | Compatible date-level subjective `next_day_recovery` 1–5 feedback for D+1, counted once per training day D. No computed recovery, sleep, or physiology substitution. |
| `next_day_recovery.missing` | No D+1 feedback and the observation window is closed. |
| `next_day_recovery.incompatible` | Present D+1 feedback fails #77 score/value/version checks, even when the observation window is still open. |
| `next_day_recovery.window_open` | No D+1 feedback, but its local calendar date has not ended. |

The four RPE categories sum to `canonical_workout_count`; the four recovery
categories sum to `training_day_count`. `rpe.current_coverage` and recovery
`coverage` each expose `numerator`, `denominator`, and `fraction`. Their
denominators include every selected workout / training day, respectively,
including open recovery windows. A zero denominator produces JSON `null` for
the fraction. No quality threshold or research sufficiency gate is applied.

The feedback contract has no existing completeness deadline. This report's
`window_rule = missing_after_start_of_local_D_plus_2` allows the whole D+1 local
date. Absence becomes a missing observation **at local midnight starting D+2**,
inclusive. This is a reporting rule, not a collection/edit cutoff. Already
available feedback counts immediately; incompatible feedback remains
incompatible. D+1 for the final training date is read outside the requested
period. Calendar arithmetic and local midnight handle 23/25-hour DST dates;
no 24-hour elapsed-time approximation is used.

`gaps.activities` and `gaps.training_days` contain up to `--gap-limit` entries
**each** (default 20, permitted 0–100). Full counters are unaffected by the
limit. Each list has a total gap count and a truncation flag. Activity order
is start time then canonical ID; day order is local date. Entries expose the
activity/date, state, source ID (and effective source for RPE), and stable
`reason_code`; recovery entries also expose D+1 and `window_closes_at` with UTC
offset. An empty list with limit zero is not evidence of complete coverage.

| Reason code | Meaning |
| --- | --- |
| `missing_rpe` | No effective RPE in either supported series. |
| `legacy_rpe_only` | Only historical 1–5 is available; current 1–10 is unavailable. |
| `incompatible_scale_or_resolution` | Current RPE resolution or selected observation is incompatible. |
| `incompatible_scale_or_version` | Legacy RPE or recovery score/value/schema is incompatible. |
| `missing_next_day_recovery` | D+1 feedback absent after window closure. |
| `next_day_recovery_window_open` | D+1 feedback absent before window closure. |

A PostgreSQL read/connection failure emits only
`{"status":"read_error","reason_code":"database_read_failed"}` and exits 1;
it never returns successful zero counters or a partial report. Other unexpected
failures also fail the command rather than returning empty observations.

Activity identity/membership, effective RPE, source disagreement, feedback
compatibility/values and all resulting counts/gaps reflect **current mutable
state**. They can change after feedback editing, deduplication or source
resolution updates. `generated_at` is report time, not a historical as-of query.
The Python service accepts a fixed aware `generated_at` for deterministic tests;
it does not rewind mutable data. With unchanged inputs and fixed report time,
the result is deterministic. Immutable decision snapshots do not make mutable
feedback historically reproducible. Never commit personal report output.

This stage measures observation completeness only. It does not prove model
quality, calibration, research readiness or causal relationships. Correlations,
readiness/RPE comparisons, trend summaries, numerical error and over/underestimate
verdicts remain outside this stage of #80, as do UI, notifications, scheduling,
schema changes and general export infrastructure.

## Versioned outcome contract (#132)

Each activity record has `outcome.contract_version = workout_outcome_v1` and
independent `outcome.targets`. The targets have a `unit` and `status`; a missing
target does not make another target or the activity record ineligible.

| Target | Unit and scale | v1 eligibility and missing rule |
| --- | --- | --- |
| `post_workout_rpe` | Activity; effective 1–10 observation (`rpe_1_10` / `rpe_observation_v1`), or historical 1–5 (`v1` / `v1_extensible`) as a separate series | Available only with a compatible stored observation. Missing and incompatible values retain their distinct statuses. A present but inconsistent 1–10 resolution is not replaced by a legacy score. |
| `subjective_result` | Activity; future ordered categories `worse`, `as_expected`, `better`, reported by the athlete relative to their expectation | `not_collected` until a versioned source and collection flow exist. No value is inferred from RPE or load. |
| `completion_state` | Activity; future categories `completed`, `partial`, `not_completed`, relative to an identified plan | `not_collected` until an explicit completion source exists. A Strava activity alone does not establish planned-workout completion. |
| `completion_ratio` | Activity; future fraction of planned workout segments completed, from 0 to 1 inclusive | `no_plan_source`; requires identified planned segments and their completion states. Zero and missing must remain distinct when implemented. |
| `planned_vs_actual_duration` | Activity; future planned and actual duration in seconds, with `actual - planned` seconds | `no_plan_source`; requires an identified planned duration and comparable actual elapsed duration. |
| `planned_vs_actual_load` | Activity; future planned and actual load, with `actual - planned` in the same named metric/version | `no_plan_source`; requires an identified plan and comparable measured load. Current TSS cannot be used as a plan. |
| `next_day_recovery` | Training day; 1–5 from date-level `next_day_recovery` feedback | Available only with compatible feedback on the following local date. Missing/incompatible feedback retains its status. |

Decision eligibility remains independent: the latest eligible same-local-day
snapshot must have been captured and computed before activity start. Recovery
for several activities on one local date is a shared contextual observation,
not several independent outcomes; day-level evaluation counts it once. Feedback
edits change the current read-only report, while append-only decision snapshots
remain historical. `generated_at` is excluded when comparing repeat builds.
This contract does not produce a composite success score or causal verdict.
The five future targets require a separate source/schema decision before their
status can become `available`; their present scales specify the intended
meaning, not an implemented collection path.
`outcome_evaluation` reports per-target availability counts for activity targets
and counts next-day recovery once per training day. Its own
`contract_version` identifies the counting rules. It does not compare scores
with predictions; the existing descriptive `evaluation` remains available.

Run from `backend/` with the usual backend environment configured:

```bash
python -m scripts.calibration_records --user-id USER --date-from 2026-09-01 --date-to 2026-09-14 --timezone Europe/Moscow
```

The CLI emits JSON to stdout and uses a repeatable-read, read-only database
transaction. Dates are inclusive local activity dates in the specified timezone
(default `WHATTE_TIMEZONE`). It returns one record for each current canonical,
nondeleted, nonexcluded Strava activity in the range. No personal output should
be committed to the repository.

## Selection and fields

- `activity_id`, `activity_start_at`, `activity_local_start`, and
  `activity_local_date` identify the current canonical activity.
- `decision` is the latest stored `decision_context_snapshot` for that local
  date with `captured_at < activity_start_at`. Its recorded
  `snapshot_json.readiness_computed_at` must be timezone-aware, no later than
  capture, and strictly earlier than activity start. Equal capture timestamps
  break ties by greatest snapshot ID. All existing event types compete on the
  same timeline. Snapshot ID, event type, reference key, model version, capture
  time, computation time, score, recommendation, age in seconds, and recorded
  signal-family availability are exposed. Missing availability stays unknown.
- `decision_missing_reason` distinguishes no same-day snapshot, only snapshots
  captured at/after start, and pre-start snapshots lacking a valid pre-start
  computation. The current `readiness_daily` row is never substituted.
- A snapshot from a different model version or without score/recommendation is
  retained with `incompatible_or_incomplete_decision` status, not silently
  interpreted as a comparable prediction.
- `load` shows current `activity_metrics` v1 source ID, TSS, and the existing
  cycling power-load inclusion rule. Missing metrics, missing power metrics,
  and unsupported sports remain distinct.
- `post_ride_rpe` uses the effective 1–10 score from
  `activity_rpe_resolution` and its selected `activity_rpe_observation` when
  present. It exposes score, scale/schema versions, selected source,
  observation ID, disagreement, and observed/received/resolved times. A
  missing or inconsistent selected observation is incompatible, not replaced
  with a legacy score. For activities without current RPE, compatible legacy
  `v1` and `v1_extensible` feedback uses the historical 1–5 Whatte scale.
  When both exist, the 1–5 row appears separately in
  `legacy_post_ride_rpe`. No 1–5 value is converted to 1–10.
- `load.intensity_band` uses the existing response-metrics intensity-band
  boundaries on the current activity's intensity factor, only when its
  power-based load is included. This is current activity context, not an
  immutable decision-time feature.
- `next_day_recovery` is date-level feedback for the next local date. Several
  activities on one date may reference the same feedback ID. It is shared
  context, not an isolated outcome for each activity or independent samples
  for summary statistics.

`generated_at` records when the report was produced. Snapshot fields are
append-only evidence. Activity identity, sport, metrics, feedback values, and
load inclusion are current canonical values and can change after deduplication,
feedback edits, or recomputation. Repeated runs over unchanged persisted inputs
produce equivalent records apart from `generated_at`; this is not a historical
as-of export for mutable fields.

## Descriptive evaluation

`evaluation.activity_states` counts every canonical activity by decision,
load, and RPE availability. `rpe_distributions` counts one effective RPE per
activity, grouped by scale, recommendation, sport, load inclusion, current
intensity band, and snapshot physiology availability. Only available decisions
and valid RPE enter these
distributions; 1–5 and 1–10 are separate series.

`evaluation.recovery_days` has one row per local training date. It uses the
earliest activity's eligible pre-activity decision and the single next-local-day
recovery observation. It exposes the number and IDs of activities, included
TSS, included activity count, and whether all, some, or none have measured
load. `recovery_distributions` separates these load-coverage and snapshot
physiology-availability states and counts
only days with both an available decision and compatible recovery feedback;
one recovery response is never counted once per activity. `day_states` retains
the missing and incompatible cases. The CLI's inclusive local date range is
the comparison window; reading the outcome for the final training date may
access the following local date.

`evaluation.review_cases` identifies two activity-level session-effort
patterns only on the 1–10 scale with included power-based load:

- `low_intensity_high_rpe`: existing `recovery` or `endurance` intensity band
  with RPE 8–10, whose labels start at Very hard;
- `high_intensity_low_rpe`: existing `threshold` or `high_intensity` intensity
  band with RPE 1–3, whose labels end at Light.

The day-level `high_intensity_advice_low_next_day_recovery` case requires an
available pre-first-activity `high_intensity` recommendation, fully measured
activity load, and next-day recovery score 1–2 (`exhausted` or `tired`). The
activity count and load are
shown because that recovery cannot be attributed to one activity. These are
cases for manual inspection, not automatic model errors or causal claims.

`evaluation.model_error.status = not_measurable`: the current recommendation
permits a category of training but does not predict a particular RPE or
next-day recovery value. `good_day_probability` is not a validated statistical
probability. No calibrated probability, error rate, overestimation verdict,
or threshold change is derived here. The decision to define a validated
prediction target and baseline belongs to #95. This CLI does not change
readiness, create snapshots, or implement the general export in #79.
