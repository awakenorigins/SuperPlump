import os, re, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

def txt(p): return (ROOT/p).read_text()

def test_cors_allowlist_and_no_origin_support():
    s = txt('api/server.js')
    assert 'function corsOrigin' in s
    assert 'if (!origin) return cb(null, true)' in s
    assert 'ALLOWED_ORIGINS.includes(origin)' in s
    assert 'app.use(cors({ origin: corsOrigin' in s
    assert 'app.use(cors());' not in s
    assert 'cors_origin_denied", "Origin is not allowed' in s

def test_compose_production_no_payments_enabled():
    y = txt('docker-compose.yml')
    assert 'NODE_ENV: production' in y
    assert 'ALLOWED_ORIGINS' in y
    s = txt('api/server.js')
    assert 'payments_disabled' in s
    assert 'credited' not in re.sub(r'app.post\("/v1/payments/webhook".*?\n\}\);', '', s, flags=re.S)
    assert s.count('"kyc_disabled"') >= 2

def test_backup_monitoring_and_secret_scan_artifacts():
    assert os.access(ROOT/'scripts/backup.sh', os.X_OK)
    assert os.access(ROOT/'scripts/restore-verify.sh', os.X_OK)
    assert 'umask 077' in txt('scripts/backup.sh')
    assert 'BACKUP_AGE_RECIPIENT' in txt('scripts/backup.sh')
    assert 'SuperPlumpLedgerMismatch' in txt('ops/prometheus/alerts.yml')
    assert 'SuperPlumpHigh5xx' in txt('ops/prometheus/alerts.yml')
    assert 'gitleaks/gitleaks-action' in txt('.github/workflows/ci.yml')
