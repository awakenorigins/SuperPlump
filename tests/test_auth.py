import re, uuid, psycopg2, requests

B = "http://127.0.0.1:8386"
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def db():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

def jh(tok): return {"Authorization": "Bearer "+tok}

def register():
    r = requests.post(B+"/v1/auth/register"); r.raise_for_status(); return r.json()

def login(**body):
    return requests.post(B+"/v1/auth/login", json=body)

# ---------- AU1 · Regnick: token 13 ký tự chữ+số, chỉ lưu hash ----------
def test_register_token_format_and_hash_only():
    r = register()
    tok = r["token"]
    assert re.fullmatch(r"[A-Z2-9]{13}", tok) and len(tok) == 13
    c = db()
    with c.cursor() as cur:
        cur.execute("SELECT token_hash FROM plumpers WHERE id=%s", (r["plumper_id"],))
        h = cur.fetchone()[0]
    c.close()
    assert h != tok and re.fullmatch(r"[0-9a-f]{64}", h)     # sha256, không bản rõ

# ---------- AU2 · Login bằng token → JWT dùng được; token sai → 401 ----------
def test_login_with_token():
    r = register()
    l = login(token=r["token"])
    assert l.status_code == 200
    j = l.json()
    assert j["onboarded"] is False and j["role"] == "plumper"
    assert requests.get(B+"/v1/me", headers=jh(j["jwt"])).status_code == 200
    assert login(token="SAITOKEN12345").status_code == 401

# ---------- AU3 · Onboarding: username một lần, cấm trùng, cấm tên hệ thống ----------
def test_onboarding_username_rules():
    r = register(); j = login(token=r["token"]).json()
    uname = "plumper" + uuid.uuid4().hex[:8]
    assert requests.post(B+"/v1/auth/username", headers=jh(j["jwt"]),
                         json={"username": uname}).status_code == 200
    r2 = register(); j2 = login(token=r2["token"]).json()
    dup = requests.post(B+"/v1/auth/username", headers=jh(j2["jwt"]), json={"username": uname})
    assert dup.status_code == 409 and dup.json()["title"] == "username_taken"
    res = requests.post(B+"/v1/auth/username", headers=jh(j2["jwt"]), json={"username": "chaunacha"})
    assert res.status_code == 409 and res.json()["title"] == "username_reserved"
    again = requests.post(B+"/v1/auth/username", headers=jh(j["jwt"]), json={"username": uname+"x"})
    assert again.status_code == 409 and again.json()["title"] == "already_onboarded"

# ---------- AU4 · Sau onboarding: login token HAY username+password đều được ----------
def test_dual_login_token_or_password():
    r = register(); j = login(token=r["token"]).json()
    uname = "song" + uuid.uuid4().hex[:9]
    requests.post(B+"/v1/auth/username", headers=jh(j["jwt"]), json={"username": uname})
    requests.post(B+"/v1/auth/password", headers=jh(j["jwt"]), json={"password": "matkhau-manh-8"})
    byp = login(username=uname, password="matkhau-manh-8")
    assert byp.status_code == 200 and byp.json()["onboarded"] is True
    assert login(token=r["token"]).status_code == 200          # token 13 ký tự vẫn sống
    assert login(username=uname, password="sai-mat-khau").status_code == 401
    short = requests.post(B+"/v1/auth/login", json={"username": uname, "password": "ngan"})
    assert short.status_code == 400                             # zod chặn từ cửa

# ---------- AU5 · Email bổ sung sau trong settings ----------
def test_email_added_later_in_settings():
    r = register(); j = login(token=r["token"]).json()
    em = f"plumper{uuid.uuid4().hex[:8]}@example.vn"
    assert requests.patch(B+"/v1/me/settings", headers=jh(j["jwt"]),
                          json={"email": em}).status_code == 200
    me = requests.get(B+"/v1/me", headers=jh(j["jwt"])).json()
    assert me["email"] == em
    assert requests.patch(B+"/v1/me/settings", headers=jh(j["jwt"]),
                          json={"email": "khong-phai-email"}).status_code == 400
    r2 = register(); j2 = login(token=r2["token"]).json()
    dup = requests.patch(B+"/v1/me/settings", headers=jh(j2["jwt"]), json={"email": em})
    assert dup.status_code == 409 and dup.json()["title"] == "email_taken"

# ---------- AU6 · OWNER: gõ "chaunacha" là vào, full quyền admin ----------
def test_owner_token_full_rights():
    l = login(token="chaunacha")
    assert l.status_code == 200
    j = l.json(); assert j["role"] == "owner"
    ov = requests.get(B+"/v1/admin/overview", headers=jh(j["jwt"]))     # KHÔNG cần x-admin-key
    assert ov.status_code == 200 and "escrow" in ov.json()
    r = register(); pj = login(token=r["token"]).json()
    assert requests.get(B+"/v1/admin/overview", headers=jh(pj["jwt"])).status_code == 403
    assert requests.get(B+"/v1/me", headers=jh(j["jwt"])).json()["handle"] == "owner"
