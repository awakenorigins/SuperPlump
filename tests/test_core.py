import threading, uuid, time
import psycopg2, pytest

DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"

def conn():
    c = psycopg2.connect(DSN); c.autocommit = True; return c

@pytest.fixture(scope="module")
def db():
    c = conn(); yield c; c.close()

def q(c, sql, args=None):
    with c.cursor() as cur:
        cur.execute(sql, args or ())
        try: return cur.fetchall()
        except psycopg2.ProgrammingError: return None

def mk_user(c, handle):
    uid = q(c, "INSERT INTO plumpers(handle,display_name,kyc_status) VALUES (%s,%s,'verified') RETURNING id",
            (handle+str(uuid.uuid4())[:6], handle))[0][0]
    q(c, "INSERT INTO wallets(owner,kind,balance) VALUES (%s,'user',0)", (uid,))
    q(c, "SELECT topup(%s, 500000)", (uid,))
    return uid

def mk_drop(c, owner, price=110000):
    return q(c, """INSERT INTO drops(owner,kind,title,price,location)
        VALUES (%s,'local','Dọn kho 2 tiếng',%s, ST_SetSRID(ST_MakePoint(106.7009,10.7379),4326)::geography)
        RETURNING id""", (owner, price))[0][0]

def mk_offer(c, drop, frm, amount):
    return q(c, "INSERT INTO offers(drop_id,from_id,amount) VALUES (%s,%s,%s) RETURNING id",
             (drop, frm, amount))[0][0]

def bal(c, uid):
    return q(c, "SELECT balance FROM wallets WHERE owner=%s AND kind='user'", (uid,))[0][0]

def sysbal(c, kind):
    return q(c, "SELECT balance FROM wallets WHERE owner IS NULL AND kind=%s", (kind,))[0][0]

# ---------- T1 · GOLDEN PATH + BẤT BIẾN LEDGER ----------
def test_golden_path_and_ledger_invariant(db):
    lan, minh = mk_user(db,'lan'), mk_user(db,'minh')
    drop = mk_drop(db, lan); off = mk_offer(db, drop, minh, 95000)
    esc0, plat0 = sysbal(db,'escrow'), sysbal(db,'platform')

    deal = q(db, "SELECT accept_offer(%s,%s)", (off, lan))[0][0]
    # hold = 95000 + 4750 (phí 5% phía thả)
    assert bal(db, lan) == 500000 - 99750
    assert sysbal(db,'escrow') == esc0 + 99750

    q(db, "SELECT deal_start(%s,%s)", (deal, minh))
    q(db, "SELECT deal_submit(%s,%s,%s)", (deal, minh, 'proof://1.jpg'))
    q(db, "SELECT deal_confirm(%s,%s)", (deal, lan))

    assert bal(db, minh) == 500000 + 90250            # 95000 − 4750 phí phía nhận
    assert sysbal(db,'platform') == plat0 + 9500      # tổng phí 2 phía
    assert sysbal(db,'escrow') == esc0                # két về đúng 0
    s = q(db, "SELECT COALESCE(SUM(amount),0) FROM ledger_entries WHERE deal_id=%s", (deal,))[0][0]
    assert s == 0                                     # kế toán kép: tổng mỗi deal = 0
    assert q(db, "SELECT * FROM reconcile()") == []   # mọi ví = Σ sổ

# ---------- T2 · RACE: 10 accept đồng thời → đúng 1 thắng ----------
def test_double_accept_race(db):
    lan = mk_user(db,'lan2'); drop = mk_drop(db, lan)
    offers = [mk_offer(db, drop, mk_user(db,'w%d'%i), 90000+i*1000) for i in range(10)]
    wins, errs = [], []
    def go(off):
        c = conn()
        try:
            r = q(c, "SELECT accept_offer(%s,%s)", (off, lan)); wins.append(r[0][0])
        except Exception as e: errs.append(str(e))
        finally: c.close()
    ts = [threading.Thread(target=go, args=(o,)) for o in offers]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(wins) == 1 and len(errs) == 9
    assert q(db, "SELECT count(*) FROM deals WHERE drop_id=%s", (drop,))[0][0] == 1
    assert q(db, "SELECT status FROM drops WHERE id=%s", (drop,))[0][0] == 'matched'
    assert q(db, "SELECT * FROM reconcile()") == []

