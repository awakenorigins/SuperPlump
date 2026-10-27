#!/usr/bin/env bash
set -euo pipefail
fail=0
check(){ if ! eval "$1"; then echo "FAIL: $2"; fail=1; else echo "ok: $2"; fi; }
check "grep -q 'NODE_ENV: production' docker-compose.yml" "compose sets NODE_ENV production"
check "grep -q 'ALLOWED_ORIGINS' docker-compose.yml && grep -q 'corsOrigin' api/server.js" "CORS is allowlist based"
check "grep -q 'payments_disabled' api/server.js" "payments remain disabled"
check "grep -q 'gitleaks' .github/workflows/ci.yml" "CI secret scan enabled"
check "test -x scripts/backup.sh && test -x scripts/restore-verify.sh" "backup and restore verification scripts executable"
check "grep -q 'SuperPlumpLedgerMismatch' ops/prometheus/alerts.yml && grep -q 'SuperPlumpHigh5xx' ops/prometheus/alerts.yml" "ledger and 5xx alerts configured"
exit "$fail"
