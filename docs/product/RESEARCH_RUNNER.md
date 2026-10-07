# Isolated parameter experiment runner (#136)

## Status

Infrastructure is implemented, with local unit/protocol tests. Actual Docker,
cgroup and PostgreSQL permission checks are wired into Backend CI; they must
pass on Linux before operational use. A home-server smoke run remains pending.

The real candidate success path is **not implemented**. The strict
`readiness_parameter_candidate_v1` contract describes a readiness recipe rather
than RPE/recovery predictions. Immutable `daily_feature_vector_v1` snapshots also
lack comparable-session response baseline context. The built-in worker records
`response_baseline_context_not_snapshotted` when response is enabled, otherwise
`outcome_prediction_contract_not_implemented`. It never silently disables a
feature, reads mutable DB history, or substitutes readiness/100 for an outcome
probability. #136 remains partial until a reviewed outcome-prediction contract,
compatible immutable inputs and a real successful run satisfy its acceptance
criteria. Synthetic success fixtures validate infrastructure only.

## Boundaries and protocol

The trusted host supervisor loads bounded JSON files, validates the full candidate
config, pinned dataset manifest/row hashes, feature/target versions, partition,
and frozen baseline artifact. Test access requires
`WHATTE_RESEARCH_TEST_ACCESS=granted`. It creates one running audit record and
executes at most two sequential containers, with fixed
`python -m scripts.research_worker` entrypoints:

1. Candidate input contains config, dataset hash, partition, config hash and
   feature-only observations. It contains no outcomes, decisions, baseline
   predictions, other partitions, database credentials or host environment.
2. Evaluator input contains only the selected dataset partition, frozen baseline
   artifact and candidate artifact. It uses `baseline_evaluator_v1` and its pinned
   metric specification. The host independently verifies the frozen output.

`research_execution_v1` request objects carry `operation: candidate | evaluate`.
Successful responses have `protocol_version`, `status: ok`, and `result`.
A successful candidate response additionally carries `candidate_config_hash`;
its `prediction_artifact_v1.candidate_id` is that hash and `candidate_version`
matches the candidate config. Logical candidate identity remains stable across
unique experiment IDs, so identical artifacts/inputs reproduce evaluation hashes.
The built-in candidate worker currently returns `status: unsupported` and a
fixed reason code, exits nonzero, and the supervisor records `failed`.

No arbitrary model module, Python expression, command, environment variable or
metric setting is accepted from candidate configuration. Operator-provided image
IDs/digests are trusted implementation artifacts and must come from reviewed
code. A digest pins bytes; it does not establish approval or model validity.

The evaluator imports only data contracts, not production settings/DB services.
The research image deliberately omits the application, `.env`, DB client and
production services. Neither container receives the Docker socket, host devices,
production volumes, or database connectivity. Filesystem is read-only except
bounded `/tmp`; network is disabled; UID/GID is 65534; capabilities are dropped;
privilege escalation is disabled. Input mount is read-only. Docker logging is
turned off and attached stdout/stderr are drained into bounded private files.

## Host requirements and limits

Use a dedicated trusted supervisor account and a local Linux Docker Engine with
cgroup v2. The supervisor needs Docker access; container workers do not. The
runner rejects unsupported host/cgroup configurations. Do not connect it to a
remote Docker daemon whose host cannot access the local input mount paths.

| CLI option | Default | Allowed range |
| --- | --- | --- |
| `--timeout-seconds` | 120 | 1–3600 |
| `--cpus` | 1 | 0.1–4 |
| `--memory-mb` | 512 | 64–4096 |
| `--pids` | 64 | 16–256 |
| `--tmp-mb` | 32 | 1–256 |
| `--output-bytes` | 8388608 | 1024–16777216 per output stream |
| `--input-bytes` | 67108864 | 1024–134217728 per input file/request |

These are engineering bounds and initial defaults, not measurements of the home
server. Select limits against available capacity before a smoke run. Memory plus
swap is capped at the same memory limit. Wall-clock timeout includes daemon
preflight, container creation/start and execution for each stage. Inspection and
cleanup use additional bounded control-call timeouts (5/10 seconds); a successful
run has at most two stages. No scheduler or concurrency/search loop is provided.
Supervisor JSON loading/validation and result verification occur on the trusted
host, with file-size bounds; container CPU/RAM limits do not apply to that host
process. Run the supervisor under host service limits if stronger bounds are
needed for its own memory/CPU usage.

## Dedicated audit writer

Apply `db-init/019_research_execution_metadata.sql` after migration 018 using the
usual separately authorized schema rollout. It adds nullable terminal
`execution_metadata` and a NOLOGIN permission group `whatte_research_writer`.
Existing audit rows remain valid and immutable.

