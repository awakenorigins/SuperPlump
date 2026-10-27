.PHONY: dev test load soak secrets up down
dev: ; ./run.sh
test: ; @cd api && node --check server.js && node --check worker.js && cd .. && python3 -m pytest tests/ -q
load: ; MASTER_KEY=dev-master-key python3 scripts/loadtest.py
soak: ; MASTER_KEY=dev-master-key python3 scripts/soak.py 75
secrets: ; ./scripts/gen-secrets.sh .env.production
up: ; docker compose --env-file .env.production up -d --build
down: ; docker compose down
