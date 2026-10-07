# Research experiment audit log (#135)

## Status and boundary

`research_experiment_v1` persists the audit metadata of one offline research
experiment. It is not an experiment runner, parameter-search loop, API, or
promotion mechanism. It cannot execute candidate code and it does not store
feature vectors, raw source data, prediction artifacts, or personal temporal
dataset rows.

Each record binds an intended candidate to immutable inputs:

- a hypothesis, candidate model version, canonical configuration, and SHA-256
  configuration fingerprint;
- a `temporal_dataset_v1` version/hash/partition;
- a frozen evaluator version and metric-specification hash;
- optional parent and baseline experiment references.

The terminal `metrics_json` stores the machine-readable output of the frozen
evaluator only after an experiment finishes. A failure instead records a
non-empty reason and optional external log reference. The actual logs and all
personal artifacts must remain outside the repository.

## Lifecycle

```text
create -> running -> candidate | rejected | failed
```

Both SQL and the service enforce one terminal transition. Candidate input
metadata, result/failure metadata, and terminal rows are immutable; deletion
is rejected. `promoted` exists in the stored status vocabulary solely for the
later explicit manual-promotion contract (#141). #135 exposes no path to set
it and performs no automatic promotion.

## Production boundary

The service queries and writes only `research_experiment`. It has no FastAPI
route or production-model integration. The later isolated runner (#136) must
use a separate research principal and pinned artifacts; this audit table is not
an authorization boundary by itself.

## Candidate validation (#137)

New records require the complete versioned
[`readiness_parameter_space_v1`](RESEARCH_PARAMETER_SPACE.md) configuration.
Creation validates all parameters and model/dataset/evaluator version bindings
before database access. The search-space version lives inside the immutable
configuration and participates in its canonical hash. Existing audit records
are preserved; new unversioned configurations are rejected.

## Isolated execution infrastructure (#136, partial)

Migration 019 adds optional terminal `execution_metadata` for resource limits,
exit/timeout/OOM/cleanup state and external log references. `metrics_json` remains
frozen evaluator output. The separate research writer uses column-level SQL grants
and no production table permissions; containers never receive its credentials.
See [research runner](RESEARCH_RUNNER.md) for the partial status, image/source/baseline
pinning, recovery procedures and outstanding outcome-prediction prerequisite.
