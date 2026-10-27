# SUPERPLUMP — KẾ HOẠCH XÂY DỰNG V1
### Breakdown kỹ thuật để build chính xác, đảm bảo hoạt động thật sự
*Phạm vi: Web-first (PWA) · Bản đồ TP.HCM · Có AI Plumper ngay trong V1 · Backend thật, dữ liệu bền vững*

---

## 0. TRIẾT LÝ KỸ THUẬT — 5 luật để "thật sự hoạt động"

1. **Client không bao giờ được tin.** Mọi chuyển trạng thái (nhận việc, khóa tiền, xác nhận, trao tiền) chạy server-side trong transaction. Client chỉ gửi ý định.
2. **Tiền đi qua sổ kế toán kép.** Mọi đồng vào/ra là 2 bút toán đối ứng trong ledger append-only. Bất biến: tổng bút toán mỗi deal = 0 khi tất toán. Có test tự động cho bất biến này.
3. **Sự thật nằm trong event log.** Mọi thay đổi trạng thái ghi vào bảng `events` (append-only, không UPDATE/DELETE). Hồ sơ minh bạch, PlumpRank, thống kê giá — tất cả tính lại được từ events (có test replay).
4. **Đổi da, không đổi xương.** Tọa độ luôn là lat/lng thật + Web Mercator. Lớp render, rail thanh toán, nhà cung cấp eKYC, nhà cung cấp LLM — đều là interface cắm-rút được.
5. **Riêng tư là ràng buộc ở tầng dữ liệu.** Vị trí chính xác không bao giờ xuất hiện trong bất kỳ API response nào trước khi deal khóa giữa đúng 2 người — enforce bằng RLS + view, có contract test.

---

## 1. STACK & LÝ DO CHỌN

| Tầng | Chọn | Lý do | Điểm cắm-rút (seam) |
|---|---|---|---|
| Frontend | **Next.js 14 (App Router) + TypeScript, PWA** | Web-first, share URL từng drop, cài như app | — |
| Bản đồ | **MapLibre GL (style "mận" tùy biến) + lớp PixiJS overlay** | MapLibre lo pan/zoom/projection chuẩn; style JSON làm Sài Gòn cách điệu; Pixi vẽ chấm sáng động 60fps | Đổi style JSON → map thật; hoặc đổi hẳn sang Mapbox |
| Backend | **Supabase: Postgres + PostGIS + Realtime + Auth + Storage + Edge Functions** | Một nền tảng đủ: geo query, realtime kênh, OTP, RLS | Postgres chuẩn → tự host được khi lớn |
| Vector/AI | **pgvector (SoulFile samples) + Claude API (engine twin + giám khảo)** | Twin = prompt + RAG, không train model riêng | Đổi LLM provider sau 1 interface |
| Hàng đợi | **pg-boss (job queue trên Postgres)** | Twin làm việc nền, timer auto-confirm | Đổi sang Redis/QStash khi scale |
| i18n | **next-intl, string key từ ngày 1** | Vi mặc định; en/zh/hi là file dịch | — |
| Hạ tầng | **Vercel + Supabase Cloud** | Deploy phút, iterate hằng ngày | — |
| Analytics | **PostHog** | Funnel + KPI pilot | — |

**Quyết định quan trọng nhất về bản đồ:** không tự vẽ 100% canvas từ đầu. Dùng geometry thật (OSM/MapLibre) + style cách điệu + landmark vẽ tay dạng sprite + lớp Pixi cho hiệu ứng sống. Được cả hai: cảm giác game *và* bộ xương tọa độ chuẩn để sau này "đổi da" miễn phí.

**Quyết định quan trọng nhất về tiền:** build **động cơ escrow nội bộ chuẩn kế toán kép ngay từ V1** (ví Plump Coin), còn rail tiền thật (nạp/rút qua cổng thanh toán/đối tác có giấy phép) là module cắm sau. Logic giữ–trao–hoàn là thật và được test kỹ; nguồn tiền là thứ thay được. *(Checkpoint pháp lý trước khi mở nạp/rút tiền thật — cần tư vấn luật, đây là nút thắt duy nhất ngoài code.)*

---

## 2. DATA MODEL — 18 bảng lõi

### 2.1 Danh tính & niềm tin
- **plumpers**: id (auth uid), handle, display_name, avatar_url, kyc_status (`none|pending|verified`), locale, created_at
- **kyc_records**: plumper_id, doc_url, selfie_url, status, reviewed_by, reviewed_at, note
- **plump_rank_events** (append-only): plumper_id, delta, reason, deal_id, created_at → rank tính từ đây
- **man_tiers** (config): tier, min_rank, tên hạng Mận, quyền lợi (số twin tối đa, mức tự động…)

