import uuid, requests, psycopg2

B = "http://127.0.0.1:8386"
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def db():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

def user(plump=0, nara=5000000):
    return requests.post(B+"/v1/dev/users",
        json={"handle":"sl","kyc":"verified","nara":nara,"plump":plump}).json()["id"]

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

def new_twin(owner):
    return requests.post(B+"/v1/twins", headers=hdr(owner), json={"name":"Tw"+uuid.uuid4().hex[:4]})

def slots(owner):
    return requests.get(B+"/v1/me/twin-slots", headers=hdr(owner)).json()

def nara(owner):
    return requests.get(B+"/v1/wallet", headers=hdr(owner)).json()["nara_available"]

# ---------- S1 · Slot mở theo cấp chủ ----------
def test_slot_limit_by_level():
    o1 = user()                      # Lv1
    assert slots(o1)["limit"] == 1
    o3 = user(); make_owner_level(o3, 3)
    assert slots(o3)["limit"] == 2, f"Lv3 → 2 slot, thực {slots(o3)['limit']}"
    o5 = user(); make_owner_level(o5, 5)
    assert slots(o5)["limit"] == 5, f"Lv5 → 5 slot, thực {slots(o5)['limit']}"

# ---------- S2 · Lv1 chỉ mở 1 twin, twin thứ 2 bị chặn ----------
def test_level1_capped_at_one():
    o = user()
    r1 = new_twin(o); assert r1.status_code == 201
    r2 = new_twin(o)
    assert r2.status_code == 403 and "twin_slot_limit_reached" in r2.text

# ---------- S3 · Phí mở twin TĂNG DẦN ----------
def test_open_fee_escalates():
    o = user(nara=5000000); make_owner_level(o, 5)   # 5 slot
    # twin 1,2 free; twin 3 = 50k; twin 4 = 150k; twin 5 = 400k
    assert slots(o)["next_open_fee"] == 0
    new_twin(o); new_twin(o)                          # mở 2 twin free
    assert slots(o)["next_open_fee"] == 50000, f"twin thứ 3 phí 50k, thực {slots(o)['next_open_fee']}"
    n0 = nara(o); new_twin(o)                          # mở twin 3 (−50k)
    assert n0 - nara(o) == 50000
    assert slots(o)["next_open_fee"] == 150000
    n1 = nara(o); new_twin(o)                          # twin 4 (−150k)
    assert n1 - nara(o) == 150000

# ---------- S4 · Không đủ Nara mở twin trả phí → chặn ----------
def test_insufficient_nara_blocks_open():
    # chủ cần Lv5 để có slot phí, nhưng cày kèo lại kiếm Nara → tách: nâng cấp xong rồi rút cạn Nara.
    o5 = user(nara=5000000); make_owner_level(o5, 5)
    new_twin(o5); new_twin(o5)                         # 2 free
    # rút cạn ví Nara để mô phỏng thiếu tiền
    c = db(); cur = c.cursor()
    cur.execute("UPDATE wallets SET balance=10000 WHERE owner=%s AND kind='user'", (o5,))
    c.close()
    r = new_twin(o5)                                   # twin 3 cần 50k > 10k
    assert r.status_code == 409 and "insufficient_nara" in r.text

# ---------- S5 · slot_index & maintenance_due gán đúng ----------
def test_slot_index_and_maintenance_set():
    o = user(nara=5000000); make_owner_level(o, 5)
    new_twin(o); new_twin(o)
    r3 = new_twin(o).json()                            # twin 3 có phí duy trì
    c = db(); cur = c.cursor()
    cur.execute("SELECT slot_index, maintenance_due_at FROM twins WHERE id=%s", (r3["twin_id"],))
    sidx, due = cur.fetchone(); c.close()
    assert sidx == 3
    assert due is not None, "twin thứ 3 phải có hạn phí duy trì"

# ---------- S6 · Đóng phí duy trì trừ Nara & gia hạn ----------
def test_pay_maintenance():
    o = user(nara=5000000); make_owner_level(o, 5)
    new_twin(o); new_twin(o)
    t3 = new_twin(o).json()["twin_id"]                 # phí duy trì 20k
    n0 = nara(o)
    r = requests.post(B+f"/v1/twins/{t3}/maintenance/pay", headers=hdr(o))
    assert r.status_code == 200
    assert n0 - nara(o) == 20000, f"phí duy trì twin 3 = 20k, thực {n0-nara(o)}"

# ---------- S7 · Twin quá hạn phí → treo → KHÔNG nhận việc ----------
def test_unpaid_twin_suspended_cannot_work():
    o = user(nara=5000000); make_owner_level(o, 5)
    new_twin(o); new_twin(o)
    t3 = new_twin(o).json()["twin_id"]
    # qualify + mandate cho twin 3
    c = db(); cur = c.cursor()
    cur.execute("INSERT INTO qualifications(twin_id,category,level,soul_version) VALUES (%s,'general','bronze',1)", (t3,))
    # ép quá hạn + chạy sweep
    cur.execute("UPDATE twins SET maintenance_due_at = now() - interval '1 day' WHERE id=%s", (t3,))
    cur.execute("SELECT sweep_unpaid_twins()")
    c.close()
    requests.post(B+f"/v1/twins/{t3}/mandates", headers=hdr(o),
        json={"categories":["general"],"max_price":10000000,"hours":720})
    client = user()
    d = requests.post(B+"/v1/drops", headers=hdr(client),
        json={"kind":"digital","title":"Viec test","price":80000}).json()["drop_id"]
    r = requests.post(B+f"/v1/drops/{d}/twin-offers", headers=hdr(o), json={"amount":80000,"twin_id":t3})
    assert r.status_code == 403 and "twin_suspended_unpaid" in r.text
    # đóng phí → hết treo → nhận việc lại được
    requests.post(B+f"/v1/twins/{t3}/maintenance/pay", headers=hdr(o))
    d2 = requests.post(B+"/v1/drops", headers=hdr(client),
        json={"kind":"digital","title":"Viec test 2","price":80000}).json()["drop_id"]
    r2 = requests.post(B+f"/v1/drops/{d2}/twin-offers", headers=hdr(o), json={"amount":80000,"twin_id":t3})
    assert "offer_id" in r2.json(), f"đóng phí xong phải nhận việc được, thực {r2.text[:200]}"

# ---------- S8 · Slot nới ra khi chủ lên cấp ----------
def test_slot_expands_with_level():
    o = user(nara=5000000); make_owner_level(o, 3)     # 2 slot
    new_twin(o); new_twin(o)
    r = new_twin(o)                                     # twin 3 bị chặn ở Lv3
    assert r.status_code == 403
    # chủ lên Lv4 → 3 slot
    for _ in range(12): settle_human(user(), o, 90000, rate=5)
    assert slots(o)["limit"] >= 3
    r2 = new_twin(o)
    assert r2.status_code == 201, "lên cấp → mở thêm slot được"
