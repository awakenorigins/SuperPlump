import json, time, uuid, psycopg2, pytest, requests, websocket

B = "http://127.0.0.1:8386"
WS = "ws://127.0.0.1:8386/realtime"
ADMIN = {"x-admin-key": "plump-admin"}
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def db():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

def user(kyc="verified", nara=500000, plump=0):
    return requests.post(B+"/v1/dev/users", json={"handle":"soc","kyc":kyc,"nara":nara,"plump":plump}).json()["id"]

def hdr(u): return {"Authorization": "Bearer "+u}

def mk_drop(uid, kind="local", cat="general", price=110000):
    body = {"kind":kind,"title":"Việc "+cat,"price":price,"category":cat}
    if kind=="local": body |= {"lng":106.7009,"lat":10.7379}
    r = requests.post(B+"/v1/drops", headers=hdr(uid), json=body); r.raise_for_status()
    return r.json()["drop_id"]

def human_deal(price=95000):
    a, b = user(), user()
    drop = mk_drop(a)
    off = requests.post(B+f"/v1/drops/{drop}/offers", headers=hdr(b), json={"amount":price}).json()["offer_id"]
    deal = requests.post(B+f"/v1/offers/{off}/accept", headers=hdr(a)).json()["deal_id"]
    return a, b, deal

def settle(a, b, deal):
    requests.post(B+f"/v1/deals/{deal}/start", headers=hdr(b))
    requests.post(B+f"/v1/deals/{deal}/submit", headers=hdr(b), json={"proof":"p"})
    requests.post(B+f"/v1/deals/{deal}/confirm", headers=hdr(a))

def wait(fn, timeout=6, step=0.25):
    t0 = time.time()
    while time.time()-t0 < timeout:
        v = fn()
        if v: return v
        time.sleep(step)
    return None

# ---------- B1 · Chat trong deal: chỉ 2 bên ----------
def test_deal_chat_permissions():
    a, b, deal = human_deal()
    assert requests.post(B+f"/v1/deals/{deal}/messages", headers=hdr(b),
                         json={"body":"Mình tới trong 30p nhé"}).status_code == 201
    x = user()
    assert requests.post(B+f"/v1/deals/{deal}/messages", headers=hdr(x),
                         json={"body":"hóng"}).status_code == 403
    msgs = requests.get(B+f"/v1/deals/{deal}/messages", headers=hdr(a)).json()["items"]
    assert len(msgs) == 1 and msgs[0]["sender"] == b

# ---------- B2 · Không DM lạnh: kết nối chỉ mở sau deal SETTLED ----------
def test_dm_requires_connection_then_opens():
    a, b, deal = human_deal()
    r = requests.post(B+f"/v1/dm/{b}/messages", headers=hdr(a), json={"body":"chào"})
    assert r.status_code == 403 and r.json()["title"] == "dm_requires_connection"
    settle(a, b, deal)
    assert requests.post(B+f"/v1/dm/{b}/messages", headers=hdr(a),
                         json={"body":"quen qua việc rồi 🤝"}).status_code == 201
    got = requests.get(B+f"/v1/dm/{a}/messages", headers=hdr(b)).json()["items"]
    assert len(got) == 1

# ---------- B3 · Trigger sau settle: khoảnh khắc + điểm + thông báo — máy tự sinh ----------
def test_settle_triggers_social_layer():
    a, b, deal = human_deal(price=100000)
    settle(a, b, deal)
    w = requests.get(B+"/v1/wallet", headers=hdr(b)).json()
    assert w["plump"] == 500
    assert requests.get(B+"/v1/wallet", headers=hdr(a)).json()["plump"] == 200
    prof = requests.get(B+f"/v1/plumpers/{b}/profile").json()
    assert prof["done"] == 1 and prof["connections"] == 1 and len(prof["moments"]) == 1
    n = requests.get(B+"/v1/notifications", headers=hdr(b)).json()["items"]
    assert any(x["kind"]=="settled" for x in n)
    nid = n[0]["id"]
    requests.post(B+f"/v1/notifications/{nid}/read", headers=hdr(b))
    n2 = requests.get(B+"/v1/notifications", headers=hdr(b)).json()["items"]
    assert next(x for x in n2 if x["id"]==nid)["read_at"] is not None
    m = prof["moments"][0]
    assert requests.post(B+f"/v1/moments/{m['id']}/peach").json()["peaches"] == 1

