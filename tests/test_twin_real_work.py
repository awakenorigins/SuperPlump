import uuid, requests, psycopg2

B = "http://127.0.0.1:8386"
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def db():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

def user(plump=0, nara=5000000):
    return requests.post(B+"/v1/dev/users",
        json={"handle":"rw","kyc":"verified","nara":nara,"plump":plump}).json()["id"]

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

def mk_drop(client, price=80000, origin=None, cat="general"):
    body = {"kind":"digital","title":"Viec "+uuid.uuid4().hex[:5],"price":price,"category":cat}
    if origin: body["origin"] = origin
    return requests.post(B+"/v1/drops", headers=hdr(client), json=body).json()["drop_id"]

def twin_offer(owner, twin_id, drop_id, amount=80000):
    return requests.post(B+f"/v1/drops/{drop_id}/twin-offers", headers=hdr(owner),
        json={"amount":amount,"twin_id":twin_id})

# ---------- R1 · Twin KHÔNG nhận việc công ích (civic) ----------
def test_twin_rejects_civic_origin():
    o = user(); make_owner_level(o, 3); tw = create_twin(o)
    client = user()
    drop = mk_drop(client, origin="civic")
    r = twin_offer(o, tw, drop)
    assert r.status_code == 403 and "twin_real_work_only" in r.text and "civic" in r.text

# ---------- R2 · Twin KHÔNG nhận việc tự sinh (self_generated) ----------
def test_twin_rejects_self_generated():
    o = user(); make_owner_level(o, 3); tw = create_twin(o)
    client = user()
    drop = mk_drop(client, origin="self_generated")
    r = twin_offer(o, tw, drop)
    assert r.status_code == 403 and "twin_real_work_only" in r.text

# ---------- R3 · Twin KHÔNG nhận việc giá dưới ngưỡng thật ----------
def test_twin_rejects_below_real_min():
    o = user(); make_owner_level(o, 3); tw = create_twin(o)
    client = user()
    drop = mk_drop(client, price=5000)                 # < min_real_price 10k
    r = twin_offer(o, tw, drop, amount=5000)
    assert r.status_code == 403 and "price_below_real_min" in r.text

# ---------- R4 · Twin KHÔNG nhận việc do CHÍNH CHỦ đăng (self-dealing) ----------
def test_twin_rejects_self_dealing():
    o = user(); make_owner_level(o, 3); tw = create_twin(o)
    # chủ tự đăng drop rồi cho twin mình nhận
    drop = mk_drop(o)                                   # owner == twin owner
    r = twin_offer(o, tw, drop)
    # chặn bởi cannot_offer_own_drop HOẶC twin_real_work_only:self_dealing
    assert r.status_code in (403, 409)
    assert ("cannot_offer_own_drop" in r.text) or ("self_dealing" in r.text)

# ---------- R5 · Twin NHẬN việc thật (client, giá đạt ngưỡng) ----------
def test_twin_accepts_real_client_work():
    o = user(); make_owner_level(o, 3); tw = create_twin(o)
    client = user()
    drop = mk_drop(client, price=80000)                # origin mặc định 'client'
    r = twin_offer(o, tw, drop)
    assert "offer_id" in r.json(), f"việc thật phải nhận được, thực {r.text[:200]}"

# ---------- R6 · Việc civic KHÔNG tính điểm cấp twin ----------
def test_civic_work_no_twin_score():
    o = user(); make_owner_level(o, 5); tw = create_twin(o)
    # Dựng 5 "deal" giả origin=civic đã SETTLED gán cho twin (đục thẳng DB, mô phỏng nếu lọt lưới)
    c = db(); cur = c.cursor()
    for _ in range(5):
        client = user()
        cur.execute("""INSERT INTO drops(owner,kind,title,description,price,status,category,origin)
                       VALUES (%s,'digital','civic job','',80000,'closed','general','civic') RETURNING id""", (client,))
        drop_id = cur.fetchone()[0]
        cur.execute("""INSERT INTO deals(drop_id,dropper,executor,agreed,hold_amount,executor_kind,twin_id,state,settled_at)
                       VALUES (%s,%s,%s,80000,84000,'twin',%s,'SETTLED',now()) RETURNING id""",
                    (drop_id, client, o, tw))
        deal_id = cur.fetchone()[0]
        cur.execute("INSERT INTO twin_jobs(twin_id,deal_id,brief,status) VALUES (%s,%s,'b','approved')", (tw, deal_id))
        cur.execute("INSERT INTO reviews(deal_id,author,target,rating,body) VALUES (%s,%s,%s,5,'r')", (deal_id, client, o))
    cur.execute("SELECT twin_score(%s)", (tw,))
    score = cur.fetchone()[0]
    c.close()
    assert score == 0, f"việc origin=civic KHÔNG được tính điểm twin, thực score={score}"

# ---------- R7 · Việc THẬT (client) CÓ tính điểm cấp twin ----------
def test_real_work_counts_twin_score():
    o = user(); make_owner_level(o, 5); tw = create_twin(o)
    c = db(); cur = c.cursor()
    for _ in range(5):
        client = user()
        cur.execute("""INSERT INTO drops(owner,kind,title,description,price,status,category,origin)
                       VALUES (%s,'digital','real job','',80000,'closed','general','client') RETURNING id""", (client,))
        drop_id = cur.fetchone()[0]
        cur.execute("""INSERT INTO deals(drop_id,dropper,executor,agreed,hold_amount,executor_kind,twin_id,state,settled_at)
                       VALUES (%s,%s,%s,80000,84000,'twin',%s,'SETTLED',now()) RETURNING id""",
                    (drop_id, client, o, tw))
        deal_id = cur.fetchone()[0]
        cur.execute("INSERT INTO twin_jobs(twin_id,deal_id,brief,status) VALUES (%s,%s,'b','approved')", (tw, deal_id))
        cur.execute("INSERT INTO reviews(deal_id,author,target,rating,body) VALUES (%s,%s,%s,5,'r')", (deal_id, client, o))
    cur.execute("SELECT twin_score(%s)", (tw,))
    score = cur.fetchone()[0]
    c.close()
    assert score > 0, f"việc thật phải tính điểm, thực score={score}"

# ---------- R8 · Việc thật nhưng KHÔNG escrow (hold=0) không tính điểm ----------
def test_no_escrow_no_score():
    o = user(); make_owner_level(o, 5); tw = create_twin(o)
    c = db(); cur = c.cursor()
    client = user()
    cur.execute("""INSERT INTO drops(owner,kind,title,description,price,status,category,origin)
                   VALUES (%s,'digital','no escrow','',80000,'closed','general','client') RETURNING id""", (client,))
    drop_id = cur.fetchone()[0]
    cur.execute("""INSERT INTO deals(drop_id,dropper,executor,agreed,hold_amount,executor_kind,twin_id,state,settled_at)
                   VALUES (%s,%s,%s,80000,0,'twin',%s,'SETTLED',now()) RETURNING id""",
                (drop_id, client, o, tw))       # hold_amount = 0 → không có escrow thật
    deal_id = cur.fetchone()[0]
    cur.execute("INSERT INTO twin_jobs(twin_id,deal_id,brief,status) VALUES (%s,%s,'b','approved')", (tw, deal_id))
    cur.execute("INSERT INTO reviews(deal_id,author,target,rating,body) VALUES (%s,%s,%s,5,'r')", (deal_id, client, o))
    cur.execute("SELECT twin_score(%s)", (tw,))
    score = cur.fetchone()[0]
    c.close()
    assert score == 0, f"việc không escrow KHÔNG tính điểm, thực {score}"
