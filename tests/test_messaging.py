import json, time, uuid, psycopg2, pytest, requests, websocket

B = "http://127.0.0.1:8386"
WS = "ws://127.0.0.1:8386/realtime"
ADMIN = {"x-admin-key": "plump-admin"}
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def db():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

def jh(t): return {"Authorization": "Bearer " + t}

def real_account(verified=True):
    """Tài khoản THẬT qua regnick → login → onboard username+password → (eKYC duyệt)."""
    tok = requests.post(B+"/v1/auth/register").json()["token"]
    j = requests.post(B+"/v1/auth/login", json={"token": tok}).json()
    un = "u" + uuid.uuid4().hex[:10]
    requests.post(B+"/v1/auth/username", headers=jh(j["jwt"]), json={"username": un})
    requests.post(B+"/v1/auth/password", headers=jh(j["jwt"]), json={"password": "matkhau-8ky"})
    if verified:   # qua "cánh cửa tên thật" để được thả/nhận việc
        kid = requests.post(B+"/v1/kyc/ekyc", headers=jh(j["jwt"]),
                            json={"provider":"vneid","ref":"M-"+uuid.uuid4().hex[:6]}).json()["kyc_id"]
        requests.post(B+f"/v1/admin/kyc/{kid}/approve", headers=ADMIN)
    return {"jwt": j["jwt"], "id": j["plumper_id"], "un": un, "token": tok}

def connect_two(a, b):
    """Cho 2 người 'quen qua việc' bằng 1 deal SETTLED — điều kiện mở DM."""
    d = requests.post(B+"/v1/drops", headers=jh(a["jwt"]),
        json={"kind":"digital","title":"Kết nối "+uuid.uuid4().hex[:5],"price":100000}).json()["drop_id"]
    o = requests.post(B+f"/v1/drops/{d}/offers", headers=jh(b["jwt"]), json={"amount":90000}).json()["offer_id"]
    dl = requests.post(B+f"/v1/offers/{o}/accept", headers=jh(a["jwt"])).json()["deal_id"]
    requests.post(B+f"/v1/deals/{dl}/start", headers=jh(b["jwt"]))
    requests.post(B+f"/v1/deals/{dl}/submit", headers=jh(b["jwt"]), json={"proof":"p"})
    requests.post(B+f"/v1/deals/{dl}/confirm", headers=jh(a["jwt"]))
    return dl

# ---------- M1 · Tài khoản THẬT + ví demo seed 100k mỗi loại ----------
def test_real_accounts_and_wallet_seed():
    a = real_account()
    w = requests.get(B+"/v1/wallet", headers=jh(a["jwt"])).json()
    assert w["nara_available"] == 100000 and w["plump"] == 100000
    # login lại bằng username+password (tài khoản thật, bền)
    re_login = requests.post(B+"/v1/auth/login", json={"username": a["un"], "password": "matkhau-8ky"})
    assert re_login.status_code == 200 and re_login.json()["plumper_id"] == a["id"]

# ---------- M2 · Không DM lạnh: chưa quen → chặn; quen rồi → mở hội thoại ----------
def test_dm_requires_connection():
    a, b = real_account(), real_account()
    r = requests.post(B+"/v1/conversations/dm", headers=jh(a["jwt"]), json={"peer": b["id"]})
    assert r.status_code == 403 and r.json()["title"] == "dm_requires_connection"
    connect_two(a, b)
    r2 = requests.post(B+"/v1/conversations/dm", headers=jh(a["jwt"]), json={"peer": b["id"]})
    assert r2.status_code == 201
    # idempotent: gọi lại trả đúng cùng hội thoại
    r3 = requests.post(B+"/v1/conversations/dm", headers=jh(b["jwt"]), json={"peer": a["id"]})
    assert r3.json()["conversation_id"] == r2.json()["conversation_id"]

# ---------- M3 · Nhắn HAI CHIỀU thật giữa 2 Plumper ----------
def test_two_way_messaging():
    a, b = real_account(), real_account()
    connect_two(a, b)
    conv = requests.post(B+"/v1/conversations/dm", headers=jh(a["jwt"]), json={"peer": b["id"]}).json()["conversation_id"]
    requests.post(B+f"/v1/conversations/{conv}/messages", headers=jh(a["jwt"]), json={"body":"Chào bạn, mình là A 👋"})
    requests.post(B+f"/v1/conversations/{conv}/messages", headers=jh(b["jwt"]), json={"body":"Chào A, B đây!"})
    requests.post(B+f"/v1/conversations/{conv}/messages", headers=jh(a["jwt"]), json={"body":"Deal vui nhé 🤝"})
    # B đọc thấy đủ 3 tin, đúng thứ tự, đúng người gửi
    msgs = requests.get(B+f"/v1/conversations/{conv}/messages", headers=jh(b["jwt"])).json()["items"]
    assert [m["body"] for m in msgs] == ["Chào bạn, mình là A 👋","Chào A, B đây!","Deal vui nhé 🤝"]
    assert msgs[0]["sender"] == a["id"] and msgs[1]["sender"] == b["id"]

