# SUPERPLUMP — BẢN ĐỒ ENDPOINT V1
### Hợp đồng API: mỗi hành động trên UI ↔ một endpoint, không lỗ hổng
*Chuẩn áp dụng (hấp thụ từ Zalando RESTful API Guidelines + Microsoft API Guidelines): tài nguyên-trung-tâm; chuyển trạng thái = `POST` sub-action; ID là chuỗi opaque; JSON `snake_case`, top-level là object; lỗi theo `application/problem+json` (RFC 7807); mọi POST đổi tiền/trạng thái bắt buộc header `Idempotency-Key`; phân trang cursor; version trong path `/v1`.*

---

## 0. Quy ước chung
- **Auth:** `Authorization: Bearer <jwt>` (Supabase). Public read không cần token.
- **Idempotency:** `Idempotency-Key: <uuid>` bắt buộc cho mọi POST tạo/chuyển trạng thái — retry an toàn tuyệt đối.
- **Lỗi:** `{ "type", "title", "status", "detail", "instance" }` — không bao giờ trả lỗi mù.
- **Phân trang:** `?cursor=<opaque>&limit=20` → `{ "items": [...], "next_cursor" }`.
- **Realtime:** kênh `map:<geohash5>` (drop mới/cập nhật), `deal:<id>` (trạng thái, chat), `plumper:<id>` (thông báo).

## 1. Danh tính & cánh cửa
| Hành động UI | Endpoint | Ghi chú |
|---|---|---|
| Nhập SĐT nhận OTP | `POST /v1/auth/otp` | rate-limit theo SĐT+IP |
| Nhập mã OTP | `POST /v1/auth/otp/verify` | trả JWT + hồ sơ |
| Nộp hồ sơ KYC | `POST /v1/kyc` (multipart: doc, selfie) | trạng thái `pending` |
| Xem trạng thái KYC | `GET /v1/kyc/status` | `none / pending / verified / rejected` |
| Sửa hồ sơ (tên, avatar) | `PATCH /v1/me` | |

## 2. Bản đồ & khám phá (public — "ô cửa sổ mở")
| Hành động UI | Endpoint | Ghi chú |
|---|---|---|
| Tải chấm trong viewport | `GET /v1/map/drops?bbox=&kinds=&cursor=` | **chỉ trả tọa độ đã snap ~300m** (`fuzzy_lat/fuzzy_lng`) — cột thật không bao giờ rời server trước khi LOCKED |
| Đếm nhịp sống | `GET /v1/map/stats?bbox=` | số việc mở, twin trực, deal hôm nay |
| Tìm kiếm | `GET /v1/search?q=&bbox=` | full-text title+desc+category |
| Mở chi tiết drop (share URL) | `GET /v1/drops/{drop_id}` | public; kèm `price_reference` (thống kê giá khu/loại từ event log) |
| Realtime chấm mới | subscribe `map:<geohash5>` | client chỉ sub các ô đang nhìn |

## 3. Thả & thương lượng (yêu cầu `verified`)
| Hành động UI | Endpoint | Ghi chú |
|---|---|---|
| Thả Plump | `POST /v1/drops` | validate; kind `local` bắt buộc point, `digital` không |
| Sửa / gỡ drop | `PATCH /v1/drops/{id}` · `POST /v1/drops/{id}/cancel` | chỉ khi chưa có deal active |
| Ngỏ lời (giá đầu) | `POST /v1/drops/{id}/offers` `{amount}` | mỗi offer = 1 điểm dữ liệu giá |
| Trả giá | `POST /v1/offers/{id}/counter` `{amount}` | round++ |
| Chấp nhận giá | `POST /v1/offers/{id}/accept` | **transaction**: kiểm drop open (FOR UPDATE) → tạo deal → `escrow_hold` → drop=matched. Partial unique index chặn double-accept |
| Từ chối | `POST /v1/offers/{id}/reject` | |
| Danh sách lời ngỏ cho drop của tôi | `GET /v1/drops/{id}/offers` | owner only |
| Chat thương lượng/deal | `POST /v1/deals/{id}/messages` · `GET …/messages?cursor=` | realtime `deal:<id>` |

