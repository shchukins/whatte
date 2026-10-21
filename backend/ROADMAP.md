# Backend Roadmap

Product direction as of 2026-10-21:
[Product context](../docs/ai/PRODUCT_CONTEXT.md) and
[Current priorities](../docs/ai/CURRENT_PRIORITIES.md) are authoritative.

## Already implemented

- Strava ingestion, raw history and explicit activity load eligibility
- dated profile, effective RPE, response metrics and comparable-session baselines
- daily load, recovery and readiness; preserved historical HealthKit rows
- Web Today/Profile/Diary, Telegram feedback and shared deterministic briefing
- snapshots, datasets and offline research infrastructure with documented
  acceptance limits; implementation is not evidence of model benefit

Detailed implementation and dated evidence:
[Current state](../docs/product/CURRENT_STATE.md).

## Next bounded product step — planned

Prepare the contract and reuse audit for a cycling-only, single-user time-change
decision using a manual weekly plan. Define minimum goal/plan/time context,
completed-work matching, allowable alternatives, missing-data behavior,
tradeoff explanations and comparison to a simple baseline.
See [Training decision MVP](../docs/product/TRAINING_DECISION_MVP.md).

Implementation follows in a separate task. No architecture, service, model
formula, API or schema change is implied by this roadmap.

## Paused / deferred

Readiness tuning, probability calibration, recovery prediction, autoresearch
expansion, additional sports/providers, calendar/equipment integrations and
automatic periodization are not current milestones. Existing contracts and
acceptance gates remain valid if those workstreams are explicitly resumed.
The completed morning-loop pilot is existing evidence, not a pending prerequisite.
