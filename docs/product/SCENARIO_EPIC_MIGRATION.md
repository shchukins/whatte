# Scenario Epic Migration

Last updated: 2026-05-19

## Summary

This migration establishes scenario-based product epics without reorganizing the whole backlog. It follows the accepted proposal in `docs/product/END_TO_END_EPICS_PROPOSAL.md` and intentionally keeps existing technical issues, labels, and discussions intact.

The migration is conservative:

- created only the six agreed top-level scenario epics
- preserved existing issue history
- did not close, delete, mass rename, or relabel issues
- did not modify completed issues
- kept deterministic product loops separate from research and future ML work

## Created epics

| Scenario epic | Issue |
| --- | --- |
| `[SCENARIO] Morning Readiness Loop` | #91 |
| `[SCENARIO] Explainable Readiness Experience` | #92 |
| `[SCENARIO] Ride Preparation and Recommendation Loop` | #93 |
| `[SCENARIO] Post-Workout Feedback Loop` | #94 |
| `[SCENARIO] Readiness Calibration Loop` | #95 |
| `[SCENARIO] Research Sandbox` | #96 |

Each scenario epic contains:

- problem statement
- user-facing flow
- definition of done
- linked existing issues
- migration note explaining that the change is additive

All six were created with the existing `type:epic` label only. No new labels were introduced.

## Issue mappings

### Morning Readiness Loop (#91)

Linked issues:

- #7 iOS app as HealthKit ingestion layer
- #51 iOS onboarding flow
- #52 System status & sync screen
- #88 Event-driven morning briefing after HealthKit sync

Migration action:

- created new scenario epic #91
- did not rename or close any linked issue

### Explainable Readiness Experience (#92)

Linked issues:

- #37 Readiness stability and volatility analytics
- #50 Readiness explanation layer
- #53 Readiness, fatigue, and recovery trend visualization
- #56 Metrics layer & explainability
- #57 Extract metrics layer
- #58 Metric-level documentation
- #59 iOS explainable readiness presentation
- #60 Unit tests for core metrics
- #81 Dynamic semantic slogan system

Migration action:

- created new scenario epic #92
- added a migration comment to #56 pointing future planning to #92
- did not rename #56, even though it is technical, to avoid unnecessary churn

### Ride Preparation and Recommendation Loop (#93)

Linked issues:

- #1 Athlete profile
- #13 Bike profile
- #14 Equipment tracking
- #15 Service log
- #16 Athlete Profile epic
- #17 Equipment & maintenance system epic
- #18 Bike Profile epic
- #19 Maintenance alerts
- #20 Equipment status visualization
- #22 Integrate equipment status into ride briefing
- #55 Training outcome prediction layer
- #76 Recommendation engine v1

Migration action:

- created new scenario epic #93
- added migration comments to #16, #17, and #18 pointing future planning to #93
- did not close or merge the older profile/equipment epics
- did not rename #55 or #76 yet, even though clearer names were suggested in the proposal

### Post-Workout Feedback Loop (#94)

Linked issues:

- #74 Morning recovery feedback collection
- #75 Pre-ride subjective readiness feedback
- #82 Unified Subjective Feedback Model epic
- #85 Sport-aware optional second-tap feedback
- #86 Source-aware subjective feedback ingestion
- #87 Subjective feedback ontology and versioning
- #89 Scheduled next-day recovery feedback prompt

Completed prior work referenced but not modified:

- #83 Extensible subjective feedback schema
- #84 Next-day recovery subjective feedback

Migration action:

- created new scenario epic #94
- added a migration comment to #82 pointing future planning to #94
- did not modify completed issues #83 or #84
- did not close #74 as duplicate, because that should be a manual follow-up after confirming overlap with #84 and #89

### Readiness Calibration Loop (#95)

Linked issues:

- #54 Readiness calibration with subjective outcomes
- #73 Adaptive Feedback Loop epic
- #77 Prediction vs outcome calibration analytics
- #78 Persist feature snapshots for future ML datasets
- #79 Dataset export pipeline for calibration and ML
- #80 Subjective feedback analytics

Migration action:

- created new scenario epic #95
- added a migration comment to #73 pointing future planning to #95
- explicitly separated production calibration from speculative/offline research
- did not split #78 or rename #79 yet

### Research Sandbox (#96)

Linked issues:

- #36 Automated model experimentation sandbox
- future research portions of #78 and #79 after deterministic calibration export is stable

Migration action:

- created new scenario epic #96
- added a migration comment to #36 pointing future research planning to #96
- kept research offline and separate from deterministic readiness/recommendation behavior

### Ambiguous enabling work

Issue #9 Unified Load Model was not forced into one scenario epic. It spans:

- Morning Readiness Loop, because whole-day load affects the morning answer
- Ride Preparation and Recommendation Loop, because total load affects recommendation safety
- Readiness Calibration Loop, because changing load inputs should be validated against outcomes

Migration action:

- added a migration comment to #9 explaining that it remains enabling work for #91, #93, and #95
- did not rename, close, split, or relabel #9

## Untouched ambiguous areas

The following areas were intentionally left unchanged:

- existing labels and auto-label workflow
- project views and milestones
- completed issues, including #83 and #84
- older technical epics, except for additive comments
- issue titles that may eventually benefit from clearer naming
- unified load work (#9-#12), because it crosses multiple scenario loops
- research/dataset wording in #78 and #79, because splitting those should happen with implementation planning
- UI identity work (#81), because it may support explainability aesthetics but should not drive the core product loops

## Suggested manual follow-ups

1. Decide whether older technical epics should remain open as umbrella context or be closed as superseded after the scenario epics are accepted.
2. Review whether #74 is now superseded by completed #84 plus open #89.
3. Consider renaming #56 to make it clearly subordinate to #92, or leave it as an implementation umbrella.
4. Consider renaming #55 to rule-based pre-ride outcome classification to reduce ML/prediction ambiguity.
5. Consider renaming #76 to deterministic recommendation object and reason codes.
6. Decide whether #78 should be split into production snapshots and future ML dataset enrichment.
7. Decide whether #79 should be renamed to calibration dataset export pipeline.
8. Decide whether new scenario epics need additional area labels after the first planning pass; this migration only used `type:epic`.

## Risks avoided intentionally

- No mass issue renames, because title churn makes backlog history harder to follow.
- No mass closures, because duplicate/superseded status should be confirmed issue by issue.
- No label deletion or new taxonomy, because current area labels remain useful for filtering.
- No completed issue edits, because completed feedback work is historical evidence.
- No project view changes, because views should be updated after the scenario epics are reviewed in GitHub.
- No speculative ML integration, because calibration and research remain separate from the deterministic product core.
- No forced mapping for unified load, because it is an enabling model stream that affects multiple user loops.

## Verification

- Confirmed no open scenario epics with the requested `[SCENARIO] ...` titles existed before creation.
- Created the six requested scenario epics as #91-#96.
- Added additive migration comments only to open legacy epic/research issues: #9, #16, #17, #18, #36, #56, #73, and #82.
- Did not modify completed issues.
- Did not reorganize project views.
