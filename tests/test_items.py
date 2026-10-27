import time, uuid, psycopg2, requests

B = "http://127.0.0.1:8386"
ADMIN = {"x-admin-key": "plump-admin"}
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def db():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

def q(c, sql, a=None):
    with c.cursor() as cur:
        cur.execute(sql, a or ())
        try: return cur.fetchall()
        except psycopg2.ProgrammingError: return None

def user(nara=500000, plump=0):
    return requests.post(B+"/v1/dev/users", json={"handle":"itm","kyc":"verified","nara":nara,"plump":plump}).json()["id"]

def hdr(u): return {"Authorization": "Bearer "+u}

def golden(a, b, price=90000, both_review=None):
    d = requests.post(B+"/v1/drops", headers=hdr(a),
        json={"kind":"digital","title":"Item test "+uuid.uuid4().hex[:6],"price":100000}).json()["drop_id"]
    o = requests.post(B+f"/v1/drops/{d}/offers", headers=hdr(b), json={"amount":price}).json()["offer_id"]
    dl = requests.post(B+f"/v1/offers/{o}/accept", headers=hdr(a)).json()["deal_id"]
    requests.post(B+f"/v1/deals/{dl}/start", headers=hdr(b))
    requests.post(B+f"/v1/deals/{dl}/submit", headers=hdr(b), json={"proof":"p"})
    requests.post(B+f"/v1/deals/{dl}/confirm", headers=hdr(a))
    if both_review:
        ra, rb = both_review
        requests.post(B+f"/v1/deals/{dl}/reviews", headers=hdr(b), json={"rating":rb,"body":""})
        requests.post(B+f"/v1/deals/{dl}/reviews", headers=hdr(a), json={"rating":ra,"body":""})
    return dl

# ---------- I1 · Mua bằng Nara = bút toán kép, reconcile vẫn 0, không mua trùng ----------
def test_buy_nara_double_entry():
    u = user()
    shop = requests.get(B+"/v1/shop", headers=hdr(u)).json()["items"]
    assert any(i["id"] == "win_landmark" and i["owned"] is False for i in shop)
    assert requests.post(B+"/v1/shop/win_landmark/buy", headers=hdr(u)).status_code == 201
    assert requests.get(B+"/v1/wallet", headers=hdr(u)).json()["available"] == 500000 - 80000
    c = db()
    rows = q(c, """SELECT COALESCE(SUM(l.amount),0), count(*) FROM ledger_entries l
                   JOIN wallets w ON w.id=l.wallet_id WHERE l.kind='purchase' AND w.owner=%s""", (u,))
    assert rows[0][1] == 1 and rows[0][0] == -80000
    assert q(c, "SELECT count(*) FROM reconcile()")[0][0] == 0     # két vẫn khớp tuyệt đối
    c.close()
    r2 = requests.post(B+"/v1/shop/win_landmark/buy", headers=hdr(u))
    assert r2.status_code == 409 and r2.json()["title"] == "already_owned"

# ---------- I2 · Thiếu tiền cả hai loại → chặn sạch ----------
def test_insufficient_both_currencies():
    poor = user(nara=10000)
    r = requests.post(B+"/v1/shop/win_landmark/buy", headers=hdr(poor))
    assert r.status_code == 409 and r.json()["title"] == "insufficient_nara"
    r2 = requests.post(B+"/v1/shop/hand_caphe/buy", headers=hdr(poor))
    assert r2.status_code == 409 and r2.json()["title"] == "insufficient_plump"

# ---------- I3 · Mua bằng Plump: điểm farm từ lao động, bút toán âm append-only ----------
def test_buy_with_plump_labor_points():
    a, b = user(), user()
    golden(a, b); golden(a, b, price=80000)          # b: 2 settle = 🍑1000
    assert requests.get(B+"/v1/wallet", headers=hdr(b)).json()["plump"] == 1000
    assert requests.post(B+"/v1/shop/hand_caphe/buy", headers=hdr(b)).status_code == 201
    assert requests.get(B+"/v1/wallet", headers=hdr(b)).json()["plump"] == 200
    c = db()
    assert q(c, "SELECT amount FROM plump_points WHERE owner=%s AND reason LIKE 'buy_%%'", (b,))[0][0] == -800
    c.close()
    assert requests.post(B+"/v1/me/equip", headers=hdr(b),
                         json={"slot":"hand","item_id":"hand_caphe"}).status_code == 200

