# PED incremental recovery study (#196)

> Priority update, 2026-10-21: further work on this research/calibration
> direction is **paused** under [current priorities](../ai/CURRENT_PRIORITIES.md).
> This document preserves its technical contract, dated evidence and acceptance
> gates; internal “next steps” apply only if the workstream is explicitly resumed.
> This does not disable existing runtime or change GitHub issue status.
> It is not a prerequisite for the [training decision MVP](TRAINING_DECISION_MVP.md).

Implemented: offline `ped_research_v1` reuses `temporal_dataset_v2`,
`baseline_evaluator_v2`, prediction artifacts, bounded credential-free
`DockerExecutor`, private runner receipts and optional `research_experiment_v1`
audit. No production readiness, probabilities, schema, notifications or automatic
promotion change. PED remains a descriptive comparison.

## Frozen protocol and prediction horizon

Observation unit is the existing canonical first-activity training day D.
Prediction occurs at its immutable day-start feature cutoff, before that day's
first workout. Target is `workout_outcome_v1.next_day_recovery`: training-day
unit, original integer 1–5, local date D+1. A completed workout contributes PED
only at a subsequent eligible day-start cutoff, after completion, source receipt,
calculation and prospective capture. Its RPE never predicts its own pre-workout
readiness. Depending on capture timing, the outcome horizon may be more than one
day after the PED-producing workout. This evaluates later self-reported recovery,
not a causal fatigue measurement or a direct prediction of production readiness.

Freeze chronological train/validation/test bounds in the dataset manifest before
fitting. `fit_as_of` follows every included train label receipt and precedes the
earliest validation cutoff; train features must also precede fit. Held-out labels
never enter fitting or container inference. Test export and evaluation require
`WHATTE_RESEARCH_TEST_ACCESS=granted`; validation remains required to establish
the fit boundary. Retain the frozen train/validation export when later supplying
test data, reproduce coefficients on unchanged train membership and never choose
candidates from test results. Protocol constants are not tuned on held-out data.

## Prospective evidence and edits

#195's current-record PED is **not** a historical as-of snapshot. Backdating it
or reconstructing overwritten ratings invalidates this study.
`ped_research_snapshot_v1` freezes target and selected comparable-session inputs,
user, completion, compute and capture times, `as_of_status=prospective_capture`,
and a canonical SHA-256 hash. Capture uses one repeatable-read, read-only
transaction, raw elapsed time for completion, effective RPE precedence and
#195's eligibility-before-LIMIT policy. It writes a private local JSON file only.

Capture after a completed rated workout and before the next prediction cutoff:

```bash
cd backend
python -m scripts.capture_ped_research --user-id USER --activity-id ACTIVITY \
  --output /private-research/captures/session.json
```

The output parent must already be private (0700); output is created once with
0600. Preserve each capture unchanged. Assemble the `snapshots` arrays into a
private envelope with `version=ped_research_snapshot_v1`; do not duplicate sessions
or alter timestamps. No automatic collection is enabled. Uncollected historical
PEDs remain missing. Hashes prove integrity, not timestamp authenticity: inputs
must originate from trusted prospective capture. Current capture cannot recover
old source precedence, edits, exclusions or FTP history. Subsequent changes do
not mutate the retained local artifact.

The supervisor verifies snapshot hashes, ownership, completed <= computed <=
captured, target receipt/recomputation before compute and recalculates PED using
the shared pure #195 calculator. Candidate baseline evidence must precede the
PED-producing target's start. Missing or incompatible RPE/source/scale/history
yields absent PED; future/late captures never contribute. The current prediction
workout is explicitly excluded. Matching and PED identities remain
`rpe_history_v1` and `personal_effort_deviation_v1`.

## Models, ablations and missingness

Use only sessions started in the seven days before prediction and captured by
its cutoff, sorted by session start/id, one prospective capture per session:

- Latest: last available PED.
- Rolling: mean of all eligible PEDs, requiring at least three.
- Persistent: 1 when the last three eligible PEDs are strictly positive, otherwise
  0; fewer than three is missing. This is an exploratory sign indicator, not a
  calibrated fatigue threshold.

Each variant compares train-fitted, frozen point models on identical paired
observations: baseline `a + b * replayed_readiness/100`; candidate
`a + b * replayed_readiness/100 + c * PED_covariate`. Fit both on the identical
variant-specific train cohort and freeze before validation; clamp predictions to
1–5. Centered OLS rejects singular/collinear designs. There is no regularization,
zero-imputation or hidden fallback. Each cohort's baseline is frozen independently;
do not compare unpaired headline errors across cohorts.

