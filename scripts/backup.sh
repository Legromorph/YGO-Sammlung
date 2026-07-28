#!/bin/sh
set -eu

BACKUP_ROOT="${BACKUP_ROOT:-/backups}"
INTERVAL_SECONDS="${BACKUP_INTERVAL_SECONDS:-86400}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
MEDIA_SOURCE="${MEDIA_SOURCE:-/data/media}"

run_backup() {
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  temporary_directory="${BACKUP_ROOT}/.${timestamp}.tmp"
  target_directory="${BACKUP_ROOT}/${timestamp}"

  mkdir -p "${BACKUP_ROOT}"
  rm -rf "${temporary_directory}"
  mkdir -p "${temporary_directory}"

  echo "[$(date -u +%FT%TZ)] PostgreSQL-Backup wird erstellt."
  pg_dump \
    --host="${PGHOST}" \
    --port="${PGPORT:-5432}" \
    --username="${PGUSER}" \
    --dbname="${PGDATABASE}" \
    --format=custom \
    --no-owner \
    --no-privileges \
    --file="${temporary_directory}/postgres.dump"

  echo "[$(date -u +%FT%TZ)] Kartenbilder werden gesichert."
  tar -czf "${temporary_directory}/card-media.tar.gz" -C "${MEDIA_SOURCE}" .

  (
    cd "${temporary_directory}"
    sha256sum postgres.dump card-media.tar.gz > SHA256SUMS
  )
  printf '{"created_at":"%s","database":"%s","media_archive":"card-media.tar.gz"}\n' \
    "$(date -u +%FT%TZ)" "${PGDATABASE}" > "${temporary_directory}/manifest.json"
  mv "${temporary_directory}" "${target_directory}"

  find "${BACKUP_ROOT}" \
    -mindepth 1 \
    -maxdepth 1 \
    -type d \
    -name '20*' \
    -mtime "+${RETENTION_DAYS}" \
    -exec rm -rf {} \;

  echo "[$(date -u +%FT%TZ)] Backup abgeschlossen: ${target_directory}"
}

if [ "${1:-}" = "--once" ]; then
  run_backup
  exit 0
fi

while true; do
  run_backup
  sleep "${INTERVAL_SECONDS}"
done
