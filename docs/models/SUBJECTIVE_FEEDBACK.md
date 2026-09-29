# Subjective Feedback

## 1. Purpose

`activity_subjective_feedback` stores lightweight subjective feedback that acts as a user-reported ground truth layer.

It captures how training felt and how recovery felt. In
`v2_signal_composition_response_v1`, date-level next-day recovery is an explicit
current-day `feeling` input. Post-ride RPE remains an observed outcome consumed
through baseline-relative versioned response metrics; raw RPE is never mapped
directly to readiness.

Current scope:

- post-ride RPE feedback
- next-day recovery feedback
- Telegram- and Web Today-based low-friction collection
- automatic scheduled next-day recovery prompt orchestration
- normalized queryable fields plus extensible payloads
- historical context snapshots for later calibration work

This is an evaluation and calibration dataset layer, not an ML decision layer.

---

## 2. Why it exists

Whatte already stores deterministic inputs and derived state:

- raw physiological inputs
- daily training load
- recovery state
- readiness state
- recommendation output

What those layers do not provide is user-reported outcome data.

Subjective feedback fills that gap by recording:

- how hard a session felt immediately after training
- how recovered the athlete felt the next day
- what readiness and recommendation looked like at feedback time

This supports future work in:

- readiness validation
- recommendation validation
- prediction vs outcome calibration
- adaptation modeling
- ML dataset generation for offline research

Important:

- no model adaptation is implemented here
- feedback changes readiness only through the documented deterministic
  `feeling` and baseline-relative `response` formulas
- deterministic calculations stay separate from the feedback layer

---

## 3. Feedback types

### 3.1 `post_ride_rpe`

Current RPE observations are in `activity_rpe_observation`, keyed by
`(canonical_activity_id, source)`. Each row retains its 1-10 score,
`rpe_1_10` scale version, `rpe_observation_v1` schema version, observed
time when known, received time, and raw
source payload. `activity_rpe_resolution` persists the effective score,
chosen source, and disagreement flag. Strava wins when present; Telegram is
the fallback, then Web. Missing RPE remains unavailable. A Strava detailed
activity's `perceived_exertion` is imported when present; a once-daily bounded
14-day check finds late Strava entries without depending on update webhooks.
Strava provides no guaranteed RPE edit timestamp, so its `observed_at` is
null and `received_at` records import time.

Telegram now emits `rpe10:{activity_id}:{score}` callbacks and Web Today
accepts 1-10. Old `rpe:{activity_id}:{score}` callbacks are recognized as
1-5 and rejected with an explicit re-entry instruction. Historical 1-5 rows
below remain unchanged and cannot enter the new response baseline.

The Telegram RPE prompt keeps the activity summary, asks for perceived
exertion on a 1-10 scale, and gives 1/5/10 anchors. Its numeric-only inline
buttons occupy two rows of five. Web Today uses one horizontal numeric scale
with the effective source and any conflicting source scores visible.

The 1-10 labels are: 1 Very easy, 2 Easy, 3 Light, 4 Comfortable,
5 Moderate, 6 Steady, 7 Hard, 8 Very hard, 9 Extremely hard, 10 Maximal.
Labels aid entry only; the integer score is the deterministic input.

Historical 1-5 contract:

Purpose:

- capture immediate perceived exertion for a completed activity

Semantics:

- activity-level feedback
- linked to `strava_activity_id`
- one canonical row per `(strava_activity_id, feedback_type)`

Scale:

- `1` → `very_easy`
- `2` → `easy`
- `3` → `moderate`
- `4` → `hard`
- `5` → `very_hard`

Telegram labels:

- `😌 Very easy`
- `🙂 Easy`
- `😐 Moderate`
- `🥵 Hard`
- `☠️ Very hard`

These labels describe only the historical series.

Callback format:

- `rpe:{activity_id}:{score}`

### 3.2 `next_day_recovery`

Purpose:

- capture delayed recovery state after the previous training day

Semantics:

- date-level feedback
- linked to `user_id + activity_date`
- `strava_activity_id` is intentionally nullable
- one canonical row per `(user_id, activity_date, feedback_type)` when `strava_activity_id is null`

Scale:

- `1` → `exhausted`
- `2` → `tired`
- `3` → `okay`
- `4` → `fresh`
- `5` → `very_fresh`

Telegram labels:

- `😴 Exhausted`
- `😐 Tired`
- `🙂 Okay`
- `⚡ Fresh`
- `🚀 Very fresh`

