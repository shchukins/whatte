# Centralized production delivery

Implemented by #189. Activation is separate from implementation. Automatic mode
is disabled unless `PRODUCTION_AUTO_DEPLOY=true` is deliberately set after a
successful Actions dry run and approved initial deployment. No automatic issue
closure is implemented; that belongs to #190.

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
backend replacement. Worker SIGTERM completes its active iteration and avoids
claiming another job. A 60-second stop timeout causes failure; it does not silently
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
records. The engine survives runner HUP/TERM/disconnection and inherits the host
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
when the previous release was recovered. #190 can later consume success evidence.

Do not enable automatic mode or close #189 until Actions connectivity, dry run,
initial rollout and production behavior are verified. Deployment authorization
alone does not imply approval to activate unattended mode.
