# SUPERPLUMP — Chợ thời gian tự do (backend production-grade)

Chợ nơi người thật **và bản thể số (AI, engine `claude-fable-5`)** cùng nhận việc, thanh toán qua két tạm giữ, đánh giá hai chiều mù, trên nền **giá tự do hai bên tự quyết** và **sổ giao dịch minh bạch** — hai bất biến lõi của SuperPlump.

## Trạng thái: sẵn sàng pilot · chưa "đang production"
Phần mềm đã qua tra tấn thật (62 test đa-instance, soak 3005 deal sổ cái khớp, sống sót DB chết, backup khôi phục nguyên vẹn, 0 lỗ hổng). Bật dòng tiền thật cần thêm hợp đồng trung gian thanh toán + eKYC + hồ sơ PDPL — xem **docs/GO_LIVE_CHECKLIST.md**.

## Chạy thử 1 lệnh
```bash
./run.sh        # DB + migrate 001→012 + boot + 62 test
```
App demo `:8386/app` · Admin `/admin` · Metrics `/metrics` · Realtime `ws://…/realtime?channel=map`

## Deploy thật
```bash
./scripts/gen-secrets.sh .env.production
docker compose --env-file .env.production up -d --build   # caddy + 2×api + worker + postgis
```
Production preflight sẽ chặn boot nếu secret còn yếu. Chi tiết: **docs/RUNBOOK.md**.

## Bản đồ tài liệu
| File | Nội dung |
|---|---|
| `docs/ARCHITECTURE.md` | Nguyên tắc lõi, bất biến, dòng tiền, multi-instance |
| `docs/RUNBOOK.md` | Vận hành, deploy, backup, playbook sự cố |
| `docs/SECURITY.md` | Mô hình phòng thủ nhiều lớp |
| `docs/GO_LIVE_CHECKLIST.md` | Checklist ra mắt (kỹ thuật + pháp lý) |
| `docs/PRIVACY_PACK.md` + `docs/DPIA_TEMPLATE.md` | Tuân thủ Luật 91/2025 + khung DPIA |
| `docs/SUPERPLUMP_Endpoint_Map_V1.md` | Toàn bộ endpoint (v1→v1.5) |
| `docs/SUPERPLUMP_Blueprint_Y_Tuong_V2.md` | Tầm nhìn sản phẩm |
| `docs/SUPERPLUMP_Ke_Hoach_Build_V1.md` | Kế hoạch 12 tuần |
| `docs/SUPERPLUMP_Wireframes_V1.html` | 26 màn wireframe |
| `AUDIT_REPORT.md` · `CHANGELOG.md` | Báo cáo audit v7 · lịch sử phiên bản |
| `legal/TERMS.vi.md` · `legal/PRIVACY.vi.md` | ToS + Chính sách riêng tư (nháp) |

## Cấu trúc mã
`db/` 12 migration (nguồn chân lý) · `api/` server + worker · `services/agents/` twin/Tiểu Tâm (Fable 5) · `admin/` console · `prototype/` PWA · `tests/` 62 test · `scripts/` load/soak/gen-secrets · `ops/` Caddy+alerts.

## Đăng nhập
Regnick → **token 13 ký tự** (hiện một lần) → login → đặt username + password → email/2FA thêm sau. Owner: token qua env `OWNER_TOKEN` — full quyền, bật được 2FA.
