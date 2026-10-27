import time, uuid, jwt as pyjwt, psycopg2, pytest, requests

B = "http://127.0.0.1:8386"
ADMIN = {"x-admin-key": "plump-admin"}
SECRET = "dev-jwt-secret"
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def db():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

def q(c, sql, a=None):
    with c.cursor() as cur:
        cur.execute(sql, a or ())
        try: return cur.fetchall()
        except psycopg2.ProgrammingError: return None

def user(kyc="verified", nara=500000):
    return requests.post(B+"/v1/dev/users", json={"handle":"sec","kyc":kyc,"nara":nara}).json()["id"]

def hdr(uid): return {"Authorization": "Bearer "+uid}
def jhdr(uid): return {"Authorization": "Bearer "+pyjwt.encode({"sub":uid}, SECRET, algorithm="HS256")}

# ---------- A1 · JWT thật: token ký đúng vào được, rác thì 401, dev-uuid vẫn chạy ở dev ----------
def test_jwt_auth_paths():
    u = user()
    assert requests.get(B+"/v1/wallet", headers=jhdr(u)).status_code == 200
    bad = {"Authorization": "Bearer "+pyjwt.encode({"sub":u}, "sai-secret", algorithm="HS256")}
    assert requests.get(B+"/v1/wallet", headers=bad).status_code == 401
    assert requests.get(B+"/v1/wallet", headers=hdr(u)).status_code == 200   # dev fallback
    assert requests.get(B+"/v1/wallet").status_code == 401

# ---------- A2 · Helmet headers ----------
def test_security_headers():
    r = requests.get(B+"/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert "x-powered-by" not in {k.lower() for k in r.headers}

# ---------- A3 · zod validation: dữ liệu bẩn chết ở cửa ----------
def test_validation_rejects_garbage():
    u = user()
    r = requests.post(B+"/v1/drops", headers=hdr(u),
        json={"kind":"local","title":"x","price":500,"lng":200,"lat":10.7})
    assert r.status_code == 400 and r.json()["title"] == "validation_error"
    r2 = requests.post(B+"/v1/deals/%s/reviews" % uuid.uuid4(), headers=hdr(u), json={"rating":9})
    assert r2.status_code == 400

# ---------- A4 · Rate limit nạp: 10/phút, cái thứ 11 → 429 ----------
def test_topup_rate_limited():
    u = user()
    codes = [requests.post(B+"/v1/wallet/topups", headers=hdr(u), json={"amount":10000}).status_code
             for _ in range(11)]
    assert codes[:10] == [201]*10 and codes[10] == 429

# ---------- A5 · Consent gate (bật cờ PDPL): chưa đồng ý vị trí → 403, đồng ý → 201 ----------
def test_location_consent_gate():
    c = db(); u = user()
    q(c, "UPDATE config SET val = jsonb_set(val,'{enforce_location_consent}','true') WHERE key='pdpl'")
    try:
        r = requests.post(B+"/v1/drops", headers=hdr(u),
            json={"kind":"local","title":"Cần consent","price":50000,"lng":106.7,"lat":10.73})
        assert r.status_code == 403 and r.json()["title"] == "consent_required"
        requests.post(B+"/v1/me/consents", headers=hdr(u), json={"purpose":"location","granted":True})
        r2 = requests.post(B+"/v1/drops", headers=hdr(u),
            json={"kind":"local","title":"Cần consent","price":50000,"lng":106.7,"lat":10.73})
        assert r2.status_code == 201
        got = requests.get(B+"/v1/me/consents", headers=hdr(u)).json()["items"]
        assert any(x["purpose"]=="location" and x["granted"] for x in got)
    finally:
        q(c, "UPDATE config SET val = jsonb_set(val,'{enforce_location_consent}','false') WHERE key='pdpl'")
        c.close()

# ---------- A6 · Quyền được lãng quên: scrub PII, sổ tiền giữ nguyên ----------
def test_data_request_delete_scrubs_pii():
    u = user()
    rid = requests.post(B+"/v1/me/data-requests", headers=hdr(u),
                        json={"kind":"delete","note":"xóa giúp mình"}).json()["request_id"]
    lst = requests.get(B+"/v1/admin/data-requests", headers=ADMIN).json()["items"]
    assert any(x["id"]==rid for x in lst)
    assert requests.post(B+f"/v1/admin/data-requests/{rid}/process", headers=ADMIN).ok
    c = db()
    name = q(c, "SELECT display_name FROM plumpers WHERE id=%s", (u,))[0][0]
    assert name == "Đã xóa theo yêu cầu"
    n_ledger = q(c, """SELECT count(*) FROM ledger_entries l JOIN wallets w ON w.id=l.wallet_id
                       WHERE w.owner=%s""", (u,))[0][0]
    assert n_ledger >= 1          # nghĩa vụ kế toán: tiền không bị xóa
    c.close()

# ---------- A7 · eKYC Điều 29: không ảnh giấy tờ, duyệt xong là verified ----------
def test_ekyc_no_document_images():
    u = user(kyc="none")
    r = requests.post(B+"/v1/kyc/ekyc", headers=hdr(u), json={"provider":"vneid","ref":"VNeID-8xk2"})
    assert r.status_code == 201
    kid = r.json()["kyc_id"]
    c = db()
    doc, prov = q(c, "SELECT COALESCE(doc_url,''), provider FROM kyc_records WHERE id=%s", (kid,))[0]
    assert doc == "" and prov == "vneid"     # không lưu ảnh CCCD
    c.close()
    requests.post(B+f"/v1/admin/kyc/{kid}/approve", headers=ADMIN)
    assert requests.get(B+"/v1/kyc/status", headers=hdr(u)).json()["status"] == "verified"

# ---------- A8 · Idempotency TTL: key cũ bị dọn ----------
def test_idempotency_ttl_cleanup():
    c = db(); k = "old-"+str(uuid.uuid4())
    q(c, """INSERT INTO idempotency_keys(key,status,body,created_at)
            VALUES (%s,200,'{}','2020-01-01')""", (k,))
    r = requests.post(B+"/v1/admin/jobs/cleanup-idempotency", headers=ADMIN, json={"hours":48}).json()
    assert r["deleted"] >= 1
    assert q(c, "SELECT count(*) FROM idempotency_keys WHERE key=%s", (k,))[0][0] == 0
    c.close()

# ---------- A9 · Sự cố 72h: deadline tự sinh ----------
def test_incident_72h_deadline():
    r = requests.post(B+"/v1/admin/incidents", headers=ADMIN,
                      json={"severity":"high","summary":"test breach"}).json()
    assert "report_by_72h" in r and r["report_by_72h"] is not None