## 4. Vòng đời Deal (máy trạng thái — mọi transition là POST sub-action, server-side)
| Hành động UI | Endpoint | Chuyển trạng thái |
|---|---|---|
| (tự động khi accept) | — | `LOCKED` + tiền vào két |
| Bắt đầu làm | `POST /v1/deals/{id}/start` | `LOCKED → IN_PROGRESS`; mở tọa độ thật cho đúng 2 bên |
| Nộp bằng chứng | `POST /v1/deals/{id}/proofs` (multipart) rồi `POST /v1/deals/{id}/submit` | `IN_PROGRESS → SUBMITTED`; hẹn giờ auto-confirm |
| Xác nhận hoàn thành | `POST /v1/deals/{id}/confirm` | `SUBMITTED → CONFIRMED → SETTLED`; `escrow_release` (phí 5% mỗi bên) |
| (im lặng quá hạn) | worker `auto_confirm` | như confirm — bảo vệ người làm |
| Hủy đồng thuận | `POST /v1/deals/{id}/cancel` | trước LOCKED tự do; sau LOCKED cần cả hai → `escrow_refund` |
| Mở tranh chấp | `POST /v1/deals/{id}/disputes` | `→ DISPUTED`, đóng băng két |
| Xem deal | `GET /v1/deals/{id}` | trả state + timeline events |

## 5. Đánh giá mù & minh bạch
| Hành động UI | Endpoint | Ghi chú |
|---|---|---|
| Gửi đánh giá | `POST /v1/deals/{id}/reviews` `{rating,text}` | chỉ khi SETTLED; **immutable** (không có PUT/DELETE) |
| Đọc đánh giá | `GET /v1/deals/{id}/reviews` | server chỉ trả khi cả hai đã nộp hoặc hết cửa sổ |
| Hồ sơ công khai 2 chiều | `GET /v1/plumpers/{id}/profile` | stats render từ `events` (replay được) |
| Sổ hành trình | `GET /v1/plumpers/{id}/timeline?cursor=` | event log công khai |
| Giá tham khảo | `GET /v1/market/price-reference?category=&geocell=` | thống kê từ deal SETTLED — bàn tay vô hình |

## 6. Ví & két (Plump Coin V1; rail tiền thật cắm sau)
| Hành động UI | Endpoint | Ghi chú |
|---|---|---|
| Xem ví | `GET /v1/wallet` | `{available, held}` — luôn = Σ ledger |
| Sổ bút toán | `GET /v1/wallet/entries?cursor=` | append-only |
| Nạp Coin | `POST /v1/wallet/topups` → webhook `POST /v1/webhooks/bank` | đối soát tự động, entry `topup` |
| (nội bộ, không expose) | `escrow_hold/release/refund` | Postgres functions SECURITY DEFINER — nơi duy nhất ghi ledger |

## 7. AI Plumper
| Hành động UI | Endpoint | Ghi chú |
|---|---|---|
| Sinh twin | `POST /v1/twins` | giới hạn theo hạng Mận |
| Nạp mẫu / quy tắc giọng | `POST /v1/twins/{id}/samples` · `PATCH /v1/twins/{id}/soul` | version SoulFile |
| Chat vườn ươm | `POST /v1/twins/{id}/sandbox/messages` | server gọi LLM với SoulFile |
| Sửa bài → mẫu mới | `POST /v1/twins/{id}/samples` `{source:"correction"}` | |
| Vào phòng thi | `POST /v1/twins/{id}/exams` `{category}` | chạy server-side, khóa soul_version |
| Xem kết quả thi | `GET /v1/exam-runs/{id}` | điểm 3 lớp; đậu → `qualifications` |
| Bài chờ duyệt | `GET /v1/twin-jobs?status=awaiting_review` | |
| Duyệt / sửa / từ chối draft | `POST /v1/twin-jobs/{id}/approve` · `/revise` · `/reject` | approve → submit deal; revise/reject → correction sample |
| Cho twin ăn | `POST /v1/twins/{id}/energy` `{coins}` | entry `energy_buy`; chặn nhận việc khi ⚡ cạn |
| Tạm dừng / bật twin | `POST /v1/twins/{id}/pause` · `/resume` | |

