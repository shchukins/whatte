# Offline outcome prediction contract proposal (#150)

## Status and review boundary

Approved for implementation, 2026-10-08. This document is the reviewed design for
[#150](https://github.com/shchukins/whatte/issues/150), not an implemented predictor.
The target, formula, fitting, versions and coverage gates were approved before coding
model semantics. Implementation and pending evidence are tracked in
[RECOVERY_PREDICTION.md](../models/RECOVERY_PREDICTION.md). #136 remains partial; #138 must wait.

The proposed predictor is offline research only. It makes a predictive association
claim conditional on an observed training day, not a causal claim about a workout,
a recommendation, or the effect of changing readiness weights. It is not a
workout-plan suitability predictor. Production readiness and decisions stay fixed.
The product-facing classes in #55 need planned-session context and are outside this
first slice; #54/#95 supply the existing calibration and outcome-attribution rules.

## Findings from source and schema inspection

- #132 provides `workout_outcome_v1`: independent RPE and next-day recovery targets.
  Recovery is contextual for a training day and must be counted once.
  RPE 1–10 and legacy 1–5 remain independent scales.
- `daily_feature_vector_v1` contains materialized load/freshness, morning feeling,
  manual and historical physiology, and recent response metrics. It omits
  `baseline_json`, response versions and the complete date/provenance needed
  for exact response replay. An absent replay capability is not a missing signal.
- `activity_response_metrics` already stores `baseline_json`, `availability_json`,
  `explanation_json`, metric version and `computed_at`, but rows are upserted.
  Copy eligible evidence at capture time; never reconstruct legacy snapshots.
- Production response selection orders by stored activity date, activity ID and
  preferred metric version. The v1 feature builder orders by start timestamp and
  does not restrict metric versions. Do not assume these selectors are equivalent.
  Stored response activity dates also need explicit timezone provenance.
- `temporal_dataset_v1` assigns recovery to the first accepted record in input
  iteration order, before final sorting. If the actual first activity is excluded,
  a later activity can become the recovery owner. A day-start prediction cannot
  inherit a later, post-first-workout snapshot.
- `research_worker.py` explicitly returns unsupported. The runner sends feature-only
  rows to candidate inference and labels only to frozen evaluation.
- #137 strictly pins v1 feature/dataset identities and describes a readiness recipe.
  It cannot acquire new prediction semantics or unknown fields silently.
- The research image omits DB clients, production settings and the application.
  Preserve this boundary when adding standalone calculation modules.

### Read-only availability preflight

Production was queried on 2026-10-08 using a repeatable-read, read-only transaction
with a 10-second statement timeout. Only counts/schema metadata were returned:
5 v1 snapshots across 5 user-days, dated 2026-10-04 through 2026-10-08; freshness
available in 5, morning feeling in 1, historical physiology in 0; no response
replay context; no cutoff later than capture. Only 2 training days had a snapshot
before the first canonical activity and a following-day feedback row.

The two feedback rows were counted by existence, not inspected for compatible
values, decisions or complete prediction eligibility. These are upper-bound
availability counts, not a frozen dataset or train/validation counts. No outcome
values, personal identifiers or test labels were exported. No split was selected.
Local database connectivity was unavailable; the production preflight succeeded.
Current evidence cannot satisfy the proposed coverage gates even before requiring
new response-capable inputs. No quality conclusion can be drawn from this inventory.

## Proposed first target and temporal unit

Use `next_day_recovery`, `prediction_type: point`, `scale: 1-5`, from
`workout_outcome_v1`. A continuous predicted score is evaluated against the
observed ordinal score using MAE in scale points. Equal category spacing is an
explicit approximation inherited from point evaluation; no calibrated probability
or clinical interpretation is claimed.

One observation is one user's local training day D. Determine the first canonical,
nondeleted, nonexcluded activity by start timestamp, then activity ID. Choose the
latest eligible same-day feature snapshot strictly before that first activity,
breaking capture ties by snapshot ID. Require:
`source_available_at <= cutoff_at <= captured_at < first_activity_start_at`.
Any required decision context must also precede that first activity.

If that first activity has no eligible pre-start snapshot/decision, exclude the day;
do not substitute a snapshot preceding only a later activity. Activities later in
the day never create additional recovery observations. The label is compatible
date-level recovery feedback on local D+1, following #132's schema/value rules.
The day key includes user identity, local date and timezone; never merge users.

The estimand is next-day reported recovery among observed training days, under
the realized mix of activity and other life events. The occurrence and workload of
those future activities are selection/outcome context, not pre-cutoff features.
This first version does not predict all calendar days or prescribe a session.

## Explicit candidate formula

Let R(c, X) be the offline replay of the existing readiness formula using reviewed
parameter recipe c and immutable feature evidence X. Preserve production numerical
operations: freshness clamp, feeling normalization, response component/channel
means, recency, configured-weight rounding, missing-family renormalization,
three-decimal contribution rounding, then one-decimal readiness rounding.
Baseline parameters are the production defaults represented by #137.

Predict recovery with the separately fitted, frozen association:

```text
x = R(c, X) / 100
predicted_recovery = clamp(alpha + beta * x, 1, 5)
```

This is a proposed statistical calibration layer, not an existing physiological
formula. Alpha and beta must be learned from train labels as described below.
Readiness/100 is only an explanatory covariate; it is never an outcome probability.
Do not assume beta is positive or force monotonicity unsupported by train evidence.

### Parameter effects

| Existing parameter | Role in this prediction |
| --- | --- |
| freshness_weight, recovery_evidence_weight | Change R through available-family composition |
| response_max_weight, response_enabled | Change R through captured baseline-backed response and recency |
| feeling_enabled | Controls available same-day morning recovery evidence |
| historical_physiology_enabled | Controls exact-date historical recovery evidence |
| recovery/endurance/moderate thresholds | No effect on R or recovery prediction; fixed at baseline defaults |
| load/physiology windows and manual physiology features | Fixed upstream or outside this first predictor |

If only freshness is available, renormalization can remove the effect of weight
changes. Report actual changes in readiness/predictions and affected observation
counts; do not claim every parameter is identifiable. A zero fitted beta can make
all candidate predictions identical. Neither condition warrants inventing effects.

## Baseline and train-only preparation

Propose a deterministic ordinary least-squares fit with intercept, performed once
using baseline-recipe readiness on eligible train days:

```text
x_bar = mean(x_i); y_bar = mean(y_i)
Sxx = sum((x_i - x_bar)^2)
beta = sum((x_i - x_bar) * (y_i - y_bar)) / Sxx
alpha = y_bar - beta * x_bar
```

Use a fixed observation-ID ordering, Python 3.11 binary64 arithmetic and a pinned
implementation for accumulation and canonical serialization. Nonfinite values
or Sxx <= 1e-12 fail with stable reasons; this tolerance is numerical, not a
physiology threshold. Do not round predictions to integer categories.

Fit only train; do not refit for each candidate, consume validation labels during
preparation, or fall back to a neutral/constant value when fitting fails. Freeze
alpha/beta, fit-method identity, baseline recipe/config hash, train membership
hash, feature/dataset identities and implementation hash in a private learned-state
artifact. The train membership hash must bind the actual train row hashes, including
labels used in fitting. Pin the full source dataset hash separately for provenance.
Store no training rows or labels in the learned-state artifact.

The primary baseline artifact evaluates R with baseline parameters through this
same frozen alpha/beta. Candidate parameters change only R; the association layer
is shared and fixed. This measures the effect of replacing the readiness recipe
inside a frozen predictor, not the quality of independently refitted models.
No additional composite or automatic winner selection is introduced.

Train-only supervised fitting is an explicit expansion beyond #55's initial
product rule-based scope, confined to #150's offline research contract. This
tradeoff requires review. If fitting is rejected, the formula must be replaced
by a separately justified rule contract; do not substitute an arbitrary scale
conversion to meet runner acceptance.

## Missingness, provenance and response capture

Missing scored families remain unavailable and are excluded by existing
renormalization rules. No scored family, invalid value, unsupported source version,
or an unprovable temporal boundary produces no prediction with a stable reason.
Require no synthetic replacement for missing planned/actual workout context.

New response-capable feature snapshots must distinguish:
`available`, proven `unavailable` with reason, and unsupported/missing capability.
Capture the selected response context, including activity date and its provenance,
activity/metric/formula versions, baseline values/current values/deviations/sample
counts, availability, source fetch timestamp, metric computation timestamp and
selection identity. All timestamps used as evidence must precede cutoff.
A proven no-eligible-response state permits the established missing-response
composition; a v1 payload without the capability fails even if response is disabled.

Read the selected sources consistently in the feature capture transaction. Preserve
the existing production formula and response date/selection semantics in replay;
do not fix production timezone behavior implicitly. Snapshot metadata must make
the stored date basis explicit. Failure to establish a supported basis is explicit.
Parity means the same formula on the same captured inputs; a separately materialized
readiness row from another computation time is not automatically an exact oracle.

Future workload/duration/TSS, post-workout RPE, D+1 feedback and target status are
absent from inference input. A prior-session RPE may be an input only as already
known response evidence. Same-day morning recovery concerns the previous day;
the label concerns D+1. Manual physiology is retained as evidence without becoming
a hidden readiness score.

## Version and migration proposal

These reviewed identities are now implemented in source; operational acceptance remains pending.

| Contract | Proposal |
| --- | --- |
| daily_feature_vector_v1 | Retain unchanged; legacy evidence remains readable |
| daily_feature_vector_v2 | Add complete response replay capability/provenance |
| temporal_dataset_v1 | Retain existing observation/hash semantics |
| temporal_dataset_v2 | Explicit training-day observations, first-activity attribution and stable IDs |
| workout_outcome_v1 | Reuse recovery definition and scale unchanged |
| readiness_parameter_space_v1 / readiness_parameter_candidate_v1 | Retain recipe meaning and validation |
| recovery_prediction_parameter_space_v1 / recovery_prediction_candidate_v1 | New complete config, supported readiness weights/toggles, fixed recommendation thresholds, pinned learned-state hash and compatible versions |
| prediction_artifact_v1 | Retain exact fields; learned-state identity belongs in config/audit metadata |
| baseline_evaluator_v1 | Retain frozen v1 validation and metric specification |
| baseline_evaluator_v2 | Explicit support for v2 day observations; same MAE/paired comparison semantics |
| research_execution_v1 | Preserve supported legacy requests and stable unsupported reasons |
| research_execution_v2 | Bind learned-state identity and new prediction/config identities |

Do not globally replace shared DATASET_VERSION or reinterpret old configs. Use
explicit version dispatch in export, validation, worker and audit persistence.
New dataset day IDs bind user/day/timezone, first activity, selected feature/decision
snapshots and target version. Manifest and row hashes bind the day attribution.
Existing audit lifecycle and column permissions should remain sufficient; verify
constraints before deciding on an additive migration.

New snapshots are captured prospectively. There is no backfill from mutable response
history, legacy snapshot rewrite, production readiness recomputation or promotion.
Any capture deployment/schema rollout needs separate operational authorization.
Historical labels in a frozen exported dataset remain frozen even if feedback is
later edited; a new export has a new hash.

## Comparison and coverage gates

Keep chronological train/validation/test boundaries frozen before model fitting.
Assign partitions by training day; do not move a day to the next partition because
feedback arrives on D+1. Require train feedback availability no later than the
declared fit-as-of boundary, strictly before the earliest validation prediction
cutoff. Outcome publication/receipt time must be retained and checked; a date alone
does not prove it was available to the fit. For this first slice use one user per
dataset and frozen state; no cross-user pooling.

Proposed engineering acceptance floors, subject to contract review:
at least 30 eligible train days and 20 paired validation days;
paired coverage >= 80% of compatible observed validation recovery targets
with eligible day-start context. These are operational floors, not statistical
power guarantees. Fix them before fitting and never lower them to pass a run.

Report the complete target/source funnel: canonical training days, absent snapshots,
incompatible inputs, absent/incompatible labels, baseline/candidate predictions,
paired days, missing predictions and coverage. Also report eligible target coverage
against all canonical days, so excluding difficult inputs cannot hide poor coverage.
Predictions are generated from feature eligibility regardless of label availability.

The frozen evaluator compares baseline and candidate on exactly the paired
observation IDs and scale. Delta MAE is candidate minus baseline; negative is
improvement. Valid execution does not require improvement. Low coverage means
`insufficient_paired_coverage` and a failed acceptance run, not a successful
candidate with empty metrics. Retain diagnostic evaluator output privately and
coverage counts in terminal audit metadata.

Test data remain closed during iteration. Never adjust splits, thresholds, features
or fit constants after inspecting test outcomes. Opening test later is a separately
authorized final evaluation step.

## Implementation and validation sequence after review

1. Implement versioned feature/capture and day-export contracts with explicit
   legacy rejection, first-activity ownership, source timestamps and stable hashes.
2. Add standalone deterministic recipe replay and train-only fit/preparation CLI.
   Preparation emits learned state plus frozen baseline predictions; inference
   imports no production config, DB clients or labels.
3. Add strict complete predictor config validation and audit version dispatch.
   Bind config, implementation/image, learned state, baseline and dataset hashes.
4. Extend the fixed worker and runner v2 request. The runner accepts a pinned
   learned-state artifact plus baseline, checks their binding before audit creation,
   and keeps feature-only inference then label-aware evaluation in two isolated
   containers. Training is explicit preparation, never implicit worker refitting.
   Verify the supplied baseline reproduces the same pinned model/state on inputs.
5. Test baseline formula parity/rounding, a real parameter-sensitive fixture,
   unchanged predictions for fixed thresholds, missing-family cases and unsupported
   v1 response capability. Cover zero-variance/nonfinite fits, train-only labels,
   receipt-time leakage, feedback edits, day ownership/input-order permutations,
   timezone boundaries, hashes, invalid states and repeatability.
6. Add a real model end-to-end fixture to the existing runner tests. Synthetic
   fixtures establish correctness, not real-data coverage or model quality.
   Run Backend CI's Linux Docker isolation/resource/cleanup checks and disposable
   PostgreSQL role/lifecycle checks; do not run write tests against production.
7. After separately authorized prospective capture rollout and sufficient new
   evidence, freeze a real dataset and baseline, then perform a separately
   authorized home-server smoke run using the #136 CLI and audit writer.
   Verify real paired coverage, terminal audit identity and container cleanup.
8. Update model/data/runner documentation and acceptance evidence. #150/#136
   stay incomplete while real-data or home-server requirements remain unmet;
   only then may #138 start.

## Accepted contract decisions

- Accept day-level next-day recovery as the first target and the ordinal MAE
  approximation, without planned-workout claims.
- Accept the explicit train-fitted affine association with one frozen mapper
  shared by baseline and candidates; it is an offline statistical model.
- Accept prospective v2 response capture/day attribution and separate predictor
  config identity, preserving all legacy v1 semantics.
- Accept the proposed coverage floors and the required data-collection delay.

No predictor implementation, schema change, deployment or home-server run is
included in this proposal delivery.
