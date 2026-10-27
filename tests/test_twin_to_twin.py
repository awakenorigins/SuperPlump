import uuid, requests, psycopg2

B = "http://127.0.0.1:8386"
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def db():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

def user(plump=0, nara=5000000):
    return requests.post(B+"/v1/dev/users",
        json={"handle":"tt","kyc":"verified","nara":nara,"plump":plump}).json()["id"]

def hdr(u): return {"Authorization": "Bearer "+u}

def settle_human(dropper, executor, price, rate=5):
    d = requests.post(B+"/v1/drops", headers=hdr(dropper),
        json={"kind":"digital","title":"H "+uuid.uuid4().hex[:6],"price":price}).json()["drop_id"]
    o = requests.post(B+f"/v1/drops/{d}/offers", headers=hdr(executor), json={"amount":price}).json()["offer_id"]
    dl = requests.post(B+f"/v1/offers/{o}/accept", headers=hdr(dropper)).json()["deal_id"]
    requests.post(B+f"/v1/deals/{dl}/start", headers=hdr(executor))
    requests.post(B+f"/v1/deals/{dl}/submit", headers=hdr(executor), json={"proof":"p"})
    requests.post(B+f"/v1/deals/{dl}/confirm", headers=hdr(dropper))
    requests.post(B+f"/v1/deals/{dl}/reviews", headers=hdr(dropper), json={"rating":rate,"body":"x"})
    requests.post(B+f"/v1/deals/{dl}/reviews", headers=hdr(executor), json={"rating":5,"body":"y"})

def make_owner_level(owner, target):
    for _ in range(3): settle_human(user(), user(), 100000)
    n = {2:2,3:6,4:16,5:42}.get(target,0)
    for _ in range(n): settle_human(user(), owner, 90000, rate=5)

def create_twin(owner, qualify="general"):
    tid = requests.post(B+"/v1/twins", headers=hdr(owner), json={"name":"Tw"+uuid.uuid4().hex[:4]}).json()["twin_id"]
    c = db(); cur = c.cursor()
    cur.execute("INSERT INTO qualifications(twin_id,category,level,soul_version) VALUES (%s,%s,'bronze',1)", (tid, qualify))
    cur.execute("UPDATE twins SET energy=1000 WHERE id=%s", (tid,))
    c.close()
    requests.post(B+f"/v1/twins/{tid}/mandates", headers=hdr(owner),
        json={"categories":[qualify],"max_price":10_000_000,"hours":720})
    return tid

def give_plump(owner, amount):
    c = db(); cur = c.cursor()
    cur.execute("INSERT INTO plump_points(owner,amount,reason) VALUES (%s,%s,'test_seed')", (owner, amount))
    c.close()

def plump_bal(owner):
    return requests.get(B+"/v1/wallet", headers=hdr(owner)).json()["plump"]

def post_market(owner, twin, price=300, cat="general"):
    return requests.post(B+"/v1/twin-market", headers=hdr(owner),
        json={"twin_id":twin,"category":cat,"title":"Tach nen 50 anh","price_plump":price})

def take_market(owner, twin, market_id):
    return requests.post(B+f"/v1/twin-market/{market_id}/take", headers=hdr(owner), json={"twin_id":twin})

# ---------- M1 · Chỉ Lv5 mới đăng được việc twin-to-twin ----------
def test_only_level5_can_post():
    o3 = user(); make_owner_level(o3, 3); tw3 = create_twin(o3)
    give_plump(o3, 100000)
    r = post_market(o3, tw3)
    assert r.status_code == 403 and "twin_market_requires_level" in r.text

def test_level5_can_post():
    o5 = user(); make_owner_level(o5, 5); tw5 = create_twin(o5)
    give_plump(o5, 100000)
    r = post_market(o5, tw5)
    assert r.status_code == 201 and "market_drop_id" in r.json()

# ---------- M2 · Lần đầu cặp chủ giao dịch → CẦN DUYỆT ----------
def test_first_transaction_needs_approval():
    poster = user(); make_owner_level(poster, 5); ptw = create_twin(poster); give_plump(poster, 100000)
    taker = user(); make_owner_level(taker, 5); ttw = create_twin(taker)
    md = post_market(poster, ptw, price=300).json()["market_drop_id"]
    r = take_market(taker, ttw, md)
    assert r.status_code == 201
    assert r.json()["state"] == "PENDING_APPROVAL", f"lần đầu phải chờ duyệt, thực {r.json()['state']}"