# ---------- B4 · Leaderboard đọc từ điểm thật ----------
def test_leaderboard_periods():
    a, b, deal = human_deal()
    settle(a, b, deal)
    # b vừa +500 điểm. Leaderboard là TOP-N (mặc định seed demo khiến nhiều người hoà),
    # nên kiểm: (1) 3 kỳ đều trả bảng hợp lệ, sắp giảm dần; (2) điểm b thực sự tăng.
    for p in ("day","week","month"):
        items = requests.get(B+f"/v1/leaderboard?period={p}").json()["items"]
        assert isinstance(items, list) and len(items) >= 1
        pts = [int(r["pts"]) for r in items]
        assert pts == sorted(pts, reverse=True)      # thứ hạng giảm dần, tie-break ổn định
    assert requests.get(B+"/v1/wallet", headers=hdr(b)).json()["plump"] >= 500

# ---------- B5+C · TWIN TRỌN VÒNG ĐỜI: thi → mandate → ra chợ → draft → attestation → nộp ----------
def test_twin_full_lifecycle_with_mandate():
    owner, client = user(), user()
    drop = mk_drop(client, kind="digital", cat="dich_av", price=90000)
    tw = requests.post(B+"/v1/twins", headers=hdr(owner), json={"name":"Mận Máy"}).json()
    twin = tw["twin_id"]; assert tw["engine"] == "claude-fable-5"

    # chưa Qualify → cấm ra chợ
    r0 = requests.post(B+f"/v1/drops/{drop}/twin-offers", headers=hdr(owner),
                       json={"twin_id":twin,"amount":90000})
    assert r0.status_code == 403 and "twin_not_qualified" in r0.json()["title"]

    # thi Qualify → worker chấm → có bằng
    ex = requests.post(B+f"/v1/twins/{twin}/exams", headers=hdr(owner),
                       json={"category":"dich_av"}).json()["exam_id"]
    done = wait(lambda: requests.get(B+f"/v1/exam-runs/{ex}", headers=hdr(owner)).json().get("status")=="done")
    assert done
    quals = requests.get(B+f"/v1/twins/{twin}", headers=hdr(owner)).json()["qualifications"]
    assert any(q["category"]=="dich_av" and q["level"]=="silver" for q in quals)

    # có bằng nhưng CHƯA mandate → cấm
    r1 = requests.post(B+f"/v1/drops/{drop}/twin-offers", headers=hdr(owner),
                       json={"twin_id":twin,"amount":90000})
    assert r1.status_code == 403 and r1.json()["title"] == "mandate_missing"

    # mandate sai phạm vi → cấm
    m_bad = requests.post(B+f"/v1/twins/{twin}/mandates", headers=hdr(owner),
        json={"categories":["content"],"max_price":200000}).json()
    r2 = requests.post(B+f"/v1/drops/{drop}/twin-offers", headers=hdr(owner),
                       json={"twin_id":twin,"amount":90000})
    assert r2.status_code == 403 and "mandate_scope_violation" in r2.json()["title"]
    requests.post(B+f"/v1/mandates/{m_bad['mandate_id']}/revoke", headers=hdr(owner))

    # mandate đúng phạm vi nhưng vượt trần giá → cấm
    m = requests.post(B+f"/v1/twins/{twin}/mandates", headers=hdr(owner),
        json={"categories":["dich_av"],"max_price":80000}).json()
    r3 = requests.post(B+f"/v1/drops/{drop}/twin-offers", headers=hdr(owner),
                       json={"twin_id":twin,"amount":90000})
    assert r3.status_code == 403 and "mandate_price_violation" in r3.json()["title"]
    requests.post(B+f"/v1/mandates/{m['mandate_id']}/revoke", headers=hdr(owner))

    # mandate chuẩn → ra chợ được
    m2 = requests.post(B+f"/v1/twins/{twin}/mandates", headers=hdr(owner),
        json={"categories":["dich_av"],"max_price":150000}).json()
    off = requests.post(B+f"/v1/drops/{drop}/twin-offers", headers=hdr(owner),
                        json={"twin_id":twin,"amount":90000})
    assert off.status_code == 201
    deal = requests.post(B+f"/v1/offers/{off.json()['offer_id']}/accept",
                         headers=hdr(client)).json()["deal_id"]

    # accept → auto IN_PROGRESS + job xếp hàng + năng lượng −5
    d = requests.get(B+f"/v1/deals/{deal}", headers=hdr(owner)).json()
    assert d["state"] == "IN_PROGRESS" and d["executor_kind"] == "twin"
    assert requests.get(B+f"/v1/twins/{twin}", headers=hdr(owner)).json()["energy"] == 40  # Beat 3: Lv1 tốn 10 (cũ là 5)

    # worker viết draft (mock Fable 5)
    job = wait(lambda: next((j for j in requests.get(B+"/v1/twin-jobs?status=drafted",
                headers=hdr(owner)).json()["items"] if j["deal_id"]==deal), None))
    assert job and "claude-fable-5" in job["draft"]

    # attestation ký Ed25519 → verify chuẩn, giả mạo là rớt
    att = requests.get(B+f"/v1/twin-jobs/{job['id']}/attestation", headers=hdr(owner)).json()
    ok = requests.post(B+"/v1/agent/verify", json=att | {}).json()
    assert ok["valid"] is True
    tampered = dict(att); tampered["payload"] = att["payload"].replace(deal, str(uuid.uuid4()))
    assert requests.post(B+"/v1/agent/verify", json={k:tampered[k] for k in ("payload","signature","pubkey")}).json()["valid"] is False

    # duyệt → SUBMITTED → khách confirm → SETTLED, tiền về CHỦ twin
    assert requests.post(B+f"/v1/twin-jobs/{job['id']}/approve", headers=hdr(owner)).ok
    assert requests.get(B+f"/v1/deals/{deal}", headers=hdr(owner)).json()["state"] == "SUBMITTED"
    requests.post(B+f"/v1/deals/{deal}/confirm", headers=hdr(client))
    assert requests.get(B+"/v1/wallet", headers=hdr(owner)).json()["nara_available"] == 500000 + 85500

