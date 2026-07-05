#!/usr/bin/env bash

set -euo pipefail

DATE=$(date +%Y-%m-%d_%H-%M-%S)

LOCAL_DIR="/data/backups/postgres"
NAS_DIR="/mnt/nas-backups/postgres"

mkdir -p "$LOCAL_DIR"
mkdir -p "$NAS_DIR"

FILE="human_engine_${DATE}.sql.gz"

echo "[INFO] creating postgres dump..."

docker exec human-engine-postgres \
  pg_dump -U human_engine human_engine \
  | gzip > "${LOCAL_DIR}/${FILE}"

echo "[INFO] validating archive..."

gzip -t "${LOCAL_DIR}/${FILE}"

echo "[INFO] copying to NAS..."

cp "${LOCAL_DIR}/${FILE}" "${NAS_DIR}/${FILE}"

echo "[INFO] uploading to Google Drive..."

rclone copy "${LOCAL_DIR}/${FILE}" gdrive:human-engine-backups/postgres

echo "[INFO] cleanup old backups..."

find "$LOCAL_DIR" -type f -name "*.sql.gz" -mtime +3 -delete
find "$NAS_DIR" -type f -name "*.sql.gz" -mtime +30 -delete

echo "[OK] backup completed: ${FILE}"