# ---------- M3 · Chủ đăng duyệt → APPROVED → kết toán chuyển Plump ----------
def test_approve_and_settle_transfers_plump():
    poster = user(); make_owner_level(poster, 5); ptw = create_twin(poster); give_plump(poster, 100000)
    taker = user(); make_owner_level(taker, 5); ttw = create_twin(taker)
    md = post_market(poster, ptw, price=300).json()["market_drop_id"]
    deal = take_market(taker, ttw, md).json()["market_deal_id"]
    # chủ đăng duyệt
    ap = requests.post(B+f"/v1/twin-market/deals/{deal}/approve", headers=hdr(poster), json={"ok":True})
    assert ap.json()["result"] == "APPROVED"
    p0 = plump_bal(poster); t0 = plump_bal(taker)
    # kết toán
    requests.post(B+f"/v1/twin-market/deals/{deal}/settle", headers=hdr(poster))
    p1 = plump_bal(poster); t1 = plump_bal(taker)
    assert p0 - p1 == 300, f"chủ đăng trả 300 Plump, thực {p0-p1}"
    assert t1 - t0 == 300, f"chủ nhận +300 Plump, thực {t1-t0}"

# ---------- M4 · Cặp đã duyệt → lần sau TỰ ĐỘNG (không cần duyệt) ----------
def test_trusted_pair_auto_approves():
    poster = user(); make_owner_level(poster, 5); ptw = create_twin(poster); give_plump(poster, 100000)
    taker = user(); make_owner_level(taker, 5); ttw = create_twin(taker)
    # giao dịch 1: duyệt tay
    md1 = post_market(poster, ptw, price=300).json()["market_drop_id"]
    d1 = take_market(taker, ttw, md1).json()["market_deal_id"]
    requests.post(B+f"/v1/twin-market/deals/{d1}/approve", headers=hdr(poster), json={"ok":True})
    requests.post(B+f"/v1/twin-market/deals/{d1}/settle", headers=hdr(poster))
    # giao dịch 2: cùng cặp chủ → tự động APPROVED
    md2 = post_market(poster, ptw, price=200).json()["market_drop_id"]
    r2 = take_market(taker, ttw, md2)
    assert r2.json()["state"] == "APPROVED", f"cặp tin cậy phải tự duyệt, thực {r2.json()['state']}"

# ---------- M5 · Chủ đăng TỪ CHỐI → REJECTED, việc mở lại ----------
def test_reject_reopens_drop():
    poster = user(); make_owner_level(poster, 5); ptw = create_twin(poster); give_plump(poster, 100000)
    taker = user(); make_owner_level(taker, 5); ttw = create_twin(taker)
    md = post_market(poster, ptw, price=300).json()["market_drop_id"]
    deal = take_market(taker, ttw, md).json()["market_deal_id"]
    ap = requests.post(B+f"/v1/twin-market/deals/{deal}/approve", headers=hdr(poster), json={"ok":False})
    assert ap.json()["result"] == "REJECTED"
    # việc mở lại (kiểm qua DB cho ổn định, tránh rate-limit endpoint listing)
    c = db(); cur = c.cursor()
    cur.execute("SELECT status FROM twin_market_drops WHERE id=%s", (md,))
    status = cur.fetchone()[0]
    c.close()
    assert status == "open", f"việc bị từ chối phải mở lại, thực status={status}"

# ---------- M6 · Không tự thuê twin mình (self-dealing) ----------
def test_no_self_dealing():
    o = user(); make_owner_level(o, 5); give_plump(o, 100000)
    tw1 = create_twin(o); tw2 = create_twin(o)   # 2 twin cùng chủ
    md = post_market(o, tw1, price=300).json()["market_drop_id"]
    r = take_market(o, tw2, md)                    # chủ dùng twin 2 nhận việc twin 1
    assert r.status_code == 403 and "twin_market_self_dealing" in r.text

# ---------- M7 · Chủ đăng thiếu Plump → chặn nhận ----------
def test_poster_insufficient_plump_blocks():
    poster = user(); make_owner_level(poster, 5); ptw = create_twin(poster)  # KHÔNG give_plump nhiều
    taker = user(); make_owner_level(taker, 5); ttw = create_twin(taker)
    # rút cạn Plump chủ đăng
    c = db(); cur = c.cursor()
    cur.execute("INSERT INTO plump_points(owner,amount,reason) SELECT %s, -plump_balance(%s), 'drain'", (poster, poster))
    c.close()
    md = post_market(poster, ptw, price=300)
    # đăng vẫn được (chưa trả tiền), nhưng nhận thì chặn
    if md.status_code == 201:
        r = take_market(taker, ttw, md.json()["market_drop_id"])
        assert r.status_code == 409 and "poster_insufficient_plump" in r.text

# ---------- M8 · Taker twin treo phí KHÔNG nhận được việc chợ ----------
def test_suspended_taker_blocked():
    poster = user(); make_owner_level(poster, 5); ptw = create_twin(poster); give_plump(poster, 100000)
    taker = user(); make_owner_level(taker, 5); ttw = create_twin(taker)
    c = db(); cur = c.cursor()
    cur.execute("UPDATE twins SET suspended_unpaid=true WHERE id=%s", (ttw,))
    c.close()
    md = post_market(poster, ptw, price=300).json()["market_drop_id"]
    r = take_market(taker, ttw, md)
    assert r.status_code == 403 and "twin_suspended_unpaid" in r.text
