"""SuperPlump mini load test — đo p50/p95/p99 + kiểm bất biến sổ cái DƯỚI TẢI.
Chạy: python3 scripts/loadtest.py  (server phải đang chạy)
Không nằm trong pytest — đây là dụng cụ vận hành."""
import time, threading, statistics, concurrent.futures as cf
import psycopg2, requests

B = "http://127.0.0.1:8386"
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"
TL = threading.local()

def S():
    if not hasattr(TL, "s"): TL.s = requests.Session()
    return TL.s

BUCKETS = {"register": [], "map_read": [], "drop_create": [], "offer": [],
           "accept": [], "transition": [], "wallet": []}
ERRORS = []

def timed(bucket, method, path, **kw):
    t0 = time.perf_counter()
    r = S().request(method, B + path, timeout=15, **kw)
    BUCKETS[bucket].append((time.perf_counter() - t0) * 1000)
    if r.status_code >= 500: ERRORS.append((path, r.status_code, r.text[:120]))
    return r

def dev_user():
    return S().post(B + "/v1/dev/users", json={"handle": "load", "kyc": "verified",
                                               "nara": 1_000_000}, timeout=15).json()["id"]

def hdr(u): return {"Authorization": "Bearer " + u}

def golden_worker(i):
    try:
        a, b = dev_user(), dev_user()
        d = timed("drop_create", "POST", "/v1/drops", headers=hdr(a), json={
            "kind": "local", "title": f"Load test việc {i}", "price": 100000,
            "lng": 106.62 + (i % 20) * 0.01, "lat": 10.71 + (i % 15) * 0.01}).json()["drop_id"]
        o = timed("offer", "POST", f"/v1/drops/{d}/offers", headers=hdr(b),
                  json={"amount": 90000 + i * 100}).json()["offer_id"]
        dl = timed("accept", "POST", f"/v1/offers/{o}/accept", headers=hdr(a)).json()["deal_id"]
        timed("transition", "POST", f"/v1/deals/{dl}/start", headers=hdr(b))
        timed("transition", "POST", f"/v1/deals/{dl}/submit", headers=hdr(b), json={"proof": "p"})
        timed("transition", "POST", f"/v1/deals/{dl}/confirm", headers=hdr(a))
        timed("wallet", "GET", "/v1/wallet", headers=hdr(b))
        return True
    except Exception as e:
        ERRORS.append(("golden", type(e).__name__, str(e)[:120])); return False

def map_reader(n):
    for k in range(n):
        timed("map_read", "GET", f"/v1/map/drops?bbox=106.{50+k%40},10.6,106.95,10.95")

def reg_login(n):
    for _ in range(n):
        tok = timed("register", "POST", "/v1/auth/register").json()["token"]
        S().post(B + "/v1/auth/login", json={"token": tok}, timeout=15)

def pct(v, p):
    if not v: return 0
    v = sorted(v); return v[min(len(v)-1, int(len(v)*p/100))]

def race_http():
    a = dev_user()
    d = S().post(B+"/v1/drops", headers=hdr(a), json={"kind":"digital","title":"Race HTTP một drop",
        "price":50000}).json()["drop_id"]
    offs = []
    for _ in range(15):
        u = dev_user()
        offs.append(S().post(B+f"/v1/drops/{d}/offers", headers=hdr(u), json={"amount":50000}).json()["offer_id"])
    codes = []
    def acc(o): codes.append(S().post(B+f"/v1/offers/{o}/accept", headers=hdr(a), timeout=15).status_code)
    with cf.ThreadPoolExecutor(15) as ex: list(ex.map(acc, offs))
    return codes.count(201), codes.count(409)

if __name__ == "__main__":
    t0 = time.time()
    with cf.ThreadPoolExecutor(24) as ex:
        futs = [ex.submit(golden_worker, i) for i in range(30)]
        futs += [ex.submit(map_reader, 15) for _ in range(8)]
        futs += [ex.submit(reg_login, 5) for _ in range(4)]
        ok = sum(1 for f in cf.as_completed(futs) if f.result() is not False)
    dur = time.time() - t0
    total = sum(len(v) for v in BUCKETS.values())
    print(f"== TẢI: {total} request / {dur:.1f}s = {total/dur:.0f} req/s (24 luồng) · lỗi 5xx/exception: {len(ERRORS)}")
    for k, v in BUCKETS.items():
        if v: print(f"   {k:12s} n={len(v):4d}  p50={pct(v,50):6.1f}ms  p95={pct(v,95):6.1f}ms  p99={pct(v,99):6.1f}ms")
    for e in ERRORS[:5]: print("   ERR:", e)
    rounds = [race_http() for _ in range(6)]
    ok_race = all(r == (1, 14) for r in rounds)
    print(f"== RACE HTTP ×6 vòng (15 accept đồng thời/vòng): {rounds} → {'ĐÚNG TUYỆT ĐỐI' if ok_race else 'SAI!'}")
    conn = psycopg2.connect(DSN); conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM reconcile()"); bad = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM wallets WHERE balance < 0"); neg = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM (SELECT deal_id, SUM(amount) s FROM ledger_entries
                       WHERE deal_id IS NOT NULL GROUP BY deal_id HAVING SUM(amount)<>0) x"""); nz = cur.fetchone()[0]
        cur.execute("SELECT balance FROM wallets WHERE kind='escrow'"); esc = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM deals WHERE state='SETTLED'"); st = cur.fetchone()[0]
    print(f"== BẤT BIẾN DƯỚI TẢI: reconcile lệch={bad} · ví âm={neg} · deal Σ≠0={nz} · escrow tồn={esc} · settled={st}")
    print("== KẾT LUẬN:", "PASS" if (bad==0 and neg==0 and nz==0 and len(ERRORS)==0) else "FAIL")