Cross variants with four settings: normal production replay, response off,
feeling off, historical physiology off (12 comparisons). Existing family
missingness and renormalization remain unchanged. Response ablation controls
potential overlap with RPE-derived baseline response context. The target is
separate recovery feedback, not workout RPE or readiness built from that same
RPE. It remains self-report, not independent physiology.

Adjustment uses the established **aggregate readiness covariate**. It does not
independently fit sleep, HRV or RHR: physiology is the existing historical
composite, and sleep is not a separate regressor. This study cannot establish
incremental value beyond every individual signal or workout-structure confounder.
That stronger claim requires a separately reviewed feature/target design and
sufficient prospective evidence. Positive PED means harder than prior comparable
sessions, without a causal fatigue or recovery conclusion.

The report includes variant/ablation train counts, eligible day counts,
compatible-target denominators, PED-present/missing strata including target
availability, replay exclusions, paired coverage, frozen evaluator MAE and
candidate-minus-baseline MAE. Point calibration is mean signed error; Brier and
probability calibration are inapplicable. A deterministic 1000-resample
calendar-week block bootstrap interval for paired MAE change uses seed 196;
fewer than four weeks yields a null interval. Three chronological sample windows
show stability without refitting. This uncertainty is exploratory, with no
multiple-comparison correction or automatic significance claim.

Inherited engineering floors are 30 paired train days, 20 paired held-out days
and 80% compatible-target coverage; they are preparation gates, not statistical
power guarantees. Below gates return `insufficient_evidence`, preserving explicit
counts/reasons and null unavailable metrics. Above gates return `refine`, requiring
review of effect, uncertainty, stability, confounders and untouched test data.
No exploratory result automatically chooses adoption or promotes a model.

## Execution and audit

```bash
cd backend
python -m scripts.run_ped_study \
  --dataset /private-research/dataset.json \
  --evidence /private-research/ped-snapshots.json \
  --fit-as-of FIT_AS_OF_ISO_TIMESTAMP --partition validation \
  --experiment-id ped-study-001 --output-root /private-research/runs \
  --image sha256:REVIEWED_RESEARCH_IMAGE_ID
```

Use the existing [research image/runbook](RESEARCH_RUNNER.md). Insufficient data
needs no image execution. Actual inference requires the pinned research image
and existing resource/network/credential isolation. Worker inputs contain fitted
coefficients and scalar covariates/identities, no held-out outcomes or their receipt
timestamps. Host recomputation authenticates outputs; the existing frozen
evaluator computes metrics. Source/config/state/evidence/dataset identities,
execution stages and report hash enter `receipt.json` and `study-report.json`.
Private directories are 0700, files 0600; IDs cannot overwrite. Exit 2 is valid
insufficient evidence, 1 invalid input/execution, 0 a reviewable study.

Add `--audit` with dedicated `WHATTE_RESEARCH_DATABASE_URL` to record the existing
experiment lifecycle. `candidate` means reviewable `refine`; `rejected` plus
aggregate metrics means insufficient evidence; `failed` means execution failure
with no metrics. Production DATABASE_URL is never the audit writer. Local receipts
need no audit provisioning. Keep all personal exports, coefficients, predictions,
captures and container inputs outside Git.

## Observed result, 2026-10-15 (Europe/Moscow)

Read-only production export: train 2026-10-01–10-10, validation through 10-15,
reserved test through 10-20 (withheld); fit boundary 10-11 23:00 +03:00.
This is an availability check, not a powered acceptance experiment.

- Canonical days: train 4, validation 2; eligible immutable rows: train 0,
  validation 2. Train exclusions: one missing day-start snapshot, three lacking
  v2 response replay context. Export exclusion metadata is diagnostic/unhashed.
- One compatible validation recovery target, no supplied prospective PED captures.
  Both validation rows are PED-missing; one has a target.
- All 12 variants/ablations: train paired 0; MAE, incremental change and uncertainty
  unavailable. No fitting, container inference or database audit writes occurred.
- Recommendation: **insufficient evidence**. Neither benefit nor absence of benefit,
  fatigue association or readiness integration is established. Collect prospective
  evidence and repeat the frozen protocol. Adoption requires a separate reviewed,
  versioned promotion.

Private artifacts are retained locally, not committed. Aggregate identities:

| Artifact | SHA-256 |
| --- | --- |
| Dataset | `d6c722a012d71863022199427b39a59f46cf49e665727872029d4361a644b49b` |
| Empty prospective envelope | `9db1e814a2e65f8f023fd98b3a220b4bf4425292a55e2354bab2efadb979ce08` |
| Study report | `e56b9489d641891ccbb2e280abc7868280ba7f4900205acd0ea933f36491bb1e` |

Synthetic tests prove mechanics and leakage guards, not athlete benefit.
Existing PED/matching behavior is regression-tested after extracting the unchanged
calculators into pure modules needed by credential-free research containers.
