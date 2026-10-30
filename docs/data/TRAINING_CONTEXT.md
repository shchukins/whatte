# Minimal persisted training context

Implemented second increment of [#93](https://github.com/shchukins/whatte/issues/93),
2026-10-30. The existing `training_time_policy_v1` rules and readiness meanings
are unchanged. Today recommendations, plan/activity linking and acceptance remain
planned.

## Manual input and storage

`/today/plan` is a native Web form in Today navigation, under the same configured
athlete and Caddy Basic Auth boundary. It edits the current **Monday–Sunday ISO
week** in `WHATTE_TIMEZONE`, one block priority (`long_z2`, `z2`, `intensity`,
`recovery`), session type/duration/key-or-supporting priority/date, and one total
available window per day. Add/remove rows; save again to edit. Without JavaScript,
saving supplies the next empty session row. Existing session IDs remain stable.
Optional shortening minima reuse the existing policy validation; there is no
inferred minimum or interval generation.

- `user_training_context`: configured user ID, nullable block priority and revision.
  The priority persists across weeks until explicitly changed/cleared.
- `training_week_plan`: `(user_id, week_start)` and an atomic JSONB `WeekPlan`
  document. Only manual inputs are stored; policy-compatible session fields are
  reused, with nullable day for unscheduled work. Runtime Pydantic validation runs
  on every read/write. SQL enforces ownership, Monday and document type.
- `sessions=null`: plan not supplied; `sessions=[]`: explicitly empty plan.
  Undated sessions stay stored and are disclosed as `session_day_unknown:<id>`.
- Omitted/unconfirmed windows are unknown, even if tentative minutes are entered.
  Confirmed zero is explicitly unavailable. Positive confirmed windows are known
  capacity, **not** a review of session compatibility or recovery tolerance.
- Goal and week save atomically. A conditional user revision rejects stale tabs
  with 409; changed local week also rejects the old form. Validation/storage errors
  preserve input. A new week has no sessions/windows carried forward automatically.
- Bounded URL-encoded POST, same-origin checks, configured user only, `no-store`
  responses. No public user-ID parameter or new API authentication mechanism.

[V2 migration](../../migrations/sql/V2__training_context.sql) is additive, transactional
and old-app compatible: two independent tables, no backfill or changes to existing
activity, profile, load, feedback or research rows. It uses the existing Flyway
manifest/checksum and production backup/approval gates. V1 and its exact catalog
remain immutable; baseline adoption/safety tests run on a V1-only fixture, while
CI applies and validates the complete migration chain before DB integration tests.

## Backend adapter

[`get_policy_context`](../../backend/backend/services/training_context_service.py)
reads a repeatable-read, read-only snapshot and returns:

- `saved_context`: block priority and full saved plan, including undated work;
- `activities`: locally stored Strava facts in the current week through today's
  local date, activity IDs, duration, sport, existing power metrics, effective RPE,
  RPE source/disagreement and existing tri-state load assessment;
- `context`: validated `TrainingDecisionContext`, or null until today's numeric
  capacity is confirmed (v1 requires an integer; no fabricated zero is supplied);
- `decision`: the existing pure policy result when context can be formed;
- `missing_context` and `limitations`: missing dates, unknown capacity, ambiguous
  today's session, policy missingness, unlinked completion and unreviewed future
  compatibility. Consumers must display these alongside policy results.

Both midnight bounds are constructed in the user's configured timezone to handle
DST and ISO-year changes. The query reuses canonical Strava identity, excludes
removed/excluded/duplicate activities, LEFT JOINs v1 metrics and effective RPE by
user + activity ID, and never filters out workouts for missing TSS. Absent metrics
stay unknown; unsupported sport/power stays explicitly uncovered. It does not
reuse a rolling-seven-day total. An empty activity list means **no eligible facts
stored locally in this range**, not proven no exercise: Strava synchronization
completeness is explicitly unverified. Database failure propagates; it is not an
empty history fallback.

Physiology disclosure reuses `load_physiology_signal` for exact-date historical
recovery. Absence never implies good recovery or blocks the adapter. Manual
physiology remains the existing separate research input. RPE and power values
are returned alongside the policy input; v1 only consumes activity ID and load
coverage and does not interpret RPE thresholds.

`today_session_id` defaults only when exactly one dated session is scheduled
today; ambiguity remains explicit. Undated work is not assigned an invented day.
No actual activity is marked as completion of a plan session, even if type,
duration or power resembles it. No training permission, substitute eligibility
or future session compatibility is inferred from readiness. Optional supplied
`ActionConstraints` is the existing policy contract, not persisted permissions.

## Remaining Today integration

The next increment must consume this adapter, show missingness/limitations,
collect explicit current training constraints and any compatibility review, let
the athlete select among multiple same-day sessions, and implement explicitly
confirmed plan/activity linkage and recommendation acceptance. It must not treat
known capacity or locally empty history as confirmation of those missing facts.
This increment adds no recommendation UI or automatic plan mutations.

Tests: [unit/form cases](../../backend/tests/test_training_context.py),
[PostgreSQL storage, boundaries and upgrade](../../backend/tests/test_training_context_integration.py),
and the unchanged [policy scenarios](../../backend/tests/test_training_decision_policy.py).