## 8. Thông báo & hệ thống
| Hành động UI | Endpoint |
|---|---|
| Danh sách thông báo | `GET /v1/notifications?cursor=` · đánh dấu đọc `POST /v1/notifications/{id}/read` |
| Đổi ngôn ngữ | `PATCH /v1/me` `{locale}` |
| Web push | `POST /v1/push/subscriptions` |

## 9. Admin (console riêng, RBAC)
| Hành động | Endpoint |
|---|---|
| Hàng đợi KYC | `GET /v1/admin/kyc?status=pending` · `POST /v1/admin/kyc/{id}/approve|reject` |
| Xử tranh chấp | `GET /v1/admin/disputes` · `POST /v1/admin/disputes/{id}/resolve` `{outcome: release|refund|split}` — ghi events + ledger |
| Đối soát nạp | `GET /v1/admin/topups?status=pending` |
| Quản lý đề thi / category | CRUD `/v1/admin/exam-tasks`, `/v1/admin/categories` |

---

## 10. Bất biến toàn hệ (test tự động gác cổng)
1. Không endpoint public nào trả tọa độ chính xác trước `LOCKED` (contract test từng payload).
2. Σ bút toán mỗi deal = 0 khi `SETTLED` (property test).
3. Không transition nào gọi được từ client ngoài danh sách §4 (thử gọi tắt → 409/403).
4. Replay `events` → hồ sơ, rank, price-reference khớp 100%.
5. Mọi POST có `Idempotency-Key` gọi 2 lần → hiệu ứng 1 lần.

---
## V1.1 · ENDPOINTS MỚI (đã hiện thực + test)
**A · PDPL:** POST /v1/kyc/ekyc · GET /v1/kyc/status · POST|GET /v1/me/consents · POST|GET /v1/me/data-requests · GET /v1/admin/data-requests · POST /v1/admin/data-requests/{id}/process · POST|GET /v1/admin/incidents · POST /v1/admin/jobs/cleanup-idempotency
**B · Social/Twin:** POST|GET /v1/deals/{id}/messages · POST|GET /v1/dm/{peer}/messages · GET /v1/notifications · POST /v1/notifications/{id}/read · GET /v1/plumpers/{id}/profile · POST /v1/moments/{id}/peach · GET /v1/leaderboard?period= · POST /v1/twins · GET /v1/twins/{id} · POST /v1/twins/{id}/exams · GET /v1/exam-runs/{id} · POST /v1/drops/{id}/twin-offers · GET /v1/twin-jobs?status= · POST /v1/twin-jobs/{id}/approve|reject
**C · Mandate/Agent:** POST /v1/twins/{id}/mandates · POST /v1/mandates/{id}/revoke · GET /v1/twin-jobs/{id}/attestation · POST /v1/agent/verify · GET /.well-known/superplump.json · GET /v1/agent/drops
**Realtime:** WS /realtime?channel=map|deal:{id}|user:{id}

**AUTH (v1.2):** POST /v1/auth/register → {token 13 ký tự, hiện một lần} · POST /v1/auth/login {token} | {username,password} → {jwt,role,onboarded} · POST /v1/auth/username · POST /v1/auth/password · GET /v1/me · PATCH /v1/me/settings {email} · Admin nhận JWT role=owner thay x-admin-key

**AUTH HARDENING (v1.3):** POST /v1/auth/logout · POST /v1/auth/refresh · GET /v1/me/sessions · POST /v1/me/sessions/{jti}/revoke · POST /v1/me/email/verify-request · POST /v1/me/email/verify · POST /v1/auth/forgot · POST /v1/auth/reset · POST /v1/auth/recovery · GET /v1/admin/recovery · POST /v1/admin/recovery/{id}/reissue-token · POST /v1/admin/plumpers/{id}/revoke-all · POST /v1/auth/2fa/setup|confirm|disable · POST /v1/auth/mfa

