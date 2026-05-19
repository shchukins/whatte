# End-to-End Epics Proposal

Last updated: 2026-05-19

## Executive summary

Human Engine should organize planning around user-facing loops, not backend areas. The current labels (`area:readiness`, `area:feedback`, `area:calibration`, `area:ios`, `area:equipment`) are useful taxonomy, but they do not describe the product promise: a user wakes up, syncs recovery data, gets an explainable readiness answer, prepares an appropriate ride, gives feedback after training, and the system uses that evidence to validate and eventually adapt the model.

The recommended epic structure is six end-to-end scenarios:

1. Morning Readiness Loop
2. Explainable Readiness Experience
3. Ride Preparation and Recommendation Loop
4. Post-Workout Feedback Loop
5. Readiness Calibration Loop
6. Research Sandbox

This keeps the deterministic core separate from AI/ML speculation. Feedback collection and calibration analytics are product-critical, but automated model experimentation should remain future-facing until the feedback dataset and export path are stable.

## Proposed epic map

### 1. Morning Readiness Loop

**Problem statement**

The user needs a trustworthy morning answer after sleep and recovery data are available. A fixed-time briefing can be stale if HealthKit has not synced, which weakens trust in the recommendation.

**End-to-end flow**

1. User opens iOS or background sync runs.
2. HealthKit data syncs to backend.
3. Backend normalizes health data and recomputes recovery, load state, and readiness.
4. Backend determines data freshness: fresh, stale, missing, or partial.
5. First fresh readiness state for the day triggers a morning briefing.
6. If no fresh sync arrives by fallback time, the system sends a degraded/stale briefing or clearly indicates missing data.
7. Today screen and Telegram show the same readiness state and freshness context.

**Definition of done**

- Morning briefing is triggered by fresh HealthKit processing, with schedule as fallback only.
- Duplicate daily briefings are prevented.
- Briefing and Today screen expose freshness state clearly.
- Stale data is never presented as fully reliable.
- iOS onboarding and system status make sync state understandable.
- Tests cover fresh, stale, missing, fallback, and duplicate-trigger behavior.

**Existing issues that belong here**

- #7 iOS app as HealthKit ingestion layer
- #51 [Feature] iOS onboarding flow
- #52 [Feature] System status & sync screen
- #88 [Feature] Event-driven morning briefing after HealthKit sync

**Issues to rename, close, merge, or split**

- Rename #88 to `[Scenario] Fresh morning readiness briefing after HealthKit sync`.
- Split #7 if it still represents broad historical iOS ingestion work: keep the remaining production gap as `Reliable HealthKit sync and freshness metadata`, and close already-completed ingestion work if current implementation covers it.
- Merge #51 and #52 only if the first product increment is a single setup/status surface; otherwise keep them as separate slices under this epic.

**Missing issues to create**

- `[Feature] Readiness data freshness model and API fields`
- `[Feature] Daily briefing delivery log and idempotency`
- `[Feature] Fallback morning briefing when HealthKit data is stale or missing`
- `[Feature] Today screen freshness and last-sync indicators`

### 2. Explainable Readiness Experience

**Problem statement**

Readiness is only valuable if the user understands why the system reached its conclusion. The experience must translate load, sleep, HRV, resting HR, missing data, and trend context into compact deterministic explanations.

**End-to-end flow**

1. Backend computes readiness from `LoadState + RecoveryState`.
2. Backend produces structured explanation factors from model components.
3. API returns machine-readable factors and compact user-facing reason text.
4. iOS and Telegram display the same explanation without running model logic locally.
5. User can see trend context and metric-level meaning without being dumped into raw data.

**Definition of done**

- Readiness responses include deterministic explanation factors.
- Explanation factors distinguish load, recovery, trend, missing data, and fallback modes.
- iOS presents concise positive/negative factors and missing-data indicators.
- Metric docs stay synchronized with displayed model behavior.
- Trend visualization supports interpretation without creating a fake secondary score.
- Tests cover explanation outputs for high fatigue, poor recovery, improving freshness, missing data, and fallback modes.

**Existing issues that belong here**

- #37 [Feature] Readiness stability and volatility analytics
- #50 [Feature] Readiness explanation layer
- #53 [Feature] Readiness, fatigue, and recovery trend visualization
- #56 [EPIC] Metrics layer & explainability (Athlytics-inspired)
- #57 [Feature] Extract metrics layer (fatigue, recovery, readiness)
- #58 [Feature] Metric-level documentation (formula + explanation)
- #59 [Feature] iOS explainable readiness presentation
- #60 [Feature] Unit tests for core metrics
- #81 [Feature] Dynamic semantic slogan system for Human Engine branding, as optional UI identity work only

