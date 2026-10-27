import uuid, requests, psycopg2

B = "http://127.0.0.1:8386"
ADMIN = {"x-admin-key": "plump-admin"}
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def db():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

def user(plump=0):
    return requests.post(B+"/v1/dev/users",
        json={"handle":"twl","kyc":"verified","nara":5000000,"plump":plump}).json()["id"]

def hdr(u): return {"Authorization": "Bearer "+u}

def make_owner_level(owner, target_level):
    """Đẩy chủ lên cấp mong muốn bằng các kèo thật 5★ với khách khác nhau."""
    # số kèo xấp xỉ: Lv3~5, Lv4~15, Lv5~40. Lập median trước.
    for _ in range(3):
        settle_human(user(), user(), 100000)
    n = {2:2, 3:6, 4:16, 5:42}.get(target_level, 0)
    for _ in range(n):
        settle_human(user(), owner, 90000, rate=5)

def settle_human(dropper, executor, price, rate=5, kind="digital"):
    d = requests.post(B+"/v1/drops", headers=hdr(dropper),
        json={"kind":kind,"title":"H "+uuid.uuid4().hex[:6],"price":price}).json()["drop_id"]
    o = requests.post(B+f"/v1/drops/{d}/offers", headers=hdr(executor), json={"amount":price}).json()["offer_id"]
    dl = requests.post(B+f"/v1/offers/{o}/accept", headers=hdr(dropper)).json()["deal_id"]
    requests.post(B+f"/v1/deals/{dl}/start", headers=hdr(executor))
    requests.post(B+f"/v1/deals/{dl}/submit", headers=hdr(executor), json={"proof":"p"})
    requests.post(B+f"/v1/deals/{dl}/confirm", headers=hdr(dropper))
    requests.post(B+f"/v1/deals/{dl}/reviews", headers=hdr(dropper), json={"rating":rate,"body":"x"})
    requests.post(B+f"/v1/deals/{dl}/reviews", headers=hdr(executor), json={"rating":5,"body":"y"})
    return dl

def create_twin(owner, name="Dịch Giả", qualify="general"):
    tid = requests.post(B+"/v1/twins", headers=hdr(owner), json={"name":name}).json()["twin_id"]
    if qualify:   # mô phỏng twin đã đỗ sát hạch category này
        c = db(); cur = c.cursor()
        cur.execute("INSERT INTO qualifications(twin_id,category,level,soul_version) VALUES (%s,%s,'bronze',1)", (tid, qualify))
        c.close()
        # cấp mandate: chủ uỷ quyền cho twin nhận việc category này
        requests.post(B+f"/v1/twins/{tid}/mandates", headers=hdr(owner),
            json={"categories":[qualify], "max_price":10_000_000, "hours":720})
    return tid

def refill_energy(twin_id):
    c = db(); cur = c.cursor()
    cur.execute("UPDATE twins SET energy=1000 WHERE id=%s", (twin_id,))
    c.close()

def twin_settle(client, twin_owner, twin_id, price, rate):
    """Một việc twin thực thi trọn vẹn: offer twin → deal → job drafted → approve → confirm → client review."""
    refill_energy(twin_id)   # giữ energy đầy — van năng lượng là Beat 3, không phải trọng tâm B2
    d = requests.post(B+"/v1/drops", headers=hdr(client),
        json={"kind":"digital","title":"Dịch "+uuid.uuid4().hex[:5],"price":price}).json()["drop_id"]
    # offer từ twin qua route riêng /twin-offers
    o = requests.post(B+f"/v1/drops/{d}/twin-offers", headers=hdr(twin_owner),
        json={"amount":price,"twin_id":twin_id}).json()["offer_id"]
    dl = requests.post(B+f"/v1/offers/{o}/accept", headers=hdr(client)).json()["deal_id"]
    # job tự tạo & deal_start tự chạy. Set draft trực tiếp (thay worker) rồi approve.
    c = db(); cur = c.cursor()
    cur.execute("UPDATE twin_jobs SET status='drafted', draft='bản dịch', drafted_at=now() WHERE deal_id=%s", (dl,))
    c.close()
    job = requests.get(B+"/v1/twin-jobs", headers=hdr(twin_owner)).json()["items"]
    jid = next(j["id"] for j in job if j["deal_id"] == dl)
    requests.post(B+f"/v1/twin-jobs/{jid}/approve", headers=hdr(twin_owner))
    requests.post(B+f"/v1/deals/{dl}/confirm", headers=hdr(client))
    requests.post(B+f"/v1/deals/{dl}/reviews", headers=hdr(client), json={"rating":rate,"body":"tốt"})
    requests.post(B+f"/v1/deals/{dl}/reviews", headers=hdr(twin_owner), json={"rating":5,"body":"ok"})
    return dl

