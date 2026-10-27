#!/usr/bin/env python3
"""SMOKE — golden path TIỀN THẬT trên môi trường production-mode:
regnick → eKYC → duyệt → nạp qua intent+webhook ký HMAC (đường tiền chính thức) → deal trọn vòng → đối chiếu ví + sổ.
  python3 scripts/smoke.py <BASE> --admin-key K --payment-secret S [--ekyc-secret S2]"""
import argparse, hashlib, hmac as hm, json, sys, uuid, requests

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("--admin-key", required=True)
    ap.add_argument("--payment-secret", required=True); ap.add_argument("--ekyc-secret")
    a = ap.parse_args()
    B = a.base.rstrip("/"); ADMIN = {"x-admin-key": a.admin_key}
    s = requests.Session(); s.verify = False
    requests.packages.urllib3.disable_warnings()
    def die(msg): print("✗ SMOKE FAIL:", msg); sys.exit(1)
    def signed(body, key):
        raw = json.dumps(body).encode()
        return raw, {"content-type": "application/json",
                     "x-signature": hm.new(key.encode(), raw, hashlib.sha256).hexdigest()}

    # 1 · regnick + login hai người
    ppl = {}
    for name in ("dropper", "executor"):
        tok = s.post(B+"/v1/auth/register", timeout=10).json()["token"]
        j = s.post(B+"/v1/auth/login", json={"token": tok}, timeout=10).json()
        ppl[name] = {"jwt": j["jwt"], "id": j["plumper_id"]}
        print(f"✓ regnick {name}: token 13 ký tự cấp OK")
    H = lambda n: {"Authorization": "Bearer " + ppl[n]["jwt"]}

    # 2 · eKYC + duyệt (webhook nếu có secret, không thì admin duyệt tay)
    for name in ("dropper", "executor"):
        kid = s.post(B+"/v1/kyc/ekyc", headers=H(name),
                     json={"provider":"vneid","ref":"SMOKE-"+uuid.uuid4().hex[:6]}, timeout=10).json()["kyc_id"]
        if a.ekyc_secret:
            raw, hh = signed({"kyc_id": kid, "result": "approved"}, a.ekyc_secret)
            r = s.post(B+"/v1/kyc/webhook", data=raw, headers=hh, timeout=10)
        else:
            r = s.post(B+f"/v1/admin/kyc/{kid}/approve", headers=ADMIN, timeout=10)
        if not r.ok: die("duyệt KYC: " + r.text[:120])
        st = s.get(B+"/v1/kyc/status", headers=H(name), timeout=10).json()["status"]
        if st != "verified": die(f"{name} chưa verified")
        print(f"✓ eKYC {name}: verified (không một tấm ảnh giấy tờ nào)")

    # 3 · Nạp bằng ĐƯỜNG TIỀN CHÍNH THỨC: intent + webhook HMAC
    it = s.post(B+"/v1/wallet/topups/intent", headers=H("dropper"), json={"amount": 200000}, timeout=10).json()
    raw, hh = signed({"provider_ref": "SMOKE-" + uuid.uuid4().hex[:10], "intent_id": it["intent_id"]}, a.payment_secret)
    r = s.post(B+"/v1/payments/webhook", data=raw, headers=hh, timeout=10)
    if not (r.ok and r.json().get("credited") == 200000): die("webhook nạp: " + r.text[:120])
    w0 = s.get(B+"/v1/wallet", headers=H("dropper"), timeout=10).json()
    if w0["available"] != 200000: die("ví sau nạp lệch: " + str(w0))
    print("✓ Nạp 200.000 qua intent + webhook HMAC — ví khớp")

    # 4 · Deal trọn vòng
    d = s.post(B+"/v1/drops", headers=H("dropper"),
        json={"kind":"digital","title":"Smoke deal go-live "+uuid.uuid4().hex[:5],"price":120000}, timeout=10).json()["drop_id"]
    o = s.post(B+f"/v1/drops/{d}/offers", headers=H("executor"), json={"amount":100000}, timeout=10).json()["offer_id"]
    dl = s.post(B+f"/v1/offers/{o}/accept", headers=H("dropper"), timeout=10).json()["deal_id"]
    for step, who in (("start","executor"),("submit","executor"),("confirm","dropper")):
        r = s.post(B+f"/v1/deals/{dl}/{step}", headers=H(who), json={"proof":"smoke"} if step=="submit" else None, timeout=10)
        if not r.ok: die(f"{step}: {r.text[:120]}")
    we = s.get(B+"/v1/wallet", headers=H("executor"), timeout=10).json()
    wd = s.get(B+"/v1/wallet", headers=H("dropper"), timeout=10).json()
    if we["available"] != 95000: die(f"executor nhận sai: {we}")
    if wd["available"] != 200000 - 105000: die(f"dropper trừ sai: {wd}")
    print("✓ Deal SETTLED: executor +95.000 (100k −5%), dropper −105.000 (100k +5%) — đúng từng đồng")

    m = s.get(B+"/metrics", timeout=10).text
    if "plump_ledger_mismatch 0" not in m: die("SỔ CÁI LỆCH SAU SMOKE")
    print("✓ ledger_mismatch = 0 sau smoke")
    print("== SMOKE: PASS — đường tiền production sống và sạch 🚀")

if __name__ == "__main__":
    main()