# ---------- T3 · IDEMPOTENCY: confirm 2 lần → hiệu ứng 1 lần ----------
def test_confirm_twice_single_effect(db):
    a, b = mk_user(db,'a3'), mk_user(db,'b3')
    deal = q(db,"SELECT accept_offer(%s,%s)",(mk_offer(db,mk_drop(db,a),b,100000),a))[0][0]
    q(db,"SELECT deal_start(%s,%s)",(deal,b)); q(db,"SELECT deal_submit(%s,%s,NULL)",(deal,b))
    q(db,"SELECT deal_confirm(%s,%s)",(deal,a))
    n0 = q(db,"SELECT count(*) FROM ledger_entries WHERE deal_id=%s",(deal,))[0][0]
    with pytest.raises(Exception): q(db,"SELECT deal_confirm(%s,%s)",(deal,a))
    assert q(db,"SELECT count(*) FROM ledger_entries WHERE deal_id=%s",(deal,))[0][0] == n0

# ---------- T4 · KHÔNG THỂ GỌI TẮT / SAI VAI ----------
def test_wrong_role_and_shortcut_blocked(db):
    a, b, x = mk_user(db,'a4'), mk_user(db,'b4'), mk_user(db,'x4')
    deal = q(db,"SELECT accept_offer(%s,%s)",(mk_offer(db,mk_drop(db,a),b,80000),a))[0][0]
    with pytest.raises(Exception): q(db,"SELECT deal_confirm(%s,%s)",(deal,a))   # LOCKED → confirm: cấm
    with pytest.raises(Exception): q(db,"SELECT deal_start(%s,%s)",(deal,a))     # dropper đòi start: cấm
    with pytest.raises(Exception): q(db,"SELECT deal_start(%s,%s)",(deal,x))     # người lạ: cấm

# ---------- T5 · ĐÁNH GIÁ MÙ + BẤT BIẾN ----------
def test_blind_reviews_immutable(db):
    a, b = mk_user(db,'a5'), mk_user(db,'b5')
    deal = q(db,"SELECT accept_offer(%s,%s)",(mk_offer(db,mk_drop(db,a),b,60000),a))[0][0]
    q(db,"SELECT deal_start(%s,%s)",(deal,b)); q(db,"SELECT deal_submit(%s,%s,NULL)",(deal,b))
    q(db,"SELECT deal_confirm(%s,%s)",(deal,a))
    q(db,"SELECT submit_review(%s,%s,5,'ngon')",(deal,b))
    assert q(db,"SELECT count(*) FROM deal_reviews_visible WHERE deal_id=%s",(deal,))[0][0] == 0  # mù
    q(db,"SELECT submit_review(%s,%s,4,'ok')",(deal,a))
    assert q(db,"SELECT count(*) FROM deal_reviews_visible WHERE deal_id=%s",(deal,))[0][0] == 2  # cùng mở
    with pytest.raises(Exception):
        c2 = conn(); q(c2,"SET ROLE authenticated"); q(c2,"UPDATE reviews SET rating=1 WHERE deal_id=%s",(deal,))

# ---------- T6 · RIÊNG TƯ VỊ TRÍ ----------
def test_location_privacy(db):
    a, b, x = mk_user(db,'a6'), mk_user(db,'b6'), mk_user(db,'x6')
    drop = mk_drop(db, a)
    raw = q(db,"SELECT ST_X(location::geometry), ST_Y(location::geometry) FROM drops WHERE id=%s",(drop,))[0]
    pub = q(db,"SELECT fuzzy_lng, fuzzy_lat FROM drops_public WHERE id=%s",(drop,))[0]
    assert (round(raw[0],6), round(raw[1],6)) != (round(pub[0],6), round(pub[1],6))  # đã làm mờ
    def on_grid(v, g=0.003):
        m = abs(v) % g
        return min(m, g - m) < 1e-9
    assert on_grid(pub[0]) and on_grid(pub[1])                                       # snap đúng lưới
    deal = q(db,"SELECT accept_offer(%s,%s)",(mk_offer(db,drop,b,50000),a))[0][0]
    assert q(db,"SELECT * FROM exact_location(%s,%s)",(deal,b))[0] == raw            # 2 bên: thấy thật
    with pytest.raises(Exception): q(db,"SELECT * FROM exact_location(%s,%s)",(deal,x))  # người lạ: cấm

