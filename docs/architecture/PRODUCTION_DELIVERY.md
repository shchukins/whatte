# Production delivery

Status: audited current state; proposed target architecture for #185 / epic #184.
Audit date: 2026-10-11 (Europe/Moscow). Architecture approval and production
activation are separate steps. Nothing described as planned below is enabled.

## Decision

Keep the existing single VPS, PostgreSQL volume, host Caddy and Docker Compose.
Use GitHub Actions for verification and release publication, GHCR for immutable
images, and ordinary OpenSSH over Tailscale for deployment transport. Adopt
Flyway Community SQL versioned migrations as a one-shot deployment tool, not a
new persistent service. Deploy backend and worker from the same image digest.

This recommendation preserves SQL-first development and the deterministic
product core. It requires no Kubernetes, new database, production AI component,
or change to physiology/readiness logic. Approval of this document selects the
mechanism for #187; it does not authorize schema writes or automated deployment.

## 1. Evidence and current production topology

Read-only SSH inspection of `human-engine-eu` succeeded. Repository and VPS
checkout both reported `89f203ddf3a901580232409c16f826684f9f0178`; both worktrees
were clean at inspection. Inspection used Compose metadata, selected Docker
inspect fields, file permissions/config equality, service/timer inventories,
filesystem metadata, HTTP checks and catalog SQL inside `BEGIN READ ONLY`.
Environment values, credentials, user rows and backup contents were not collected.

| Component | Verified current state |
| --- | --- |
| Host | `human-engine-eu`; app checkout `/srv/human-engine`; Docker Compose v5.5.1 |
| Backend | `human-engine-backend`; local build; Uvicorn `backend.app:app`; `127.0.0.1:8000` published; writable `/srv/human-engine/backend:/app` bind mount |
| Worker | `human-engine-worker`; separate local build; `python -m backend.worker`; no source mount or published host port |
| Database | `human-engine-postgres`; `pgvector/pgvector:pg16-trixie`; PostgreSQL 16.14; `vector` 0.8.3 and `plpgsql` 1.0 |
| Data | Named volume `human-engine_postgres_data` mounted at `/var/lib/postgresql/data`; host `db-init` mounted at `/docker-entrypoint-initdb.d` |
| Network | All three app containers on `human-engine_default`; PostgreSQL port 5432 bound to the host's Tailscale address by `compose.override.yaml` |
| Edge | Host `caddy` active; `/etc/caddy/Caddyfile` byte-identical to tracked `infra/eu-edge/Caddyfile`; TLS/public proxy to loopback backend |
| Access | Main-domain `/today*` and `/dashboard*` use Basic Auth; API-domain versions blocked; `/today` returned 401 and API `/today` 404 without credentials |
| Health | Local `/healthz`: `{"ok":true}`; local `/dbz`: `{"db":"ok"}`; public API `/healthz`: HTTP 200; PostgreSQL container healthy |
| Secrets | Host `.env` via `env_file` in all three services; includes database, Strava and Telegram credentials; `.env` mode 0664, owned by deployment user |
| Administrative access | Current SSH user belongs to Docker group and has unrestricted passwordless sudo; database role used for inspection is a superuser |
| Tailscale | `tailscaled` active, client 1.102.4; ordinary host SSH service active |
| Other services | An unrelated VPN container runs on this VPS; no running Grafana/Loki/Promtail containers appeared in `docker ps` |
| Capacity snapshot | Root filesystem 38 GB, about 30 GB free; application database about 35 MB; capacity is not a restore benchmark |

Backend and worker image IDs differ, neither has an OCI revision label, and
their container creation dates differ (October 11 and October 8 respectively).
The checkout SHA is therefore **not evidence of a coherent running release**.
The backend mount can expose checked-out code independently of the built image;
the worker runs packaged code. Exact worker source revision remains unverified.

### Repository discrepancies and unverified facts

- Root [compose.yaml](../../compose.yaml) describes the VPS app but has no
  database host port. The active untracked override adds the Tailscale binding.
  Future explicit production Compose must preserve this access deliberately;
  copying root Compose alone is not configuration parity.