# ---------- I4 · Gác slot & sở hữu ----------
def test_slot_and_ownership_guards():
    u = user()
    requests.post(B+"/v1/shop/non_la_neon/buy", headers=hdr(u))
    r = requests.post(B+"/v1/me/equip", headers=hdr(u), json={"slot":"hand","item_id":"non_la_neon"})
    assert r.status_code == 400 and r.json()["title"] == "slot_mismatch"
    r2 = requests.post(B+"/v1/me/equip", headers=hdr(u), json={"slot":"head","item_id":"mu_chrome"})
    assert r2.status_code == 403 and r2.json()["title"] == "not_owned"
    assert requests.post(B+"/v1/me/equip", headers=hdr(u),
                         json={"slot":"head","item_id":"non_la_neon"}).status_code == 200

# ---------- I5 · Phòng: set slot + khách xem được ----------
def test_room_set_and_public_view():
    u = user()
    requests.post(B+"/v1/shop/wp_neon/buy", headers=hdr(u))
    requests.post(B+"/v1/shop/lamp_neon/buy", headers=hdr(u))
    assert requests.post(B+"/v1/me/room", headers=hdr(u),
                         json={"slot":"wallpaper","item_id":"wp_neon"}).status_code == 200
    requests.post(B+"/v1/me/room", headers=hdr(u), json={"slot":"lamp","item_id":"lamp_neon"})
    room = requests.get(B+f"/v1/plumpers/{u}/room").json()
    slots = {r["slot"]: r["item_id"] for r in room["room"]}
    assert slots == {"wallpaper":"wp_neon","lamp":"lamp_neon"}
    assert room["shelf"] == [] and room["guestbook"] == []

# ---------- I6 · Mốc lao động: settle đủ mốc → Chổi Vàng tự mọc trên kệ ----------
def test_labor_milestone_grants_shelf_item():
    c = db()
    q(c, """UPDATE config SET val = jsonb_set(val,'{milestone_broom}','3') WHERE key='items'""")
    try:
        a, b = user(nara=1_000_000), user()
        for _ in range(3): golden(a, b)
        inv = requests.get(B+"/v1/me/inventory", headers=hdr(b)).json()["inventory"]
        assert any(i["item_id"]=="choi_vang" and i["via"]=="earned" for i in inv)
        room = requests.get(B+f"/v1/plumpers/{b}/room").json()
        assert any(s["item_id"]=="choi_vang" for s in room["shelf"]) and room["done"] == 3
        r = requests.post(B+"/v1/shop/choi_vang/buy", headers=hdr(user()))
        assert r.status_code == 409 and r.json()["title"] == "item_not_for_sale"   # oai không bán
    finally:
        q(c, """UPDATE config SET val = jsonb_set(val,'{milestone_broom}','10') WHERE key='items'"""); c.close()

# ---------- I7 · Tặng: phải quen qua việc, chỉ đồ nara-giftable, chuyển sở hữu sạch ----------
def test_gift_rules():
    a, b = user(), user()
    requests.post(B+"/v1/shop/non_la_neon/buy", headers=hdr(a))
    r = requests.post(B+"/v1/me/inventory/non_la_neon/gift", headers=hdr(a), json={"to": b})
    assert r.status_code == 403 and r.json()["title"] == "gift_requires_connection"
    golden(a, b)
    assert requests.post(B+"/v1/me/inventory/non_la_neon/gift", headers=hdr(a),
                         json={"to": b}).status_code == 200
    inv_a = requests.get(B+"/v1/me/inventory", headers=hdr(a)).json()["inventory"]
    inv_b = requests.get(B+"/v1/me/inventory", headers=hdr(b)).json()["inventory"]
    assert not any(i["item_id"]=="non_la_neon" for i in inv_a)
    assert any(i["item_id"]=="non_la_neon" and i["via"]=="gift" for i in inv_b)
    requests.post(B+"/v1/shop/hand_caphe/buy", headers=hdr(b))     # b có 🍑500 từ golden... 500<800
    r2 = requests.post(B+"/v1/me/inventory/hand_caphe/gift", headers=hdr(b), json={"to": a})
    assert r2.status_code == 409 and r2.json()["title"] == "not_giftable"

