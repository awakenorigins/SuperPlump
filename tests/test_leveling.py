import uuid, requests

B = "http://127.0.0.1:8386"
ADMIN = {"x-admin-key": "plump-admin"}

def user(plump=0):
    return requests.post(B+"/v1/dev/users",
        json={"handle":"lvl","kyc":"verified","nara":5000000,"plump":plump}).json()["id"]

def hdr(u): return {"Authorization": "Bearer "+u}

def settle_deal(dropper, executor, price, rate_exec=5, rate_drop=5, kind="digital"):
    """Tạo 1 deal SETTLED giữa 2 người, 2 bên chấm điểm nhau."""
    d = requests.post(B+"/v1/drops", headers=hdr(dropper),
        json={"kind":kind,"title":"K "+uuid.uuid4().hex[:6],"price":price}).json()["drop_id"]
    o = requests.post(B+f"/v1/drops/{d}/offers", headers=hdr(executor),
        json={"amount":price}).json()["offer_id"]
    dl = requests.post(B+f"/v1/offers/{o}/accept", headers=hdr(dropper)).json()["deal_id"]
    requests.post(B+f"/v1/deals/{dl}/start", headers=hdr(executor))
    requests.post(B+f"/v1/deals/{dl}/submit", headers=hdr(executor), json={"proof":"p"})
    requests.post(B+f"/v1/deals/{dl}/confirm", headers=hdr(dropper))
    # hai bên review nhau (điểm hiển thị cần đủ 2 review)
    requests.post(B+f"/v1/deals/{dl}/reviews", headers=hdr(dropper), json={"rating":rate_exec,"body":"x"})
    requests.post(B+f"/v1/deals/{dl}/reviews", headers=hdr(executor), json={"rating":rate_drop,"body":"y"})
    return dl

def level_of(u):
    return requests.get(B+"/v1/me/level", headers=hdr(u)).json()

# ---------- L1 · Người mới = Lv1, score 0 ----------
def test_newbie_level1():
    u = user()
    d = level_of(u)
    assert d["level"] == 1 and d["score"] == 0 and d["valid_deals"] == 0

# ---------- L2 · CHẤT LƯỢNG THẮNG SỐ LƯỢNG ----------
# A: 6 kèo với 6 khách khác nhau, toàn 5★.  B: 6 kèo cùng 6 khách nhưng toàn 2★.
# A phải có score CAO HƠN HẲN B dù cùng số kèo & cùng độ đa dạng.
def test_quality_beats_quantity():
    a = user(); b = user()
    a_clients = [user() for _ in range(6)]
    b_clients = [user() for _ in range(6)]
    for c in a_clients: settle_deal(c, a, 100000, rate_exec=5)   # a nhận việc, khách chấm a 5★
    for c in b_clients: settle_deal(c, b, 100000, rate_exec=2)   # b bị chấm 2★
    la, lb = level_of(a), level_of(b)
    assert la["avg_rating"] == 5.0 and lb["avg_rating"] == 2.0
    assert la["score"] > lb["score"] * 2, f"5★ score {la['score']} phải áp đảo 2★ score {lb['score']}"

# ---------- L3 · ĐA DẠNG KHÁCH: 6 khách khác nhau > 6 kèo cùng 1 khách ----------
def test_diversity_beats_repetition():
    a = user(); b = user()
    solo_client = user()
    many_clients = [user() for _ in range(6)]
    for _ in range(6): settle_deal(solo_client, a, 100000, rate_exec=5)   # cùng 1 khách 6 lần
    for c in many_clients: settle_deal(c, b, 100000, rate_exec=5)         # 6 khách khác nhau
    la, lb = level_of(a), level_of(b)
    assert la["distinct_clients"] == 1 and lb["distinct_clients"] == 6
    assert lb["score"] > la["score"], "6 khách khác nhau phải hơn 6 lần cùng 1 khách"

# ---------- L4 · CHỐNG CÀY ẢO: 2 acc thuê nhau giá bèo không lên cấp ----------
# Hai người làm 30 kèo cho nhau giá 1.000 (bất thường thấp) → sau grace, score gần như đứng yên.
def test_self_dealing_low_price_blocked():
    a = user(); b = user()
    # trước tiên tạo mặt bằng giá loại 'digital' bằng vài kèo giá thật từ người khác
    for _ in range(3):
        settle_deal(user(), user(), 100000)   # median digital ~100k
    a0 = level_of(a)["score"]
    for _ in range(30):                        # a & b cày chéo giá 1.000
        settle_deal(a, b, 1000, rate_exec=5, rate_drop=5)
    a1 = level_of(a)
    # 30 kèo giá 1.000đ (dưới sàn tuyệt đối) → chỉ ~grace được tính điểm, cùng 1 khách.
    # Bằng chứng chống cày: SCORE rất thấp và LEVEL vẫn thấp dù 30 kèo.
    assert a1["distinct_clients"] == 1
    assert a1["score"] <= 3, f"30 kèo giá bèo phải cho score thấp (chỉ ~grace tính), thực: {a1['score']}"
    assert a1["level"] == 1, "cày ảo giá bèo KHÔNG được lên cấp"

# ---------- L5 · Kèo giá THẬT vẫn tính bình thường ----------
def test_normal_price_counts():
    a = user()
    for _ in range(3): settle_deal(user(), user(), 100000)   # lập mặt bằng
    clients = [user() for _ in range(5)]
    for c in clients: settle_deal(c, a, 90000, rate_exec=5)  # giá gần median → hợp lệ
    d = level_of(a)
    assert d["valid_deals"] == 5 and d["distinct_clients"] == 5
    assert d["level"] >= 3, f"5 kèo thật 5★ nên đạt Lv3+, thực: Lv{d['level']}"

# ---------- L6 · level_detail: to_next giảm dần khi cày thêm ----------
def test_to_next_decreases():
    a = user()
    for _ in range(3): settle_deal(user(), user(), 100000)
    c1 = [user() for _ in range(2)]
    for c in c1: settle_deal(c, a, 90000, rate_exec=5)
    d1 = level_of(a)
    c2 = [user() for _ in range(3)]
    for c in c2: settle_deal(c, a, 90000, rate_exec=5)
    d2 = level_of(a)
    assert d2["score"] > d1["score"]
    if d1["to_next"] is not None and d2["to_next"] is not None and d1["level"] == d2["level"]:
        assert d2["to_next"] < d1["to_next"]

# ---------- L7 · profile công khai có level ----------
def test_public_profile_has_level():
    a = user()
    for _ in range(3): settle_deal(user(), user(), 100000)
    for c in [user() for _ in range(5)]: settle_deal(c, a, 90000, rate_exec=5)
    prof = requests.get(B+f"/v1/plumpers/{a}/profile").json()
    assert "level" in prof and prof["level"] >= 3 and "level_score" in prof
