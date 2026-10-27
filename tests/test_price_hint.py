import uuid, requests, psycopg2

B = "http://127.0.0.1:8386"
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def db():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

def user(nara=5000000):
    return requests.post(B+"/v1/dev/users",
        json={"handle":"ph","kyc":"verified","nara":nara,"plump":0}).json()["id"]

def hdr(u): return {"Authorization": "Bearer "+u}

def settle(dropper, executor, price, cat="general", origin=None):
    body = {"kind":"digital","title":"Viec "+uuid.uuid4().hex[:5],"price":price,"category":cat}
    if origin: body["origin"] = origin
    d = requests.post(B+"/v1/drops", headers=hdr(dropper), json=body).json()["drop_id"]
    o = requests.post(B+f"/v1/drops/{d}/offers", headers=hdr(executor), json={"amount":price}).json()["offer_id"]
    dl = requests.post(B+f"/v1/offers/{o}/accept", headers=hdr(dropper)).json()["deal_id"]
    requests.post(B+f"/v1/deals/{dl}/start", headers=hdr(executor))
    requests.post(B+f"/v1/deals/{dl}/submit", headers=hdr(executor), json={"proof":"p"})
    requests.post(B+f"/v1/deals/{dl}/confirm", headers=hdr(dropper))
    return dl

def hint(u, cat="general", kind=None):
    q = f"?category={cat}"
    if kind: q += f"&kind={kind}"
    return requests.get(B+f"/v1/price-hint{q}", headers=hdr(u)).json()

# ---------- P1 · Chưa đủ dữ liệu → báo rõ, không bịa ----------
def test_insufficient_sample():
    u = user()
    h = hint(u, cat="cat_"+uuid.uuid4().hex[:6])   # category chưa có kèo nào
    assert h["enough_data"] is False
    assert h["suggestion"] is None
    assert "Chưa đủ dữ liệu" in h["note"]

# ---------- P2 · Đủ mẫu → trả khoảng phân vị hợp lý ----------
def test_hint_returns_quartiles():
    u = user()
    cat = "dich_"+uuid.uuid4().hex[:6]
    prices = [40000, 45000, 50000, 55000, 60000, 65000]   # median ~52.5k
    for p in prices:
        settle(user(), user(), p, cat=cat)
    h = hint(u, cat=cat)
    assert h["enough_data"] is True, f"6 kèo phải đủ mẫu, thực sample={h['sample']}"
    s = h["suggestion"]
    assert s["low"] <= s["typical"] <= s["high"], f"p25≤median≤p75, thực {s}"
    assert 45000 <= s["typical"] <= 60000, f"median trong khoảng hợp lý, thực {s['typical']}"

# ---------- P3 · CHỈ tính việc thật (civic không vào gợi ý) ----------
def test_hint_excludes_civic():
    u = user()
    cat = "clip_"+uuid.uuid4().hex[:6]
    # 6 kèo civic giá rất cao (200k) — KHÔNG được tính
    for _ in range(6):
        settle(user(), user(), 200000, cat=cat, origin="civic")
    h = hint(u, cat=cat)
    # civic bị loại → không đủ mẫu client
    assert h["enough_data"] is False, "việc civic KHÔNG được vào gợi ý giá"

# ---------- P4 · Kèo dưới sàn tuyệt đối không kéo gợi ý ----------
def test_hint_excludes_below_floor():
    u = user()
    cat = "seo_"+uuid.uuid4().hex[:6]
    # 6 kèo thật giá bình thường
    for p in [40000,45000,50000,55000,60000,65000]:
        settle(user(), user(), p, cat=cat)
    # thêm 10 kèo giá 1000 (dưới sàn 10k) — không được kéo median xuống
    for _ in range(10):
        settle(user(), user(), 1000, cat=cat)
    h = hint(u, cat=cat)
    assert h["enough_data"] is True
    # median vẫn quanh 50k, không bị kéo về ~1k
    assert h["suggestion"]["typical"] >= 40000, f"kèo dưới sàn không được kéo median, thực {h['suggestion']['typical']}"

# ---------- P5 · Gợi ý KHÔNG ép — vẫn đăng được giá bất kỳ ----------
def test_hint_does_not_impose():
    u = user()
    cat = "any_"+uuid.uuid4().hex[:6]
    for p in [40000,45000,50000,55000,60000]:
        settle(user(), user(), p, cat=cat)
    h = hint(u, cat=cat)
    typical = h["suggestion"]["typical"]
    # đăng việc giá GẤP 10 lần gợi ý — vẫn phải cho phép (tự do tuyệt đối)
    r = requests.post(B+"/v1/drops", headers=hdr(u),
        json={"kind":"digital","title":"Gia cao ngat","price":typical*10,"category":cat})
    assert r.status_code == 201, "giá tự do: đăng giá nào cũng được, gợi ý không ép"
    # đăng giá RẺ hơn nhiều cũng được
    r2 = requests.post(B+"/v1/drops", headers=hdr(u),
        json={"kind":"digital","title":"Gia be","price":2000,"category":cat})
    assert r2.status_code == 201

# ---------- P6 · Gợi ý có kèm cỡ mẫu + phạm vi ----------
def test_hint_has_sample_and_scope():
    u = user()
    cat = "meta_"+uuid.uuid4().hex[:6]
    for p in [30000,35000,40000,45000,50000,55000,60000]:
        settle(user(), user(), p, cat=cat)
    h = hint(u, cat=cat)
    assert h["sample"] == 7, f"cỡ mẫu đúng, thực {h['sample']}"
    assert h["scope"] in ("toàn quốc","khu","khu+giờ")
    assert "tham khảo" in h["note"] and "tự quyết" in h["note"]

# ---------- P7 · Drop detail vẫn có price_reference (tương thích cũ) ----------
def test_drop_detail_still_has_reference():
    u = user(); ex = user()
    cat = "compat_"+uuid.uuid4().hex[:6]
    for p in [40000,50000,60000]:
        settle(user(), user(), p, cat=cat)
    d = requests.post(B+"/v1/drops", headers=hdr(u),
        json={"kind":"digital","title":"Viec moi","price":50000,"category":cat}).json()["drop_id"]
    detail = requests.get(B+f"/v1/drops/{d}", headers=hdr(ex)).json()
    assert "price_reference" in detail, "drop detail vẫn giữ price_reference (không vỡ tương thích)"