**Issues to rename, close, merge, or split**

- Rename #56 from a technical epic to `[Scenario] Explainable readiness experience`, or close it after this scenario epic replaces it.
- Keep #57 and #60 as implementation support, but do not let them define the epic. They are internal quality slices.
- Rename #37 to `[Feature] Readiness trend and volatility explanation indicators`.
- Move #81 out of core planning or mark as low-priority UI polish. It should not block readiness, explanation, or calibration loops.

**Missing issues to create**

- `[Feature] Structured readiness explanation factor schema`
- `[Feature] Explanation templates for Telegram morning briefing`
- `[Feature] Missing-data and fallback explanations in readiness API`
- `[Feature] Explanation regression fixtures for canonical readiness scenarios`

### 3. Ride Preparation and Recommendation Loop

**Problem statement**

The user needs to decide what training is appropriate today and what practical constraints matter before leaving. This should be a deterministic ride preparation flow, not a vague "ride integration" bucket.

**End-to-end flow**

1. User opens Today screen, Telegram, or taps "Go riding".
2. System reads current readiness, recovery, load, data quality, and equipment status.
3. Deterministic decision layer returns recommendation category and reason codes.
4. Ride briefing shows training guidance plus equipment warnings/checklist when available.
5. User prepares for the ride with confidence that recommendation and equipment state are consistent.

**Definition of done**

- Recommendation engine returns deterministic recommendation object, reason codes, and data-quality warnings.
- Ride briefing uses readiness and decision outputs; it does not recalculate model state.
- Equipment status can be summarized into ride-blocking, warning, and ok states.
- Bike profile, component tracking, service log, and maintenance alerts support ride preparation.
- iOS and Telegram can display a compact briefing.
- Tests cover recommendation zones, poor data quality, equipment warning aggregation, and no-equipment fallback.

**Existing issues that belong here**

- #1 [Feature] Athlete profile (FTP, HR, weight)
- #13 [Feature] Bike profile
- #14 [Feature] Equipment tracking (chain, brakes, tires)
- #15 [Feature] Service log (maintenance events)
- #16 [EPIC] Athlete Profile
- #17 [EPIC] Equipment & maintenance system
- #18 [EPIC] Bike Profile
- #19 [Feature] Maintenance alerts
- #20 [Feature] Equipment status visualization
- #22 [Feature] Integrate equipment status into ride briefing
- #55 [Feature] Training outcome prediction layer, only as rule-based pre-ride outcome classification
- #76 [Feature] Recommendation engine v1

**Issues to rename, close, merge, or split**

- Replace #16, #17, and #18 with one scenario epic: `[Scenario] Ride preparation and recommendation loop`.
- Keep #1 as profile data needed for recommendations and equipment calculations, not as its own epic.
- Merge #13 into the ride preparation epic; bike profile alone is too small to be an epic.
- Rename #55 to `[Feature] Rule-based pre-ride outcome classification` to avoid premature prediction/ML framing.
- Rename #76 to `[Feature] Deterministic recommendation object and reason codes`.

**Missing issues to create**

- `[Feature] Ride briefing endpoint using readiness, recommendation, and equipment status`
- `[Feature] Equipment status aggregation for ride briefing`
- `[Feature] Ride preparation checklist model`
- `[Feature] Data-quality warnings in recommendation output`

### 4. Post-Workout Feedback Loop

**Problem statement**

Human Engine needs low-friction subjective outcome data. The user should be asked for the right signal at the right time: immediate post-ride effort, next-day recovery, and optionally pre-ride readiness, while preserving source and schema semantics.

**End-to-end flow**

1. Activity is ingested from Strava.
2. User receives a one-tap post-ride RPE prompt.
3. After relevant training days, user receives one next-day recovery prompt.
4. Optional pre-ride subjective readiness can be collected before training when useful.
5. Feedback rows persist normalized score, source, type, payload, and historical context snapshot.
6. Repeated taps update canonical rows and do not duplicate feedback.

**Definition of done**

- Post-ride and next-day feedback are automatic, low-friction, optional, and idempotent.
- Feedback ontology and source mappings are documented and versioned.
- Feedback supports Telegram now and future iOS/manual/Strava sources without losing origin semantics.
- Scheduled next-day prompts avoid duplicate prompts and respect timezone/quiet-hour rules.
- Feedback collection does not alter readiness or recommendation logic directly.
- Tests cover callback validation, upsert behavior, prompt scheduling, source mapping, and versioned semantics.

