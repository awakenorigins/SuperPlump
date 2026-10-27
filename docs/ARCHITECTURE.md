# ARCHITECTURE — SuperPlump

## Nguyên tắc lõi
**Không tin tầng trên.** Mọi luật (escrow, chuyển trạng thái, quyền, KYC, consent, mandate) sống trong hàm PL/pgSQL + ràng buộc DB. API chỉ là lớp dịch HTTP↔SQL; UI chỉ là cửa sổ. Gian lận phải bất khả thi ở tầng dữ liệu, không phải "được kiểm ở tầng code".

## Bất biến khóa bằng cấu trúc
- `ledger_entries`, `reviews`, `events`, `plump_points` — REVOKE UPDATE/DELETE (append-only).
- `wallets.balance` CHECK ≥ 0 · kế toán kép: mỗi lần chuyển = 2 dòng, Σ mỗi deal = 0.
- Một drop một deal sống: partial unique index.
- `accept_offer` khóa **cha→con** (drop trước, offer sau) — chống deadlock AB-BA.
- Vị trí: view công khai snap lưới ~300m; tọa độ thật chỉ qua hàm kiểm 2-bên-deal.

## Dòng tiền (một deal)
topup → **hold** (giá+phí thả vào escrow) → start → submit → confirm/auto → **settle** (net về người làm, phí về platform, escrow về 0). Tranh chấp: release / refund / split — nhánh nào cũng đưa escrow về 0.

## Danh tính & auth
regnick → token 13 ký tự (lưu sha256) → login → onboarding username + password (scrypt) → email/2FA thêm sau. Login bằng token HOẶC username+password. JWT mang jti (thu hồi được) + refresh rotation. Verify HS256 hoặc RS256/JWKS. Owner = role full quyền, token qua env.

## Bản thể số (twin)
SoulFile → thi Qualify (worker chấm 3 lớp) → được cấp hạng theo category → chủ ký **mandate** (phạm vi + trần giá + hạn, khóa Ed25519, privkey mã hóa KMS envelope) → twin ra chợ trong đúng mandate → nhận việc auto-start → worker gen draft (Fable 5) → chủ duyệt → nộp qua máy trạng thái chung. Mỗi đầu ra có **attestation ký số** verify được → sẵn sàng cho agent bên ngoài.

## Multi-instance
API stateless. Realtime: mỗi node LISTEN pg NOTIFY, event fan-out mọi node. Rate-limit: bảng `rate_limits` đếm chung. Worker: tiến trình riêng, `FOR UPDATE SKIP LOCKED` nên chạy nhiều bản không giẫm nhau.

## Sơ đồ thư mục
`db/` 12 migration (nguồn chân lý) · `api/server.js` HTTP + realtime · `api/worker*.js` job engine · `services/agents/` spec twin/Tiểu Tâm · `admin/` console · `prototype/` PWA demo · `tests/` 62 test 6 nhóm · `scripts/` load/soak/gen-secrets · `ops/` Caddy+alerts · `legal/` ToS+Privacy · `docs/` toàn bộ tài liệu.
