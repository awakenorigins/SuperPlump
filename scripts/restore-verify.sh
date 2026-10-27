#!/usr/bin/env bash
# Verifies a backup can restore into a disposable Postgres container.
set -euo pipefail
backup="${1:?usage: scripts/restore-verify.sh BACKUP.sql.gz[.age]}"
tmp="$(mktemp -d)"
name="superplump-restore-verify-$$"
trap 'rm -rf "$tmp"; docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
in="$backup"
if [[ "$backup" == *.age ]]; then
  [[ -n "${BACKUP_AGE_IDENTITY:-}" ]] || { echo "BACKUP_AGE_IDENTITY required for .age backup" >&2; exit 2; }
  command -v age >/dev/null || { echo "age not installed" >&2; exit 2; }
  age -d -i "$BACKUP_AGE_IDENTITY" -o "$tmp/restore.sql.gz" "$backup"
  in="$tmp/restore.sql.gz"
fi
docker run -d --name "$name" -e POSTGRES_USER=plump -e POSTGRES_PASSWORD=plump -e POSTGRES_DB=superplump postgis/postgis:16-3.4 >/dev/null
ready=0
for i in {1..40}; do
  if docker exec "$name" pg_isready -U plump -d superplump >/dev/null 2>&1; then
    # The PostGIS entrypoint briefly starts and then restarts PostgreSQL while
    # installing extensions. Require readiness to survive that restart.
    sleep 3
    if docker exec "$name" pg_isready -U plump -d superplump >/dev/null 2>&1; then ready=1; break; fi
  fi
  sleep 1
done
[[ "$ready" = 1 ]] || { echo "restore database did not become ready" >&2; exit 1; }
# The dump preserves grants for Supabase-compatible roles. Recreate the
# no-login role expected by those GRANT statements before replaying schema.
docker exec "$name" psql -U plump -d superplump -v ON_ERROR_STOP=1 -q \
  -c "DO \$\$ BEGIN CREATE ROLE authenticated NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END \$\$;"
gunzip -c "$in" | docker exec -i "$name" psql -U plump -d superplump -v ON_ERROR_STOP=1 -q
docker exec "$name" psql -U plump -d superplump -Atc "select 'ok:' || count(*) from information_schema.tables where table_schema='public';"