**Existing issues that belong here**

- #74 [Feature] Morning recovery feedback collection
- #75 [Feature] Pre-ride subjective readiness feedback
- #82 [EPIC] Unified Subjective Feedback Model
- #85 [Feature] Sport-aware optional second-tap feedback
- #86 [Feature] Source-aware subjective feedback ingestion
- #87 [Feature] Subjective feedback ontology and versioning
- #89 [Feature] Scheduled next-day recovery feedback prompt

Completed issues that should be referenced as prior work, not reopened:

- #83 [Feature] Extensible subjective feedback schema
- #84 [Feature] Next-day recovery subjective feedback

**Issues to rename, close, merge, or split**

- Rename #82 to `[Scenario] Post-workout feedback loop`.
- Close or supersede #74 if #84 already completed the next-day recovery storage/interaction portion; keep #89 for automated scheduling.
- Keep #75 as optional and later than post-ride plus next-day recovery; pre-ride prompts add friction and should be justified by calibration value.
- Keep #85 behind stable primary feedback; optional second tap should not delay longitudinal signal collection.

**Missing issues to create**

- `[Feature] Post-ride RPE prompt delivery state and deduplication`
- `[Feature] Feedback prompt quiet-hours and timezone rules`
- `[Feature] iOS subjective feedback entry point`
- `[Feature] Feedback completeness monitoring`

### 5. Readiness Calibration Loop

**Problem statement**

The product should learn whether its deterministic readiness and recommendation outputs match user outcomes. This is not ML yet; it is reproducible comparison between predicted state, recommendation, activity load, and subjective outcome.

**End-to-end flow**

1. System snapshots readiness, recommendation, model version, data quality, and relevant features at decision time.
2. User completes training and provides feedback.
3. Next-day recovery feedback is linked to previous training day.
4. Analytics join prediction context with actual outcomes.
5. Product surfaces mismatch cases and calibration summaries.
6. Model thresholds and recommendation rules can later be adjusted explicitly and versioned.

**Definition of done**

- Calibration records are reproducible from persisted snapshots and feedback.
- Analytics identify overestimation, underestimation, missing-data uncertainty, and recommendation mismatch cases.
- Dataset export exists for offline analysis without adding online ML behavior.
- Calibration does not mutate historical readiness or silently alter deterministic formulas.
- Model/version metadata is sufficient to compare outputs across changes.

**Existing issues that belong here**

- #36 [Research] Automated model experimentation sandbox (autoresearch-like loop), future only
- #54 [Feature] Readiness calibration with subjective outcomes
- #73 [EPIC] Adaptive Feedback Loop
- #77 [Feature] Prediction vs outcome calibration analytics
- #78 [Feature] Persist feature snapshots for future ML datasets
- #79 [Feature] Dataset export pipeline for calibration and ML
- #80 [Feature] Subjective feedback analytics

**Issues to rename, close, merge, or split**

- Rename #73 to `[Scenario] Readiness calibration loop`, or close it once this scenario epic replaces it.
- Split #78 into one product-critical snapshot issue and one future-ML dataset enrichment issue. The former belongs here; the latter belongs to Research Sandbox.
- Rename #79 to `[Feature] Calibration dataset export pipeline`; keep "ML" as future-compatible, not current scope.
- Move #36 out of calibration execution order until #54, #77, #78, #79, and #80 are stable.

**Missing issues to create**

- `[Feature] Calibration record query joining readiness, recommendation, load, and feedback`
- `[Feature] Recommendation mismatch taxonomy`
- `[Feature] Calibration dashboard or report endpoint`
- `[Feature] Versioned calibration decision log for threshold changes`

### 6. Research Sandbox

**Problem statement**

Automated experimentation can be useful later, but it should not become the product core before there is stable feedback, snapshots, exports, and deterministic calibration reporting.

**End-to-end flow**

1. Dataset export produces reproducible JSONL/CSV records.
2. Offline scripts run controlled parameter sweeps or model comparisons.
3. Backtests produce validation reports.
4. Human review decides whether deterministic formulas, thresholds, or recommendation rules should change.
5. Accepted changes are versioned and documented before they affect production outputs.

**Definition of done**

- Sandbox runs outside production decision paths.
- Experiments are reproducible and tied to exported dataset versions.
- Reports compare model versions against subjective outcomes and data quality.
- No LLM or automated research loop changes readiness, recommendations, or calibration without review.

