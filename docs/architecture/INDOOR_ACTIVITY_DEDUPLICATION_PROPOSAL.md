# Indoor activity deduplication

Status: implemented deterministic MyWhoosh/Garmin baseline. This document
records the current contract; it is not a proposal or a deployment runbook.

## Problem

One physical indoor ride can reach Strava twice: once from MyWhoosh and once from
Garmin. Both raw records must remain auditable, while only the MyWhoosh activity
contributes to load, notifications, and subjective feedback.

## Source fields

`strava_activity_raw` persists these useful columns directly:

- `activity_type` (from Strava `sport_type` or `type`)
- `name`
- `start_date`
- `moving_time_s`
- `elapsed_time_s`
- `trainer`

It also preserves the complete Strava detail response in `raw_json`. Source
classification can therefore inspect `sport_type`, `type`, `trainer`,
`device_name`, `external_id`, `upload_id`, and any app/upload metadata returned
by Strava. Activity name is a fallback signal, not the primary classifier.

## Persisted state

Add deduplication state to `strava_activity_raw`:

- `duplicate_of_activity_id`
- `is_excluded`
- `exclusion_reason`
- `duplicate_confidence`
- `duplicate_reason`
- `duplicate_detected_at`
- `duplicate_detection_version`
- `deduplication_manual_override`
- `duplicate_candidate_activity_id`

The candidate id preserves a manually separated pair without making it a
canonical link. A self-reference check prevents direct self-links; service code
resolves links defensively and rejects cycles.

Add `activity_delivery_log`, keyed by `(activity_id, delivery_type)`, for
atomic post-ride and RPE delivery claims. The current `notification_log` has a
date-based uniqueness contract for daily readiness and cannot safely represent
multiple rides on the same day.

## Matching contract

The detector evaluates activities belonging to the same user by actual workout
time, never by Strava upload order.

Automatic merge requires:

- both activities are cycling activities;
- exactly one is classified as MyWhoosh and the other as Garmin;
- overlap divided by the shorter interval is at least `0.80`;
- elapsed-duration difference divided by the longer duration is at most `0.15`;
- start-time difference is at most the named start tolerance;
- neither side has a manual-separate override for the pair.

Confidence is a transparent weighted score:

- source pair: `0.50`
- overlap ratio: up to `0.30`
- duration similarity: up to `0.15`
- start similarity: up to `0.05`

All hard gates must pass and confidence must meet the high-confidence threshold.
MyWhoosh is always canonical; Garmin is retained, linked, and excluded.

## Pipeline behavior

Deduplication runs after raw data and metrics are stored, but before daily load
recomputation and user notification. A changed link triggers the existing
deterministic recomputation chain. Repeated webhook, update, backfill, and worker
runs preserve the same state.

`daily_training_load` excludes `is_excluded` rows. Downstream fitness, load
state, readiness, and briefing inputs consume the recomputed daily table and
therefore receive the de-duplicated load.

Post-ride notification and RPE delivery resolve the canonical family and use
the delivery log so either arrival order produces one delivery of each type.
Old Garmin callback payloads remain valid: callback handling resolves the
canonical MyWhoosh id while retaining the original id in feedback payload.

## Manual actions

Telegram callback state transitions are:

- exclude: set a manual exclusion;
- separate: clear the automatic link and persist the blocked candidate pair;
- restore: clear a manual exclusion when the activity is not still an automatic
  duplicate.

Each changed state recomputes affected load/state. Message editing reports the
result. No destructive delete is used.

The backend callback formats and state transitions are implemented in this
increment. Attaching late-arrival-aware buttons to an already delivered Garmin
message is deferred: it requires persisting chat/message coordinates and
editing that historical message after MyWhoosh arrives. No non-working buttons
are emitted meanwhile.

## Schema note

Migration `db-init/007_indoor_activity_deduplication.sql` defines the additive
schema used by this contract. Application startup does not apply migrations to
an existing volume. Schema removal is a separate, destructive operator change
and is intentionally not documented as a routine rollback.
