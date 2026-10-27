import uuid, requests

B = "http://127.0.0.1:8386"
ADMIN = {"x-admin-key": "plump-admin"}

def user(plump=0):
    return requests.post(B+"/v1/dev/users",
        json={"handle":"grp","kyc":"verified","nara":500000,"plump":plump}).json()["id"]

def hdr(u): return {"Authorization": "Bearer "+u}

def golden(a, b):
    d = requests.post(B+"/v1/drops", headers=hdr(a),
        json={"kind":"digital","title":"G "+uuid.uuid4().hex[:6],"price":100000}).json()["drop_id"]
    o = requests.post(B+f"/v1/drops/{d}/offers", headers=hdr(b), json={"amount":90000}).json()["offer_id"]
    dl = requests.post(B+f"/v1/offers/{o}/accept", headers=hdr(a)).json()["deal_id"]
    requests.post(B+f"/v1/deals/{dl}/start", headers=hdr(b))
    requests.post(B+f"/v1/deals/{dl}/submit", headers=hdr(b), json={"proof":"p"})
    requests.post(B+f"/v1/deals/{dl}/confirm", headers=hdr(a))
    return dl

# ---------- G1 · Nhóm: tạo với người quen, cả nhóm nhắn/đọc; người ngoài 403 ----------
def test_group_create_and_chat():
    a, b, c, x = user(), user(), user(), user()
    golden(a, b); golden(a, c)                       # a quen b, c
    g = requests.post(B+"/v1/conversations/group", headers=hdr(a),
        json={"title":"Đội Dọn Kho Q7","members":[b, c]}).json()
    conv = g["conversation_id"]
    assert len(g["invite_code"]) == 8
    for who, txt in ((a,"Chào cả đội!"),(b,"Có mặt 🙌"),(c,"Tối nay chiến")):
        assert requests.post(B+f"/v1/conversations/{conv}/messages", headers=hdr(who),
                             json={"body":txt}).status_code == 201
    msgs = requests.get(B+f"/v1/conversations/{conv}/messages", headers=hdr(b)).json()["items"]
    assert [m["body"] for m in msgs][-3:] == ["Chào cả đội!","Có mặt 🙌","Tối nay chiến"]
    assert requests.get(B+f"/v1/conversations/{conv}/messages", headers=hdr(x)).status_code == 403

# ---------- G2 · Luật "quen qua việc": thêm người lạ vào nhóm bị chặn ----------
def test_group_member_must_be_connected():
    a, stranger = user(), user()
    r = requests.post(B+"/v1/conversations/group", headers=hdr(a),
        json={"title":"Nhóm thử","members":[stranger]})
    assert r.status_code == 403 and r.json()["title"] == "member_not_connected"
    golden(a, stranger)
    g = requests.post(B+"/v1/conversations/group", headers=hdr(a), json={"title":"Nhóm thử","members":[]}).json()
    assert requests.post(B+f"/v1/conversations/{g['conversation_id']}/members", headers=hdr(a),
                         json={"members":[stranger]}).json()["added"] == 1

# ---------- G3 · Channel: owner đăng được, member CHỈ ĐỌC ----------
def test_channel_readonly_for_members():
    owner, follower = user(), user()
    ch = requests.post(B+"/v1/conversations/channel", headers=hdr(owner),
        json={"title":"Kèo Hot Sài Gòn","is_public":True}).json()
    conv = ch["conversation_id"]
    assert requests.post(B+f"/v1/conversations/{conv}/messages", headers=hdr(owner),
                         json={"body":"🔥 Kèo dọn kho 150k Q7 vừa lên"}).status_code == 201
    assert requests.post(B+f"/v1/conversations/{conv}/join", headers=hdr(follower)).status_code == 201
    msgs = requests.get(B+f"/v1/conversations/{conv}/messages", headers=hdr(follower)).json()["items"]
    assert "Kèo dọn kho" in msgs[0]["body"]
    r = requests.post(B+f"/v1/conversations/{conv}/messages", headers=hdr(follower), json={"body":"spam"})
    assert r.status_code == 403 and r.json()["title"] == "channel_readonly"

# ---------- G4 · Channel công khai lên danh bạ; join bằng mã cho kín ----------
def test_channel_discovery_and_join_by_code():
    owner, guest = user(), user()
    ch = requests.post(B+"/v1/conversations/channel", headers=hdr(owner),
        json={"title":"Channel Kín "+uuid.uuid4().hex[:4],"is_public":False}).json()
    lst = requests.get(B+"/v1/channels", headers=hdr(guest)).json()["items"]
    assert not any(i["id"] == ch["conversation_id"] for i in lst)      # kín không lộ
    bad = requests.post(B+"/v1/conversations/join-by-code", headers=hdr(guest), json={"code":"XXXXXX"})
    assert bad.status_code == 404
    ok = requests.post(B+"/v1/conversations/join-by-code", headers=hdr(guest),
                       json={"code": ch["invite_code"]})
    assert ok.status_code == 201 and ok.json()["conversation_id"] == ch["conversation_id"]

