# Immutable training-day research dataset

`temporal_dataset_v2` supports the first offline recovery predictor. It retains the
`workout_outcome_v1` definition while making the observation unit explicit.

One observation is one user/local training day, selected from the first canonical
activity ordered by start timestamp then activity ID, before any eligibility
filtering. Missing first-activity decision/snapshot evidence excludes the day;
a later activity cannot take ownership. Only the latest eligible same-day snapshot
strictly before that first activity is used, with ID as the capture-time tie break.

Each row binds user/day/timezone, first activity ID/start, immutable feature and
decision snapshot IDs, cutoff/capture boundaries and independent recovery evidence.
The observation ID binds those identities and target version. Row hashes bind
the complete row, including the frozen feedback value/update timestamp.
The manifest hash binds source snapshot IDs, row hashes, chronological split,
versions/timezone and canonical day counts. One user per dataset is supported.

Available recovery targets require local D+1 attribution and a feedback update
timestamp no earlier than that target local date. Features obey
`source_available_at <= cutoff_at <= captured_at < first_activity_start_at`;
the decision computation and capture must also precede the first activity.
The evaluator validates identities, timezone, partition dates, row/manifest hashes
and unique day ownership. No activity workload becomes a pre-workout covariate.

V1 export semantics and hashes remain unchanged. V2 rejects/excludes v1 snapshots
with `response_baseline_context_not_snapshotted`; it never upgrades them from
mutable DB history. Export defaults to v1; select `--dataset-version temporal_dataset_v2`
explicitly. V2 supports JSON/JSONL. Test rows are withheld without explicit access.

Outcome sources are current canonical feedback at export time; the exported
dataset is the frozen boundary. Feedback edits make a new export/hash, rather than
mutating an existing dataset. The exporter retains the existing separate read-only
transactions for outcome/decision records and feature snapshots; it does not claim
a single database-wide historical as-of transaction. Keep exports outside the repo.

See [RECOVERY_PREDICTION.md](../models/RECOVERY_PREDICTION.md) for fitting receipt-time
boundaries, minimum coverage, learned state and execution.
