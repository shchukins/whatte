# Decision-to-outcome records and evaluation (#77)

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
