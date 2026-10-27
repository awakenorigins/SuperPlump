"""Soak test: tải trộn liên tục N giây, soi trôi latency + rò RAM + bất biến cuối."""
import os, sys, time, threading, statistics, concurrent.futures as cf
import psycopg2, requests

B = "http://127.0.0.1:8386"
DSN = "host=127.0.0.1 dbname=superplump user=plump password=plump"
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 75
THREADS = 32
TL = threading.local()
def S():
    if not hasattr(TL, "s"): TL.s = requests.Session()
    return TL.s
LAT, ERR = [], []
STOP = time.time() + DURATION

def hdr(u): return {"Authorization": "Bearer "+u}
def mk(kind="user"):
    return S().post(B+"/v1/dev/users", json={"handle":"soak","kyc":"verified","nara":2_000_000}, timeout=15).json()["id"]

POLICY = []
def loop(i):
    a, b = mk(), mk()
    n = 0; deals = 0
    while time.time() < STOP:
        try:
            if deals and deals % 15 == 0:
                a, b = mk(), mk(); deals += 1        # xoay user như chợ thật, khỏi húc phanh velocity
            t0 = time.perf_counter()
            if n % 3 == 0:
                rd = S().post(B+"/v1/drops", headers=hdr(a), json={"kind":"local","title":f"Soak {i}-{n}","price":80000,
                    "lng":106.6+(n%25)*0.01,"lat":10.7+(n%12)*0.01}, timeout=15)
                if rd.status_code == 429: POLICY.append("velocity"); n += 1; continue
                d = rd.json()["drop_id"]; deals += 1
                o = S().post(B+f"/v1/drops/{d}/offers", headers=hdr(b), json={"amount":75000}, timeout=15).json()["offer_id"]
                dl = S().post(B+f"/v1/offers/{o}/accept", headers=hdr(a), timeout=15).json()["deal_id"]
                S().post(B+f"/v1/deals/{dl}/start", headers=hdr(b), timeout=15)
                S().post(B+f"/v1/deals/{dl}/submit", headers=hdr(b), json={"proof":"p"}, timeout=15)
                S().post(B+f"/v1/deals/{dl}/confirm", headers=hdr(a), timeout=15)
            elif n % 3 == 1:
                S().get(B+"/v1/map/drops?bbox=106.5,10.6,106.95,10.95", timeout=15)
                S().get(B+"/v1/leaderboard?period=day", timeout=15)
            else:
                S().get(B+"/v1/wallet", headers=hdr(b), timeout=15)
                S().get(B+"/metrics", timeout=15)
            LAT.append(((time.perf_counter()-t0)*1000, time.time()))
        except Exception as e:
            ERR.append(str(e)[:80])
        n += 1

def rss_mb(pid):
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS"): return int(line.split()[1]) // 1024
    except Exception: return -1

if __name__ == "__main__":
    pid = int(os.environ.get("API_PID", "0"))
    rss0 = rss_mb(pid)
    with cf.ThreadPoolExecutor(THREADS) as ex:
        list(ex.map(loop, range(THREADS)))
    rss1 = rss_mb(pid)
    def pct(vals, p):
        vals = sorted(vals); return vals[min(len(vals)-1, int(len(vals)*p/100))] if vals else 0
    t_start = min(t for _, t in LAT); t_end = max(t for _, t in LAT)
    third = (t_end - t_start) / 3
    first = [ms for ms, t in LAT if t < t_start + third]
    last  = [ms for ms, t in LAT if t > t_end - third]
    print(f"== SOAK {DURATION}s @ {THREADS} luồng: {len(LAT)} vòng op ({len(LAT)/DURATION:.0f}/s) · lỗi thật: {len(ERR)} · phanh chính sách 429: {len(POLICY)}")
    print(f"   p50 {pct([m for m,_ in LAT],50):.0f}ms · p95 {pct([m for m,_ in LAT],95):.0f}ms · p99 {pct([m for m,_ in LAT],99):.0f}ms")
    drift = (pct(last,95) / max(pct(first,95), 1))
    print(f"   TRÔI p95 (⅓ cuối / ⅓ đầu): {pct(first,95):.0f}ms → {pct(last,95):.0f}ms = ×{drift:.2f} {'✓ ổn' if drift < 2 else '✗ XẤU ĐI'}")
    print(f"   RAM node: {rss0}MB → {rss1}MB (Δ{rss1-rss0:+}MB) {'✓' if rss1-rss0 < 150 else '✗ nghi rò'}")
    conn = psycopg2.connect(DSN); conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM reconcile()"); bad = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM wallets WHERE balance<0"); neg = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM deals WHERE state='SETTLED'"); st = cur.fetchone()[0]
    print(f"   BẤT BIẾN sau soak: reconcile lệch={bad} · ví âm={neg} · settled={st}")
    ok = bad == 0 and neg == 0 and len(ERR) == 0 and drift < 2
    print("== SOAK:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