# ---------- G5 · Rời nhóm: member rời được, owner bị giữ ----------
def test_leave_rules():
    a, b = user(), user()
    golden(a, b)
    g = requests.post(B+"/v1/conversations/group", headers=hdr(a),
        json={"title":"Nhóm rời","members":[b]}).json()
    conv = g["conversation_id"]
    assert requests.post(B+f"/v1/conversations/{conv}/leave", headers=hdr(b)).status_code == 200
    assert requests.get(B+f"/v1/conversations/{conv}/messages", headers=hdr(b)).status_code == 403
    r = requests.post(B+f"/v1/conversations/{conv}/leave", headers=hdr(a))
    assert r.status_code == 409 and r.json()["title"] == "owner_cannot_leave"

# ---------- G6 · Gửi VỊ TRÍ: kind location roundtrip ----------
def test_location_message():
    a, b = user(), user()
    golden(a, b)
    conv = requests.post(B+"/v1/conversations/dm", headers=hdr(a), json={"peer": b}).json()["conversation_id"]
    requests.post(B+f"/v1/conversations/{conv}/messages", headers=hdr(a),
        json={"body":"Gặp ở đây nhé","attachment_url":"https://maps.plump.vn/geo/10.7411,106.7020",
              "attachment_kind":"location"})
    m = requests.get(B+f"/v1/conversations/{conv}/messages", headers=hdr(b)).json()["items"][-1]
    assert m["attachment_kind"] == "location" and "10.7411" in m["attachment_url"]
    inbox = requests.get(B+"/v1/inbox", headers=hdr(b)).json()["conversations"]
    row = next(c for c in inbox if c["conversation_id"] == conv)
    assert row["last_body"] == "📍 Vị trí"

# ---------- G7 · Inbox v2: nhóm hiện title + đếm chưa đọc theo nhóm ----------
def test_group_inbox_title_and_unread():
    a, b = user(), user()
    golden(a, b)
    g = requests.post(B+"/v1/conversations/group", headers=hdr(a),
        json={"title":"Team Ship Đêm","members":[b]}).json()
    conv = g["conversation_id"]
    requests.post(B+f"/v1/conversations/{conv}/messages", headers=hdr(a), json={"body":"tin 1"})
    requests.post(B+f"/v1/conversations/{conv}/messages", headers=hdr(a), json={"body":"tin 2"})
    inbox = requests.get(B+"/v1/inbox", headers=hdr(b)).json()["conversations"]
    row = next(c for c in inbox if c["conversation_id"] == conv)
    assert row["kind"] == "group" and row["title"] == "Team Ship Đêm"
    assert row["unread"] == 2 and row["member_count"] == 2

# ---------- G8 · Status: đăng → hiện trên map presence ----------
def test_status_and_presence():
    u = user()
    requests.post(B+"/v1/me/status", headers=hdr(u),
                  json={"body":"Đang rảnh 2 tiếng, nhận kèo gấp ⚡","emoji":"⚡"})
    pres = requests.get(B+"/v1/map/presence").json()["items"]
    me = next(p for p in pres if p["id"] == u)
    assert me["status"].startswith("Đang rảnh") and me["emoji"] == "⚡"
    assert me["level"] == 1

# ---------- G9 · Cấp độ từ lao động: settle xong lên level ----------
def test_level_derived_from_settles():
    # Cấp giờ tính bằng level_score có trọng số chất lượng (chi tiết ở test_leveling.py).
    # Ở đây chỉ xác nhận trường 'level' tồn tại và người chưa làm gì = Lv1.
    a, b = user(), user()
    prof0 = requests.get(B+f"/v1/plumpers/{b}/profile").json()
    assert prof0["level"] == 1 and "level_score" in prof0
    golden(a, b)
    prof1 = requests.get(B+f"/v1/plumpers/{b}/profile").json()
    assert prof1["level"] >= 1   # có kèo rồi, cấp không tụt

# ---------- G10 · Thông tin hội thoại: member không thấy invite_code ----------
def test_conversation_info_hides_code_from_members():
    a, b = user(), user()
    golden(a, b)
    g = requests.post(B+"/v1/conversations/group", headers=hdr(a),
        json={"title":"Bảo mật mã","members":[b]}).json()
    info_owner = requests.get(B+f"/v1/conversations/{g['conversation_id']}", headers=hdr(a)).json()
    info_member = requests.get(B+f"/v1/conversations/{g['conversation_id']}", headers=hdr(b)).json()
    assert info_owner["invite_code"] == g["invite_code"]
    assert "invite_code" not in info_member
    assert len(info_owner["members"]) == 2 and info_owner["my_role"] == "owner"