# ---------- M4 · Inbox + đếm chưa đọc + con trỏ đã đọc ----------
def test_inbox_unread_and_read_cursor():
    a, b = real_account(), real_account()
    connect_two(a, b)
    conv = requests.post(B+"/v1/conversations/dm", headers=jh(a["jwt"]), json={"peer": b["id"]}).json()["conversation_id"]
    for i in range(3):
        requests.post(B+f"/v1/conversations/{conv}/messages", headers=jh(a["jwt"]), json={"body":f"tin {i}"})
    # B có 3 chưa đọc
    inbox = requests.get(B+"/v1/inbox", headers=jh(b["jwt"])).json()
    assert inbox["total_unread"] == 3
    row = next(c for c in inbox["conversations"] if c["conversation_id"] == conv)
    assert row["unread"] == 3 and row["last_body"] == "tin 2" and row["peer_id"] == a["id"]
    # B đọc tới tin cuối
    last_id = requests.get(B+f"/v1/conversations/{conv}/messages", headers=jh(b["jwt"])).json()["items"][-1]["id"]
    requests.post(B+f"/v1/conversations/{conv}/read", headers=jh(b["jwt"]), json={"upto": last_id})
    assert requests.get(B+"/v1/inbox/unread-count", headers=jh(b["jwt"])).json()["total_unread"] == 0
    # người GỬI không tự thấy chưa đọc
    assert requests.get(B+"/v1/inbox/unread-count", headers=jh(a["jwt"])).json()["total_unread"] == 0

# ---------- M5 · Reply + Edit + Revoke ----------
def test_reply_edit_revoke():
    a, b = real_account(), real_account()
    connect_two(a, b)
    conv = requests.post(B+"/v1/conversations/dm", headers=jh(a["jwt"]), json={"peer": b["id"]}).json()["conversation_id"]
    m1 = requests.post(B+f"/v1/conversations/{conv}/messages", headers=jh(a["jwt"]), json={"body":"Câu hỏi gốc?"}).json()["message_id"]
    # B reply vào m1
    m2 = requests.post(B+f"/v1/conversations/{conv}/messages", headers=jh(b["jwt"]),
                       json={"body":"Trả lời nè","reply_to":m1}).json()["message_id"]
    msgs = requests.get(B+f"/v1/conversations/{conv}/messages", headers=jh(a["jwt"])).json()["items"]
    reply = next(m for m in msgs if m["id"] == m2)
    assert reply["reply_to"] == m1 and reply["reply_preview"] == "Câu hỏi gốc?"
    # A sửa tin của A
    assert requests.patch(B+f"/v1/messages/{m1}", headers=jh(a["jwt"]), json={"body":"Câu hỏi đã sửa"}).ok
    # B KHÔNG sửa được tin của A
    assert requests.patch(B+f"/v1/messages/{m1}", headers=jh(b["jwt"]), json={"body":"phá"}).status_code == 403
    # A thu hồi
    assert requests.post(B+f"/v1/messages/{m1}/revoke", headers=jh(a["jwt"])).ok
    after = requests.get(B+f"/v1/conversations/{conv}/messages", headers=jh(b["jwt"])).json()["items"]
    gone = next(m for m in after if m["id"] == m1)
    assert gone["revoked_at"] is not None and gone["body"] is None

# ---------- M6 · Typing + attachment ----------
def test_typing_and_attachment():
    a, b = real_account(), real_account()
    connect_two(a, b)
    conv = requests.post(B+"/v1/conversations/dm", headers=jh(a["jwt"]), json={"peer": b["id"]}).json()["conversation_id"]
    assert requests.post(B+f"/v1/conversations/{conv}/typing", headers=jh(a["jwt"])).ok
    seen = requests.get(B+f"/v1/conversations/{conv}/messages", headers=jh(b["jwt"])).json()
    assert a["id"] in seen["typing"]
    # gửi ảnh
    requests.post(B+f"/v1/conversations/{conv}/messages", headers=jh(a["jwt"]),
                  json={"attachment_url":"https://cdn.example.vn/pic.jpg","attachment_kind":"image"})
    msgs = requests.get(B+f"/v1/conversations/{conv}/messages", headers=jh(b["jwt"])).json()["items"]
    assert msgs[-1]["attachment_kind"] == "image" and msgs[-1]["attachment_url"].endswith("pic.jpg")

# ---------- M7 · Người ngoài hội thoại KHÔNG đọc/gửi được ----------
def test_non_member_blocked():
    a, b, x = real_account(), real_account(), real_account()
    connect_two(a, b)
    conv = requests.post(B+"/v1/conversations/dm", headers=jh(a["jwt"]), json={"peer": b["id"]}).json()["conversation_id"]
    assert requests.get(B+f"/v1/conversations/{conv}/messages", headers=jh(x["jwt"])).status_code == 403
    assert requests.post(B+f"/v1/conversations/{conv}/messages", headers=jh(x["jwt"]),
                         json={"body":"chen ngang"}).status_code == 403

