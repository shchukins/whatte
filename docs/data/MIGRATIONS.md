# Versioned SQL migrations

Implemented mechanism: Flyway Community 11.16.0, pinned by container digest in
[`scripts/migrate.py`](../../scripts/migrate.py). PostgreSQL stores ordered versions,
checksums and outcomes in `public.flyway_schema_history`. Flyway's PostgreSQL
transactional lock serializes runners; lock retry is bounded. A failed command
returns nonzero and must stop delivery. App startup never runs migrations.
Centralized deployment and automatic issue closure remain inactive (#188–#190).

## Artifacts and initial schema

[`V1__baseline.sql`](../../migrations/sql/V1__baseline.sql) initializes an **empty**
PostgreSQL 16 / pgvector database. It combines the full ordered historical bootstrap;
[`baseline_sources.json`](../../migrations/baseline_sources.json) inventories the
original source order and SHA-256. Historical files stay intact. Flyway owns the
transaction; historical top-level BEGIN/COMMIT were removed from the new V1 copy.
Do not replay `db-init/`, `sql/` or the historical bootstrap on production.
Compose no longer mounts incomplete historical scripts into the database entrypoint.

The 2026-10-11 catalog audit found two production variants that V1 explicitly
preserves instead of assuming historical files ran:

- `notification_log`: production has `related_activity_id`, `sent_at NOT NULL
  DEFAULT now()`, no `created_at`, and legacy daily/activity unique indexes.
  V1 uses this existing structure before the historical lifecycle additions.
- `strava_webhook_event.dedupe_key`: production has NOT NULL and a full unique
  constraint, rather than the historical nullable/partial-index definition.
  The full constraint supports the existing `ON CONFLICT (dedupe_key)` handler.

V1 also preserves `document`, `document_chunk`, their sequences/constraints/index,
pgvector and `analytics.daily_state`; their definitions were exported from the
catalog without rows into [legacy_objects.sql](../../migrations/verification/legacy_objects.sql).
The view and legacy tables are auxiliary historical objects; this work does not
activate AI or change physiological calculations. Existing `superset_reader`
SELECT/schema/default privileges and the research writer's column privileges are
included. On a fresh cluster missing permission groups are NOLOGIN; login identities,
passwords and role activation remain externally provisioned. Adoption changes no
existing role, privilege, table, data or sequence value.

[expected_catalog.json](../../migrations/verification/expected_catalog.json) is the
reviewed definition snapshot: 822 catalog elements, equal between the fresh baseline
and production before adoption. [catalog.sql](../../migrations/verification/catalog.sql)
checks names, types/nullability/defaults, column grants, constraints, indexes and
validity, sequence definitions/ownership, functions/triggers, view definitions,
extensions, owners, object/default ACLs and RLS flags. ACL order and physical column
order are normalized; sequence current values are excluded because they are data.
Extension-owned implementation objects are represented by extension version.
All non-system schemas are inventoried; currently these are `public` and
`analytics`. An unexpected schema blocks adoption. Host login attributes/secrets are not part of the schema snapshot.

[backfill_checks.sql](../../migrations/verification/backfill_checks.sql) checks aggregate
postconditions for canonical feedback IDs, dated FTP/HR max and delivery states.
Existing dated manual corrections are preserved. No backfill runs during adoption.
Any violation or catalog mismatch blocks baseline, rather than guessing or repairing.

## Authoring and safety classification

Add `V2__description.sql`, then V3 onward, with an entry in
[manifest.json](../../migrations/manifest.json): file SHA-256, risk, transactional
flag, old-app compatibility and review evidence. Applied files are immutable;
fixes get a new version. Never update applied SQL or use Flyway repair/clean.
Verification SQL is also hash-bound to the manifest.
The runner rejects undeclared files, callbacks, repeatable migrations, SQL sidecar
configuration and embedded transaction control. The runner allows no arbitrary
Flyway flags or JDBC query overrides. Credentials enter only through a protected
environment, never Git, command arguments, logs or an application startup hook.

| Risk | Examples | Production requirement |
| --- | --- | --- |
| `compatible` | Nullable added column; new independent table | Reviewed old-app compatibility, current backup and target-bound release approval |
| `destructive` | Drop/rename; narrowed type; new restrictive constraint | Separate explicit approval bound to the exact migration SHA and recovery plan |
| `backfill` | Updating historical records | Explicit data review, bounded plan and exact migration approval |
| `long_running` | Large table rewrite/index or broad update | Explicit time/locking plan and migration approval |
| `baseline` | V1 initialization/adoption | Fresh DB in CI/development; separate production baseline approval |

Classification is a human-reviewed contract, not a SQL keyword heuristic. Review
must account for data volume, old API/worker reads/writes and defaults/constraints.
Use expand/contract: add compatible structures, deploy both consumers, migrate data
in a separately reviewed increment, and remove old structures only after compatibility
ends. Normal migrations are transactional; nontransactional operations (including
CREATE INDEX CONCURRENTLY) are rejected by this entrypoint and need a separately
approved procedure. Lock timeout is 5s and statement timeout 120s. Do not evade those
bounds in SQL; split large operations or use the separately reviewed procedure.
Current schema-owner privileges are necessary for historical role/extension setup;
separating runtime DML/migration identities remains a delivery prerequisite, not an
implicit role transition here.

## CI and local rehearsal

Supply `FLYWAY_URL=jdbc:postgresql://host:5432/database`, `FLYWAY_USER` and
`FLYWAY_PASSWORD` through the environment. `MIGRATION_ENVIRONMENT` defaults to
`production`; explicitly select `ci` or `development` for disposable databases.
Docker and Python 3 are required. Container networking defaults to Linux host
networking; set `MIGRATION_DOCKER_NETWORK` for an isolated test container/network.
Docker receives only the selected DB credentials, never the shared application `.env`.

```sh
python3 scripts/migrate.py migrate
python3 scripts/migrate.py verify-baseline
python3 scripts/migrate.py validate
```

The DB integration CI job initializes a fresh database via Flyway, verifies the
catalog/backfill assertions, rehearses no-op repeat, checksum mismatch, transactional
failure, concurrent execution, interruption/recovery, existing-database baseline
adoption and exact risky-operation approvals, then runs the existing application DB
integration tests. Run the safety suite **only against a disposable cluster**:

```sh
MIGRATION_ENVIRONMENT=ci MIGRATION_TEST_DISPOSABLE=yes python3 scripts/test_migrations.py
```

The suite creates/drops uniquely named test databases and can create NOLOGIN groups;
do not point it at production. Approval/backup receipts in tests are synthetic fixtures.
Policy-only tests are `backend/tests/test_migration_policy.py` and require no DB.

## Production baseline adoption

1. Select an exact reviewed SHA with successful required CI. Keep current API/worker
   running; do not apply V1 to an existing database. Run `verify-baseline` read-only
   using schema-owner access. Preserve the reviewed catalog and aggregate evidence.
2. Confirm the owned regular backup process, encrypted off-host storage/retention,
   restore instructions and alerts. Create a fresh PostgreSQL 16 custom-format dump,
   verify integrity and restore into an isolated database/volume with required
   roles/extensions. Verify schema, per-table counts, research/raw records and a
   functional app read; record measured restore time. Never restore the live volume.
3. Prepare a private approval JSON receipt for the exact action, JDBC target,
   manifest SHA, canonical catalog hash and verified backup. Request separate human
   baseline authorization **after** the plan/evidence is concrete. A general deploy
   request does not replace the issue's separately reviewed baseline-write gate.
4. Under the operator's host delivery lock, rerun checks and execute:
   `python3 scripts/migrate.py baseline --approval-file /protected/approval.json`.
   This creates only Flyway history and a version-1 BASELINE marker; V1 SQL is skipped.
   Its description stores `Whatte V1 sha256=<hash>` because skipped V1 has no Flyway
   checksum. Future info/validate/migrate verifies that stored hash against the artifact.
   Existing history blocks a second baseline; reconcile it without deleting history.
5. Verify one successful BASELINE row, matching V1 hash, `validate`, repeat `migrate`
   with zero applied migrations and unchanged catalog/data. Retain private approval,
   backup and structured command outcomes on the host and off-host. No app rebuild
   is needed for migration tooling/documentation; no production PostgreSQL recreation.

Receipt fields (values below describe the schema, not an approval):

```json
{
  "action": "baseline",
  "authorized_by": "operator identity",
  "authorization_reference": "explicit reviewed authorization reference",
  "target": "jdbc:postgresql://host:5432/database",
  "manifest_sha256": "sha256 of migrations/manifest.json",
  "catalog_hash": "canonical JSON SHA returned by verify-baseline",
  "backup": {
    "reference": "protected backup location/manifest",
    "sha256": "64 hex digits identifying the verified archive",
    "verified_at": "UTC ISO timestamp, at most 24 hours old",
    "restore_verified": true,
    "off_host_encrypted": true,
    "regular_backup_process": "owner, schedule, retention and monitoring reference",
    "config_path": "/protected/backup.json",
    "config_sha256": "sha256 of the reviewed private backup configuration",
    "receipt_path": "/protected/restored-receipt.json",
    "receipt_sha256": "sha256 of the exact archive restore proof"
  }
}
```

The operator attests authorization and the full restore drill. The runner validates
receipt binding/freshness, the live catalog, the private backup configuration/proof
hashes and then invokes the restricted receiving-side NAS probe and downloads the
actual archive to recheck its checksum immediately before production SQL writes.
NAS failure, wrong NFS export/protocol, missing/corrupt archive or failed/stale restore
proof blocks migration even if an older approval exists. See
[backup installation and recovery](../../ops/backup/README.md).
Future production `migrate` with pending changes needs a similarly bound receipt
(`action=migrate`); risky files additionally require `approved_migrations` mapping
filename to SHA-256. Preflight must verify the referenced backup still exists.
Release automation, restricted transport and automatic issue closure are not
activated by this tool. Their host-wide lock/release identity belong to #188–#190.

## Failure and recovery

Commands emit structured started/succeeded/failed events and return nonzero on
failure. Container errors expose exit/error code without credentials or row values.
For a failed Flyway operation inspect private operator output using the same pinned
image/settings and protect any diagnostic data. Stop delivery before app replacement.
A normal failed/interrupted PostgreSQL migration rolls back its transaction; confirm
actual server session, schema and history before retry. A disconnected client
may leave a running server statement until PostgreSQL detects the closed connection;
do not infer released locks/rollback solely from container exit. Previous successful
versions remain applied.
Flyway lock prevents concurrent migration SQL; it does not stop unrelated app writes.
Do not automatically undo SQL, run repair/clean, or restore the database after an app
failure. Roll back application code only when compatible with the resulting schema;
otherwise request an explicitly approved forward fix or restore. Preserve evidence
and private backups. Never delete volumes, recreate production DB or replay V1.

## Activation evidence

Implementation, rehearsal and production adoption evidence is recorded in #187.
After separate operator authorization and successful CI for `e3cb268`, production
Flyway baseline V1 was recorded on 2026-10-12 at 09:02:34 UTC. The single successful
`BASELINE` history row binds the skipped V1 to SHA-256
`1bd6bb42e5d6d7bd2e66045e5e119d5c9b5e92bf9c72d8394d13b5258ba29ae3`.
V1 SQL was not executed. Validation passed, repeated migrate executed zero
migrations, all 822 catalog elements still matched and backfill violations remained
zero. Backend, worker and PostgreSQL container identities/start times were unchanged;
local health and DB checks passed. Automatic production deployment, migration
execution and issue closure remain inactive.

## V2: manual training context

[V2__training_context.sql](../../migrations/sql/V2__training_context.sql) adds two
independent manual-input tables, with no historical data changes. See the
[context contract](TRAINING_CONTEXT.md). `verify-baseline` remains an exact V1
adoption check; after V2 use `validate`. CI rehearses exact V1 adoption separately
and applies the full chain before application integration tests. Production
pending-migration backup/approval requirements remain unchanged.
