# PRIVACY PACK — Tuân thủ Luật BVDLCN 91/2025/QH15 (hiệu lực 1/1/2026) + NĐ 356/2025
## 1 · Bản đồ dữ liệu
| Dữ liệu | Bảng | Mục đích | Lưu ý |
|---|---|---|---|
| Danh tính (tên, handle) | plumpers | vận hành tài khoản | scrub được theo yêu cầu |
| eKYC ref (KHÔNG ảnh giấy tờ) | kyc_records.provider_ref | "cánh cửa tên thật" | Điều 29: cấm thu ảnh CCCD → chỉ mã tham chiếu VNeID/VNPT/FPT |
| Vị trí drop | drops.location | ghép việc gần | public LUÔN snap ~300m; exact chỉ 2 bên deal |
| Giao dịch | ledger_entries | kế toán | append-only, GIỮ khi user xóa (nghĩa vụ pháp lý) |
| Nội dung twin học | SoulFile (ngoài DB core) | bản thể số | cần consent `twin_training` |
## 2 · Consent (Điều 4 — đồng ý & rút lại)
Purposes: `location · marketing · twin_training · analytics · cross_border` → `POST/GET /v1/me/consents`. Cờ `pdpl.enforce_location_consent` bật gate ở tầng SQL. Mặc định hệ thống nghiêng về bảo vệ (mờ vị trí, không track).
## 3 · Quyền chủ thể dữ liệu ↔ Endpoint
`POST /v1/me/data-requests` kind = `access | delete | withdraw | restrict` → hàng đợi admin `GET/POST /v1/admin/data-requests/:id/process`. `delete` = quyền được lãng quên: scrub PII, giữ sổ tài chính.
## 4 · Sự cố 72 giờ (Điều 23.1)
`POST /v1/admin/incidents` → `authority_deadline = detected_at + 72h` tự sinh. Runbook: phát hiện → tạo incident → đánh giá phạm vi → báo cơ quan chuyên trách trước deadline → thông báo chủ thể → đóng hồ sơ.
## 5 · Xuyên biên giới
Chỉ khi có consent `cross_border` + hồ sơ ĐGTĐCDL. Mức phạt tối đa 5% doanh thu → mặc định giữ dữ liệu trong nước.
## 6 · DPO & Hồ sơ ĐGTĐ
SuperPlump xử lý dữ liệu nhạy cảm (vị trí, danh tính) → KHÔNG thuộc diện miễn 5 năm của startup: cần chỉ định nhân sự bảo vệ DLCN + lập hồ sơ đánh giá tác động trước pilot.
