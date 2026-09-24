# Decision-to-outcome records (#77, phase 1)

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
  time, computation time, score, recommendation, and age in seconds are exposed.
- `decision_missing_reason` distinguishes no same-day snapshot, only snapshots
  captured at/after start, and pre-start snapshots lacking a valid pre-start
  computation. The current `readiness_daily` row is never substituted.
- A snapshot from a different model version or without score/recommendation is
  retained with `incompatible_or_incomplete_decision` status, not silently
  interpreted as a comparable prediction.
- `load` shows current `activity_metrics` v1 source ID, TSS, and the existing
  cycling power-load inclusion rule. Missing metrics, missing power metrics,
  and unsupported sports remain distinct.
- `post_ride_rpe` is the current canonical feedback row. Compatible legacy
  `v1` and `v1_extensible` observations use the 1–5 Whatte scale. Other schema
  versions or inconsistent score/value pairs are exposed as incompatible;
  they are never converted into this series.
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

This phase does not infer mismatch or model error from RPE, estimate calibrated
probabilities, or change readiness. Outcomes remain separately inspectable;
targets, denominators, comparison windows, and missing-input strata belong to
#95 before calibration conclusions.
