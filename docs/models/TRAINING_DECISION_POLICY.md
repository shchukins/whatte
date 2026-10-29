# Minimal training time policy

Implemented backend-only increment of [#93](https://github.com/shchukins/whatte/issues/93),
2026-10-29. Rule version: `training_time_policy_v1`.
[Source](../../backend/backend/services/training_decision_policy.py),
[unit scenarios](../../backend/tests/test_training_decision_policy.py).
This is a pure proposal function, not an active Today/Telegram flow or a planner.

## Contract

`choose_training_action(TrainingDecisionContext) -> TrainingDecision` takes a
caller-supplied snapshot, never reads the clock, database or network, and never
writes a plan. Pydantic models validate input and support JSON serialization.
The caller supplies today's local date (normally using `WHATTE_TIMEZONE`).

- `block_priority`: one supported stimulus, `long_z2`, `z2`, `intensity` or
  `recovery`. This is a deliberately narrow block priority, not a goal ontology.
- `week_plan`: identified sessions in today's ISO week, each with date, type,
  total minutes and `key`/`supporting` priority. `today_session_id` selects the
  session being reconsidered. Other same-day sessions are not implicitly changed.
- `completed`: activities with an optional **confirmed** plan-session ID and
  existing `ActivityLoadAssessment` (`True` included, `False` unsupported,
  `None` unknown). Reuse `assess_stored_activity_load` when assembling stored
  activity context. No TSS value or type-based matching is performed here.
  Confirmation is independent of load coverage. `None` means unknown history;
  an empty tuple means explicitly no completed work.
- `available_minutes`: nonnegative whole minutes including warm-up/cool-down.
- `future_windows`: later dates in the same week, capacity and confirmation.
  `None` is unknown; an empty tuple means no supplied windows. A move also requires
  `compatible_session_ids`, explicitly reviewed by the caller/user for neighboring
  sessions, tolerance and weekly budget. The policy does not calculate safe spacing.
  It conservatively rejects dates occupied by another pending planned session.
- `constraints`: explicit permission for training today and separately intensity,
  permitted action flags, and a whitelist of substitute plan-session IDs reviewed
  as acceptable **today** (including their effect on remaining sessions).
  Unknown permission does not authorize training. Future compatibility is separate
  from today's permission. No permission is inferred from readiness.
- Optional `physiology_available`: disclosure only; missing physiology does not
  prohibit a decision or imply good recovery. Existing subjective/readiness evidence
  can inform the supplied constraints; this function adds no new thresholds.

A plan-specific `minimum_shortened_minutes` permits shortening easy cycling or
recovery work only. No universal minimum duration is supplied. Intensity cannot
be shortened without a separate verified template, which is outside this increment.
Only complete, explicitly permitted pending plan sessions can substitute; their
minutes include warm-up/cool-down. No generated intervals or workout catalog.

## Rules and tie handling

First build feasible options, then use these ordinal priorities. They are explicit
allocation heuristics, **not** estimates of adaptation or physiological equivalence.

1. `KEEP` the original session when it fits and current permissions allow it.
2. If today's session is key and matches the block priority: prefer a reviewed
   `RESCHEDULE` preserving it fully, then `SHORTEN`, then `SUBSTITUTE`, then `SKIP`.
3. Otherwise: prefer an explicitly allowed unfinished block-key `SUBSTITUTE`, then
   `SHORTEN`, then `RESCHEDULE`, then `SKIP`.
4. Training prohibited today: only reviewed `RESCHEDULE` or `SKIP` can be selected.
   Already completed target: `SKIP`, with no assertion of lost work.
5. Multiple substitute candidates are an unresolved choice. Multiple fully reviewed
   windows use earliest date, then window ID, as a logistical tie-break.

Thus 120-minute long Z2 with 50 minutes available can produce all four actions
under different explicit constraints. Shortening produces 50 minutes of Z2,
retaining partial aerobic work and losing 70 minutes plus the full long-session
stimulus. Intensity is never invented to compensate for this loss. A pending key
intensity session is only considered when supplied and explicitly permitted.
Substitution proposes moving its occurrence to today and omitting today's original
session; it does not simultaneously reschedule the omitted session. A combined
week rewrite is outside this increment.

The product contract requires `KEEP` when no change is justified, so this fifth
non-adaptation outcome supplements the four requested actions.

Missing block priority, today's plan, completed-work history or training permission
or intensity permission for an intensity target returns `status="uncertain"`, `recommendation=null`, explicit `missing_context` and
feasible alternatives. Distinct substitute ties and no admissible action also
return uncertainty. Unknown windows exclude moves without blocking today's options.
Unsupported/unknown load remains a warning; it is never converted to zero load,
rest or confirmed completion. No judgement of total fatigue is made from it.

## Output and boundaries

`recommendation` and `alternatives` share the same structured option contract:
action, session ID/type/minutes, window ID, reasons, preserved/lost stimulus and
proposed week consequences. `selection_reasons` explains ordering and identifies
pending key sessions. `rejected` records infeasibility by action; feasible lower
ranked options remain alternatives, not rejected options. Warnings and missing
context remain separate. No numeric benefit, optimality or guaranteed recovery.

Readiness mapping and its shared `recommendation/reason/briefing` delivery contract
are unchanged. Those categories do not encode plan actions, so coercing this policy
into them would break the baseline contract. Future adapters can consume this
backend-owned result in Today/Telegram without reimplementing the rules. No API,
UI, storage, automatic mutation, calendar integration or physiological model is
introduced. Input provenance/freshness, user confirmation/persistence, richer
explanations and outcome evaluation remain subsequent work under #93.
