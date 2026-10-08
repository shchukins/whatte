# Offline recovery prediction (#150)

## Status

Implemented in source with unit/model/protocol checks. The approved contract is
[OUTCOME_PREDICTION_CONTRACT_PROPOSAL.md](../product/OUTCOME_PREDICTION_CONTRACT_PROPOSAL.md).
Real Linux Docker/PostgreSQL integration checks are wired into Backend CI and must
pass before operational use. Prospective capture deployment, sufficient real-data
coverage and separately authorized home-server smoke execution remain pending.
#150 and #136 are not complete; #138 remains blocked by those acceptance steps.

## Target and formula

The first target is `workout_outcome_v1.next_day_recovery`, a training-day contextual
score on 1–5. Predicting a continuous score and measuring MAE assumes equal ordinal
spacing. This is an offline association among observed training days, without a
planned-session or causal claim.

```text
x = offline_readiness(reviewed_recipe, immutable_day_inputs) / 100
predicted_recovery = clamp(alpha + beta * x, 1, 5)
```

Offline replay preserves production normalization, response scoring/recency,
missing-family renormalization and rounding, with explicit candidate weights.
No direct readiness-to-outcome conversion is used. Alpha and beta come from
train-only OLS with intercept, baseline-recipe readiness and observed recovery.
A single frozen mapper is shared by baseline and every candidate for that dataset.
It is not refitted for each candidate. Negative or zero slopes are retained;
predictions need not change when available evidence makes a parameter irrelevant.

`recovery_prediction_parameter_space_v1` /
`recovery_prediction_candidate_v1` preserve the reviewed #137 weight bounds and
toggle semantics, fix recommendation thresholds at 40/60/75, and pin a
`learned_state_hash`, feature v2, dataset v2 and evaluator v2. Legacy recipe configs
remain valid with their original unsupported prediction behavior. Manual physiology
is evidence only; it is not substituted for historical recovery scores.

## Train-only preparation and state

Training rows are sorted by stable observation ID. Binary64 additions use a fixed
serial order, explicitly avoiding Python's changed built-in float summation in
3.12+. Nonfinite inputs and Sxx <= 1e-12 fail. These are numerical checks, not
physiology thresholds.

At least 30 eligible train days are required. Feedback update/availability time
must precede the declared fit-as-of boundary; that boundary must strictly precede
the earliest validation feature cutoff. This may require a gap before the first
eligible validation day to receive the last train day's D+1 feedback. A late train
label fails instead of entering fitting or being silently replaced.

The private `recovery_affine_state_v1` contains alpha/beta, sample count, fit method
and cutoff, dataset hash, train membership/row hash, baseline recipe hash and
implementation hash. It contains no train rows or labels. The implementation
hash binds replay, configuration, scorer, evaluator adapters and data identities.
The Docker image is independently pinned by immutable image ID/digest.

The trusted supervisor verifies the frozen state against deterministic train-only
preparation and reproduces baseline predictions before creating an audit record.
This is integrity verification, not candidate-specific fitting. It also verifies
the worker's candidate predictions against the pinned implementation. Neither
inference request receives labels, decisions, realized workload or DB credentials.

## Commands

Export compatible source evidence with the existing exporter:

```bash
python -m scripts.export_temporal_dataset \
  --user-id USER --train-start YYYY-MM-DD --train-end YYYY-MM-DD \
  --validation-end YYYY-MM-DD --test-end YYYY-MM-DD \
  --dataset-version temporal_dataset_v2 --format json
```

Keep that output private and immutable. Test rows remain withheld by default.
Prepare with an explicit fit cutoff selected before any validation inference:

```bash
python -m scripts.prepare_recovery_prediction \
  --dataset /private-research/dataset.json \
  --fit-as-of FIT_TIMESTAMP_WITH_TIMEZONE \
  --output-root /private-research/prepared
```

The output directory is created once with mode 0700; files use 0600 and are never
overwritten. Outputs are learned state, baseline config, baseline predictions and
missing-prediction reasons. A partial preparation directory needs operator
inspection rather than an overwrite/retry. Clone the complete baseline config and
change only reviewed parameters to create a candidate.

The existing runner command adds `--learned-state`:

```bash
python -m scripts.run_research_experiment \
  --config /private-research/candidate.json \
  --dataset /private-research/dataset.json \
  --baseline /private-research/prepared/baseline-predictions.json \
  --learned-state /private-research/prepared/learned-state.json \
  --partition validation --experiment-id recovery-001 \
  --hypothesis 'Reviewed weight change for next-day recovery prediction' \
  --image sha256:REVIEWED_IMAGE_ID --output-root /private-research/runs
```

Use the dedicated research writer credentials described in
[RESEARCH_RUNNER.md](../product/RESEARCH_RUNNER.md); no production DSN fallback exists.
The v2 predictor rejects a train-partition run as an acceptance evaluation.
Final test use requires explicit access and must not influence iteration.

## Missingness and comparison

Unavailable input families remain explicit and are excluded by the established
composition. Missing replay capability, invalid provenance, nonfinite values,
post-cutoff sources and no scored family produce no prediction with reason counts.
Disabling response does not make a legacy payload with unknown capability valid.
If the selected mutable response/raw row was updated after cutoff, v2 capture
records unsupported / response_as_of_state_unprovable. It neither falls back to
an older session nor treats the unknown prior state as proven absence.

`prediction_artifact_v1` is unchanged. Missing reasons are a separate private
preparation artifact or terminal execution metadata, not extra artifact fields.
`baseline_evaluator_v2` adapts explicit day observations to the unchanged metric
functions of v1, then publishes its own dataset/evaluator/specification identity.
The host independently verifies its output.

A successful acceptance run needs at least 20 paired validation days and 80%
paired coverage among compatible targets with day-start context. These are
engineering floors, not statistical power claims. Audit metadata also reports
canonical training days and day-start-context days, exposing source coverage.
Too little coverage terminates as `failed / insufficient_paired_coverage`, with
diagnostic evaluator stdout retained privately. Improvement is not required;
MAE deltas use candidate minus baseline and imply no winner or promotion.

## Delivery boundary

No schema migration is needed: existing feature version text, audit columns and
dedicated column grants support v2. Existing records remain unchanged. New
deployment would prospectively capture v2 vectors; it does not backfill v1 snapshots,
recompute production readiness or introduce an online learner. Deploying capture
and running a home-server smoke test require separate operational authorization.

Unit and fixture-based model success establish calculation/protocol correctness.
They do not establish adequate real data or scientific quality. The 2026-10-08
availability preflight in the proposal cannot satisfy the coverage floors.


## Local validation evidence

On 2026-10-08 the full backend unit suite passed: 493 tests, with 17 integration
checks deselected. The added model suite covers real worker computation, state and
baseline verification, fitting/receipt-time leakage, day attribution, timezone,
parameter effects, missingness, repeatability and preparation CLI file permissions.
An additional paired-fraction coverage case was then checked separately.

The local interpreter is Python 3.14.3; the pinned research image and Linux CI use
3.11. Explicit serial binary64 accumulation preserves the reviewed operation order.
Docker, a local PostgreSQL server and psql are unavailable on this machine, so no
Docker/PostgreSQL integration result is claimed. CI includes the reviewed worker
image plus a real CLI -> two containers -> dedicated SQL audit test on disposable
data. A separately authorized home-server run on sufficiently covered real evidence
remains required.