Provision a separate LOGIN externally with membership only in that group, no
production table ownership/write grants, no superuser/CREATEDB/CREATEROLE/
REPLICATION/BYPASSRLS attributes, and no unsafe inherited privileges. Do not use
backend credentials. The permission group can SELECT/INSERT audit inputs,
UPDATE only terminal result fields and use the audit ID sequence. It cannot
DELETE audit rows; the existing lifecycle trigger prevents terminal mutation.
Connection preflight rejects elevated membership, other table write grants,
executable application SECURITY DEFINER functions and writable user schemas.

The CLI reads only `WHATTE_RESEARCH_DATABASE_URL` for persistence and never falls
back to `DATABASE_URL`. Credentials stay in the trusted host process. Neither
logs, receipts nor CLI errors contain connection strings. The terminal audit
record stores evaluator metrics separately from exit status, timeout/OOM flags,
limits, duration and private log references. Immutable input metadata pins image,
baseline artifact hash, supervisor source hash and metric specification hash.

## Command

Build from the reviewed backend source on the research host; retain the resulting
immutable image ID, then supply that ID (or a reviewed registry digest) to the CLI:

```bash
docker build -f backend/Dockerfile.research -t whatte-research:reviewed backend
docker image inspect --format '{{.Id}}' whatte-research:reviewed
```

Run from `backend/` with the separately provisioned research DSN in the environment:

```bash
python -m scripts.run_research_experiment \
  --config /private-research/candidate.json \
  --dataset /private-research/dataset.json \
  --baseline /private-research/baseline-predictions.json \
  --partition validation --experiment-id run-001 \
  --hypothesis 'Explicit experiment hypothesis' \
  --image sha256:REVIEWED_IMAGE_ID \
  --output-root /private-research/runs \
  --timeout-seconds 120 --cpus 1 --memory-mb 512
```

The output root must be private (mode 0700); experiment directories cannot already
exist. Image pulls, builds and mutable tags are forbidden during execution.
Validation errors happen before audit creation; invalid configs cannot enter the
strict #137 audit contract. Supported execution failures and unsupported models
end in `failed`; a validated successful evaluation ends in `candidate`. This
status does not imply winner selection, statistical improvement or promotion.
The CLI exits nonzero for failures; JSON stdout contains only status/references.
`receipt_updated: false` signals a local receipt-write failure after the audit
transition; inspect the DB as the source of truth. A full local disk does not
prevent terminal audit persistence.

## Recovery and retention

Artifacts remain outside the repository in a private directory per experiment:
`receipt.json`, each stage's read-only request, bounded `stdout.json` and
`stderr.log`. These files can contain personal feature/target/prediction data;
they never enter the audit table. Retention and removal are operator-managed.

Timeout/output overflow triggers client termination, container kill, inspection
and forced removal. Cleanup failure is itself a failed run, never a successful
result; the private receipt retains the unique container name for manual cleanup.
An unresponsive Docker daemon can prevent removal; verify the referenced container
is gone before starting more work. In-memory execution is not retried.

If audit persistence fails, the CLI fails and retains a private receipt with
`persistence_failed`. If creation fails, its receipt stays `creating`. Reconcile
against the audit DB before retrying anything: a network error can occur after
commit. Duplicate IDs never overwrite records or artifacts. A supervisor crash
or lost connectivity can leave `running` records; there is no automatic recovery
or scheduler. Use the existing terminal persistence interface after verifying
container cleanup and recorded inputs. Never modify a terminal record.

## Validation

Local tests exercise config rejection, synthetic success, unsupported requests,
version/hash integrity, frozen evaluator verification, repeatability, persistence
failure, real pipe draining, timeout termination and output caps. Opt-in integration
checks require isolated/disposable environments:

```bash
RUN_DOCKER_TESTS=1 python -m pytest tests/test_research_container_integration.py -v
RUN_DB_TESTS=1 python -m pytest tests/test_research_writer_integration.py -v
```

Backend CI runs both groups. Docker fixtures test actual read-only mounts, UID,
network isolation, cgroup CPU/RAM/PID settings, OOM, timeouts, failures, output caps
and container removal; they do not implement a production prediction model.
SQL checks verify dedicated-role audit writes, production write denial, duplicate
IDs and terminal immutability.

## Follow-up dependency

[Issue #150](https://github.com/shchukins/whatte/issues/150) defines and implements
the deterministic offline outcome-prediction contract and compatible immutable
inputs. Complete that dependency and a real end-to-end run before closing #136
or starting the #138 search loop. The broader product prediction layer remains #55.
