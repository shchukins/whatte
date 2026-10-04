# Frozen research evaluator (#134)

## Status and boundary

`baseline_evaluator_v1` is an offline, read-only evaluator for prediction
artifacts produced against one immutable `temporal_dataset_v1` partition. It
does not train a model, execute candidate code, change production state, select
a winner, or promote a candidate.

The evaluator accepts prediction data rather than a Python callback or model
module. Candidate execution and isolation belong to the later research runner.
This keeps metric definitions outside the candidate boundary: a candidate
cannot provide metric names, calibration bins, log-loss clipping, or comparison
rules.

The current production recommendation permits a category of training; it does
not predict a particular RPE or next-day recovery value.
`good_day_probability` is not treated as a calibrated probability and is not
silently mapped to any `workout_outcome_v1` target.

## Prediction artifact

Each baseline or candidate uses `prediction_artifact_v1`:

```json
{
  "prediction_schema_version": "prediction_artifact_v1",
  "candidate_id": "example-candidate",
  "candidate_version": "v1",
  "dataset_hash": "<temporal dataset manifest hash>",
  "partition": "validation",
  "target_specs": [
    {
      "target_name": "post_workout_rpe",
      "prediction_type": "point",
      "scale": "1-10"
    }
  ],
  "predictions": [
    {
      "observation_id": "<stable observation id>",
      "targets": {
        "post_workout_rpe": {"value": 6.5}
      }
    }
  ]
}
```

Top-level fields and target-spec fields are exact. Unknown fields are rejected,
so an artifact cannot inject its own evaluator configuration. Observation IDs
must belong to the selected partition and cannot repeat. The artifact dataset
hash and partition must match the input dataset.
The evaluator recomputes the temporal manifest hash and each visible row hash
before scoring, and rejects modified dataset content.

Supported v1 prediction types:

- `point`: a finite numeric `value`; evaluated with MAE against an available
  target on the exact declared scale;
- `binary_probability`: a finite `probability` from 0 through 1; evaluated only
  against an explicitly available binary target with `value` equal to `0`,
  `1`, `false`, or `true` and scale `binary`.

RPE 1–10, historical RPE 1–5, and next-day recovery 1–5 are separate target
series. The evaluator never converts between scales. The temporal dataset's
`shared_training_day_target` rows remain ineligible, so one recovery response
is not scored once per activity.

## Metrics and denominators

Every target result includes:

- partition row count;
- eligible, scored, missing-target, incompatible-target,
  missing-prediction, and invalid-prediction counts;
- all observed target status counts;
- target-specific metrics, or `null` when the scored denominator is zero.

Point predictions expose MAE. Compatible binary probabilities expose Brier
score, log loss, and a ten-bin calibration table. Expected calibration error
is the observation-count-weighted mean absolute difference between each
non-empty bin's mean probability and observed positive rate. Bins are
`[0.0, 0.1)`, ..., `[0.9, 1.0]`. Log loss clips probabilities with the fixed
evaluator constant `1e-15` to keep JSON finite.

The output contains the evaluator version and a SHA-256 hash of its canonical
metric specification. Changing a metric, bin rule, comparison rule, or
clipping constant requires a new evaluator version.

## Baseline comparison

Baseline and candidate are reported independently. Their comparison is
recomputed only on observation IDs that both artifacts scored for the same
target, prediction type, and scale. It reports the paired denominator,
baseline metrics, candidate metrics, and `candidate_minus_baseline` deltas.
All v1 metrics are errors, so a negative delta is lower, but the evaluator does
not collapse them into a score or declare a winner. Candidate selection rules
belong to the deterministic search-loop contract.

## CLI

Run from `backend/`:

```bash
python -m scripts.evaluate_research_candidate \
  --dataset /outside-repository/dataset.json \
  --partition validation \
  --baseline /outside-repository/baseline.json \
  --candidate /outside-repository/candidate.json
```

The stable JSON result is written to stdout. Personal datasets, predictions,
and results must remain outside the repository. Test evaluation additionally
requires `WHATTE_RESEARCH_TEST_ACCESS=granted`, matching the explicit-access
boundary of the temporal dataset export. This environment guard is not a
production authorization system; the future isolated runner must also use a
separate research principal and pinned evaluator artifact.
