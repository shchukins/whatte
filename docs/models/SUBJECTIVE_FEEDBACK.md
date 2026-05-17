# Subjective Feedback

## 1. Purpose

`activity_subjective_feedback` stores lightweight subjective feedback that acts as a user-reported ground truth layer.

It captures how training felt and how recovery felt, while keeping the deterministic readiness pipeline unchanged.

Current scope:

- post-ride RPE feedback
- next-day recovery feedback
- Telegram-based low-friction collection
- normalized queryable fields plus extensible payloads
- historical context snapshots for later calibration work

This is an evaluation and calibration dataset layer, not an ML decision layer.

---

## 2. Why it exists

Human Engine already stores deterministic inputs and derived state:

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
- no recommendation changes are driven by feedback yet
- deterministic calculations stay separate from the feedback layer

---

## 3. Feedback types

### 3.1 `post_ride_rpe`

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

Extensible fields:

- `feedback_schema_version`
- `feedback_payload`
- `context_json`

Operational fields:

- `created_at`
- `updated_at`

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
callback: rpe:{activity_id}:{score}
↓
upsert activity-level row
↓
best-effort Telegram confirmation
```

Example row shape:

```json
{
  "strava_activity_id": 17855535922,
  "activity_date": "2026-05-14",
  "feedback_type": "post_ride_rpe",
  "feedback_value": "hard",
  "feedback_score": 4,
  "source": "telegram",
  "feedback_schema_version": "v1_extensible",
  "feedback_payload": {},
  "context_json": {
    "readiness_score": 63.5,
    "recommendation": "moderate"
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
- change readiness calculations
- change recommendation logic in production

It does:

- record user-reported outcomes
- preserve historical system context
- create an evaluation dataset for future calibration work

This boundary keeps Human Engine deterministic while making later validation possible.

---

## 10. Roadmap

Possible next steps:

- sport-specific second-tap feedback
- morning recovery scheduler
- iOS-native feedback collection
- Strava subjective import if available
- recommendation calibration
- offline ML experiments using accumulated subjective feedback

These are roadmap items, not current behavior.