### 2.2 Chợ & giao dịch
- **categories**: id, name_key (i18n), kind (`physical|digital`), twin_allowed (bool)
- **drops** (tin đăng): id, owner_id, category_id, title, description, price_offer, time_window (tstzrange), **location geography(Point)** *(cột nhạy cảm — không bao giờ select trực tiếp)*, geocell (geohash6 precompute), status (`open|matched|closed|cancelled|expired`), requires_proof, created_at, expires_at
- **offers** (thương lượng): id, drop_id, from_id, amount, round, status (`pending|accepted|rejected|countered`), created_at → *mỗi offer là một điểm dữ liệu giá cho thị trường*
- **deals** (giao kèo): id, drop_id, dropper_id, executor_id, executor_kind (`human|twin`), twin_id?, agreed_price, state (xem máy trạng thái §3), locked_at, submitted_at, confirmed_at, settled_at
- **messages**: deal_id, sender_id, body, created_at (chat theo deal)
- **proofs**: deal_id, uploader_id, media_url, note, created_at
- **reviews**: deal_id, author_id, target_id, rating (1–5), text, submitted_at — *chỉ hiển thị khi cả hai đã nộp hoặc hết cửa sổ; không có UPDATE/DELETE policy*
- **disputes**: deal_id, opened_by, reason, status, resolution (`release|refund|split`), resolved_by, resolved_at

### 2.3 Tiền
- **wallets**: plumper_id, available, held *(số dư luôn suy ra được từ ledger — có job đối soát)*
- **ledger_entries** (append-only, kế toán kép): id, deal_id?, wallet_id, kind (`topup|hold|release|refund|fee_dropper|fee_executor|energy_buy|withdraw`), amount (+/−), created_at
- Ba hàm Postgres SECURITY DEFINER, atomic: `escrow_hold(deal)`, `escrow_release(deal)`, `escrow_refund(deal)` — nơi DUY NHẤT được ghi ledger

### 2.4 Bản thể số
- **twins**: id, owner_id, name, avatar_url, status (`draft|sandbox|live|paused|suspended`), autonomy (`supervised|semi|auto`), energy, concurrency_cap, created_at
- **soul_files**: twin_id, version, system_prompt, style_rules (jsonb), locked_at *(bản đậu Qualify bị khóa version)*
- **soul_samples**: twin_id, content, embedding (pgvector), source (`upload|correction|completed_job`)
- **exams / exam_tasks / exam_runs**: ngân hàng đề theo category (template có tham số sinh biến thể), exam_runs lưu bài làm + auto_score + judge_score + human_review
- **qualifications**: twin_id, category_id, level (`bronze|silver|gold`), soul_version, exam_run_id, granted_at, revoked_at
- **twin_job_runs**: deal_id, twin_id, tokens_in/out, cost, draft_output, approved_by?, created_at
- **energy_ledger**: twin_id, delta, reason

### 2.5 Sự thật
- **events** (append-only): id, aggregate_type, aggregate_id, event_type, payload jsonb, actor_id, created_at — *xương sống minh bạch; view công khai của hồ sơ 2 chiều đọc từ đây*

---

## 3. MÁY TRẠNG THÁI DEAL — trái tim của hệ thống

```
OPEN(drop) ──offer accepted──▶ LOCKED ──▶ IN_PROGRESS ──▶ SUBMITTED ──▶ CONFIRMED ──▶ SETTLED
                                 │              │              │             ▲            │
                                 │              │              └─timeout────┘(auto-confirm│
                                 │              │                sau X giờ im lặng)       ▼
                                 └──────────────┴────────── DISPUTED ──admin──▶ RESOLVED (release/refund/split)
   (mọi trạng thái trước LOCKED: hủy tự do · sau LOCKED: hủy = đồng thuận hoặc dispute)
```

**Luật chuyển trạng thái (server-side, atomic):**
- `accept_offer`: transaction gồm — kiểm tra drop còn `open` (SELECT FOR UPDATE) → tạo deal → `escrow_hold` → drop = `matched`. **Partial unique index**: chỉ 1 deal active/drop → chặn double-accept tận gốc.
- `submit`: bắt buộc có proof nếu `requires_proof`.
- `confirm` → `escrow_release` (trừ phí, chia đều 2 phía) → mở cửa sổ review mù.
- **Auto-confirm**: dropper im lặng quá X giờ sau SUBMITTED → hệ thống confirm (bảo vệ người làm). Timer chạy bằng pg-boss.
- `dispute`: đóng băng tiền, đẩy vào hàng đợi admin; resolution ghi events + ledger tương ứng.
- Twin executor: LOCKED → enqueue job cho worker; `supervised` thì output là draft chờ chủ duyệt trước khi `submit`.

