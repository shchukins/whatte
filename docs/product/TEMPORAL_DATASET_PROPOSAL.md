# Versioned temporal research dataset (#133)

## Status

Implemented as an offline, read-only export contract. It does not train a
model, select a candidate, alter readiness, or commit personal records.

## Observation boundary

An activity observation is eligible only when it has both:

- an immutable `research_feature_snapshot` captured before the activity starts;
- an eligible pre-activity `decision_context_snapshot` and the independent
  `workout_outcome_v1` target envelope.

The feature snapshot is built with `daily_feature_vector_v1` using its recorded
`cutoff_at`. Current rows are never used to reconstruct a missing historical
snapshot. A missing snapshot is reported as an excluded observation rather
than silently filled from current state.

The stable observation identity is a SHA-256 digest of the user, canonical
activity ID, chosen feature snapshot ID, chosen decision snapshot ID, feature
version, and target version. It deliberately excludes export time and dataset
partition so the same source observation retains its identity across exports.

## Temporal partitions

`temporal_dataset_v1` accepts four inclusive local-date bounds:

```text
train_start .. train_end
train_end + 1 .. validation_end
validation_end + 1 .. test_end
```

All bounds and the supplied timezone are part of the manifest. The builder
rejects reversed or overlapping ranges. It does not randomize, shuffle, or
cross-validate. Empty partitions are valid and remain explicit in the
manifest.

The normal export contains train and validation only. Test rows are withheld
unless the caller passes `--include-test` and supplies
`WHATTE_RESEARCH_TEST_ACCESS=granted`. Production access must additionally use
a separate research principal and output location; a local CLI environment
variable is an explicit guard, not an authorization system by itself.

## Targets and missingness

Each row retains the full versioned target envelope and all feature
availability/reason-code metadata. Missing or incompatible targets do not
become zeros or cause another target to disappear. `next_day_recovery` is
included only on the earliest eligible activity for each local training day;
later activities expose `shared_training_day_target` instead, so one feedback
row is not copied into several independent training examples.

## Reproducibility

Rows are sorted by `(activity_start_at, observation_id)`. Every row gets a
canonical JSON hash; the manifest records the sorted row hashes, source
snapshot IDs, split configuration, feature and target versions, and a dataset
hash. `generated_at` is presentation metadata and is not part of that hash.

The CLI writes JSON, JSONL, or CSV to stdout only. Redirect output outside the
repository and never commit it.