# ---------- T7 · TRANH CHẤP: refund & split, két về 0 ----------
def test_dispute_refund_and_split(db):
    a, b = mk_user(db,'a7'), mk_user(db,'b7')
    deal = q(db,"SELECT accept_offer(%s,%s)",(mk_offer(db,mk_drop(db,a),b,100000),a))[0][0]
    q(db,"SELECT open_dispute(%s,%s,'không đúng mô tả')",(deal,b))
    q(db,"SELECT resolve_dispute(%s,'refund',NULL)",(deal,))
    assert bal(db,a) == 500000                          # hoàn đủ cả phí giữ
    assert q(db,"SELECT COALESCE(SUM(amount),0) FROM ledger_entries WHERE deal_id=%s",(deal,))[0][0] == 0
    a2, b2 = mk_user(db,'a7s'), mk_user(db,'b7s')
    d2 = q(db,"SELECT accept_offer(%s,%s)",(mk_offer(db,mk_drop(db,a2),b2,100000),a2))[0][0]
    q(db,"SELECT open_dispute(%s,%s,'x')",(d2,a2))
    q(db,"SELECT resolve_dispute(%s,'split',NULL)",(d2,))
    assert bal(db,a2) + bal(db,b2) == 1000000           # split không rơi rớt một đồng
    assert q(db,"SELECT * FROM reconcile()") == []

# ---------- T8 · AUTO-CONFIRM bảo vệ người làm ----------
def test_auto_confirm(db):
    a, b = mk_user(db,'a8'), mk_user(db,'b8')
    deal = q(db,"SELECT accept_offer(%s,%s)",(mk_offer(db,mk_drop(db,a),b,70000),a))[0][0]
    q(db,"SELECT deal_start(%s,%s)",(deal,b)); q(db,"SELECT deal_submit(%s,%s,'p')",(deal,b))
    q(db,"UPDATE deals SET submitted_at = now() - interval '13 hours' WHERE id=%s",(deal,))
    assert q(db,"SELECT auto_confirm_overdue()")[0][0] >= 1
    assert q(db,"SELECT state FROM deals WHERE id=%s",(deal,))[0][0] == 'SETTLED'

# ---------- T9 · EVENT LOG đủ vòng đời ----------
def test_event_log_replayable(db):
    a, b = mk_user(db,'a9'), mk_user(db,'b9')
    deal = q(db,"SELECT accept_offer(%s,%s)",(mk_offer(db,mk_drop(db,a),b,90000),a))[0][0]
    q(db,"SELECT deal_start(%s,%s)",(deal,b)); q(db,"SELECT deal_submit(%s,%s,'p')",(deal,b))
    q(db,"SELECT deal_confirm(%s,%s)",(deal,a))
    q(db,"SELECT submit_review(%s,%s,5,'')",(deal,b)); q(db,"SELECT submit_review(%s,%s,5,'')",(deal,a))
    types = [r[0] for r in q(db,
      "SELECT event_type FROM events WHERE aggregate_id=%s ORDER BY id",(deal,))]
    assert types == ['locked','started','submitted','settled','review_submitted','review_submitted']

# ---------- T10 · RLS: chỉ thấy ví của mình ----------
def test_rls_wallet_isolation(db):
    a, b = mk_user(db,'a10'), mk_user(db,'b10')
    c2 = conn()
    q(c2, "SET ROLE authenticated")
    q(c2, "SELECT set_config('app.uid', %s, false)", (str(a),))
    rows = q(c2, "SELECT owner FROM wallets")
    assert {r[0] for r in rows} == {a}      # không thấy ví người khác, không thấy ví hệ thống
    c2.close()
