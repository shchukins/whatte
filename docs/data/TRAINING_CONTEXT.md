# Minimal persisted training context

Implemented second increment of [#93](https://github.com/shchukins/whatte/issues/93),
2026-10-30. The existing `training_time_policy_v1` rules and readiness meanings
are unchanged. Today recommendations are integrated as of 2026-10-31; plan/activity linking
and acceptance were implemented on 2026-11-01 (see the decision loop below).

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
No activity is automatically marked as completion of a plan session, even if
type, duration or power resembles it. Explicit fulfillment links now populate
`CompletedSession.confirmed_plan_session_id`. No training permission, substitute eligibility
or future session compatibility is inferred from readiness. Optional supplied
`ActionConstraints` is the existing policy contract, not persisted permissions.

## Today integration, 2026-10-31

Today reads `get_policy_context` and presents the existing policy output. The
adapter also returns the exact local `today` used for its snapshot. Optional
`reviewed_window_ids` carries explicit user compatibility review for the selected
today session into the existing future-window contract. No capacity or readiness
is interpreted as permission.

`POST /today/training-decision` accepts native URL-encoded form data: local
`decision_day`, current `revision`, `minutes` (empty unknown, 0 unavailable),
optional `session_id`, training/intensity permission (`yes`, `no`, empty unknown),
repeated `reviewed_window` dates and `substitute` session IDs. All IDs/dates are
validated against the saved context before writing. `save_today_availability`
patches only today's window, retaining block priority, all sessions and all other
windows through the existing atomic revision check. Stale local day/revision is
409; invalid form 422; failed storage 503. Input remains available for correction.
The body is bounded to 16 KiB, uses the existing same-origin boundary and returns
no-store responses. No migration is needed.

A successful POST redirects to `/today` with date-scoped preview constraints.
GET reads one real snapshot and computes a proposal without writes. The POST now
also persists the immutable proposal when a recommendation is available. Unknown
time is never fabricated as zero. Permissions and compatibility reviews are
preview state, not accepted decisions; opening the bare URL requires explicit
permission again. No future-window carryover or automatic plan rewrite occurs; a separate explicit
acceptance is required for the proposed plan change.

Plan/activity linkage and decision acceptance were added in Task 4 below.
Confirmed completion means fulfillment of the selected assignment, including its
accepted shortening; it does not establish that a shortened stimulus equals the
original full stimulus. Local activity facts and load coverage are shown with explicit
completeness/matching limitations; RPE remains context without new thresholds.

Tests: [unit/form cases](../../backend/tests/test_training_context.py),
[PostgreSQL storage, boundaries and upgrade](../../backend/tests/test_training_context_integration.py),
and the unchanged [policy scenarios](../../backend/tests/test_training_decision_policy.py).


## Decision loop, 2026-11-01

Implemented in `training_decision_loop.py` and additive transactional
[V3](../../migrations/sql/V3__training_decision_loop.sql). This stores training-policy
choices separately from the readiness-specific `decision_context_snapshot`:
that infrastructure requires readiness model/category semantics, so reusing its
writer would record a different decision. The same immutable JSON + fingerprint
principle is retained. No Strava payload, RPE or metric row is copied.

- `training_decision`: ID, owner, local decision date/week, target assignment ID,
  input revision, exact `TrainingDecisionContext`, rule version in the input and
  result, full proposed result/tradeoffs, fingerprint and formation time.
  Inputs are the bounded policy inputs needed for replay, rather than the entire
  physiology/profile/Strava context. `presented_at` records explicit re-presentation;
  original evidence and `proposed_at` remain unchanged.
- `training_decision_choice`: one explicit `accepted` or `declined` response per
  decision, time and resulting revision. No row means no response (`proposed`).
  Repeated identical responses return successfully without applying changes again;
  a conflicting response is 409. Declining does not change the plan or mark rest.
- Read states: `proposed`, `accepted`, `declined`, `stale`, `superseded`.
  An unanswered proposal becomes stale if its input revision, facts or rule version
  changes; a more recently presented proposal for the same target supersedes it.
  The original proposal/choice is retained. Answered choices remain historical
  choices even when `stale=true` signals subsequent context changes.
- Repeated explicit preview POSTs with the same revision, policy context and rule
  version reuse one row. Saving unchanged confirmed capacity is a no-op. GET and
  recomputation neither accept nor write proposals. Preview-only GET results need
  the native save/preview POST before they can be accepted.

`POST /today/training-choice` takes only `decision_id` and `choice` (accepted or
declined). It rechecks ownership, local day, revision, current eligible activities,
newer proposals and deterministic replay of the stored recommendation. A stale
choice returns 409 without applying any plan change. The client never supplies a
new workout or chooses an arbitrary stored alternative under the original consent.
To select another supported recommendation, change the explicit constraints and
save a new proposal; the old proposal is not recorded as accepted.

Acceptance updates the existing weekly document and choice atomically:

- SHORTEN keeps the target ID, applies proposed type/duration and clears the old
  shortening minimum. Original full duration remains in immutable evidence.
- RESCHEDULE moves the same ID to the reviewed date. No additional occurrence.
- SUBSTITUTE moves the supplied replacement ID to today and leaves the omitted
  original target undated. It is still retained, with no invented replacement date.
- KEEP and SKIP retain the weekly document; SKIP never fabricates completed work
  or automatically compensates for it later.

All plan/choice/link writes share a per-user transaction lock and revision boundary.
A completed assignment cannot be deleted or edited into a different assignment
under the same ID; new work needs a new ID. Other plan inputs remain editable.

### Explicit activity correspondence

`POST /today/training-completion` takes `decision_day`, `revision`, canonical
`activity_id`, `session_id`, and `correspondence=fulfilled|different`. It validates
ownership, current local day/week and plan revision; the activity must be an
eligible canonical locally stored Strava fact from this week through today.
The assignment must have a non-future date in the same saved week. A matching
activity date, duration, sport or power never proves fulfillment.

`training_session_activity` stores only owner/week/assignment, canonical ID,
optional accepted decision ID, explicit correspondence and confirmation time.
One canonical activity can have one link; a fulfilled assignment can have only
one credited activity. Identical retries succeed without extra rows; incompatible
links fail with 409. Missing RPE, TSS, supported power/sport or physiology never
block confirmation. `different` preserves the relationship/observed attempt but
leaves the assignment pending. Confirmation is currently immutable in this UI;
there is no correction/history workflow or cross-week linking in this increment.

Canonical identity re-selection transfers the link in the existing deduplication
transaction. Conflicting linked assignments abort the merge rather than crediting
both; manual identity reconciliation is needed. Deleted/excluded/duplicate facts
are not passed into the policy. Reimport of the same Strava ID remains one fact.

The next `get_policy_context` exposes `activities[].plan_link` and supplies only
explicit `fulfilled` links for existing dated assignments to
`CompletedSession.confirmed_plan_session_id`. This prevents repeated key work in
the unchanged policy. Unlinked/different work still contributes its actual load
coverage and explicit matching uncertainty. Completion of an accepted 50-minute
assignment does not claim equivalence to the original 120-minute stimulus.

For Today and future #197 delivery the backend also returns:

- `decisions`: immutable offered action/inputs plus response, status and stale flag;
- `session_statuses`: current week assignment IDs, pending/fulfilled and confirmed
  canonical activity ID (independent of missing today's capacity);
- `delivery`: status, latest decision ID and `offer_training=false` when a workout
  is already recorded today or an up-to-date answer is already saved.

Today shows today's fact before a new prescription, offers native correspondence
forms, and shows accepted/declined status. A recorded activity suppresses another
automatic workout even if unlinked, different or unsupported for load. Existing
readiness briefing remains separate and unchanged. No #197 redesign, Telegram UI,
weekly replanner, automatic matching or physiology/rule changes are included.

### Verification and manual production check

The PostgreSQL integration suite covers proposal → acceptance → canonical activity
→ manual fulfillment → next policy, replay reads/retries, stale day/revision/rules,
no answer/decline, missing and unsupported load, absent RPE/physiology, key completion,
replacement/move identity, conflicting links, canonical re-selection and local
DST/ISO-week boundaries. V3 upgrade is rehearsed in an isolated namespace without
modifying existing context/activity rows. CI applies/validates the entire migration
chain with pgvector before running this suite; V1/V2 remain byte-for-byte unchanged.

After exact-SHA CI and confirmed production deployment (including approved V3):

1. In Plan week, supply a dated 120-minute long Z2 with a 40-minute explicit
   shortening minimum and `long_z2` block priority. Do this only for an actual plan.
2. In Today, enter 50 minutes and explicitly allow training. Leave future-window
   reviews unset for this shortening example; save to obtain SHORTEN.
3. Reload Today, accept, reload again. The selected assignment remains the same
   ID at 50 minutes; the accepted decision retains its original 120-minute input.
4. After a real Strava activity imports, Today shows the fact without another
   automatic workout. Select the assignment and confirm fulfillment (or explicitly
   different if that is what happened). No RPE/TSS input is required.
5. Reload: confirmed fulfillment remains visible. The next policy context contains
   its canonical ID and assignment ID; pending key work excludes this assignment.
   Repeating a confirmation must not add activity, choice or plan occurrences.

This is a functional loop, not evidence of sporting benefit. #93 remains open for
its Telegram plan-action delivery criterion; #197 remains a separate presentation task.