Web Today uses the same canonical score/value mapping and triggers the same
backend readiness recomputation after the idempotent date-level upsert.

Callback format:

- `recovery:{user_id}:{target_date}:{score}`

Why delayed recovery matters:

- immediate RPE reflects session perception
- next-day recovery reflects accumulated effect of the previous load
- for readiness validation, delayed recovery is often the more informative target

---

## 4. Data model

Table:

- `activity_subjective_feedback`

Core fields:

- `user_id`
- `strava_activity_id`
- `activity_date`
- `feedback_type`
- `feedback_value`
- `feedback_score`
- `source`

Active feedback sources:

- `telegram` for Telegram callback collection
- `web` for authenticated Web Today native forms

Extensible fields:

- `feedback_schema_version`
- `feedback_payload`
- `context_json`

Operational fields:

- `created_at`
- `updated_at`

Prompt delivery table:

- `subjective_feedback_prompt_log`

Prompt delivery fields:

- `user_id`
- `prompt_type`
- `target_date`
- `sent_at`
- `source`
- `delivery_status`
- `telegram_message_id`
- `created_at`
- `updated_at`

Why a separate prompt log exists:

- delivery orchestration has a different lifecycle than the feedback answer row
- prompt idempotency must be persisted even before a callback arrives
- callback rows should remain outcome data, while prompt rows remain transport/orchestration data

### 4.1 Activity-level vs date-level semantics

Activity-level feedback:

- uses `strava_activity_id`
- may optionally also carry `activity_date`
- currently used by `post_ride_rpe`

Date-level feedback:

- uses `activity_date` as the canonical target date
- leaves `strava_activity_id = null`
- currently used by `next_day_recovery`

Nullable `strava_activity_id` does not mean “missing linkage by mistake”.
It means the feedback is about a day-level recovery state rather than one exact activity.

### 4.2 Partial unique indexes

The table supports two idempotency rules:

- activity-level uniqueness: unique (`strava_activity_id`, `feedback_type`) where `strava_activity_id is not null`
- date-level uniqueness: unique (`user_id`, `activity_date`, `feedback_type`) where `strava_activity_id is null`

Why partial indexes are used:

- activity-level and date-level feedback need different natural keys
- a single global unique constraint would overfit one shape and break the other
- repeated Telegram taps should update the canonical row instead of creating duplicates

---

## 5. Normalized fields vs payload vs context

### 5.1 Normalized fields

Normalized fields are the primary query surface.

They answer questions like:

- what feedback type is this
- what score did the athlete choose
- what canonical label corresponds to that score
- what source produced the row

These fields are stable, explicit, and suitable for filtering, grouping, and analytics.

### 5.2 `feedback_payload`

`feedback_payload` stores additive, feedback-type-specific details.

It does not replace normalized fields.

Example `next_day_recovery` payload:

```json
{
  "target_date": "2026-05-15",
  "previous_date": "2026-05-14",
  "previous_training_load": 85.0,
  "previous_activities_count": 2,
  "linked_activity_ids": [17855535922, 17855535923]
}
```

Why payload exists:

- different feedback families need different supporting context
- not every dimension deserves a dedicated normalized column yet
- extensibility should remain additive and explicit

Rules:

- canonical score stays in `feedback_score`
- canonical categorical value stays in `feedback_value`
- payload stores only supporting dimensions or linkage details

### 5.3 `context_json`

`context_json` stores a historical snapshot of derived state at feedback time.

Typical fields:

```json
{
  "snapshot_date": "2026-05-15",
  "readiness_score": 63.5,
  "good_day_probability": 0.72,
  "status_text": "Good",
  "recommendation": "moderate",
  "freshness": 4.2,
  "recovery_score": 71.0,
  "recovery_explanation": {
    "sleep_score": 74.0
  }
}
```

Why snapshots are persisted historically:

- readiness and recommendation at feedback time are part of the observed event
- later recomputes or model changes should not rewrite history
- calibration requires comparing what the system predicted then versus what the athlete reported then

This is why `context_json` is intentionally historical rather than recomputed on read.

---

## 6. Schema versioning philosophy

`feedback_schema_version` exists to version payload semantics, not to replace the normalized model.

Current philosophy:

- normalized columns remain the stable contract
- payload meaning may expand over time
- incompatible payload changes should bump `feedback_schema_version`
- old rows remain valid historical records

Practical rule:

- if a change only adds optional payload keys, the current version may remain valid
- if a change reinterprets existing payload keys, bump the version

---

## 7. Telegram UX philosophy

