# Open decisions

This document records only choices that can change the product contract. It is
not a backlog: implementation starts only after a bounded decision is made and
the affected model, API, and data documents are updated.

Product direction changed on 2026-10-21:
[Product context](../ai/PRODUCT_CONTEXT.md) and
[bounded MVP](../product/TRAINING_DECISION_MVP.md). Readiness calibration is not
a prerequisite for the time-adaptation experiment. Existing issue statuses and
runtime behavior are not changed by this document.

## OD-001: Readiness calibration

**Current fact:** `v2_signal_composition_response_v1` is deterministic, and
`good_day_probability = readiness_score / 100` is a presentation mapping, not
a calibrated probability.

**Decision needed if resumed:** identify which training decision calibration
would improve, then assess whether evidence supports changing weights, zones,
probability wording, or none. Version any changed model and preserve prior rows.
The morning-loop pilot #108 is completed baseline evidence, not a pending gate.

**Status:** paused as a product priority; no production tuning authorized.

## OD-002: Canonical delivery formatting

**Current fact:** `decision_engine.build_persisted_readiness_briefing` is the
canonical recommendation, reason, and briefing contract for materialized
current readiness. Telegram orchestration consumes it.

**Decision needed:** identify and remove any remaining notification-only
wording that can change the decision meaning. Delivery-specific metadata may
remain, but it must not derive a second recommendation.

**Status:** shared decision contract implemented; investigate only concrete
remaining delivery drift. Do not schedule a duplicate unification project.

## OD-003: First non-cycling load input

**Current fact:** cycling activities with valid power-based TSS form the
production load baseline. Unsupported or missing load is explicit; it is never
invented as zero or estimated.

**Decision needed:** select at most one non-cycling Strava activity type,
define its deterministic input and validation method, and specify how it joins
daily load without changing the cycling contract.

**Status:** deferred; the first time-adaptation experiment is cycling-only.

## OD-004: Source expansion

**Current fact:** active inputs are Strava, dated user profile, and
Web/Telegram subjective feedback. HealthKit data is historical exact-date
physiology only; ingestion and the iOS client are retired.

**Decision needed:** before adding any source, define ownership, timezone,
normalization, conflict rules, historical replay, and missing-data behavior.

**Status:** deferred.

## OD-005: User-facing planning layer

**Current fact:** the current decision layer maps materialized readiness to
`recovery`, `endurance`, `moderate`, or `high_intensity`. It is not a workout
planner.

**Decision needed:** define the minimum manual goal/plan/time inputs, matching of
completed activities to planned stimuli, allowed alternatives, weekly-plan proposal
semantics and missing-data behavior. Reuse existing components; do not move domain
calculation into UI or AI. Define the comparison baseline and evidence before use.

**Status:** next bounded product preparation; direction and limits accepted in the
[MVP](../product/TRAINING_DECISION_MVP.md), implementation contract still open.
No calibration or recovery-research dependency.

## OD-006: Evidence of progress and decision value

**Current fact:** load-model `fitness`, readiness, RPE history and plan compliance
do not independently measure sporting adaptation. The current system does not
establish causal benefit from its recommendations.

**Decision needed before the trial:** choose a block goal and comparable control
tasks, define how conditions and incomplete observations are recorded, and agree
when to continue, simplify or stop. Compare decision usefulness to the simple
baseline without claiming the unobserved sporting outcome of another choice.

**Status:** required trial design, not a request for a predictive fitness model.

## Lifecycle

`open decision -> bounded contract -> implementation -> ADR or canonical docs`

Do not describe a decision as implemented before its code, tests, and canonical
documentation land together.