**Test bắt buộc cho §3:** unit test từng cạnh chuyển; property test "không tồn tại đường đi ra trạng thái không hợp lệ"; race test 50 client cùng accept 1 drop → đúng 1 thắng; idempotency test gọi `release` 2 lần → chỉ ghi 1 lần.

---

## 4. BẢN ĐỒ SỐNG — spec kỹ thuật

- **Kiến trúc lớp:** MapLibre (nền style mận, ranh quận/sông/đường từ OSM) → sprite landmark vẽ tay (Bến Thành, Landmark 81, Nhà thờ Đức Bà…) đặt đúng tọa độ → **PixiJS overlay**: chấm mận đập nhịp, ripple khi drop mới, vệt sáng bay khi deal LOCKED/SETTLED, quầng aura riêng cho twin.
- **Môi trường sống:** biến style theo giờ địa phương (ngày/đêm); OpenWeather API → hạt mưa trên overlay khi HCM mưa thật.
- **Realtime theo ô:** kênh Supabase Realtime đặt tên theo geohash5; client subscribe đúng các ô trong viewport; server broadcast `drop_created|drop_updated|deal_settled`.
- **Mật độ:** clustering theo zoom (supercluster); budget 800 sprite động/khung hình trên mobile; LOD: xa = quầng nhiệt quận, gần = chấm.
- **Riêng tư:** API trả `ST_SnapToGrid(location, ~300m)`; cột location thật chỉ đọc được qua policy "2 bên của deal LOCKED". Contract test: mọi endpoint public không chứa tọa độ 6 số lẻ.
- **Chế độ cửa sổ mở:** toàn bộ map view + chi tiết drop đọc được không cần đăng nhập; mỗi drop có URL SEO-able để share Zalo/FB.

---

## 5. AI PLUMPER — spec kỹ thuật

**Pipeline vòng đời:**
1. **Create**: form kỹ năng + upload mẫu → chunk + embed vào `soul_samples`; soul_file v1.
2. **Sandbox**: chat chủ↔twin (server gọi Claude với system prompt = soul_file + top-k samples); nút "sửa bài" → correction thành sample mới.
3. **Qualify** (server-side, chủ không can thiệp): chọn category → sinh đề từ template có tham số → twin làm bằng đúng soul_version production → chấm 3 lớp: rule checks → LLM-judge (rubric, temperature 0, model khác vai) → hàng đợi người duyệt cho bài sát ngưỡng + audit ngẫu nhiên. Đậu → `qualifications` + khóa soul_version. Rớt → cooldown + feedback.
4. **Execute**: worker pg-boss nhận job khi deal LOCKED có executor twin → chạy → `supervised`: draft chờ duyệt (SLA nhắc chủ); `auto`: nộp thẳng. Mỗi run trừ **energy** (mua bằng Plump Coin → cover chi phí API + chống spam + sink kinh tế).
5. **Grow**: việc SETTLED + rating tốt → output thành sample mới; rating category tụt ngưỡng → thu hồi Qualify, buộc thi lại.

**Hàng rào:** twin chỉ nhận category `kind=digital` & `twin_allowed=true`; danh sách cấm (pháp lý/y tế/gian lận học thuật); moderation pass trên output; concurrency_cap theo autonomy; số twin/chủ theo hạng Mận; nhãn AI + tên chủ hiển thị ở mọi nơi twin xuất hiện.

**V1 mở 2 hạng mục:** Dịch Anh–Việt, Viết content. (Xử lý bảng tính = V1.1.)

---

## 6. KYC, PHÂN QUYỀN & CHỐNG ABUSE

- **V1 pilot**: OTP số điện thoại (Supabase Auth) + upload CCCD + selfie → hàng đợi admin duyệt thủ công → `verified`. **V2**: tích hợp eKYC (VNPT/FPT) sau interface `KycProvider`.
- **RLS gate**: INSERT vào drops/offers/twins(live) yêu cầu `kyc_status='verified'`. Xem map: public.
- **Chống abuse V1**: rate limit tạo drop/offer theo user+IP; unique số điện thoại; giới hạn deal đồng thời theo hạng Mận; ảnh proof có EXIF timestamp check nhẹ; report + shadow-flag.

---

## 7. LỘ TRÌNH 12 TUẦN — milestone kèm Definition of Done

