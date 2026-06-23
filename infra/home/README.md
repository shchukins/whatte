# Home Node

The home node is the primary Human Engine runtime.

Current role:

- FastAPI backend
- background worker
- PostgreSQL
- NAS-oriented PostgreSQL backups
- local observability stack

Current runtime compose:

- Main runtime compose stays at [compose.yaml](/srv/human-engine/compose.yaml).
- It currently defines:
  - `postgres`
  - `backend`
  - `worker`

Why it was not moved:

- It is the active root-level runtime entrypoint.
- Moving it now would create avoidable risk for existing `docker compose` commands, paths, and operator habits.

Related files currently associated with the home node:

- [compose.yaml](/srv/human-engine/compose.yaml)
- [scripts/backup_postgres.sh](/srv/human-engine/scripts/backup_postgres.sh)
- [infra/backup/backup_postgres.sh](/srv/human-engine/infra/backup/backup_postgres.sh)
- [infra/monitoring/observability/docker-compose.yml](/srv/human-engine/infra/monitoring/observability/docker-compose.yml)
- [backend/infra/docker-compose.yml](/srv/human-engine/backend/infra/docker-compose.yml)

Status note:

- `backend/infra/docker-compose.yml` was left in place. It appears to be a secondary local Postgres-only helper, not the primary stack.