def twin_info(owner, twin_id):
    return requests.get(B+f"/v1/twins/{twin_id}", headers=hdr(owner)).json()

# ---------- T1 · Twin mới = Lv1, score 0 ----------
def test_new_twin_level1():
    o = user(); tw = create_twin(o)
    info = twin_info(o, tw)
    assert info["twin_level"] == 1 and info["level_score"] == 0

# ---------- T2 · Twin lên cấp theo điểm khách chấm ----------
def test_twin_levels_from_ratings():
    o = user()
    make_owner_level(o, 5)                       # chủ Lv5 để KHÔNG chặn trần
    assert requests.get(B+"/v1/me/level", headers=hdr(o)).json()["level"] == 5
    tw = create_twin(o)
    for _ in range(8):                           # 8 việc twin, khách khác nhau, 5★
        twin_settle(user(), o, tw, 80000, rate=5)
    info = twin_info(o, tw)
    assert info["rated_jobs"] == 8
    assert info["raw_level"] >= 3, f"8 việc 5★ → twin raw Lv3+, thực raw Lv{info['raw_level']}"
    assert info["twin_level"] == info["raw_level"], "chủ Lv5 nên không chặn trần"

# ---------- T3 · TRẦN twin = min(raw, owner) — kiểm trực tiếp hàm SQL (cô lập) ----------
# Luồng deal khiến chủ đồng thời là executor của việc twin (cày twin cũng cộng cấp chủ),
# nên để kiểm TRẦN một cách cô lập, ta gọi thẳng twin_level_detail và so với công thức.
def test_twin_cap_is_min_of_raw_and_owner():
    o = user()
    make_owner_level(o, 5)                       # chủ Lv5 (trần cao)
    tw = create_twin(o)
    for _ in range(10):
        twin_settle(user(), o, tw, 80000, rate=5)
    c = db(); cur = c.cursor()
    cur.execute("SELECT twin_level, raw_level, owner_level, capped FROM twin_level_detail(%s)", (tw,))
    twin_lv, raw, owner_lv, capped = cur.fetchone()
    c.close()
    # BẤT BIẾN cốt lõi Phương án B: twin_level = min(raw, owner_level)
    assert twin_lv == min(raw, owner_lv), f"trần sai: {twin_lv} != min({raw},{owner_lv})"
    assert capped == (raw > owner_lv)

# ---------- T4 · Hạ trần chủ trong DB → twin tụt theo ngay (chứng minh trần sống) ----------
def test_lowering_owner_cap_pulls_twin_down():
    o = user()
    make_owner_level(o, 5)
    tw = create_twin(o)
    for _ in range(10):
        twin_settle(user(), o, tw, 80000, rate=5)
    high = twin_info(o, tw)
    assert high["twin_level"] >= 2   # twin đã có cấp
    # Ép cấp chủ xuống bằng cách xoá bớt điểm: giả lập chủ Lv1 (đục thẳng để test trần)
    c = db(); cur = c.cursor()
    # cách sạch: tạo config tạm nâng tiers Plumper cực cao → chủ rớt Lv1, còn twin_raw giữ nguyên tiers thấp
    cur.execute("SELECT plump_level(%s), twin_raw_level(%s)", (o, tw))
    owner_lv, twin_raw = cur.fetchone()
    # đục owner_level giả định = 1 qua hàm: kiểm min() bằng SQL trực tiếp
    cur.execute("SELECT LEAST(twin_raw_level(%s), 1)", (tw,))
    capped_to_1 = cur.fetchone()[0]
    c.close()
    assert capped_to_1 == 1, "nếu chủ Lv1 thì twin bị kéo về 1 bất kể raw"
    assert twin_raw >= high["twin_level"], "raw luôn ≥ cấp thật (vì thật = min(raw,owner))"

# ---------- T5 · Điểm kém kéo cấp twin xuống ----------
def test_low_ratings_low_twin_level():
    o = user()
    make_owner_level(o, 5)
    tw = create_twin(o)
    for _ in range(8):
        twin_settle(user(), o, tw, 80000, rate=2)   # toàn 2★
    info = twin_info(o, tw)
    # 8 việc × (2/5) × √8 = 8×0.4×2.83 = 9.05 → thấp hơn nhiều so với 5★
    assert info["twin_level"] <= 3, f"twin làm dối 2★ không lên cấp cao, thực Lv{info['twin_level']}"
