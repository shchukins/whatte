#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Approved sudo installation required.' >&2; exit 1; }
repo=${1:?tested production repository path required}
config=${2:?protected backup configuration required}
[[ "$repo" == /srv/human-engine ]] || { echo 'Unexpected repository path.' >&2; exit 1; }
for unit in whatte-postgres-backup.service whatte-postgres-backup.timer whatte-postgres-backup-failure.service; do
    [[ ! -e "/etc/systemd/system/$unit" ]] || { echo "Refusing to overwrite $unit" >&2; exit 1; }
done
[[ ! -e /home/sergey/.config/whatte-backup/backup.json ]] || { echo 'Refusing to replace existing config.' >&2; exit 1; }
# A real receiver probe must succeed before enabling scheduled writes.
runuser -u sergey -- python3 "$repo/scripts/postgres_backup.py" verify --config "$config" --receipt "${3:?verified restore receipt required}"
install -o sergey -g sergey -m 0600 "$config" /home/sergey/.config/whatte-backup/backup.json
for unit in whatte-postgres-backup.service whatte-postgres-backup.timer whatte-postgres-backup-failure.service; do
    install -o root -g root -m 0644 "$repo/ops/backup/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now whatte-postgres-backup.timer
systemctl list-timers whatte-postgres-backup.timer --no-pager
