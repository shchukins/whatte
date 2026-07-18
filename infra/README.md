# Infrastructure Map

This directory documents the Whatte infrastructure layout without changing the current runtime state.

Target structure:

```text
infra/
  home/
  eu-edge/
  monitoring/
  backup/
```

Current node split:

- `eu-edge/`: current VPS production entrypoint and backend host for `shchukin.de` domains. Caddy/TLS/reverse-proxy role.
- `home/`: legacy / secondary home-node context. Older backend, worker, PostgreSQL, local observability, NAS-oriented backup assumptions may still be documented here, but this is not the current primary production topology.
- `monitoring/`: operational observability stack and related notes. The primary production status surface is now `https://shchukin.de/dashboard`; Grafana/Loki is lower-level log analysis.
- `backup/`: backup scripts and backup-specific notes.

Current runtime locations kept as-is:

- Main app compose remains at [compose.yaml](/srv/human-engine/compose.yaml).
- Observability compose remains at [infra/monitoring/observability/docker-compose.yml](/srv/human-engine/infra/monitoring/observability/docker-compose.yml).
- Existing backup runtime script remains at [scripts/backup_postgres.sh](/srv/human-engine/scripts/backup_postgres.sh).
- Secondary local Postgres-only compose remains at [backend/infra/docker-compose.yml](/srv/human-engine/backend/infra/docker-compose.yml).

Classification snapshot:

- Home node:
  - [compose.yaml](/srv/human-engine/compose.yaml)
  - [scripts/backup_postgres.sh](/srv/human-engine/scripts/backup_postgres.sh)
  - [db-init](/srv/human-engine/db-init)
  - [sql](/srv/human-engine/sql)
  - [backend/infra/docker-compose.yml](/srv/human-engine/backend/infra/docker-compose.yml)
- EU edge:
  - [infra/eu-edge/Caddyfile](/srv/human-engine/infra/eu-edge/Caddyfile)
- Monitoring:
  - [infra/monitoring/observability](/srv/human-engine/infra/monitoring/observability)
  - [docs/architecture/OBSERVABILITY.md](/srv/human-engine/docs/architecture/OBSERVABILITY.md)
- Backup:
  - [infra/backup/backup_postgres.sh](/srv/human-engine/infra/backup/backup_postgres.sh)
  - [scripts/backup_postgres.sh](/srv/human-engine/scripts/backup_postgres.sh)

Notes:

- No tracked Caddy config existed in the repo before this reorganization pass.
- `backend/infra/docker-compose.yml` looks like a secondary helper for local Postgres exposure on `127.0.0.1:5433`, not the current main runtime stack.
- Observability files already live under `infra/monitoring/observability`; they were not moved to avoid breaking commands and existing documentation.
- Old home-server Telegram watchdog / cron monitoring is legacy after the production move to VPS and should not be treated as primary monitoring.