- [infra/README.md](../../infra/README.md) and
  [infra/home/README.md](../../infra/home/README.md) retain home-node classification
  and NAS assumptions. The verified primary backend/worker/database are on the VPS.
- Tracked observability Compose publishes Grafana/Loki ports and contains a
  default Grafana credential; it is not evidence of an active VPS stack. Do not
  activate it as part of delivery or restart unrelated VPN/monitoring services.
- Tracked Caddy contains a Basic Auth password hash, despite infrastructure
  notes saying edge credentials are absent. Do not reproduce it in release
  metadata/logs; later separate secret configuration and review exposure.
- `.env` is Git-ignored, but `compose.override.yaml` is neither tracked nor
  ignored by the current `.gitignore`. Its absence from VPS `git status` does
  not explain the host's exclusion rules; do not assume it is versioned.
- Tailnet ACLs, public/cloud firewall policy, Tailscale SSH mode, GHCR package
  visibility/pull credentials, GitHub environment protection availability,
  external backup services and provider snapshots were not verified. Existing
  operator SSH does not prove a GitHub runner can connect with restricted access.
- Catalog inspection found 35 public tables, including historical HealthKit,
  research tables and `document` / `document_chunk`. No Flyway/Alembic migration
  history table appeared. Verified profile constraints include `hr_max` from
  `020`; this is a spot check, not proof every historical SQL file was applied.

## 2. Current manual delivery

The current repository has tests in
  [.github/workflows/backend-ci.yml](../../.github/workflows/backend-ci.yml),
including a twice-run database bootstrap and integration tests. It has no
production image publication or deploy workflow. Deployment is operator-driven:
the server builds from checkout rather than pulling a verified release.

The following describes the existing code-only command path, **not commands
executed during this audit**. Preconditions are successful CI for the selected
commit, clean server checkout and explicit review of schema requirements:

```bash
ssh human-engine-eu
cd /srv/human-engine
git status --short
git fetch origin
git merge --ff-only origin/main
git rev-parse HEAD
docker compose config --quiet
docker compose up -d --build --no-deps backend
docker compose ps
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/dbz
curl -fsS https://api.shchukin.de/healthz
```

Worker changes require explicitly including `worker` in the application rollout.
Backend-only updates explain a possible release mismatch; future delivery must
always account for both services. `origin/main` is a mutable target: current
manual operation must verify the resulting SHA equals the tested/authorized SHA.
Existing SQL updates are manually selected and applied with `psql -v
ON_ERROR_STOP=1 ... -f <reviewed-file>`; there is no verified persistent migration
ledger. The exact historical sequence of production SQL executions is unknown.

Edge deployment is separately documented in
[infra/eu-edge/README.md](../../infra/eu-edge/README.md): copy the Caddyfile,
validate, reload Caddy, then check public health. The existing `deploy.sh`
overwrites the active file before validation and masks its final health failure
with `|| true`; it must not be reused as the automated app deployment gate.

## 3. SQL lifecycle and selected migration mechanism

Docker entrypoint initialization only handles a fresh data directory. Adding
`db-init/*.sql` does not upgrade the existing volume. Root `db-init` alone is
also not a complete fresh schema: base tables under `sql/` are prerequisites.
[bootstrap_schema.sh](../../backend/tests/integration/bootstrap_schema.sh)
explicitly orders ingestion, profile, health and analytics tables before the
numbered changes `001`–`020`. CI replay proves that selected bootstrap can run
twice; `IF NOT EXISTS` does not validate existing definitions or detect drift.

Historical files include schema creation, constraint replacement, functions,
triggers and data backfills (`007` canonical activity IDs, `020` profile HR max).
Transaction handling is mixed: `020` contains `BEGIN`/`COMMIT`, while other files
can execute several statements without a file-wide transaction under plain psql.
Some `ALTER TABLE IF EXISTS` clauses silently skip absent dependencies. Replaying
all files against production is neither baseline verification nor a safe upgrade.

