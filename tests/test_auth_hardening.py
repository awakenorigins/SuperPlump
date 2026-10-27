import base64, hashlib, hmac, struct, time, uuid, psycopg2, requests

B = "http://127.0.0.1:8386"
ADMIN = {"x-admin-key": "plump-admin"}
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def jh(t): return {"Authorization": "Bearer "+t}
def register(): return requests.post(B+"/v1/auth/register").json()
def login(**b): return requests.post(B+"/v1/auth/login", json=b)

def onboard(pw="matkhau-manh-8"):
    r = register(); j = login(token=r["token"]).json()
    un = "h" + uuid.uuid4().hex[:10]
    requests.post(B+"/v1/auth/username", headers=jh(j["jwt"]), json={"username": un})
    requests.post(B+"/v1/auth/password", headers=jh(j["jwt"]), json={"password": pw})
    return r, j, un

def totp(secret_b32, offset=0):
    key = base64.b32decode(secret_b32 + "=" * ((8 - len(secret_b32) % 8) % 8))
    counter = int(time.time() // 30) + offset
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0xF
    return str(((h[o] & 0x7F) << 24 | h[o+1] << 16 | h[o+2] << 8 | h[o+3]) % 10**6).zfill(6)

def mailbox_code(email):
    for _ in range(20):
        items = requests.get(B+"/v1/dev/mailbox", params={"to": email}).json()["items"]
        if items: return items[0]["code"]
        time.sleep(0.1)
    return None

# ---------- H1 · Lockout: 5 phát sai → phát 6 khóa luôn cả pass đúng ----------
def test_lockout_after_five_failures():
    _, _, un = onboard()
    for _ in range(5):
        assert login(username=un, password="sai-bet-roi-8").status_code == 401
    r = login(username=un, password="matkhau-manh-8")
    assert r.status_code == 429 and r.json()["title"] == "locked_out"

# ---------- H2 · Logout thu hồi phiên: JWT cũ chết ngay ----------
def test_logout_revokes_session():
    r, _, un = onboard()
    j = login(username=un, password="matkhau-manh-8").json()["jwt"]
    assert requests.get(B+"/v1/me", headers=jh(j)).status_code == 200
    assert requests.post(B+"/v1/auth/logout", headers=jh(j)).status_code == 200
    dead = requests.get(B+"/v1/me", headers=jh(j))
    assert dead.status_code == 401 and dead.json()["title"] == "session_revoked"

# ---------- H3 · Refresh rotation: jwt mới sống, jwt cũ chết ----------
def test_refresh_rotation():
    r = register()
    j_old = login(token=r["token"]).json()["jwt"]
    j_new = requests.post(B+"/v1/auth/refresh", headers=jh(j_old)).json()["jwt"]
    assert requests.get(B+"/v1/me", headers=jh(j_new)).status_code == 200
    assert requests.get(B+"/v1/me", headers=jh(j_old)).status_code == 401

# ---------- H4 · Owner revoke-all: đuổi mọi phiên của một user ----------
def test_owner_revoke_all_sessions():
    r = register()
    j1 = login(token=r["token"]).json()["jwt"]
    j2 = login(token=r["token"]).json()["jwt"]
    out = requests.post(B+f"/v1/admin/plumpers/{r['plumper_id']}/revoke-all", headers=ADMIN).json()
    assert out["revoked"] >= 2
    assert requests.get(B+"/v1/me", headers=jh(j1)).status_code == 401
    assert requests.get(B+"/v1/me", headers=jh(j2)).status_code == 401
    ses = login(token=r["token"]).json()["jwt"]
    lst = requests.get(B+"/v1/me/sessions", headers=jh(ses)).json()["items"]
    assert sum(1 for x in lst if x["revoked_at"]) >= 2

# ---------- H5 · Verify email qua hộp thư dev; mã sai bị chặn ----------
def test_email_verification_flow():
    r = register(); j = login(token=r["token"]).json()["jwt"]
    em = f"v{uuid.uuid4().hex[:8]}@example.vn"
    requests.patch(B+"/v1/me/settings", headers=jh(j), json={"email": em})
    assert requests.post(B+"/v1/me/email/verify-request", headers=jh(j)).json()["sent"]
    assert requests.post(B+"/v1/me/email/verify", headers=jh(j),
                         json={"code": "000000"}).status_code == 401
    code = mailbox_code(em); assert code
    assert requests.post(B+"/v1/me/email/verify", headers=jh(j),
                         json={"code": code}).json()["verified"] is True

# ---------- H6 · Quên mật khẩu: reset qua email verify + thu hồi mọi phiên ----------
def test_forgot_reset_password():
    r, _, un = onboard()
    j = login(username=un, password="matkhau-manh-8").json()["jwt"]
    em = f"f{uuid.uuid4().hex[:8]}@example.vn"
    requests.patch(B+"/v1/me/settings", headers=jh(j), json={"email": em})
    requests.post(B+"/v1/me/email/verify-request", headers=jh(j))
    requests.post(B+"/v1/me/email/verify", headers=jh(j), json={"code": mailbox_code(em)})
    assert requests.post(B+"/v1/auth/forgot", json={"email": em}).json()["ok"]
    code = mailbox_code(em)
    assert requests.post(B+"/v1/auth/reset",
        json={"email": em, "code": code, "password": "mat-khau-moi-9"}).json()["reset"]
    assert login(username=un, password="matkhau-manh-8").status_code == 401   # pass cũ chết
    assert login(username=un, password="mat-khau-moi-9").status_code == 200   # pass mới sống
    assert requests.get(B+"/v1/me", headers=jh(j)).status_code == 401         # phiên cũ bị đuổi

# ---------- H7 · Mất token 13 ký tự: owner cấp lại tay, token cũ vô hiệu ----------
def test_owner_manual_token_reissue():
    r, _, un = onboard()
    req = requests.post(B+"/v1/auth/recovery", json={"username": un, "note": "mất token"}).json()
    lst = requests.get(B+"/v1/admin/recovery", headers=ADMIN).json()["items"]
    assert any(x["id"] == req["request_id"] for x in lst)
    out = requests.post(B+f"/v1/admin/recovery/{req['request_id']}/reissue-token", headers=ADMIN).json()
    new_tok = out["new_token"]
    assert len(new_tok) == 13
    assert login(token=r["token"]).status_code == 401       # token cũ chết
    assert login(token=new_tok).status_code == 200           # token mới sống

# ---------- H8 · 2FA owner: login chaunacha → đòi mã TOTP → mã đúng mới có full quyền ----------
def test_owner_2fa_full_flow():
    j = login(token="chaunacha").json()["jwt"]
    setup = requests.post(B+"/v1/auth/2fa/setup", headers=jh(j)).json()
    secret = setup["secret"]
    assert requests.post(B+"/v1/auth/2fa/confirm", headers=jh(j),
                         json={"code": totp(secret)}).json()["enabled"]
    try:
        step1 = login(token="chaunacha").json()
        assert step1.get("mfa_required") is True and "jwt" not in step1
        bad = requests.post(B+"/v1/auth/mfa", json={"mfa_token": step1["mfa_token"], "code": "000000"})
        assert bad.status_code == 401
        good = requests.post(B+"/v1/auth/mfa",
                             json={"mfa_token": step1["mfa_token"], "code": totp(secret)}).json()
        assert good["role"] == "owner"
        assert requests.get(B+"/v1/admin/overview", headers=jh(good["jwt"])).status_code == 200
        assert requests.get(B+"/v1/me", headers=jh(step1["mfa_token"])).status_code == 401  # mfa-token ≠ JWT
    finally:
        j2 = requests.post(B+"/v1/auth/mfa",
            json={"mfa_token": login(token="chaunacha").json()["mfa_token"],
                  "code": totp(secret)}).json()["jwt"]
        assert requests.post(B+"/v1/auth/2fa/disable", headers=jh(j2),
                             json={"code": totp(secret)}).json()["disabled"]