| # | Tuần | Milestone | Nội dung chính | DoD — "chạy thật" nghĩa là |
|---|---|---|---|---|
| M0 | 0–1 | **Nền móng** | Monorepo + CI, Supabase, schema §2 + RLS, bảng events, design tokens, i18n skeleton, auth OTP | Migrate sạch từ 0; RLS test pass; đăng nhập OTP trên mobile thật |
| M1 | 2–3 | **Bản đồ sống** | Style mận MapLibre + Pixi dots + clustering + realtime geohash + chế độ xem không login | 2 thiết bị thấy drop của nhau <1s; 60fps @500 dots; vị trí luôn mờ |
| M2 | 3–4 | **Drop & thương lượng** | Tạo drop (KYC gate), offer/counter chip UI, tạo deal, chat theo deal | E2E: thả → mặc cả 3 vòng → chốt (chưa tiền) |
| M3 | 5–6 | **Escrow & vòng đời** | Wallet + ledger kép + 3 hàm escrow atomic, máy trạng thái đủ, proof, confirm + auto-confirm, phí chia đôi | Property test ledger=0; race test double-accept; settle đúng phí từng xu |
| M4 | 6–7 | **Minh bạch & PlumpLife** | Review mù (rule hiển thị), hồ sơ công khai 2 chiều từ events, PlumpRank v1, hạng Mận, view "giá gần đây theo loại/khu" | Không đọc được review đối phương trước khi nộp; replay events = đúng số liệu hồ sơ |
| M5 | 8–10 | **AI Plumper** | Twin create + SoulFile + sandbox + Qualify 2 hạng mục + supervised execution + energy | 1 twin thi đậu thật → nhận việc thật → chủ duyệt → settle → review, toàn trình E2E |
| M6 | 10–11 | **Trọng tài & Admin** | Admin console: KYC queue, dispute resolve, quản lý category/đề thi; flow dispute; moderation | 1 dispute xử lý end-to-end, tiền đi đúng resolution |
| M7 | 12 | **Cứng hóa & Pilot-ready** | k6 load test, audit RLS, rate limit, PWA polish, PostHog funnel, landing + share URL, seed pilot | k6: 1.000 viewer + 100 drop/phút ổn; Lighthouse PWA ≥90; checklist pilot ký |

**Pilot (tuần 13–14):** việc tại chỗ ở 1 phường/1 campus + việc số phủ toàn quốc (twin là dân cư đầu tiên). KPI sống còn: % drop có offer trong 24h · time-to-first-offer · tỉ lệ settle · tỉ lệ dispute · D7 retention · tỉ lệ twin đậu Qualify.

*Ước lượng cho 1 dev full-time + AI hỗ trợ code; 2 dev thì chạy song song M1‖M2 và M4‖M5, rút còn ~9 tuần.*

---

## 8. RỦI RO KỸ THUẬT & ĐỐI SÁCH

| Rủi ro | Đối sách đã thiết kế |
|---|---|
| Double-accept / race tiền | Partial unique index + SELECT FOR UPDATE + idempotency key; race test trong CI |
| Lộ vị trí thật | Cột location cách ly bằng RLS + view snap; contract test mọi payload |
| Chi phí Claude API phình | Energy trả bằng Coin định giá theo token thật; cache; cap concurrency |
| Realtime fanout đắt | Kênh theo geohash, chỉ subscribe viewport; throttle broadcast |
| Map lag trên máy yếu | Pixi budget + LOD + tắt hiệu ứng mưa ở low-power |
| Gian lận thi Qualify | Thi server-side, đề tham số hóa, khóa soul_version, audit người thật |
| Nạp/rút tiền thật (pháp lý) | V1 chỉ Coin nội bộ; rail thật cắm sau qua đối tác có phép — checkpoint luật trước khi mở |
| Ledger lệch số | Job đối soát đêm: wallet = Σledger; lệch → alert + freeze |

---

## 9. TIÊU CHÍ NGHIỆM THU TỔNG (V1 được gọi là "hoạt động thật sự" khi)

1. Golden path người↔người và người↔twin chạy E2E trên thiết bị thật, tiền (Coin) đi đúng từng bút toán.
2. Toàn bộ chuyển trạng thái chỉ thực hiện được qua server; thử gọi tắt từ client đều bị chặn (test).
3. Tắt server render/replay lại từ `events` → hồ sơ, rank, thống kê giá khớp 100%.
4. Không một API nào trả tọa độ chính xác trước LOCKED (contract test xanh).
5. k6 đạt tải mục tiêu; không mất realtime event ở 100 drop/phút.
6. Một người lạ cầm điện thoại: mở link → hiểu map → xem một drop → (KYC) → thả một drop trong <3 phút không cần hướng dẫn.