# ---------- M8 · REALTIME: tin nhắn bay tới người nhận qua WebSocket <3s ----------
def test_realtime_message_delivery():
    a, b = real_account(), real_account()
    connect_two(a, b)
    conv = requests.post(B+"/v1/conversations/dm", headers=jh(a["jwt"]), json={"peer": b["id"]}).json()["conversation_id"]
    ws = websocket.create_connection(WS + f"?channel=conversation:{conv}", timeout=5)
    assert json.loads(ws.recv())["type"] == "subscribed"
    requests.post(B+f"/v1/conversations/{conv}/messages", headers=jh(a["jwt"]), json={"body":"realtime ping"})
    msg = json.loads(ws.recv())
    assert msg["type"] == "message" and msg["sender"] == a["id"] and "message_id" in msg
    ws.close()

# ---------- M9 · Badge inbox realtime tới kênh user của người nhận ----------
def test_realtime_inbox_badge():
    a, b = real_account(), real_account()
    connect_two(a, b)
    conv = requests.post(B+"/v1/conversations/dm", headers=jh(a["jwt"]), json={"peer": b["id"]}).json()["conversation_id"]
    ws = websocket.create_connection(WS + f"?channel=user:{b['id']}", timeout=5)
    assert json.loads(ws.recv())["type"] == "subscribed"
    requests.post(B+f"/v1/conversations/{conv}/messages", headers=jh(a["jwt"]), json={"body":"badge test"})
    msg = json.loads(ws.recv())
    assert msg["type"] == "message" and msg["to"] == b["id"]
    ws.close()

# ---------- M10 · Chat trong DEAL: tự tạo hội thoại, 2 bên nhắn ----------
def test_deal_conversation():
    a, b = real_account(), real_account()
    dl = connect_two(a, b)
    conv = requests.post(B+f"/v1/deals/{dl}/conversation", headers=jh(a["jwt"])).json()["conversation_id"]
    requests.post(B+f"/v1/conversations/{conv}/messages", headers=jh(a["jwt"]), json={"body":"Về deal này..."})
    msgs = requests.get(B+f"/v1/conversations/{conv}/messages", headers=jh(b["jwt"])).json()["items"]
    assert msgs[0]["body"] == "Về deal này..."

# ========== FARM PLUMP MỞ RỘNG ==========
# ---------- F1 · Khách thưởng Plump sau deal ----------
def test_tip_after_deal():
    a, b = real_account(), real_account()
    dl = connect_two(a, b)   # b là executor, deal đã SETTLED
    p0 = requests.get(B+"/v1/wallet", headers=jh(b["jwt"])).json()["plump"]
    assert requests.post(B+f"/v1/deals/{dl}/tip", headers=jh(a["jwt"]), json={"amount":1000}).status_code == 201
    assert requests.get(B+"/v1/wallet", headers=jh(b["jwt"])).json()["plump"] == p0 + 1000
    # ngoài khoảng bị chặn (zod chặn ở cửa: >5000)
    assert requests.post(B+f"/v1/deals/{dl}/tip", headers=jh(a["jwt"]), json={"amount":5001}).status_code == 400

# ---------- F2 · Nhiệm vụ công ích có cap ngày ----------
def test_civic_tasks_capped():
    a = real_account()
    got = [requests.post(B+"/v1/civic/verify_report/claim", headers=jh(a["jwt"])).status_code for _ in range(4)]
    assert got[:3] == [201,201,201] and got[3] == 429   # cap 3/ngày

# ---------- F3 · Giúp Plumper mới thưởng một lần ----------
def test_help_newbie_once():
    helper, newbie = real_account(), real_account()
    r1 = requests.post(B+f"/v1/help-newbie/{newbie['id']}", headers=jh(helper["jwt"]))
    assert r1.status_code == 201 and r1.json()["earned"] == 300
    assert requests.post(B+f"/v1/help-newbie/{newbie['id']}", headers=jh(helper["jwt"])).status_code == 409

# ---------- F4 · Thưởng bảng xếp hạng theo kỳ, không cấp trùng ----------
def test_leaderboard_rewards():
    a, b = real_account(), real_account()
    connect_two(a, b)   # tạo điểm để có mặt trên bảng
    # grant lần đầu trong kỳ 'month' có thể đã chạy ở test khác trên cùng DB → chấp nhận >=0,
    # điều CỐT LÕI: gọi 2 lần liên tiếp, tổng số cấp thêm ở lần 2 = 0 (idempotent theo kỳ)
    requests.post(B+"/v1/admin/jobs/grant-leaderboard/month", headers=ADMIN).json()
    r2 = requests.post(B+"/v1/admin/jobs/grant-leaderboard/month", headers=ADMIN).json()
    assert r2["granted"] == 0    # cùng kỳ, không cấp lại — bằng chứng chống cấp trùng
    # và bảng xếp hạng đọc được, có người
    board = requests.get(B+"/v1/leaderboard?period=month", headers=jh(a["jwt"])).json()
    assert len(board["items"]) >= 1
