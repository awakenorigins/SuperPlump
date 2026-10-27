import uuid, requests, psycopg2, time

B = "http://127.0.0.1:8386"
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def db():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

def user(plump=0, nara=5000000):
    return requests.post(B+"/v1/dev/users",
        json={"handle":"en","kyc":"verified","nara":nara,"plump":plump}).json()["id"]

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
    tid = requests.post(B+"/v1/twins", headers=hdr(owner), json={"name":"Twin"+uuid.uuid4().hex[:4]}).json()["twin_id"]
    c = db(); cur = c.cursor()
    cur.execute("INSERT INTO qualifications(twin_id,category,level,soul_version) VALUES (%s,%s,'bronze',1)", (tid, qualify))
    c.close()
    requests.post(B+f"/v1/twins/{tid}/mandates", headers=hdr(owner),
        json={"categories":[qualify],"max_price":10_000_000,"hours":720})
    return tid

def set_energy(twin_id, val):
    c = db(); cur = c.cursor()
    cur.execute("UPDATE twins SET energy=%s, energy_updated_at=now() WHERE id=%s", (val, twin_id))
    c.close()

def twin_info(owner, tid):
    return requests.get(B+f"/v1/twins/{tid}", headers=hdr(owner)).json()

def twin_take_job(client, owner, tid, price=80000, rate=None):
    """Twin nhận + làm 1 việc; nếu rate cho, khách chấm điểm."""
    d = requests.post(B+"/v1/drops", headers=hdr(client),
        json={"kind":"digital","title":"J "+uuid.uuid4().hex[:5],"price":price}).json()["drop_id"]
    resp = requests.post(B+f"/v1/drops/{d}/twin-offers", headers=hdr(owner),
        json={"amount":price,"twin_id":tid})
    if "offer_id" not in resp.json():
        return resp   # trả lỗi để test kiểm
    o = resp.json()["offer_id"]
    dl = requests.post(B+f"/v1/offers/{o}/accept", headers=hdr(client)).json()["deal_id"]
    c = db(); cur = c.cursor()
    cur.execute("UPDATE twin_jobs SET status='drafted',draft='d',drafted_at=now() WHERE deal_id=%s", (dl,))
    c.close()
    jid = next(j["id"] for j in requests.get(B+"/v1/twin-jobs", headers=hdr(owner)).json()["items"] if j["deal_id"]==dl)
    requests.post(B+f"/v1/twin-jobs/{jid}/approve", headers=hdr(owner))
    requests.post(B+f"/v1/deals/{dl}/confirm", headers=hdr(client))
    if rate:
        requests.post(B+f"/v1/deals/{dl}/reviews", headers=hdr(client), json={"rating":rate,"body":"r"})
        requests.post(B+f"/v1/deals/{dl}/reviews", headers=hdr(owner), json={"rating":5,"body":"o"})
    return dl

# ---------- E1 · Trần energy theo cấp CHỦ ----------
def test_cap_scales_with_owner_level():
    o1 = user(); tw1 = create_twin(o1)                 # chủ Lv1
    cap1 = twin_info(o1, tw1)["energy_cap"]
    o5 = user(); make_owner_level(o5, 5); tw5 = create_twin(o5)   # chủ Lv5
    cap5 = twin_info(o5, tw5)["energy_cap"]
    assert cap1 == 50, f"chủ Lv1 → cap 50, thực {cap1}"
    assert cap5 == 130, f"chủ Lv5 → cap 130 (50+20×4), thực {cap5}"
    assert cap5 > cap1

# ---------- E2 · Chi phí việc GIẢM theo cấp TWIN ----------
def test_cost_decreases_with_twin_level():
    o = user(); make_owner_level(o, 5); tw = create_twin(o)
    cost_lv1 = twin_info(o, tw)["job_cost"]             # twin Lv1 → 10
    # đẩy twin lên cấp cao bằng nhiều việc 5★ (nạp energy liên tục để không cạn)
    for _ in range(20):
        set_energy(tw, 200)
        twin_take_job(user(), o, tw, rate=5)
    info = twin_info(o, tw)
    assert cost_lv1 == 10
    if info["twin_level"] >= 3:
        assert info["job_cost"] < 10, f"twin Lv{info['twin_level']} phải tốn <10, thực {info['job_cost']}"

# ---------- E3 · Hết energy → KHÔNG nhận việc ----------
def test_no_energy_blocks_job():
    o = user(); make_owner_level(o, 3); tw = create_twin(o)
    set_energy(tw, 3)                                   # dưới cost (10)
    resp = twin_take_job(user(), o, tw)
    assert hasattr(resp, "status_code") and resp.status_code == 403
    assert "twin_no_energy" in resp.text

