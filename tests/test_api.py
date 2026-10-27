import uuid, psycopg2, pytest, requests

B = "http://127.0.0.1:8386"
ADMIN = {"x-admin-key": "plump-admin"}
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def db():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

def user(kyc="verified", nara=500000):
    r = requests.post(B+"/v1/dev/users", json={"handle":"e2e","kyc":kyc,"nara":nara}); r.raise_for_status()
    return r.json()["id"]

def hdr(uid): return {"Authorization": "Bearer "+uid}

def full_deal(a=None, b=None, price=95000):
    a, b = a or user(), b or user()
    drop = requests.post(B+"/v1/drops", headers=hdr(a),
        json={"kind":"local","title":"E2E dọn kho","price":110000,"lng":106.7009,"lat":10.7379}).json()["drop_id"]
    off = requests.post(B+f"/v1/drops/{drop}/offers", headers=hdr(b), json={"amount":price}).json()["offer_id"]
    deal = requests.post(B+f"/v1/offers/{off}/accept", headers=hdr(a)).json()["deal_id"]
    return a, b, drop, off, deal

# ---------- E1 · health + vòng đời trọn vẹn qua HTTP ----------
def test_e2e_full_lifecycle():
    assert requests.get(B+"/health").json()["ok"] is True
    a, b, drop, off, deal = full_deal()
    assert requests.post(B+f"/v1/deals/{deal}/start",  headers=hdr(b)).json()["state"] == "IN_PROGRESS"
    assert requests.post(B+f"/v1/deals/{deal}/submit", headers=hdr(b),
                         json={"proof":"proof://e2e.jpg"}).json()["state"] == "SUBMITTED"
    assert requests.post(B+f"/v1/deals/{deal}/confirm", headers=hdr(a)).json()["state"] == "SETTLED"
    assert requests.get(B+"/v1/wallet", headers=hdr(b)).json()["available"] == 500000 + 90250
    tl = [e["event_type"] for e in requests.get(B+f"/v1/deals/{deal}", headers=hdr(a)).json()["timeline"]]
    assert tl == ["locked","started","submitted","settled"]

# ---------- E2 · KYC gate qua HTTP: 403 problem+json, duyệt xong thì mở ----------
def test_kyc_gate_and_admin_approve():
    u = user(kyc="none")
    r = requests.post(B+"/v1/drops", headers=hdr(u),
                      json={"kind":"digital","title":"việc test kyc","price":50000})
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["title"] == "kyc_required"
    kid = requests.post(B+"/v1/kyc/ekyc", headers=hdr(u), json={"provider":"vneid","ref":"VNeID-t"}).json()["kyc_id"]
    assert requests.get(B+"/v1/kyc/status", headers=hdr(u)).json()["status"] == "pending"
    assert requests.post(B+f"/v1/admin/kyc/{kid}/approve", headers=ADMIN).ok
    assert requests.get(B+"/v1/kyc/status", headers=hdr(u)).json()["status"] == "verified"
    assert requests.post(B+"/v1/drops", headers=hdr(u),
                         json={"kind":"digital","title":"việc test kyc","price":50000}).status_code == 201

# ---------- E3 · Idempotency-Key: gọi 2 lần → cùng 1 deal, DB chỉ 1 ----------
def test_idempotency_key_replay():
    a, b = user(), user()
    drop = requests.post(B+"/v1/drops", headers=hdr(a),
        json={"kind":"local","title":"idem","price":80000,"lng":106.68,"lat":10.75}).json()["drop_id"]
    off = requests.post(B+f"/v1/drops/{drop}/offers", headers=hdr(b), json={"amount":80000}).json()["offer_id"]
    key = str(uuid.uuid4())
    h = {**hdr(a), "Idempotency-Key": key}
    r1 = requests.post(B+f"/v1/offers/{off}/accept", headers=h)
    r2 = requests.post(B+f"/v1/offers/{off}/accept", headers=h)
    assert r1.json()["deal_id"] == r2.json()["deal_id"]
    c = db(); cur = c.cursor()
    cur.execute("SELECT count(*) FROM deals WHERE drop_id=%s", (drop,))
    assert cur.fetchone()[0] == 1; c.close()

