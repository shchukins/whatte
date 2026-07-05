# Backup

This directory stores backup-related infrastructure artifacts.

Current files:

- [backup_postgres.sh](/srv/human-engine/infra/backup/backup_postgres.sh)

Runtime note:

- The existing runtime-oriented script currently lives at [scripts/backup_postgres.sh](/srv/human-engine/scripts/backup_postgres.sh).
- Operators may continue using `/srv/human-engine/scripts/backup_postgres.sh` as the installed runtime path.
- This repo change does not modify cron, mounts, credentials, or `rclone` configuration.

Current behavior of the script:

- creates a PostgreSQL dump from container `human-engine-postgres`
- writes local archives under `/data/backups/postgres`
- copies archives to `/mnt/nas-backups/postgres`
- uploads archives through `rclone`
- deletes old local and NAS archives by retention rules

Manual validation:

```bash
bash -n /srv/human-engine/infra/backup/backup_postgres.sh
bash -n /srv/human-engine/scripts/backup_postgres.sh
```
