# Immutable application releases

Implemented in #188: Backend CI tests a pinned Python dependency set, then builds
one Linux amd64 application image from [Dockerfile.release](../../backend/Dockerfile.release)
and publishes it to `ghcr.io/shchukins/whatte-backend:<40-character-main-SHA>`.
The release job runs only after unit/research and database/migration jobs pass;
PRs cannot publish. It does not deploy, migrate or close issues. Existing SHA tags
are never overwritten; reruns after publication use the recorded image/artifact
instead of rebuilding. New source/dependency changes require a new commit.

The base Python 3.11 image is digest-pinned; [requirements.lock](../../backend/requirements.lock)
pins the entire resolved dependency set used by both CI and the image. Update the
lock deliberately with a tested resolution when dependencies change. This fixes
inputs and versions; it does not promise byte-identical layers/timestamps across
independent builds. Production pulls the single already-built digest.

The release artifact `release-<SHA>` contains `release-manifest.json`, production
Compose, dependency lock and migration manifest, retained in Actions for 90 days.
The manifest binds the SHA, image digest, platform, CI run and SHA-256 hashes of
Compose/dependencies/migration inputs. The published digest is smoke-tested with
API health/version and worker imports without credentials/network access. Only
runtime code and dependency inputs enter the image, never host `.env` or data.

`GET /version` reports `{"git_sha":"<SHA>"}` from image-owned metadata;
development without that metadata returns `{"git_sha":null}`. No database or
upstream request is made. Environment/checkout SHA cannot override image revision.
Worker startup logs `worker_started` with the same `git_sha`; read-only
`python -c 'from backend.release import RELEASE; print(RELEASE)'` inside either
container provides the same identity. OCI revision/source labels accompany it.

## Registry access and retention

Publish with job-scoped `GITHUB_TOKEN` (`contents: read`, `packages: write`).
The package is initially private. Public visibility requires operator approval
and package settings; after approval anonymous pulls require no VPS credential.
For a private package, provision a separate read-only `read:packages` classic PAT
on VPS through `docker login --password-stdin`, outside Git/logs; never persist the
CI token. See [GHCR access](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

No automatic registry deletion or host image pruning is enabled. Retain all
published SHA releases for now, including current and previous compatible digest.
Save the manifests and production Compose used for current/rollback releases in
private host storage (outside checkout); the 90-day Actions artifact expiry is
not an image retention policy. Any later cleanup must exclude these digests and
retain at least the last five successful releases and 30 days, with a reviewed
list before deletion. Untagged provenance/SBOM manifests are part of retained
releases; do not delete them independently.

## Authorized manual delivery during transition

Centralized production delivery remains #189, with automatic verification and
issue lifecycle in #190. This runbook is an operator procedure, not an activated
deployment service. First validate exact-SHA CI success, manifest/file hashes,
clean server checkout, GHCR pull access, backup status, schema compatibility and
existing DB/network/port parity. No database migration is part of #188.

Use [compose.production.yaml](../../compose.production.yaml) explicitly, with
project `human-engine`; do not merge root development Compose or implicit
`compose.override.yaml`. It uses the existing external volume and network, shared
host `.env`, PostgreSQL Tailscale access, container identities and backend loopback
port. Existing `compose.yaml`/Dockerfile keep local development functionality.

Prepare a private release env file, e.g. `/home/sergey/.config/whatte-release/current.env`:

```text
WHATTE_IMAGE=ghcr.io/shchukins/whatte-backend@sha256:<verified-digest>
POSTGRES_BIND_ADDRESS=<existing-host-Tailscale-address>
```

Save previous images/config/manifest first. Hold a host `flock` throughout rollout
and recovery, pull before stopping anything, and inspect the pulled OCI revision.
Use the fixed config below (working directory `/srv/human-engine`):

```sh
docker compose -p human-engine --env-file "$RELEASE_ENV" -f compose.production.yaml config --quiet
docker compose -p human-engine --env-file "$RELEASE_ENV" -f compose.production.yaml pull backend worker
docker compose -p human-engine --env-file "$RELEASE_ENV" -f compose.production.yaml stop -t 60 worker
docker compose -p human-engine --env-file "$RELEASE_ENV" -f compose.production.yaml up -d --no-deps backend
# Verify /healthz, /dbz and /version locally before starting worker.
docker compose -p human-engine --env-file "$RELEASE_ENV" -f compose.production.yaml up -d --no-deps worker
```

Verify identical image ID/digest/revision for both services, no app mounts, stable
worker startup/idle or ordinary processing, public API health/version and existing
401/404 Today access boundaries. Verify PostgreSQL container ID/start time/volume
are unchanged; do not run `up` for PostgreSQL. Record the exact SHA/digest, checks
and prior release reference on host and in issue evidence. A replacement briefly
interrupts API; inspect/drain in-flight work, and keep the operator session open.
No extra sync/recompute/notification is part of verification.

## Compatible rollback

For subsequent immutable releases, retain the previous digest, release manifest,
Compose and env. Validate that the current schema supports the prior application;
stop worker, pull the **previous digest**, deploy backend with its saved Compose
and env, verify health/database/revision, then deploy worker from the same digest.
Repeat public checks and persist the rollback result. A digest pull and disposable
API smoke test can rehearse rollback without changing production data.

For the first transition, retain both legacy image IDs and an explicit recovery
Compose containing those images with no builds; snapshot current backend source
into a retained local recovery image before fast-forwarding the checkout, since
its old image may differ from source exposed by the bind mount. Rehearse health,
version availability (legacy may not have `/version`) and a database read from
that recovery image in a disposable container before stopping live services.
Use that recovery configuration for **both** app services if initial verification
fails. Never silently rebuild the legacy images or use a later mutable checkout.

Application rollback does not reverse SQL. Leave compatible additive migrations
in place. Unknown/incompatible schema needs an approved forward fix or restore;
never automatically undo migrations, repair/clean Flyway, restore/drop the DB,
remove volumes, restart PostgreSQL, or run `docker compose down`.