# ---------- E4 · Riêng tư qua HTTP: map trả tọa độ mờ, người lạ 403 ----------
def test_privacy_over_http():
    a, b, drop, off, deal = full_deal()
    items = requests.get(B+"/v1/map/drops?bbox=106.5,10.6,106.95,10.95").json()["items"]
    for it in items:
        if it.get("fuzzy_lng") is not None:
            m = abs(it["fuzzy_lng"]) % 0.003
            assert min(m, 0.003-m) < 1e-9          # mọi tọa độ public đều nằm trên lưới mờ
    stranger = user()
    r = requests.get(B+f"/v1/deals/{deal}/location", headers=hdr(stranger))
    assert r.status_code == 403 and r.json()["title"] == "location_denied"
    ok = requests.get(B+f"/v1/deals/{deal}/location", headers=hdr(b)).json()
    assert abs(ok["lng"] - 106.7009) < 1e-6        # hai bên deal: thấy thật

# ---------- E5 · Review mù qua HTTP ----------
def test_blind_reviews_over_http():
    a, b, drop, off, deal = full_deal()
    requests.post(B+f"/v1/deals/{deal}/start", headers=hdr(b))
    requests.post(B+f"/v1/deals/{deal}/submit", headers=hdr(b), json={})
    requests.post(B+f"/v1/deals/{deal}/confirm", headers=hdr(a))
    requests.post(B+f"/v1/deals/{deal}/reviews", headers=hdr(b), json={"rating":5,"body":"ngon"})
    assert requests.get(B+f"/v1/deals/{deal}/reviews").json()["items"] == []      # còn mù
    requests.post(B+f"/v1/deals/{deal}/reviews", headers=hdr(a), json={"rating":4,"body":"ok"})
    assert len(requests.get(B+f"/v1/deals/{deal}/reviews").json()["items"]) == 2  # cùng mở

# ---------- E6 · Tranh chấp: đóng băng → admin refund → ví hồi nguyên ----------
def test_dispute_admin_refund_over_http():
    a, b, drop, off, deal = full_deal(price=100000)
    requests.post(B+f"/v1/deals/{deal}/disputes", headers=hdr(b), json={"reason":"không đúng mô tả"})
    r = requests.post(B+f"/v1/deals/{deal}/confirm", headers=hdr(a))
    assert r.status_code == 409                    # đóng băng: không transition được
    assert requests.post(B+f"/v1/admin/disputes/{deal}/resolve", headers=ADMIN,
                         json={"outcome":"refund"}).ok
    assert requests.get(B+"/v1/wallet", headers=hdr(a)).json()["available"] == 500000

# ---------- E7 · Auto-confirm chạy qua endpoint vận hành ----------
def test_auto_confirm_job_endpoint():
    a, b, drop, off, deal = full_deal(price=70000)
    requests.post(B+f"/v1/deals/{deal}/start", headers=hdr(b))
    requests.post(B+f"/v1/deals/{deal}/submit", headers=hdr(b), json={"proof":"p"})
    c = db(); cur = c.cursor()
    cur.execute("UPDATE deals SET submitted_at = now() - interval '13 hours' WHERE id=%s", (deal,)); c.close()
    assert requests.post(B+"/v1/admin/jobs/auto-confirm", headers=ADMIN).json()["settled"] >= 1
    assert requests.get(B+"/v1/wallet", headers=hdr(b)).json()["available"] == 500000 + 66500

# ---------- E8 · Sai vai / admin key sai → chặn đúng mã ----------
def test_auth_and_role_errors():
    a, b, drop, off, deal = full_deal()
    assert requests.post(B+f"/v1/deals/{deal}/start", headers=hdr(a)).status_code == 403
    assert requests.get(B+"/v1/admin/overview", headers={"x-admin-key":"sai"}).status_code == 403
    assert requests.get(B+"/v1/wallet").status_code == 401
