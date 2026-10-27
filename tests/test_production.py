import hashlib, hmac as hm, json, time, uuid, psycopg2, requests

B = "http://127.0.0.1:8386"
ADMIN = {"x-admin-key": "plump-admin"}
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"
PAY_SECRET = b"dev-payment-secret"
EKYC_SECRET = b"dev-ekyc-secret"

def db():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

def q(c, sql, a=None):
    with c.cursor() as cur:
        cur.execute(sql, a or ())
        try: return cur.fetchall()
        except psycopg2.ProgrammingError: return None

def user(kyc="verified", nara=500000):
    return requests.post(B+"/v1/dev/users", json={"handle":"prod","kyc":kyc,"nara":nara}).json()["id"]

def hdr(u): return {"Authorization": "Bearer "+u}

def signed(body, key):
    raw = json.dumps(body).encode()
    return raw, {"content-type": "application/json",
                 "x-signature": hm.new(key, raw, hashlib.sha256).hexdigest()}

def golden(a, b, price=90000):
    d = requests.post(B+"/v1/drops", headers=hdr(a), json={"kind":"digital","title":"Việc sạch "+uuid.uuid4().hex[:6],"price":100000}).json()["drop_id"]
    o = requests.post(B+f"/v1/drops/{d}/offers", headers=hdr(b), json={"amount":price}).json()["offer_id"]
    dl = requests.post(B+f"/v1/offers/{o}/accept", headers=hdr(a)).json()["deal_id"]
    requests.post(B+f"/v1/deals/{dl}/start", headers=hdr(b))
    requests.post(B+f"/v1/deals/{dl}/submit", headers=hdr(b), json={"proof":"p"})
    requests.post(B+f"/v1/deals/{dl}/confirm", headers=hdr(a))
    return dl

def wait(fn_, timeout=8, step=0.25):
    t0 = time.time()
    while time.time()-t0 < timeout:
        v = fn_()
        if v: return v
        time.sleep(step)
    return None

# ---------- P1 · Metrics Prometheus + request-id ----------
def test_metrics_and_request_id():
    r = requests.get(B+"/health")
    assert r.headers.get("x-request-id")
    requests.get(B+"/v1/map/drops")
    m = requests.get(B+"/metrics").text
    assert "plump_http_requests_total{" in m
    assert "plump_ledger_mismatch 0" in m
    assert "plump_escrow_balance" in m and "plump_http_duration_ms_bucket" in m

# ---------- P2 · JWKS RS256 (Supabase-style): token RSA ký đúng thì vào ----------
def test_jwks_rs256_verification():
    u = user()
    tok = requests.post(B+"/v1/dev/sign-rs256", json={"sub": u}).json()["token"]
    assert requests.get(B+"/v1/me", headers=hdr(tok)).status_code == 200
    parts = tok.split(".")
    bad = parts[0] + "." + parts[1] + "." + ("A" + parts[2][1:])
    assert requests.get(B+"/v1/me", headers=hdr(bad)).status_code == 401

# ---------- P3 · KMS envelope: DB không còn khóa bản rõ, attestation vẫn verify ----------
def test_mandate_privkey_encrypted_at_rest():
    owner = user()
    twin = requests.post(B+"/v1/twins", headers=hdr(owner), json={"name":"KMS Twin"}).json()["twin_id"]
    m = requests.post(B+f"/v1/twins/{twin}/mandates", headers=hdr(owner),
        json={"categories":["dich_av"],"max_price":150000}).json()
    c = db()
    prv, enc = q(c, "SELECT privkey, privkey_enc FROM twin_mandates WHERE id=%s", (m["mandate_id"],))[0]
    c.close()
    assert prv is None and enc and len(enc) > 60      # bản rõ tuyệt chủng, chỉ còn ciphertext GCM

# ---------- P4 · Pilot: mọi đường nạp/payment bị niêm phong ----------
def test_payment_rails_disabled_in_pilot():
    u = user(nara=0)
    intent = requests.post(B+"/v1/wallet/topups/intent", headers=hdr(u), json={"amount":120000})
    assert intent.status_code == 403 and intent.json()["title"] == "payments_disabled"
    webhook = requests.post(B+"/v1/payments/webhook", json={
        "provider_ref":"disabled", "intent_id":str(uuid.uuid4())})
    assert webhook.status_code == 403 and webhook.json()["title"] == "payments_disabled"

