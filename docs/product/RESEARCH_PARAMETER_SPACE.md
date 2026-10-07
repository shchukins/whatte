# Bounded readiness parameter space (#137)

## Implemented contract

`readiness_parameter_space_v1` defines a strict, data-only candidate configuration
for the existing readiness composition and recommendation categories. It does
not execute a candidate, build predictions, search, schedule, or promote a model.
Production calculations continue to use their existing constants.

The baseline configuration represents the current
`v2_signal_composition_response_v1` recipe exactly: freshness weight 0.6,
recovery evidence budget 0.4, maximum response weight 0.2, all three optional
signal families enabled, and recommendation thresholds 40/60/75. The source
model version pins normalization, response channel selection/averaging, recency,
rounding, clamping, missingness, and probability-like presentation semantics.
`readiness_parameter_candidate_v1` identifies this parameter contract, not a
production model write version or an implemented prediction engine.

## Allowed parameters

Every field is required. Defaults are annotations in the machine-readable schema
and are exported as a complete baseline config; validation never silently fills
an incomplete config. Unknown fields, numeric strings, boolean-as-number values,
non-finite numbers, and unsupported versions are rejected.

| Parameter | Type | Inclusive bounds / set | Default | Meaning |
| --- | --- | --- | --- | --- |
| `freshness_weight` | number | 0.4–0.8 | 0.6 | Weight before availability renormalization |
| `recovery_evidence_weight` | number | 0.2–0.6 | 0.4 | Evidence budget shared by response and recovery signals |
| `response_max_weight` | number | 0–0.3 | 0.2 | Maximum weight of a current usable response |
| `response_enabled` | boolean | true / false | true | Enable baseline-backed response evidence |
| `feeling_enabled` | boolean | true / false | true | Enable available morning recovery evidence |
| `historical_physiology_enabled` | boolean | true / false | true | Enable exact-date historical recovery score |
| `recovery_threshold` | number | 0–100 | 40 | Exclusive upper boundary for recovery |
| `endurance_threshold` | number | 0–100 | 60 | Exclusive upper boundary for endurance |
| `moderate_threshold` | number | 0–100 | 75 | Inclusive upper boundary for moderate |

Weight bounds are explicit engineering limits for the first research space,
not physiological estimates or evidence of better outcomes. They retain a
substantial freshness contribution and cap the optional response contribution.
Threshold bounds follow the existing 0–100 readiness scale. Boundary choices
may yield empty extreme categories; no minimum category width is implied.
Changing any allowed range or semantic rule requires a new search-space version.

Required pinned string fields and their sole allowed/default values:

| Field | Value |
| --- | --- |
| `search_space_version` | `readiness_parameter_space_v1` |
| `candidate_model_version` | `readiness_parameter_candidate_v1` |
| `baseline_source_model_version` | `v2_signal_composition_response_v1` |
| `feature_vector_version` | `daily_feature_vector_v1` |
| `dataset_version` | `temporal_dataset_v1` |
| `evaluator_version` | `baseline_evaluator_v1` |

## Compatibility and fixed behavior

- Freshness weight plus recovery evidence weight must equal 1, within an
  absolute binary-float tolerance of `1e-12`; values are not normalized for users.
- Maximum response weight must not exceed the recovery evidence budget.
- Disabled response requires maximum response weight zero.
- Recommendation thresholds must be strictly increasing.
- Response uses fixed seven-day recency and the existing ratio/drift scoring
  constants (2 points per deviation percent and 10 points per drift percentage
  point). Its actual weight is reduced by recency and baseline availability.
- After subtracting response weight, the remaining evidence budget is split
  equally between enabled, available feeling and historical physiology signals.
  Missing/disabled signals carry no score contribution; available weights are
  renormalized. No new synthetic neutral value or fallback is introduced.
- Load remains context scored through freshness, never another weighted signal.
- Manual physiology remains raw/derived research evidence. It is not a readiness
  score and cannot substitute for the historical physiology signal.

The exported JSON Schema describes field types, allowed values, bounds, and
requiredness. `x-compatibility-constraints` documents cross-field comparisons;
these are enforced by `validate_candidate_config`, not by generic JSON Schema
engines. All callers must use that validator before recording or executing a run.

## Immutable input limitation

HRV/RHR/sleep baseline windows (currently 28 days / minimum 7 observations),
load decay constants (40/4/9 days and fatigue weights 0.65/0.35), and response
baseline construction are not tunable in this space. Their outputs are already
materialized in immutable feature snapshots; changing these inputs would require
a separately versioned, leakage-safe history contract.

The present feature dataset does not contain all comparable-session response
baseline context needed to replay the production formula exactly. A future
runner must explicitly validate input capabilities and reject unsupported replay;
it must not silently disable response, reconstruct history from current DB state,
or manufacture missing baseline evidence. Baseline recipe representation here
is not a claim of executable baseline replay on every existing dataset.

Readiness and recommendation are not RPE/recovery predictions. This contract
adds no mapping from readiness or `good_day_probability` to workout outcome
values. Candidate prediction semantics remain an explicit prerequisite for #136.
The frozen evaluator and its metrics cannot be configured by candidates.

## CLI and experiment persistence

Run from `backend/`:

```bash
python -m scripts.validate_research_config --schema
python -m scripts.validate_research_config --baseline
python -m scripts.validate_research_config --config /outside-repository/candidate.json
```

Validation returns normalized config and its canonical SHA-256 hash. Invalid
input exits nonzero. The CLI and schema module have no database dependency.

`create_research_experiment` now validates the complete config and verifies that
its model/dataset/evaluator versions match the experiment metadata before DB
access. The search-space version is persisted inside immutable `candidate_config`
and included in `candidate_config_hash`; no migration is needed. Existing audit
rows remain unchanged. New unversioned configs are rejected deliberately.

The runner must additionally verify actual feature/dataset/evaluator versions,
artifact hashes, selected partition, test access, and implementation identity.
An audit config alone does not prove that its claimed inputs were used.

## Runner infrastructure (#136, partial)

[The isolated runner](RESEARCH_RUNNER.md) now validates this configuration before
execution and records explicit unsupported failures. Its fixed candidate worker
does not yet implement outcome predictions or response replay. This does not
turn the parameter recipe into an executable/calibrated prediction model.