**PRODUCTION (v1.5):** GET /metrics · POST /v1/wallet/topups/intent · POST /v1/payments/webhook (HMAC) · POST /v1/kyc/webhook (HMAC) · POST /v1/reports · GET /v1/admin/reports · POST /v1/admin/reports/{id}/action · POST /v1/admin/plumpers/{id}/suspend|unsuspend · GET /v1/admin/fraud-flags · GET /terms · /privacy · DEV: /v1/dev/jwks · /v1/dev/sign-rs256

**VẬT PHẨM (v1.7):** GET /v1/shop · POST /v1/shop/{id}/buy · GET /v1/me/inventory · POST /v1/me/equip · POST /v1/me/room · POST /v1/me/inventory/{id}/gift · GET /v1/plumpers/{id}/room · POST /v1/plumpers/{id}/guestbook · POST /v1/admin/jobs/refresh-prestige

**NHẮN TIN (v1.8):** GET /v1/inbox · GET /v1/inbox/unread-count · POST /v1/conversations/dm · POST /v1/deals/{id}/conversation · GET|POST /v1/conversations/{id}/messages · POST /v1/conversations/{id}/read · POST /v1/conversations/{id}/typing · PATCH /v1/messages/{id} · POST /v1/messages/{id}/revoke · WS channel=conversation:{id}
**FARM PLUMP (v1.8):** POST /v1/deals/{id}/tip · POST /v1/civic/{kind}/claim · POST /v1/help-newbie/{id} · POST /v1/admin/jobs/grant-leaderboard/{period}

**NHÓM/CHANNEL/MAP (v1.9):** POST /v1/conversations/group · POST /v1/conversations/channel · GET /v1/channels · POST /v1/conversations/{id}/join · POST /v1/conversations/join-by-code · POST /v1/conversations/{id}/leave · POST /v1/conversations/{id}/members · GET /v1/conversations/{id} · POST /v1/me/status · GET /v1/map/presence

**CẤP BẬC (Beat 1 · v2.2):** GET /v1/me/level · profile công khai +level/+level_score · SQL: level_score(), plump_level(), level_detail(), median_price_for_kind()

**TWIN CÓ CẤP (Beat 2 · v2.3):** GET /v1/twins/:id +twin_level/+raw_level/+owner_level/+capped_by_owner · SQL: twin_score(), twin_raw_level(), twin_level(), twin_level_detail()

**VAN NĂNG LƯỢNG (Beat 3 · v2.4):** GET /v1/twins/:id +energy/+energy_cap/+job_cost · POST /v1/twins/:id/energy/refill · SQL: twin_energy_cap(), twin_job_cost(), apply_energy_regen(), refill_energy(), spend_nara()

**SLOT TWIN (Beat 4 · v2.5):** GET /v1/me/twin-slots · POST /v1/twins/:id/maintenance/pay · SQL: twin_slot_limit(), twin_open_fee(), twin_maintenance_fee(), create_twin(), pay_maintenance(), sweep_unpaid_twins()

**TWIN CHỈ VIỆC THẬT (Beat 5 · v2.6):** POST /v1/drops +origin · SQL: _twin_real_work_only(), _twin_escrow_backed(), twin_score() (siết origin/escrow/giá)

**TWIN-TO-TWIN (Beat 6 · v2.7):** POST/GET /v1/twin-market · POST /v1/twin-market/:id/take · /deals/:id/approve · /deals/:id/settle · SQL: post_twin_market(), take_twin_market(), approve_twin_market(), settle_twin_market(), twin_market_can_post()

**GIÁ GỢI Ý (Beat 7 · v2.8):** GET /v1/price-hint · SQL: price_hint() (phân vị theo khu/giờ/loại, chỉ việc thật, không ép)
