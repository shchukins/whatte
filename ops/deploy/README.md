# Centralized production delivery

Implemented by #189. Activation is separate from implementation. Automatic mode
is disabled unless `PRODUCTION_AUTO_DEPLOY=true` is deliberately set after a
successful Actions dry run and approved initial deployment. It was separately
approved and activated on 2026-10-12. Issue lifecycle automation (#190) is
implemented but disabled until separate approval sets `PRODUCTION_AUTO_CLOSE=true`.
Deployment activation does not enable closure.

`Production deployment` receives successful `Backend CI` workflow completions
for main pushes. It independently verifies exact SHA, completed CI, all required
unit/database/publication jobs and release artifact identity. Manual
`workflow_dispatch` selects a current main SHA and defaults to `dry-run`.
Failed CI cannot deploy. A successful publication alone never activates production.
Documentation-only differences from the running release return `docs_skipped`;
this check spans the whole range since production, including earlier undelivered
runtime changes. Publication can still produce an image for a documentation SHA.

GitHub concurrency uses one production group with active cancellation disabled.
Pending runs may be replaced and ordering is not guaranteed. The host holds the
existing `deploy.lock` through preflight, migrations, rollout and recovery. It
rechecks current main and ancestry against the last successful running release
under that lock. Stale/branched releases are rejected. This is forward delivery;
rollback requires an explicitly reviewed operator procedure using saved digest,
Compose and env. Never use force-push/reset or destructive Docker commands.

## One-time connectivity preparation

Use ephemeral Tailscale runner nodes tagged for deployment. Limit the tag's ACL
to the production VPS TCP/22; do not grant broad tailnet access. Configure an OAuth
client with `auth_keys` write for that tag. Repository/environment secrets:

- `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET` (never place values in Git or chat).
- `PRODUCTION_SSH_KEY`: a dedicated Ed25519 key, not the operator's existing key.
- `PRODUCTION_KNOWN_HOSTS`: host key obtained via the existing authenticated
  operator connection; do not trust an unverified runner `ssh-keyscan`.

Variables: `TS_DEPLOY_TAG`, `PRODUCTION_SSH_TARGET` (existing deployment account
and Tailscale host), `PRODUCTION_AUTO_DEPLOY` (leave unset/false initially).
Use a `production` environment; apply available protection/reviewer rules to
manual initial activation. GitHub token has read-only contents/actions permissions.
VPS GHCR pull credentials, database credentials and app `.env` stay on VPS.

Install [ssh_gate.py](ssh_gate.py) root-owned at
`/usr/local/lib/whatte-deploy/ssh_gate.py`, mode 0755. The dedicated public key in
the existing deployment account's authorized_keys must have:

```text
restrict,command="/usr/bin/python3 /usr/local/lib/whatte-deploy/ssh_gate.py" ssh-ed25519 <dedicated-public-key>
```

This key cannot open a shell, PTY, forwarding or SFTP. It accepts only
`whatte-deploy-v1` plus a bounded JSON request on stdin, checks public GitHub CI
again, fetches current main, and extracts that tracked commit. It never accepts
script paths or commands from the runner. Keep the account's operator and backup
keys intact. Docker privileges imply deployment-level host control through
trusted main code; this is command restriction, not a sandbox against compromised
main. Public GitHub API outages/rate limits fail closed.

## Host state and initial validation

Protected state: `/home/sergey/.config/whatte-release`. Existing immutable #188
release must be imported into `current.json`, with release manifest fields and
absolute `compose`/`env` paths for verified rollback. Save Compose outside the
checkout. Do not invent a prior SHA for legacy images; transition from legacy
needs the #188 snapshot/recovery procedure first.

Create private `deployment.json`, mode 0600:

```json
{
  "postgres_bind_address": "100.x.y.z",
  "backup_config": "/protected/backup.json",
  "migration_credentials": "/protected/migration-credentials.json",
  "migration_approval": "/protected/optional-reviewed-migrate-approval.json"
}
```

The private migration credentials JSON contains `FLYWAY_URL`, `FLYWAY_USER`,
`FLYWAY_PASSWORD` and optionally `MIGRATION_DOCKER_NETWORK`, as documented in
[Migration rules](../../docs/data/MIGRATIONS.md). Prefer a migration-specific DB
role; never include credentials in command arguments/output. The engine invokes
the existing Flyway entrypoint, not arbitrary changed SQL. Validation, V1 adoption,
artifact checksums and transactional compatibility remain mandatory. Pending
migrations require the existing reviewed receipt with live off-host backup and
exact restore proof; risky entries additionally require approval of exact SQL
hashes. Incompatible/nontransactional migrations require a separate maintenance
procedure; automation fails closed. No automatic baseline/repair/clean/restore.

Dry run checks CI, ordering, manifest, current health/worker identity and Flyway
validation/status/compatibility/approval. It fetches Git and extracts temporary
files, but does not change containers, create backups, run SQL migrations, merge
the checkout or update the current release. Follow with an explicitly approved
`deploy` dispatch. Every real rollout creates and round-trip checks a fresh
encrypted off-host backup; backup failure preserves the app. This is integrity
proof, not a new decrypt/restore drill. SQL writes still require the separate
restore proof required by the migration framework.

The engine pulls and verifies the OCI revision/digest, checks Compose parity and
a disposable API DB-read/version test, then migrates and drains worker before
backend replacement. New workers handle SIGTERM/SIGINT, complete their active
iteration and avoid claiming another job. Delivery explicitly uses SIGINT:
legacy Python PID 1 workers have a Python SIGINT handler but no SIGTERM handler,
so the kernel ignores default SIGTERM. The first transition waits for a recent
legacy idle event within its 10-second sleep before sending SIGINT; if no safe
window appears, it aborts without interrupting legacy in-flight work. Subsequent
releases drain through the new signal handler. A 60-second stop timeout causes failure; it does not silently
accept a killed job. Uvicorn handles API graceful shutdown; one backend replica
still has brief downtime. Then worker starts on the same digest. Checks cover
health/database/version, worker startup plus idle or ordinary processed job,
container identity/mounts/restarts, public version and 401/404 route boundaries,
and unchanged PostgreSQL ID/start time/data mounts. No synthetic sync, recompute
or notification is triggered by verification. Existing normal scheduled work runs.

Only after successful QA does the checkout fast-forward and `current.json` change.
Saved `releases/<SHA>` contains the manifest, Compose and env; no image pruning is
enabled. Retain current/previous releases according to the #188 retention policy.

## Failure, disconnect and recovery

`active.json` and `delivery-<SHA>-<mode>.json` are atomic, fsynced, private phase
records, including sanitized failure reason and failed phase. The engine survives runner HUP/TERM/disconnection and inherits the host
lock. A runner cancellation is not a rollback. Observe host state before retry.
An interrupted nonterminal record blocks further deployments until an operator
reconciles actual app digests, database history and the last successful reference.
Never change that record merely to unlock a retry.

Preflight/backup/image/config failure leaves the current app running. Migration
failure blocks replacement and requires history inspection; applied earlier
migrations remain. After rollout failure with known old-app-compatible schema,
the engine redeploys both previous services with saved Compose/env, checks local
health/worker and unchanged DB, and records `recovered`. If recovery fails,
`recovery_failed` requires operator action. Never restore/undo SQL automatically.
GitHub retains outcome artifacts for 90 days; the host keeps durable phase/release
records even if SSH/CI is interrupted. A failed dispatch remains a failed job even
when the previous release was recovered. The separate lifecycle job consumes only fully verified SUCCESS evidence.

Do not enable automatic mode or close #189 until Actions connectivity, dry run,
initial rollout and production behavior are verified. Deployment authorization
alone does not imply approval to activate unattended mode.

## Initial activation evidence

On 2026-10-12, the operator authorized the first deployment and explicitly kept
push-triggered deployment disabled until separate confirmation after health checks.
`PRODUCTION_AUTO_DEPLOY=false` was retained at that initial checkpoint; manual
dispatch was operational.

- [Exact-SHA CI](https://github.com/shchukins/whatte/actions/runs/38286350068)
  passed for `26458179ff829d95c62d3e91d951d90cd656063a`; 756 local unit tests
  passed and migration/database/release checks passed in CI.
- [Actions dry run](https://github.com/shchukins/whatte/actions/runs/38286888365)
  verified Tailscale/OpenSSH access, current runtime, release inputs, Flyway
  validation and zero pending migrations without changing application services.
- [Initial successful rollout](https://github.com/shchukins/whatte/actions/runs/38287033900)
  created a fresh encrypted off-host backup with round-trip integrity verification,
  executed no SQL migrations, and deployed both services to
  `ghcr.io/shchukins/whatte-backend@sha256:a641a16078208a86dbfbf536bfd2a595801e0a263855b60476a6fc84df01c38f`.
  Health/database/public version, worker startup/progress, shared image/no mounts
  and route boundaries passed; PostgreSQL ID/start time/mounts were unchanged.
- [Failed-CI eligibility rehearsal](https://github.com/shchukins/whatte/actions/runs/38254090684)
  failed at selection before Tailscale or SSH, as expected.
- [First drain refusal and recovery](https://github.com/shchukins/whatte/actions/runs/38254929822)
  exposed legacy PID 1 SIGTERM behavior, preserved the existing backend and
  restored the previous worker. The final engine uses a verified legacy idle
  window plus SIGINT; the new worker's SIGINT/SIGTERM handlers were verified.

The deployment tag's saved policy allows only production VPS TCP/22; accept/deny
tests cover the application/database ports and another address. User-owned device
access and the existing Tailscale SSH policy were preserved. The dedicated SSH key
rejects ordinary commands and forwarding. No unattended deployment or automatic
issue closure was enabled by these validations.

### Subsequent automatic deployment activation

On 2026-10-12 the operator separately approved unattended push deployment.
`PRODUCTION_AUTO_DEPLOY=true` was verified on 2026-10-13; the first observed
[successful automatic rollout](https://github.com/shchukins/whatte/actions/runs/38292966404)
ran from `workflow_run` for `4b82fad32c0f58cf631f502005162591c85a8de9`.
Automatic issue closure remains separately gated and was not activated.

## Issue lifecycle and completion policy

Final lifecycle: `Issue → Codex → Tests → Commit → Push → CI/CD → Production
verification → Close issue`. Implementation and production acceptance are separate.

Commit subjects may reference `(#190)` for traceability. Only terminal Git
trailers explicitly opt runtime issues into lifecycle handling:

```text
feat(delivery): implement verified results (#190)

Whatte-Issue-Ref: #190
```

Use `Whatte-Issue-Complete: #190` instead of Ref only once the entire issue is
implemented and tested, with no outstanding work beyond delivery verification.
One trailer per issue, exact repository-local number, no closing keywords. The
engine's original `previous_sha..git_sha` range includes all intervening commits
and skipped releases. Oldest-to-newest signals are folded by issue; a later Ref
revokes Complete. Plain mentions/body prose have no effect. PR numbers and foreign
repository identities are rejected before any issue writes. Do not put Complete
trailers on documentation or non-deploying setup tasks.

The host records `whatte_delivery_v1`: selected/previous SHA and digest, CI run,
start/end UTC timestamps, migration/health status, individual verification checks,
phase and outcome. Terminal deploy outcomes are SUCCESS, FAILED, ROLLED_BACK or
REQUIRES_INTERVENTION. Dry run/docs skip/in-progress are PENDING and cannot close
issues. SUCCESS requires local backend/DB/version, public health/version,
shared image/no mounts/restarts, recent ordinary worker progress, route boundaries,
unchanged PostgreSQL and a read-only Diary data/render smoke. The smoke rejects
partial data errors even when the page returns HTTP 200. It creates no records,
requests no ingestion and sends no notifications. No PII is emitted.

`close-issues` receives only the deployment artifact of this successful Actions
run, checks its exact selected SHA and evidence, then reads Git history. It has
issues-write permission; deployment retains read-only permissions. It runs only
when `PRODUCTION_AUTO_CLOSE=true` and mode is deploy. Leave this variable unset
until prerequisites, local tests and an authorized live rehearsal have passed and
the operator explicitly approves activation. No Telegram notification is added.

Closed issues are skipped; a partial GitHub failure leaves the job red and retry
only closes remaining open issues. Duplicate successful deployments reuse the
original durable record after fresh runtime checks, preserving the original
change range rather than replacing it with an empty range. Retry the lifecycle
job from the same run after an API failure. A failed verification/deployment
cannot reach closure, including a successfully rolled-back release. SSH failure
without a result produces a clear Actions summary; inspect durable host records
before retrying. Outcome artifacts remain available for 90 days; host results
remain durable. GitHub closure failure does not roll back a healthy deployment.

Documentation-only and deliberately non-deploying CI/CD setup tasks use a
separate **manual** completion policy: local checks, exact-SHA CI, recorded
acceptance evidence and individual requested closure. Document delivery to the
server is verified if requested. These tasks never manufacture a production
SUCCESS or force an app restart. Setup tasks changing delivery behavior need an
authorized dry run/rollout before live operation can be claimed.

Recovery retains the #189 compatibility gate: pending migrations must explicitly
be old-app-compatible; unknown/incompatible schema prevents automatic application
rollback. Compatible rollout failure restores both prior services from saved
Compose/env and checks health, worker, functional read and preserved DB identity.
SQL is never reversed. Reconciliation/forward repair is an operator procedure.
Tests in `test_deployment.py` and `test_issue_lifecycle.py` rehearse host success,
compatible rollback, failed recovery/migration, skipped intermediate releases,
multi-commit completion, API interruption and duplicate closure without production
or GitHub writes. Live activation is separately authorized and recorded.
