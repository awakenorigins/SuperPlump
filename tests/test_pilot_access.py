import os, re, subprocess, requests

B = os.getenv("SUPERPLUMP_BASE", "http://127.0.0.1:8386")
ADMIN = {"x-admin-key": os.getenv("SUPERPLUMP_ADMIN_KEY", "plump-admin")}

def psql_value(sql):
    r = subprocess.run([
        "docker", "compose", "exec", "-T", "db", "psql", "-U", "plump", "-d", "superplump", "-Atc", sql
    ], check=True, capture_output=True, text=True)
    return r.stdout.strip()

def hdr(tok): return {"Authorization": "Bearer "+tok}

def register_login():
    r = requests.post(B+"/v1/auth/register"); r.raise_for_status()
    j = r.json()
    l = requests.post(B+"/v1/auth/login", json={"token": j["token"]}); l.raise_for_status()
    return j, l.json()["jwt"]

def age_user(uid, minutes=6):
    psql_value(f"UPDATE plumpers SET created_at=now()-interval '{int(minutes)} minutes' WHERE id='{uid}'::uuid")

def wallet(uid):
    row = psql_value(
        f"SELECT w.balance,COALESCE((SELECT SUM(amount) FROM plump_points WHERE owner='{uid}'::uuid),0) "
        f"FROM wallets w WHERE owner='{uid}'::uuid AND kind='user'"
    )
    bal, plump = row.split('|')
    return int(bal), int(plump)

def test_register_pilot_seed_token_and_no_plump_seed():
    reg, jwt = register_login()
    assert re.fullmatch(r"[A-Z2-9]{13}", reg["token"])
    nara, plump = wallet(reg["plumper_id"])
    assert nara == 1313
    assert plump == 0
    assert requests.get(B+"/v1/me", headers=hdr(jwt)).status_code == 200
    assert requests.get(B+"/v1/plumpers/"+reg["plumper_id"]+"/profile").status_code == 200

def test_pilot_age_gate_replaces_kyc_for_drops_and_suspended_still_blocks():
    reg, jwt = register_login()
    body = {"kind":"digital", "title":"pilot digital task", "price":50000}
    early = requests.post(B+"/v1/drops", headers=hdr(jwt), json=body)
    assert early.status_code == 403
    assert early.json()["title"] == "pilot_wait_required"
    age_user(reg["plumper_id"])
    ok = requests.post(B+"/v1/drops", headers=hdr(jwt), json=body)
    assert ok.status_code == 201, ok.text
    psql_value(f"UPDATE plumpers SET suspended_at=now() WHERE id='{reg['plumper_id']}'::uuid")
    blocked = requests.post(B+"/v1/drops", headers=hdr(jwt), json=body)
    assert blocked.status_code in (401, 403)
    if blocked.status_code == 403:
        assert blocked.json()["title"] == "account_suspended"

def test_direct_topup_and_payment_intent_disabled():
    reg, jwt = register_login()
    top = requests.post(B+"/v1/wallet/topups", headers=hdr(jwt), json={"amount":10000})
    assert top.status_code == 403 and top.json()["title"] == "topup_disabled"
    intent = requests.post(B+"/v1/wallet/topups/intent", headers=hdr(jwt), json={"amount":10000})
    assert intent.status_code == 403 and intent.json()["title"] == "payments_disabled"
    webhook = requests.post(B+"/v1/payments/webhook", json={"provider_ref":"x", "intent_id":"00000000-0000-0000-0000-000000000000"})
    assert webhook.status_code == 403 and webhook.json()["title"] == "payments_disabled"
    assert wallet(reg["plumper_id"])[0] == 1313
