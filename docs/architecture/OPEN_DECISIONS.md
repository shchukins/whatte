# Open decisions

This document records only choices that can change the product contract. It is
not a backlog: implementation starts only after a bounded decision is made and
the affected model, API, and data documents are updated.

## OD-001: Readiness calibration

**Current fact:** `v2_signal_composition_response_v1` is deterministic, and
`good_day_probability = readiness_score / 100` is a presentation mapping, not
a calibrated probability.

**Decision needed:** after the 14-day morning-loop pilot, decide whether the
evidence supports changing signal weights, score zones, probability wording, or
none of them. The decision must name the evidence, version any changed model,
and preserve prior rows.

**Status:** waiting for pilot evidence.

## OD-002: Canonical delivery formatting

**Current fact:** `decision_engine.build_persisted_readiness_briefing` is the
canonical recommendation, reason, and briefing contract for materialized
current readiness. Telegram orchestration consumes it.

**Decision needed:** identify and remove any remaining notification-only
wording that can change the decision meaning. Delivery-specific metadata may
remain, but it must not derive a second recommendation.

**Status:** implementation follow-up.

## OD-003: First non-cycling load input

**Current fact:** cycling activities with valid power-based TSS form the
production load baseline. Unsupported or missing load is explicit; it is never
invented as zero or estimated.

**Decision needed:** select at most one non-cycling Strava activity type,
define its deterministic input and validation method, and specify how it joins
daily load without changing the cycling contract.

**Status:** not started.

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

**Decision needed:** define a bounded planning capability—such as duration,
timing, or a plan-aware constraint—without moving calculation into UI or AI.

**Status:** deferred until calibration evidence is reviewed.

## Lifecycle

`open decision -> bounded contract -> implementation -> ADR or canonical docs`

Do not describe a decision as implemented before its code, tests, and canonical
documentation land together.