# ---------- I8 · Sổ khách: chỉ ai từng deal chung ----------
def test_guestbook_gating():
    owner, stranger = user(), user()
    r = requests.post(B+f"/v1/plumpers/{owner}/guestbook", headers=hdr(stranger),
                      json={"body":"hóng phòng đẹp"})
    assert r.status_code == 403 and r.json()["title"] == "guestbook_requires_deal"
    golden(owner, stranger)
    assert requests.post(B+f"/v1/plumpers/{owner}/guestbook", headers=hdr(stranger),
                         json={"body":"Làm chung vui, phòng chất 🍑"}).status_code == 201
    gb = requests.get(B+f"/v1/plumpers/{owner}/room").json()["guestbook"]
    assert len(gb) == 1 and "🍑" in gb[0]["body"]
    r3 = requests.post(B+f"/v1/plumpers/{owner}/guestbook", headers=hdr(owner), json={"body":"tự khen"})
    assert r3.status_code == 409

# ---------- I9 · Aura 5★: đạt thì thắp, tụt là RỤNG + tự tháo khỏi người ----------
def test_prestige_aura_grant_and_decay():
    c = db()
    q(c, """UPDATE config SET val = jsonb_set(val,'{aura_min_reviews}','2') WHERE key='items'""")
    try:
        star = user()
        c1, c2, c3 = user(), user(), user()
        golden(c1, star, both_review=(5,5))
        golden(c2, star, both_review=(5,5))
        r = requests.post(B+"/v1/admin/jobs/refresh-prestige", headers=ADMIN).json()
        assert r["granted"] >= 1
        inv = requests.get(B+"/v1/me/inventory", headers=hdr(star)).json()["inventory"]
        assert any(i["item_id"]=="aura_5sao" for i in inv)
        assert requests.post(B+"/v1/me/equip", headers=hdr(star),
                             json={"slot":"aura","item_id":"aura_5sao"}).status_code == 200
        golden(c3, star, both_review=(1,5))            # khách chấm 1★ → avg tụt
        r2 = requests.post(B+"/v1/admin/jobs/refresh-prestige", headers=ADMIN).json()
        assert r2["revoked"] >= 1
        inv2 = requests.get(B+"/v1/me/inventory", headers=hdr(star)).json()
        assert not any(i["item_id"]=="aura_5sao" for i in inv2["inventory"])
        assert not any(e["item_id"]=="aura_5sao" for e in inv2["equipped"])   # rụng là tháo luôn
    finally:
        q(c, """UPDATE config SET val = jsonb_set(val,'{aura_min_reviews}','5') WHERE key='items'"""); c.close()

# ---------- I10 · Skin twin: mua được nhưng nhãn AI khóa vĩnh viễn ----------
def test_twin_skin_ai_label_locked():
    u = user()
    shop = requests.get(B+"/v1/shop", headers=hdr(u)).json()["items"]
    holo = next(i for i in shop if i["id"]=="twin_skin_holo")
    assert holo["meta"]["ai_label_locked"] is True
    requests.post(B+"/v1/shop/twin_skin_holo/buy", headers=hdr(u))
    assert requests.post(B+"/v1/me/equip", headers=hdr(u),
                         json={"slot":"twin_skin","item_id":"twin_skin_holo"}).status_code == 200