# ---------- P5 · Pilot: KYC submit/callback bị niêm phong ----------
def test_kyc_rails_disabled_in_pilot():
    u = user(kyc="none")
    submit = requests.post(B+"/v1/kyc/ekyc", headers=hdr(u),
                           json={"provider":"vneid","ref":"VNeID-cb"})
    assert submit.status_code == 403 and submit.json()["title"] == "kyc_disabled"
    callback = requests.post(B+"/v1/kyc/webhook", json={"kyc_id":str(uuid.uuid4()),"result":"approved"})
    assert callback.status_code == 403 and callback.json()["title"] == "kyc_disabled"
    assert requests.get(B+"/v1/kyc/status", headers=hdr(u)).json()["status"] == "none"

# ---------- P6 · Trang pháp lý ----------
def test_legal_pages():
    for p, kw in (("/terms","không đặt trần"), ("/privacy","72 giờ")):
        r = requests.get(B+p)
        assert r.status_code == 200 and kw in r.text and "SuperPlump" in r.text

# ---------- P7 · Từ cấm chặn tại SQL ----------
def test_banned_words_blocked():
    u = user()
    r = requests.post(B+"/v1/drops", headers=hdr(u),
        json={"kind":"digital","title":"bán test-banned-word giá rẻ","price":50000})
    assert r.status_code == 422 and r.json()["title"] == "content_blocked"

# ---------- P8 · Report → admin gỡ tin: biến khỏi chợ ----------
def test_report_and_admin_hide():
    a, x = user(), user()
    d = requests.post(B+"/v1/drops", headers=hdr(a),
        json={"kind":"digital","title":"Tin bị tố cáo nè","price":50000}).json()["drop_id"]
    rid = requests.post(B+"/v1/reports", headers=hdr(x),
        json={"target_kind":"drop","target_id":d,"reason":"lừa đảo"}).json()["report_id"]
    assert any(i["id"]==rid for i in requests.get(B+"/v1/admin/reports", headers=ADMIN).json()["items"])
    requests.post(B+f"/v1/admin/reports/{rid}/action", headers=ADMIN, json={"action":"hide_target"})
    c = db()
    st = q(c, "SELECT status, mod_status FROM drops WHERE id=%s", (d,))[0]
    c.close()
    assert st == ("cancelled", "flagged")

# ---------- P9 · Treo tài khoản: hành động chết, gỡ treo sống lại ----------
def test_suspension_blocks_actions():
    u = user()
    requests.post(B+f"/v1/admin/plumpers/{u}/suspend", headers=ADMIN)
    r = requests.post(B+"/v1/drops", headers=hdr(u),
        json={"kind":"digital","title":"Đăng khi bị treo","price":50000})
    assert r.status_code == 403 and r.json()["title"] == "account_suspended"
    requests.post(B+f"/v1/admin/plumpers/{u}/unsuspend", headers=ADMIN)
    assert requests.post(B+"/v1/drops", headers=hdr(u),
        json={"kind":"digital","title":"Đăng sau gỡ treo","price":50000}).status_code == 201

# ---------- P10 · Radar thông đồng: cặp settle 4 deal/ngày → cắm cờ ----------
def test_collusion_pair_flagged():
    a, b = user(nara=2_000_000), user()
    for _ in range(4): golden(a, b)
    c = db()
    n = q(c, """SELECT count(*) FROM fraud_flags WHERE kind='pair_velocity'
                AND a=LEAST(%s::uuid,%s::uuid) AND b=GREATEST(%s::uuid,%s::uuid)""", (a,b,a,b))[0][0]
    c.close()
    assert n == 1

# ---------- P11 · AI moderation (worker): tin bẩn tự bị gỡ, tin sạch được duyệt ----------
def test_ai_moderation_worker():
    u = user()
    bad = requests.post(B+"/v1/drops", headers=hdr(u),
        json={"kind":"digital","title":"giao hàng flag-me tối nay","price":50000}).json()["drop_id"]
    ok = requests.post(B+"/v1/drops", headers=hdr(u),
        json={"kind":"digital","title":"Thiết kế logo cà phê","price":50000}).json()["drop_id"]
    c = db()
    got = wait(lambda: (q(c, "SELECT mod_status,status FROM drops WHERE id=%s", (bad,))[0]
                        if q(c, "SELECT mod_status FROM drops WHERE id=%s", (bad,))[0][0] != "pending" else None))
    assert got == ("flagged", "cancelled")
    got2 = wait(lambda: (q(c, "SELECT mod_status FROM drops WHERE id=%s", (ok,))[0]
                         if q(c, "SELECT mod_status FROM drops WHERE id=%s", (ok,))[0][0] != "pending" else None))
    c.close()
    assert got2 == ("ok",)
