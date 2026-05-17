# Subjective Feedback

## 1. Purpose

`activity_subjective_feedback` stores lightweight subjective feedback linked to completed activities.

Current scope:

- immediate post-ride RPE collection
- one-tap Telegram input
- historical context snapshot persistence
- extensible payload storage for future subjective dimensions

This is a data collection layer, not an ML layer.

---

## 2. Why it exists

Human Engine already stores deterministic load, recovery and readiness outputs.
What is still missing is user-reported ground truth about how a ride actually felt.

This dataset is intended to support future:

- readiness calibration
- recommendation validation
- prediction error estimation
- personalization
- adaptation modeling

No recommendation learning or model adaptation is implemented here yet.

---

## 3. Current feedback type

Implemented now:

- `post_ride_rpe`

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

---

## 4. Schema

Table:

- `activity_subjective_feedback`

Fields:

- `id`
- `user_id`
- `strava_activity_id`
- `activity_date` nullable helper field for future date-based feedback flows
- `feedback_type`
- `feedback_value`
- `feedback_score`
- `source`
- `feedback_schema_version`
- `feedback_payload`
- `context_json`
- `created_at`
- `updated_at`

Normalized core fields remain the primary query surface:

- `feedback_type` identifies the feedback family
- `feedback_value` stores the canonical categorical value
- `feedback_score` stores the canonical numeric score
- `source` stores ingestion origin

Extensible fields are additive:

- `feedback_schema_version` tracks how payload semantics should be interpreted
- `feedback_payload` stores optional extra dimensions as JSON
- `activity_date` can support future feedback that is day-linked rather than activity-only

Current semantics:

- current Telegram RPE writes use `feedback_type = post_ride_rpe`
- current Telegram RPE writes use `source = telegram`
- new writes use `feedback_schema_version = v1_extensible`
- pre-migration rows are backfilled as `feedback_schema_version = v1`
- plain RPE rows may keep `feedback_payload = {}` when no extra fields are captured

Constraint:

- unique (`strava_activity_id`, `feedback_type`)

This makes repeated button presses safe and keeps one canonical subjective record per activity and feedback type.

---

## 5. Context Snapshot

`context_json` stores the model state snapshot that existed at feedback time.

Current snapshot fields:

```json
{
  "readiness_score": 63.5,
  "recommendation": "moderate",
  "freshness": 4.2,
  "recovery_score": 71.0
}
```

Important:

- values are persisted as historical facts
- they are not recomputed later from current state
- this preserves reproducibility for later evaluation work

---

## 6. Flow

```text
activity ingestion
↓
training processed Telegram notification
↓
second Telegram message with inline RPE buttons
↓
callback payload: rpe:{activity_id}:{score}
↓
idempotent upsert into activity_subjective_feedback
↓
Telegram confirmation message edit
```

---

## 7. Architectural rationale

This layer intentionally stays outside the deterministic calculation core:

- it does not alter load calculations
- it does not alter readiness calculations
- it does not introduce probabilistic behavior
- it only records user feedback plus contemporaneous deterministic context

That separation keeps Human Engine explainable while creating future evaluation data.

---

## 8. Payload usage

`feedback_payload` is optional and additive.
It must not replace the normalized fields above.

Example future payload:

```json
{
  "legs_fatigue": 2,
  "motivation": 4
}
```

Rules:

- keep the canonical score in `feedback_score`
- keep the canonical label in `feedback_value`
- store only extra dimensions in `feedback_payload`
- bump `feedback_schema_version` when payload semantics change incompatibly

## 9. Backward compatibility

The Telegram RPE flow remains unchanged:

- same inline buttons
- same callback payload format: `rpe:{activity_id}:{score}`
- same idempotent upsert key: (`strava_activity_id`, `feedback_type`)
- same message edit confirmation behavior

Older rows remain valid historical records.
They receive additive defaults during migration and continue to satisfy existing queries against normalized fields.

## 10. Future extensibility

The schema and service layer are designed so additional feedback types can be added later, for example:

- `next_day_recovery`
- `legs_freshness`
- sport-specific post-session questions
- source-aware ingestion beyond Telegram

These are not implemented yet.
