# Wearable-independent Morning Loop pilot

## Purpose

This report measures the reliability and observed use of the deterministic
morning loop for GitHub issue #108. It reads stored backend state and does not
recompute readiness or change model parameters.

## Scope and command

The inclusive interval uses `WHATTE_TIMEZONE` unless a timezone is passed. The
unit for morning metrics is one local calendar day. The unit for post-workout
RPE is one canonical activity with a successfully stored RPE prompt delivery.

Run from `backend/`:

```bash
python -m scripts.pilot_report \
  --user-id sergey \
  --date-from 2026-09-01 \
  --date-to 2026-09-14
```

The command writes JSON to stdout and performs only `SELECT` queries.

For a human-readable report, keep the same interval and add:

```bash
python -m scripts.pilot_report \
  --user-id sergey \
  --date-from 2026-09-01 \
  --date-to 2026-09-14 \
  --format markdown
```

JSON remains the default and existing metric names retain their original
definitions. Markdown is a rendering of the same in-memory report; it does not
run a second query or change stored data.

## Training-load coverage (#123)

The report adds a read-only `load_coverage` section to JSON and Markdown. It
assesses stored Strava activities for each report-local day using the current
`activity_metrics` `v1` row and the same `resolve_activity_load` rule used by
daily load aggregation. It is a current assessment, not a snapshot of what was
included when a historical readiness decision was delivered. The coverage
query makes no provider requests and does not recompute or write load.

`canonical_activities` excludes deleted records, linked duplicates, and
user-excluded records. Those categories are counted separately in
`excluded_records`, with priority deleted, duplicate, then user-excluded if a
record has more than one flag. For canonical activities, `included` means the
resolver accepts the activity; `not_included` means it rejects an activity with
an available metrics row; and `unknown_assessment` means the `v1` metrics row
is absent. These three counts sum to `canonical_activities`. The activity list
contains both known not-included and unknown assessments, with distinct reasons:
`unsupported_sport`, `missing_required_power_metrics`, or
`unavailable_metrics_record`.

The daily state distinguishes `no_recorded_activity`, `excluded_only`,
`supported_measured_load`, `recorded_unmodeled_activity`,
`unknown_assessment`, and `mixed_coverage`. A day with an unsupported or unknown
activity is not reported as measured zero load or proof of rest. Activities
without a stored start time cannot be assigned to a local report day. Coverage
does not change the existing pilot metrics, their denominators, daily-load
aggregation, readiness, or notification behavior.

## Metric definitions

| Metric | Numerator | Denominator | Stored source |
|---|---|---|---|
| Valid morning recommendation | Days with current-version readiness and a deterministic recommendation | All local days | `readiness_daily` |
| Valid recommendation without physiology | Valid days where physiology availability is false | Valid recommendation days | `readiness_daily.explanation_json.signal_families` |
| Morning recovery response | Eligible days with recovery feedback | Days after a stored training day | `daily_training_load`, `activity_subjective_feedback` |
| Post-workout RPE completion | Prompted canonical activities with RPE | Canonical activities with a successful RPE prompt | `activity_delivery_log`, `activity_subjective_feedback` |
| Signal-family distribution | Days where each family is available or used | Counts over the interval | `readiness_daily.explanation_json` |
| Stale/missing required training input | Days without a same-local-day training source snapshot | All local days | `readiness_daily.explanation_json.source_timestamps` |
| Recommendation change after check-in | Daily comparisons whose score or recommendation category changed | Days with both a first-before and last-after snapshot | `decision_context_snapshot` |
| Readiness score change after check-in | Daily comparisons with a changed score | Days where both snapshots contain a score | `decision_context_snapshot` |
| Recommendation category change after check-in | Daily comparisons with a changed category | Days where both snapshots contain a category | `decision_context_snapshot` |
| Ingestion failures | Failed/error ingest jobs | Count | `strava_activity_ingest_job` |
| Delivery failures | Failed readiness deliveries and recovery prompts | Count | notification and prompt logs |

Every rate includes its numerator and denominator. A zero denominator produces
`null`, not zero percent.