# ---------- E4 · Làm việc TRỪ energy đúng chi phí ----------
def test_job_deducts_energy():
    o = user(); make_owner_level(o, 3); tw = create_twin(o)
    set_energy(tw, 50)
    cost = twin_info(o, tw)["job_cost"]
    twin_take_job(user(), o, tw)                        # không chấm điểm (khỏi hoàn 5★)
    after = twin_info(o, tw)["energy"]
    assert after == 50 - cost, f"energy phải = {50-cost}, thực {after}"

# ---------- E5 · Việc khách chấm 5★ HOÀN energy ----------
def test_excellent_refills_energy():
    o = user(); make_owner_level(o, 3); tw = create_twin(o)
    set_energy(tw, 50)
    cost = twin_info(o, tw)["job_cost"]
    twin_take_job(user(), o, tw, rate=5)               # khách chấm 5★ → hoàn 15
    after = twin_info(o, tw)["energy"]
    # 50 - cost + 15 (không vượt cap)
    assert after == min(50 - cost + 15, twin_info(o, tw)["energy_cap"]), f"5★ phải hoàn energy, thực {after}"
    assert after > 50 - cost, "phải cao hơn sau khi hoàn 5★"

# ---------- E6 · Việc chấm 3★ KHÔNG hoàn energy ----------
def test_non_excellent_no_refill():
    o = user(); make_owner_level(o, 3); tw = create_twin(o)
    set_energy(tw, 50)
    cost = twin_info(o, tw)["job_cost"]
    twin_take_job(user(), o, tw, rate=3)               # 3★ → không hoàn
    after = twin_info(o, tw)["energy"]
    assert after == 50 - cost, f"3★ không hoàn, energy phải = {50-cost}, thực {after}"

# ---------- E7 · Mua energy bằng Nara (trừ ví, nạp tới cap) ----------
def test_buy_energy_with_nara():
    o = user(nara=5000000); make_owner_level(o, 3); tw = create_twin(o)
    cap = twin_info(o, tw)["energy_cap"]
    set_energy(tw, 10)
    nara0 = requests.get(B+"/v1/wallet", headers=hdr(o)).json()["nara_available"]
    r = requests.post(B+f"/v1/twins/{tw}/energy/refill", headers=hdr(o), json={"source":"buy"}).json()
    nara1 = requests.get(B+"/v1/wallet", headers=hdr(o)).json()["nara_available"]
    assert r["energy"] == cap, f"mua phải nạp đầy tới cap {cap}, thực {r['energy']}"
    assert nara1 < nara0, "phải trừ Nara"
    assert nara0 - nara1 == (cap-10)*2000, f"giá đúng (cap-10)×2000, thực {nara0-nara1}"

# ---------- E8 · Nhặt (gather) nạp energy không tốn Nara ----------
def test_gather_refill_free():
    o = user(); make_owner_level(o, 3); tw = create_twin(o)
    set_energy(tw, 10)
    nara0 = requests.get(B+"/v1/wallet", headers=hdr(o)).json()["nara_available"]
    r = requests.post(B+f"/v1/twins/{tw}/energy/refill", headers=hdr(o), json={"source":"gather"}).json()
    nara1 = requests.get(B+"/v1/wallet", headers=hdr(o)).json()["nara_available"]
    assert r["energy"] == 18, f"nhặt +8 → 18, thực {r['energy']}"
    assert nara1 == nara0, "nhặt không tốn Nara"

# ---------- E9 · Refill không vượt CAP ----------
def test_refill_caps_out():
    o = user(); make_owner_level(o, 3); tw = create_twin(o)
    cap = twin_info(o, tw)["energy_cap"]
    set_energy(tw, cap - 2)
    r = requests.post(B+f"/v1/twins/{tw}/energy/refill", headers=hdr(o), json={"source":"event"}).json()  # +25
    assert r["energy"] == cap, f"không vượt cap {cap}, thực {r['energy']}"

# ---------- E10 · Regen thụ động theo thời gian ----------
def test_passive_regen():
    o = user(); make_owner_level(o, 3); tw = create_twin(o)
    set_energy(tw, 20)
    # giả lập 5 giờ trôi qua
    c = db(); cur = c.cursor()
    cur.execute("UPDATE twins SET energy_updated_at = now() - interval '5 hours' WHERE id=%s", (tw,))
    c.close()
    e = twin_info(o, tw)["energy"]                      # GET gọi apply_energy_regen
    assert e == 20 + 5*2, f"5h × 2/h = +10 → 30, thực {e}"