| Option | Fit and tradeoff |
| --- | --- |
| Flyway Community (selected) | Native ordered SQL migrations, schema history, checksum validation, explicit baseline, PostgreSQL transactional locking. Adds a pinned CLI/container and Java runtime outside the application. |
| Alembic | Fits Python and supports explicit SQL, but its normal revision scripts/version table require extra checksum and concurrent-execution controls for #187. ORM/autogeneration is unnecessary for this SQL-first project. |
| Custom psql/Python runner | Reuses existing tools but makes us maintain history, checksum validation, locking and failure recovery ourselves. Avoid rebuilding those guarantees. |

Flyway [validate](https://documentation.red-gate.com/flyway/reference/commands/validate)
checks stored migration checksums; its
[PostgreSQL support](https://documentation.red-gate.com/flyway/reference/database-driver-reference/postgresql-database)
uses transactional locking by default. These capabilities make it the preferred
mechanism; pin and test the selected Community distribution/image in #187.
Do not depend on paid schema-diff/undo capabilities. SQL checksums detect edits,
not all manual database drift; independent catalog assertions remain required.

### Baseline adoption in #187 (planned)

1. Build a reviewed `V1__baseline.sql` from the full ordered schema for an empty
   database, preserving existing SQL semantics. Inventory each original file,
   ordering, extensions and objects; identify app-managed versus legacy/auxiliary
   objects such as `document` tables explicitly. Keep historical files intact.
2. Test a fresh PostgreSQL 16 + pgvector database, replay/no-op behavior, catalog
   assertions, existing integration tests, checksum mismatch, concurrent runners,
   interrupted/failed migration and old-app/new-schema compatibility.
3. Compare production catalog definitions against that baseline: columns/types,
   defaults, constraints, indexes, functions/triggers, extensions and ownership.
   Table presence alone is insufficient. Validate backfill postconditions with
   aggregate checks; do not export private rows into Git.
4. Document and resolve mismatches explicitly, without deleting legacy data or
   pretending skipped scripts ran. Verify a restorable backup before any writes.
5. After separate authorization, record an explicit Flyway baseline at version 1.
   Existing production must **not execute V1**. A new empty database executes V1;
   future changes use V2 onward. Store the reviewed baseline manifest/hash since
   a baseline marker does not checksum the skipped V1 script.

Flyway [baseline](https://documentation.red-gate.com/flyway/reference/commands/baseline)
excludes migrations through the chosen version; it does not compare schemas.
Keep `baselineOnMigrate=false`, `cleanDisabled=true`, out-of-order migration
disabled, and validation enabled. Never automatically `repair` checksum/history
failures. Applied migrations are immutable; corrections get a new version.

Use one transaction per normal migration and bounded lock/statement timeouts.
Normalize transaction ownership in newly prepared migrations instead of blindly
wrapping files with embedded commits. Nontransactional operations such as
`CREATE INDEX CONCURRENTLY`, large backfills, destructive constraints or drops
require explicit classification, approval and recovery procedures. A tool lock
does not prevent unrelated SQL or application writes. New app startup must not
run migrations; a separately privileged one-shot job owns that responsibility.

## 4. Target release and deployment sequence (planned)

```text
selected main SHA -> required CI -> build once -> GHCR image digest
 -> production approval/eligibility -> Tailscale + restricted OpenSSH
 -> host deployment lock -> backup + migration validation
 -> approved migrations -> backend + worker rollout -> verification
 -> durable release result -> issue lifecycle eligibility
```

GitHub Actions is already used for CI. GHCR supports
[pulling by digest](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry);
use one digest for API and worker commands, with source SHA/OCI revision and a
manifest containing image, migration artifact/checksum, config version and CI run.
Tags are human labels, not deployment identities. Remove the backend source
mount from an explicit production Compose; keep local development mounts separate.
Do not let an implicit host override reintroduce builds or source mounts.

1. Select a specific eligible main SHA. Required unit, database, migration and
   release checks must succeed for that SHA. Documentation-only changes skip
   rollout; changes to SQL, dependencies, templates or runtime configuration count.
2. Build/test/publish once. Pull the new digest before disruption, retain the
   prior digest and verify manifest/config, disk space, backup and migration plan.
3. Acquire a host-wide `flock` held for the full deployment, including recovery.
   Use GitHub concurrency with active deployment cancellation disabled. GitHub
   documents that [ordering is not guaranteed](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency);
   recheck eligibility under the host lock and reject stale commits relative to
   the last successful release. Explicit authorized rollback is a separate mode.
4. Validate migration checksums/status and schema compatibility. Snapshot a
   verified backup under the policy below. Apply only approved pending migrations;
   failures block rollout. Expand schema while old API/worker still run only when
   compatibility is proven. Otherwise use an approved maintenance window, drain
   API writes and stop worker before migration; abort rather than guess safety.
5. Stop/drain the worker, replace backend, check local health/database/revision,
   then start worker with the same digest and verify its revision and operation.
   Use Compose `up --no-deps` for app services; preserve database and its volume.
6. Check public health, protected-route boundaries, expected changed surface,
   startup/error signals and bounded worker progress without sending unsolicited
   notifications or triggering sync/recompute. Record old/new SHA and digest,
   migration state, verification evidence and success/failure durably on host and CI.

Single backend replacement has a brief outage and mixed-version transition;
zero downtime is not promised. Worker/API compatibility, graceful shutdown and
in-flight jobs need validation in #189. A process being up, HTTP 401, or checkout
SHA alone does not establish release identity or product correctness. #190 must
add/define the revision and worker verification contracts before activation.

### Failure and rollback

- Before migrations or replacement: leave current release running, record failure.
- Transactional migration failure: retain old app, verify rollback of that
  transaction and inspect history before retry. Earlier successful migrations
  remain applied. Partial nontransactional work requires an operator repair plan.
- After migration/app failure: redeploy **both** app services to previous digest
  only if the resulting schema is compatible. Leave additive schema in place;
  never automatically undo SQL, restore a database, or run Flyway repair/clean.
- Incompatible schema or uncertain partial work: enter documented maintenance,
  retain evidence and request an approved forward fix or restore. Restoring loses
  writes after the backup; application rollback cannot solve that.
- Disconnect/cancel/reboot: host procedure must record phases and support recovery
  from actual running images/history. CI cancellation is not rollback. Release
  locks only after termination/recovery; a leftover record requires reconciliation.

Never use `docker compose down -v`, remove volumes, recreate production PostgreSQL,
or `git reset --hard`. Retain old images/manifests until rollback retention expires.

## 5. Backup and recovery requirements

The tracked [backup script](../../scripts/backup_postgres.sh) performs `pg_dump |
gzip`, `gzip -t`, NAS copy, rclone upload and local/NAS retention (3/30 days).
On the audited VPS neither backup directory exists, the NAS path is not mounted,
and rclone is absent. No relevant PostgreSQL backup timer/user cron was found;
root crontab query exited 1. This does not exclude an external backup system.
There is **no verified app backup/restore capability** on this host. Dpkg's backup
timer does not cover PostgreSQL. This is a blocker for production migration activation.

Before #187 writes or #189 activation, establish an owned and monitored backup
process: encrypted off-host copies, failure alerts, retention, manifest with time,
source release/schema version, integrity checksum and recovery instructions.
Use PostgreSQL 16-compatible `pg_dump` (prefer custom format) and tested restore
tooling; preserve required roles/ownership and pgvector extension availability.
`gzip -t` checks an archive, not logical database restorability. See PostgreSQL
[pg_dump documentation](https://www.postgresql.org/docs/16/app-pgdump.html).

Proposed minimum policy, subject to operational approval: daily backup with RPO
at most 24 hours; a fresh verified backup immediately before schema changes;
retain 7 daily and 4 weekly copies off-host plus the pre-change backup through the
rollback window. Target RTO at most 2 hours, proven by an isolated restore drill,
not inferred from database size. If that RPO is unacceptable, scope WAL/PITR
separately. Check free space and all command exit codes; block deployment if the
required backup is unavailable or stale. Do not assume an unmounted NAS directory
is off-host storage.

Restore drill must cover data/schema, historical raw and research audit records,
roles/extensions, application health and a functional read. Record measured time
and outcome without exposing private rows. Production recovery requires approval,
API/worker write suspension, preservation of the damaged database for diagnosis,
restore into a separate database/volume where possible, verification and deliberate
switch-over. Never test restore against the live volume.

## 6. Security and connectivity

Use ephemeral tagged GitHub runners on the existing tailnet and ordinary SSH to
the VPS, rather than exposing production SSH/DB to changing public runner IPs.
The [official Tailscale Action](https://github.com/tailscale/github-action/blob/main/README.md)
supports ephemeral nodes. Narrow tailnet policy to deployment tag -> VPS SSH;
do not give runners access to PostgreSQL or the rest of the tailnet. Test this
read-only in #189; current access is not proof of the proposed policy.

Pin reviewed Actions to commit SHAs and tool/container versions/digests. Verify
SSH host identity using an independently trusted known-host key, never
`StrictHostKeyChecking=no` or an unauthenticated scan as the only trust source.
Use a dedicated SSH deployment identity with a restricted, root-owned deployment
entrypoint that accepts only validated SHA/digest inputs and fixed Compose paths.
Docker-group access is effectively root; the current unrestricted operator account
must not become the CI identity. Keep emergency operator access separately.

Application credentials stay on VPS and out of build context/artifacts/logs.
Split database/application environment sets; the current shared `.env` exposes
unneeded Strava/Telegram secrets to PostgreSQL. Restrict secret file permissions;
separate migration schema-owner privilege from runtime DML privilege after an
explicitly planned/tested role transition. Do not change current roles in #185.

Publish using least-privilege `GITHUB_TOKEN` package permissions. For private GHCR,
VPS needs separately provisioned read-only package access; do not retain the
ephemeral CI token as host credentials. Confirm visibility/access in #188.
Production credentials must not reach pull-request code or untrusted forks.
Use a protected production environment where available; verify account/repository
support for required reviewers. If unavailable, retain a manual authorization gate
rather than assuming protection. Migration approval is additional to deploy approval.

## 7. Incremental plan and activation gates

| Issue | Deliverable and dependency | Exit evidence |
| --- | --- | --- |
| #185 | This audit and architecture proposal | Read-only topology evidence, selected migration mechanism, explicit unknowns; architecture review still required |
| #186 | Main-based development and explicit commit/push/check rules | Documented workflow; no deployment or closure activated |
| #187 | Approved SQL mechanism, complete baseline, CI failure/lock/checksum tests | Fresh schema + repeat no-op + integration tests; verified production diff and restorable backup; baseline writes separately approved |
| #188 | Approved immutable GHCR release and production Compose | Same digest/revision for backend and worker, no code mounts/builds; private pull tested; DB override/config parity reviewed |
| #189 | Depends on #187/#188; restricted transport, lock, rollout/recovery | Read-only preflight; stale/cancel/concurrent/failure rehearsals; backup drill; explicitly approved initial production rollout |
| #190 | Depends on #186/#189; release verification and issue linkage | Tested revision/worker/route checks, durable deployment result; closure only for eligible issues after their verification |

Backup readiness, role/secret hardening, GHCR read access and tailnet policy must
be assigned as concrete prerequisites in those implementation tasks; they are
not delivered by this architecture document. No new infrastructure is installed.
Do not enable automatic deploy or issue closure until prerequisites pass, initial
rollout succeeds and activation is explicitly approved. Documentation/research
issues need their own completion evidence and should not force an app deployment.

## 8. Audit validation and remaining work

Validated against the actual VPS: service/mount/network configuration, local
override behavior, database version/extensions/table inventory/profile constraints,
Caddy config equality, access boundaries, health, backup prerequisites and existing
CI/schema ordering. Only this document changes in #185; application tests are not
needed for a documentation-only audit. Check Markdown links and `git diff --check`.

Remaining before implementation/activation: agree architecture; complete full
schema/backfill comparison in #187; verify off-host backup/restore; pin/test Flyway;
verify GHCR and restricted runner access; establish release identity/worker checks;
test compatible rollback and deployment ordering. None is represented as already
implemented, and no production service/schema/secret/workflow was modified.