The original combined recommendation-change metric remains backward compatible.
The additive score and category metrics make score-only changes distinct from
changes that cross a decision threshold. Each daily row includes the signed
score delta and the before/after category transition.

## Post-workout RPE funnel

The funnel separates delivery coverage from participation:

1. `eligible_canonical_activities` counts non-excluded canonical activities for
   which eligibility can still be determined. A stored delivery proves the
   activity was eligible when claimed. An activity with no delivery and no RPE
   is still eligible under the current rule.
2. `successfully_prompted` counts `activity_delivery_log` rows with
   `delivery_status = 'sent'` for `post_ride_rpe`.
3. `prompted_responses` counts those successfully prompted activities with a
   stored canonical RPE. This is the numerator of the existing completion rate.
4. `unanswered_prompts` is successful prompts without a stored response.
5. `not_successfully_prompted` is known-eligible activities without a successful
   prompt. `failed_or_incomplete_prompts` identifies retained non-sent delivery
   rows, while `missing_prompt_records` identifies known-eligible activities
   with no delivery row. The ledger still cannot recover deleted or otherwise
   unrecorded attempts.
6. `recorded_responses` includes all canonical RPE responses. A response without
   a delivery row is reported separately as `unprompted_responses`; because the
   time at which the response first existed is not stored, its historical prompt
   eligibility remains `unknown` rather than being reconstructed.

All activity dates use the pilot timezone. Excluded duplicates are omitted, so
one physical session contributes at most one canonical activity.

The funnel is observed when the report query runs. Prompt state comes from the
current canonical delivery ledger and response state from the current canonical
feedback row; neither table is an event history. Therefore the report describes
stored coverage and participation as of query time, not the exact sequence of
every historical attempt.

## Historical decision snapshots (#78 production slice)

`decision_context_snapshot` stores append-only evidence after an accepted daily
readiness delivery and immediately before and after a recovery check-in. It
stores the computed decision, model version, explanation, source timestamps,
and signal availability. It does not participate in model calculations.
Identical retries are idempotent by a SHA-256 fingerprint of decision state.

The report presents three states separately:

- the latest daily delivery snapshot and its capture time;
- a daily check-in comparison from the first `recovery_checkin_before` snapshot
  to the last `recovery_checkin_after` snapshot and both capture times;
- current persisted `readiness_daily` state and its update time.

The daily comparison does not claim that multiple individual check-ins are
paired. A delivery snapshot is evidence of captured decision state around the
delivery path, not proof of the exact rendered Telegram content. Missing
historical snapshots remain missing; current readiness is never substituted.

Snapshots begin after migration `010_decision_context_snapshot.sql`. Earlier
before/after states cannot be reconstructed reliably because `readiness_daily`
and feedback upserts retain canonical current state.

## Synthetic Markdown excerpt

The following illustrates the format only; it is not production data:

```markdown
## Post-workout RPE funnel

- Eligible canonical activities: 3
- Historical eligibility unknown: 1
- Successfully prompted: 2
- Failed or incomplete prompt records: 0
- Missing prompt records: 1
- Not successfully prompted: 1
- Recorded responses: 2
- Prompted responses: 1
- Unanswered prompts: 1
- Unprompted responses: 1

| Date | Score | Recommendation | Physiology | RPE eligible/sent/answered | Score delta | Category transition |
|---|---:|---|---|---:|---:|---|
| 2026-09-01 | 70.0 | moderate | not available | 3/2/1 | 10.0 | endurance -> moderate |
```

## Explicit limitations

- Duplicate delivery attempts are not historically countable. Lifecycle tables
  keep canonical state instead of every attempt. The report returns
  `not_measurable` rather than an invented zero rate.
- API and Web share the backend readiness query, but historical rendered output
  is not recorded. Full presentation consistency is `not_measurable`.
- Processing, decision, and presentation failures lack a durable relational
  event store. Their report values are `null`; Loki remains operational evidence.
- Fourteen rows satisfy only interval length. Conclusions still require review
  of missing data and actual participation.
