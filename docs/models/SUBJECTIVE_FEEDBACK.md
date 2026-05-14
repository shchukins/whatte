# Subjective Feedback

## 1. Purpose

`activity_subjective_feedback` stores lightweight subjective feedback linked to completed activities.

Current scope:

- immediate post-ride RPE collection
- one-tap Telegram input
- historical context snapshot persistence

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
- `feedback_type`
- `feedback_value`
- `feedback_score`
- `source`
- `context_json`
- `created_at`
- `updated_at`

Current semantics:

- `feedback_type = post_ride_rpe`
- `source = telegram`

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

## 8. Future extensibility

The schema and service layer are designed so additional feedback types can be added later, for example:

- `next_morning_feeling`
- `legs_freshness`
- `readiness_feeling`
- `subjective_sleep_quality`

These are not implemented yet.