**Existing issues that belong here**

- #36 [Research] Automated model experimentation sandbox (autoresearch-like loop)
- Future portions of #78 and #79 after deterministic calibration export is stable

**Issues to rename, close, merge, or split**

- Rename #36 to `[Research] Offline model experimentation sandbox`.
- Explicitly mark #36 as blocked by stable feedback collection, calibration analytics, and dataset export.

**Missing issues to create**

- `[Research] Backtesting protocol for readiness model versions`
- `[Research] Parameter sweep runner for offline calibration experiments`
- `[Research] Model comparison report format`

## Issue-to-epic mapping table

| Issue | Current title | Proposed scenario epic | Recommendation |
| --- | --- | --- | --- |
| #1 | [Feature] Athlete profile (FTP, HR, weight) | Ride Preparation and Recommendation Loop | Keep; clarify it supports recommendations and ride setup |
| #7 | iOS app as HealthKit ingestion layer | Morning Readiness Loop | Split/close completed portions |
| #9 | [EPIC] Unified Load Model | Morning Readiness Loop / Ride Preparation and Recommendation Loop | Rename later as user-facing "whole-day load awareness"; keep as technical sub-epic only if needed |
| #10 | [Feature] Strava multisport load ingestion | Morning Readiness Loop / Readiness Calibration Loop | Keep under whole-day load awareness, not standalone epic |
| #11 | [Feature] Daily activity load from HealthKit | Morning Readiness Loop / Readiness Calibration Loop | Keep under whole-day load awareness |
| #12 | [Feature] Unified load model implementation | Morning Readiness Loop / Readiness Calibration Loop | Keep as implementation slice; avoid changing readiness formula without calibration |
| #13 | [Feature] Bike profile | Ride Preparation and Recommendation Loop | Keep; not an epic |
| #14 | [Feature] Equipment tracking (chain, brakes, tires) | Ride Preparation and Recommendation Loop | Keep |
| #15 | [Feature] Service log (maintenance events) | Ride Preparation and Recommendation Loop | Keep |
| #16 | [EPIC] Athlete Profile | Ride Preparation and Recommendation Loop | Close/merge into scenario epic |
| #17 | [EPIC] Equipment & maintenance system | Ride Preparation and Recommendation Loop | Rename/replace with scenario epic |
| #18 | [EPIC] Bike Profile | Ride Preparation and Recommendation Loop | Close/merge into #17 replacement |
| #19 | [Feature] Maintenance alerts | Ride Preparation and Recommendation Loop | Keep |
| #20 | [Feature] Equipment status visualization | Ride Preparation and Recommendation Loop | Keep |
| #22 | [Feature] Integrate equipment status into ride briefing | Ride Preparation and Recommendation Loop | Keep; anchor equipment to ride briefing |
| #36 | [Research] Automated model experimentation sandbox | Research Sandbox | Keep future; rename and block on calibration foundation |
| #37 | [Feature] Readiness stability and volatility analytics | Explainable Readiness Experience | Rename to trend explanation indicators |
| #50 | [Feature] Readiness explanation layer | Explainable Readiness Experience | Keep |
| #51 | [Feature] iOS onboarding flow | Morning Readiness Loop | Keep |
| #52 | [Feature] System status & sync screen | Morning Readiness Loop | Keep |
| #53 | [Feature] Readiness, fatigue, and recovery trend visualization | Explainable Readiness Experience | Keep |
| #54 | [Feature] Readiness calibration with subjective outcomes | Readiness Calibration Loop | Keep |
| #55 | [Feature] Training outcome prediction layer | Ride Preparation and Recommendation Loop | Rename to rule-based pre-ride outcome classification |
| #56 | [EPIC] Metrics layer & explainability (Athlytics-inspired) | Explainable Readiness Experience | Rename/replace scenario epic |
| #57 | [Feature] Extract metrics layer (fatigue, recovery, readiness) | Explainable Readiness Experience | Keep as internal implementation support |
| #58 | [Feature] Metric-level documentation (formula + explanation) | Explainable Readiness Experience | Keep |
| #59 | [Feature] iOS explainable readiness presentation | Explainable Readiness Experience | Keep |
| #60 | [Feature] Unit tests for core metrics | Explainable Readiness Experience | Keep as quality support |
| #73 | [EPIC] Adaptive Feedback Loop | Readiness Calibration Loop | Rename/replace scenario epic |
| #74 | [Feature] Morning recovery feedback collection | Post-Workout Feedback Loop | Supersede with #84/#89 if duplicate |
| #75 | [Feature] Pre-ride subjective readiness feedback | Post-Workout Feedback Loop | Keep later; optional |
| #76 | [Feature] Recommendation engine v1 | Ride Preparation and Recommendation Loop | Rename to deterministic recommendation object |
| #77 | [Feature] Prediction vs outcome calibration analytics | Readiness Calibration Loop | Keep |
| #78 | [Feature] Persist feature snapshots for future ML datasets | Readiness Calibration Loop / Research Sandbox | Split deterministic snapshots from future ML enrichment |
| #79 | [Feature] Dataset export pipeline for calibration and ML | Readiness Calibration Loop / Research Sandbox | Rename to calibration dataset export |
| #80 | [Feature] Subjective feedback analytics | Readiness Calibration Loop | Keep |
| #81 | [Feature] Dynamic semantic slogan system for Human Engine branding | Explainable Readiness Experience | Move to low-priority UI identity |
| #82 | [EPIC] Unified Subjective Feedback Model | Post-Workout Feedback Loop | Rename as scenario epic |
| #85 | [Feature] Sport-aware optional second-tap feedback | Post-Workout Feedback Loop | Keep after primary feedback is stable |
| #86 | [Feature] Source-aware subjective feedback ingestion | Post-Workout Feedback Loop | Keep |
| #87 | [Feature] Subjective feedback ontology and versioning | Post-Workout Feedback Loop | Keep |
| #88 | [Feature] Event-driven morning briefing after HealthKit sync | Morning Readiness Loop | Rename as scenario slice |
| #89 | [Feature] Scheduled next-day recovery feedback prompt | Post-Workout Feedback Loop | Keep |

