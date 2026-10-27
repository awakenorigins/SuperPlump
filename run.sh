#!/usr/bin/env bash
# Một lệnh dựng SuperPlump từ số 0 và tự audit
set -e
createdb superplump 2>/dev/null || true
psql superplump -c "CREATE EXTENSION IF NOT EXISTS postgis;"
for f in db/00*.sql; do psql superplump -v ON_ERROR_STOP=1 -q -f "$f"; done
( cd api && npm i --silent && node server.js & )
sleep 1.5
python3 -m pytest tests/ -q     # kỳ vọng: 34 passed
echo "App demo: http://localhost:8386/app · Admin: http://localhost:8386/admin"