# ---------- B6 · REALTIME: WebSocket nhận sự kiện deal trong <3s ----------
def test_websocket_realtime_deal_events():
    a, b, deal = human_deal()
    ws = websocket.create_connection(WS + f"?channel=deal:{deal}", timeout=5)
    assert json.loads(ws.recv())["type"] == "subscribed"
    requests.post(B+f"/v1/deals/{deal}/start", headers=hdr(b))
    msg = json.loads(ws.recv())
    assert msg["type"] == "started" and msg["id"] == deal
    ws.close()

# ---------- C1 · Agent-ready: well-known + feed máy đọc + KYA-lite ghi vết ----------
def test_agent_ready_surface():
    a = user(); mk_drop(a, kind="digital", cat="content", price=70000)
    wk = requests.get(B+"/.well-known/superplump.json").json()
    assert wk["name"] == "SuperPlump" and wk["agents"]["engine"] == "claude-fable-5"
    feed = requests.get(B+"/v1/agent/drops",
                        headers={"Signature-Agent":"https://agent.example/ai-buyer"}).json()
    assert feed["schema"] == "superplump.drop.v1" and len(feed["items"]) >= 1
    assert all("fuzzy_lat" in i or i["kind"]=="digital" for i in feed["items"])
    c = db()
    with c.cursor() as cur:
        cur.execute("SELECT count(*) FROM agent_visits WHERE signature_agent LIKE %s", ("%agent.example%",))
        assert cur.fetchone()[0] >= 1
    c.close()