## Recommended changes

1. Replace current epic issues #16, #17, #18, #56, #73, and #82 with scenario epics, or rename them if preserving issue history is more useful.
2. Do not create separate epics for Athlete Profile, Bike Profile, or Metrics Layer. They are important enabling capabilities, but not end-to-end user scenarios.
3. Create a new top-level epic for `Morning Readiness Loop`; the backlog currently has critical issues but no product epic around the morning user moment.
4. Create or rename a top-level epic for `Ride Preparation and Recommendation Loop`; this connects recommendation, athlete profile, equipment, maintenance, and ride briefing.
5. Keep `Research Sandbox` explicitly future-facing and offline. It should be blocked by stable feedback, snapshots, calibration analytics, and exports.
6. Keep unified load work (#9-#12) as an enabling technical stream, but avoid making it a planning epic until it is framed as a user-facing "whole-day load awareness" problem.
7. Treat #81 as product identity polish, not a core readiness loop dependency.

## Open questions

- Should completed issue #84 replace open #74, or should #74 be closed as duplicate/superseded?
- Is #7 mostly complete now that HealthKit full-sync and Today screen exist, or does it still represent production iOS background sync gaps?
- Should unified load (#9-#12) wait until calibration analytics exist, or is there enough deterministic confidence to implement a first TSS-like whole-day load model now?
- What is the minimum ride briefing scope: readiness recommendation only, or readiness plus equipment status from the first increment?
- Should pre-ride subjective readiness (#75) be collected before the post-workout and next-day loops are stable, given the extra user friction?
- What is the canonical product surface for each loop: Telegram first, iOS first, or both from the beginning?
- Should the project maintain GitHub epic issues as planning artifacts, or should this document become the source of truth until the proposal is reviewed?

## Suggested next implementation order

1. **Morning Readiness Loop**: implement freshness-aware briefing and sync/status visibility (#88, #51, #52, remaining #7). This protects trust in the daily answer.
2. **Explainable Readiness Experience**: complete structured explanation factors and compact UI presentation (#50, #59, #53, #58, #60). This makes the answer understandable.
3. **Ride Preparation and Recommendation Loop**: stabilize deterministic recommendation output before expanding ride briefing (#76, #55 renamed, #1, #22). This turns readiness into action.
4. **Post-Workout Feedback Loop**: automate next-day prompts and finish version/source semantics (#89, #87, #86, #85 later). This builds longitudinal ground truth.
5. **Readiness Calibration Loop**: add snapshots, calibration joins, analytics, and export (#54, #77, #78 split, #79 renamed, #80). This validates the model without hidden adaptation.
6. **Equipment-aware ride preparation expansion**: deepen bike/component/service features (#13-#20) once ride briefing has a place to use them.
7. **Research Sandbox**: start only after calibration exports are reproducible (#36). Keep it offline and review-gated.
