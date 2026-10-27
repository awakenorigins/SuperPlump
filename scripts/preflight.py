#!/usr/bin/env python3
"""PREFLIGHT — cổng go-live của SuperPlump. Chạy TRƯỚC khi mở cửa cho người lạ.
Cách dùng:
  python3 scripts/preflight.py https://plump.example.vn \
      --owner-token <TOKEN_MỚI> --admin-key <KEY_MỚI> [--allow-http]
Exit 0 = được phép go-live. Exit 1 = CẤM MỞ CỬA, sửa mục ✗ trước."""
import argparse, json, sys, uuid, hashlib, hmac as hm
import requests

P, F = [], []
def check(name, ok, detail=""):
    (P if ok else F).append(name)
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if detail and not ok else ""))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base"); ap.add_argument("--owner-token"); ap.add_argument("--admin-key")
    ap.add_argument("--allow-http", action="store_true")
    a = ap.parse_args()
    B = a.base.rstrip("/")
    s = requests.Session(); s.verify = False
    requests.packages.urllib3.disable_warnings()

    print(f"== PREFLIGHT: {B}")
    # 1 · Sống & giao thức
    h = s.get(B + "/health", timeout=8)
    check("health ok", h.ok and h.json().get("ok") is True)
    check("HTTPS (hoặc --allow-http sau proxy)", B.startswith("https") or a.allow_http,
          "đang chạy HTTP trần")
    check("x-request-id header", bool(h.headers.get("x-request-id")))

    # 2 · Bề mặt DEV phải đóng
    check("POST /v1/dev/users đã đóng", s.post(B + "/v1/dev/users", json={}, timeout=8).status_code == 404)
    check("GET /v1/dev/mailbox đã đóng", s.get(B + "/v1/dev/mailbox", timeout=8).status_code == 404)
    check("GET /v1/dev/jwks đã đóng", s.get(B + "/v1/dev/jwks", timeout=8).status_code == 404)
    check("dev-uuid auth bị từ chối",
          s.get(B + "/v1/wallet", headers={"Authorization": "Bearer " + str(uuid.uuid4())}, timeout=8).status_code == 401)

    # 3 · Credential mặc định phải CHẾT
    check("owner token mặc định 'chaunacha' đã chết",
          s.post(B + "/v1/auth/login", json={"token": "chaunacha"}, timeout=8).status_code == 401)
    check("admin key mặc định 'plump-admin' đã chết",
          s.get(B + "/v1/admin/overview", headers={"x-admin-key": "plump-admin"}, timeout=8).status_code == 403)
    if a.owner_token:
        check("owner token MỚI khác mặc định", a.owner_token != "chaunacha")
        r = s.post(B + "/v1/auth/login", json={"token": a.owner_token}, timeout=8)
        jwt_owner = None
        if r.ok and r.json().get("mfa_required"):
            check("owner login (đang bật 2FA — tốt)", True); 
        else:
            check("owner token mới đăng nhập được", r.ok and r.json().get("role") == "owner")
            jwt_owner = r.json().get("jwt") if r.ok else None
        # 4 · Đường in tiền trực tiếp phải đóng
        if jwt_owner:
            t = s.post(B + "/v1/wallet/topups", headers={"Authorization": "Bearer " + jwt_owner},
                       json={"amount": 10000}, timeout=8)
            check("route tự nạp/mint Nara đã niêm phong (403 topup_disabled)",
                  t.status_code == 403 and t.json().get("title") == "topup_disabled")
    if a.admin_key:
        check("admin key mới hoạt động",
              s.get(B + "/v1/admin/overview", headers={"x-admin-key": a.admin_key}, timeout=8).ok)

    # 5 · Webhook phải đòi chữ ký
    body = json.dumps({"provider_ref": "preflight", "intent_id": str(uuid.uuid4())}).encode()
    bad = {"content-type": "application/json",
           "x-signature": hm.new(b"sai-secret", body, hashlib.sha256).hexdigest()}
    pay = s.post(B + "/v1/payments/webhook", data=body, headers=bad, timeout=8)
    check("payments webhook đã tắt hoàn toàn trong pilot",
          pay.status_code == 403 and pay.json().get("title") == "payments_disabled")
    ekyc = s.post(B + "/v1/kyc/webhook", data=body, headers=bad, timeout=8)
    check("KYC webhook đã tắt hoàn toàn trong pilot",
          ekyc.status_code == 403 and ekyc.json().get("title") == "kyc_disabled")

    # 6 · Pháp lý & quan sát
    check("/terms 200", s.get(B + "/terms", timeout=8).ok)
    check("/privacy 200", s.get(B + "/privacy", timeout=8).ok)
    m = s.get(B + "/metrics", timeout=8)
    check("/metrics sống", m.ok and "plump_http_requests_total" in m.text)
    check("SỔ CÁI KHỚP (ledger_mismatch = 0)", "plump_ledger_mismatch 0" in m.text)

    print(f"\n== KẾT LUẬN: {len(P)} ✓ · {len(F)} ✗ → " +
          ("ĐƯỢC PHÉP GO-LIVE 🚀" if not F else "CẤM MỞ CỬA — sửa các mục ✗"))
    sys.exit(0 if not F else 1)

if __name__ == "__main__":
    main()