Current Telegram collection is intentionally lightweight.

Principles:

- optional feedback
- low-friction longitudinal collection
- one message per prompt
- one-tap answer in the current MVP
- maximum three taps as a design ceiling for future flows
- best-effort acknowledgements and message edits after persistence

Why this matters:

- calibration data quality depends on repeated participation
- repeated participation depends on low user friction
- the system needs longitudinal consistency more than questionnaire depth

Current confirmation behavior:

- persistence happens first
- Telegram callback acknowledgement is best-effort
- Telegram message edit is best-effort
- Telegram failure after persistence must not invalidate the recorded feedback

---

## 8. Current flows

### 8.1 Post-ride RPE flow

```text
activity ingestion
↓
training processed notification
↓
Telegram RPE prompt
↓
callback: rpe10:{activity_id}:{score}
↓
upsert source observation and resolve effective RPE
↓
best-effort Telegram confirmation
```

Current observation shape (illustrative):

```json
{
  "canonical_activity_id": 17855535922,
  "source": "telegram",
  "score": 7,
  "scale_version": "rpe_1_10",
  "schema_version": "rpe_observation_v1",
  "observed_at": "2026-09-28T07:00:00Z",
  "received_at": "2026-09-28T07:00:01Z",
  "source_payload": {
    "callback_data": "rpe10:17855535922:7",
    "context": {"readiness_score": 63.5}
  }
}
```

### 8.2 Next-day recovery flow

```text
previous day has training signal
↓
Telegram recovery prompt for target date
↓
callback: recovery:{user_id}:{target_date}:{score}
↓
upsert date-level row
↓
best-effort Telegram confirmation
```

Prompt usefulness rules in MVP:

- previous day has `daily_training_load.tss > 0`
- or previous day has `daily_training_load.activities_count > 0`
- or activities exist in `strava_activity_raw` for that date

Example row shape:

```json
{
  "strava_activity_id": null,
  "activity_date": "2026-05-15",
  "feedback_type": "next_day_recovery",
  "feedback_value": "fresh",
  "feedback_score": 4,
  "source": "telegram",
  "feedback_schema_version": "v1_extensible",
  "feedback_payload": {
    "target_date": "2026-05-15",
    "previous_date": "2026-05-14",
    "previous_training_load": 85.0,
    "previous_activities_count": 2,
    "linked_activity_ids": [17855535922, 17855535923]
  },
  "context_json": {
    "snapshot_date": "2026-05-15",
    "readiness_score": 58.0,
    "recommendation": "endurance"
  }
}
```

MVP note:

- there is no morning scheduler yet
- manual/debug prompt sending exists
- scheduler design remains future work

---

## 9. Architectural boundary

The subjective feedback layer does not:

- change load calculations
- change recovery calculations
- derive a readiness score directly from raw post-ride RPE
- adapt readiness weights or recommendation thresholds implicitly

It does:

- record user-reported outcomes
- preserve historical system context
- create an evaluation dataset for future calibration work
- provide date-level `next_day_recovery` as a deterministic `feeling` signal
- trigger current-day readiness recomputation after an idempotent feeling upsert

This boundary keeps Whatte deterministic while making later validation possible.

---

## 10. Roadmap

Possible next steps:

- sport-specific second-tap feedback
- morning recovery scheduler
- richer Web feedback interaction
- Strava subjective import if available
- recommendation calibration
- offline ML experiments using accumulated subjective feedback

These are roadmap items, not current behavior.

## 6. Next-day recovery scheduling

The backend now owns automated next-day recovery prompt scheduling.

Current V1 flow:

1. the worker checks once per loop whether the current UTC hour matches `NEXT_DAY_RECOVERY_PROMPT_HOUR_UTC`
2. target date is the current UTC date
3. candidate users are discovered from the previous day via `daily_training_load` and `strava_activity_raw`
4. backend skips users who already have `next_day_recovery` feedback for the target date
5. backend claims a prompt-log row in `subjective_feedback_prompt_log` before sending Telegram
6. successful delivery updates the same row to `delivery_status = sent` and stores `telegram_message_id` when available
7. repeated scheduler runs stay idempotent because the prompt-log natural key is `(user_id, prompt_type, target_date)`

Skip reasons currently include:

- `no_previous_training_day`
- `feedback_already_exists`
- `prompt_already_sent`
- `prompt_delivery_in_progress`

Current limitation:

- scheduling is UTC-based, not per-user timezone-based yet
- this is intentional for V1 because user timezone orchestration is not yet modeled consistently across the backend
