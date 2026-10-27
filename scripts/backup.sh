#!/usr/bin/env bash
# Daily-compatible encrypted backup with retention. Does not install cron/timers.
set -euo pipefail
umask 077
DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
mkdir -p "$DIR"
chmod 700 "$DIR"
ts="$(date +%F-%H%M%S)"
plain="$DIR/superplump-$ts.sql.gz"
out="$plain"
if [[ -n "${BACKUP_AGE_RECIPIENT:-}" ]]; then out="$plain.age"; fi
if [[ -n "${PGHOST:-}" && "${PGHOST}" != "db" ]]; then
  pg_dump -h "${PGHOST}" -U "${PGUSER:-plump}" "${PGDATABASE:-superplump}" | gzip -9 > "$plain"
else
  docker compose exec -T db pg_dump -U "${PGUSER:-plump}" "${PGDATABASE:-superplump}" | gzip -9 > "$plain"
fi
chmod 600 "$plain"
if [[ -n "${BACKUP_AGE_RECIPIENT:-}" ]]; then
  command -v age >/dev/null || { echo "age not installed" >&2; exit 2; }
  age -r "$BACKUP_AGE_RECIPIENT" -o "$out" "$plain"
  chmod 600 "$out"; rm -f "$plain"
fi
find "$DIR" -maxdepth 1 -type f \( -name 'superplump-*.sql.gz' -o -name 'superplump-*.sql.gz.age' \) -mtime +"$RETENTION_DAYS" -delete
printf 'backup=%s size=%s retention_days=%s\n' "$out" "$(du -h "$out" | cut -f1)" "$RETENTION_DAYS"
