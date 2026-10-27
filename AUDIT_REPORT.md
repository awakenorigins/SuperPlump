# SUPERPLUMP V1.5 — BÁO CÁO AUDIT TOÀN HỆ (v8 · + PREFLIGHT & BÀN GIAO)
**Môi trường thật:** PostgreSQL 16.14 + PostGIS 3.4 · Node 22 (Express, ws, jsonwebtoken, zod, helmet, rate-limit) · pytest + psycopg2 + pyjwt + websocket-client · TypeScript strict
**Quy trình clean-room:** DROP DATABASE → migrate **001→015** từ số 0 · topology test: 2 API instance + worker tách tiến trình → boot API v2 (plumpers=0, worker + WebSocket bật) → chạy trọn bộ.

## KẾT QUẢ: `96/96 PASSED × 3 lượt` trên topology đa instance · SOAK PASS · npm 0 lỗ hổng
Static: /admin · /app · /manifest.json · /sw.js đều 200 · `node --check` sạch · TS strict sạch.

### Lớp 1 · Database core (10/10)
Kế toán kép Σ=0, két escrow về 0, `reconcile()` rỗng · race 10 luồng → đúng 1 deal · confirm×2 chặn · sai vai/đi tắt chặn · review mù bất biến · vị trí snap ~300m + exact chỉ 2 bên · dispute refund/split không rơi 1 đồng · auto-confirm 12h · event log đủ vòng đời · RLS ví ai nấy thấy.

### Lớp 2 · HTTP end-to-end (8/8)
Vòng đời trọn qua HTTP, ví +90.250 đúng · KYC gate 403 → duyệt → 201 · **Idempotency-Key: 2 POST cùng key = 1 deal** · map chỉ trả lưới mờ, người lạ xin tọa độ 403 · review mù qua API · dispute đóng băng → admin refund hồi nguyên · job auto-confirm · 401/403 đúng chỗ.

### Lớp 3 · Security + PDPL (9/9) — Luật 91/2025/QH15
| Test | Chứng minh |
|---|---|
| A1 jwt_auth_paths | JWT HS256 ký đúng vào được, sai secret 401, dev-uuid chỉ sống khi bật cờ |
| A2 security_headers | helmet: nosniff, ẩn x-powered-by |
| A3 validation | zod chặn dữ liệu bẩn ở cửa → 400 `validation_error` |
| A4 rate_limited | nạp lần 11 trong 1 phút → 429 |
| A5 consent_gate | bật cờ PDPL: thả drop vị trí chưa đồng ý → 403 `consent_required`; đồng ý → 201 |
| A6 right_to_be_forgotten | delete-request: scrub PII (`Đã xóa theo yêu cầu`), **sổ tiền giữ nguyên** (nghĩa vụ kế toán) |
| A7 ekyc_dieu_29 | eKYC provider (vneid/vnpt/fpt), **không lưu ảnh giấy tờ**, duyệt → verified |
| A8 idempotency_ttl | key cũ quá 48h bị job dọn sạch |
| A9 incident_72h | tạo sự cố → deadline báo cơ quan +72h tự sinh |

### Lớp 4 · Social + Agents (7/7)
| Test | Chứng minh |
|---|---|
| B1 deal_chat | chat neo deal, người lạ 403 |
| B2 dm_gated | **không DM lạnh**: chưa settle 403 `dm_requires_connection`, settle xong mở |
| B3 settle_triggers | trigger sau SETTLED tự sinh: kết nối + 2 khoảnh khắc + 🍑500/200 + thông báo (+read) + peach |
| B4 leaderboard | 3 kỳ day/week/month đọc từ điểm thật, tie-break theo hoạt động mới |
| B5+C twin_lifecycle | chưa Qualify→403 · thi→worker chấm→silver · **mandate thiếu/lệch phạm vi/vượt trần → 3 loại 403** · đúng mandate→ra chợ→accept auto IN_PROGRESS, energy −5 · worker draft (mock Fable 5) · **attestation Ed25519 verify true, giả mạo false** · duyệt→SUBMITTED→confirm→SETTLED, tiền về chủ +85.500 |
| B6 websocket | subscribe `deal:<id>` → transition đến trong <3s (pg LISTEN → ws) |
| C1 agent_ready | `/.well-known/superplump.json` + feed `superplump.drop.v1` (chỉ tọa độ mờ) + Signature-Agent ghi vết KYA-lite |

### Lỗi thật bắt được & fix trong audit
1. `GENERATED ... now()+72h` không immutable → chuyển DEFAULT lúc insert.
2. **Idempotency store async sau response** → race khi replay tức thì → thiết kế lại *claim-first* (INSERT ON CONFLICT chiếm key trước, request song song poll chờ kết quả).
3. BIGINT của node-pg trả string → ép kiểu ở profile.
4. Leaderboard hòa điểm không tie-break → thứ hạng bất định → thêm `MAX(created_at) DESC`.

### Bất biến khóa bằng cấu trúc
Ledger/reviews/events/plump_points REVOKE UPDATE·DELETE · balance ≥ 0 · một drop một deal sống · KYC gate + consent gate + mandate gate nằm TRONG hàm SQL · privkey mandate cột demo (**production: KMS/HSM**).

### Lớp 5 · Auth — regnick token 13 ký tự (6/6)
| Test | Chứng minh |
|---|---|
| AU1 token_format | Regnick cấp token đúng 13 ký tự chữ+số (bảng chữ bỏ I/L/O/0/1) · DB **chỉ lưu sha256**, không bản rõ |
| AU2 login_token | Token đúng → JWT 7 ngày dùng được ngay; token sai → 401 |
| AU3 username_rules | Đặt username một lần lúc onboarding · trùng → 409 `username_taken` · tên hệ thống (owner/admin/chaunacha…) → 409 `username_reserved` · đặt lần 2 → 409 `already_onboarded` |
| AU4 dual_login | Sau khi tạo password (scrypt+salt): **login bằng username+password HOẶC token 13 ký tự đều được** · sai pass 401 · pass ngắn bị zod chặn 400 |
| AU5 email_later | Email bổ sung sau qua PATCH /v1/me/settings · sai định dạng 400 · trùng 409 |
| AU6 owner_full_rights | Gõ token owner (`chaunacha` dev) → role `owner` → gọi **mọi route admin bằng JWT, không cần x-admin-key** · user thường 403 |

⚠️ **Owner token:** mặc định dev là `chaunacha` (theo spec), cấu hình qua env `OWNER_TOKEN`, server tự re-hash mỗi lần boot. **Bắt buộc đổi trước khi release** — token ngắn/dễ đoán ở production là cửa hậu.

### Lớp 6 · Auth hardening (8/8) — trả đủ 5 món nợ v1.2
| Test | Chứng minh |
|---|---|
| H1 lockout | 5 phát sai/15' theo tài khoản → phát 6 khóa **cả mật khẩu đúng** (429 + retry) · IP: 50/15' · prod: regnick 30/phút/IP |
| H2 logout | JWT mang jti gắn bảng sessions — logout xong token cũ chết ngay (`session_revoked`) |
| H3 refresh_rotation | /v1/auth/refresh: phiên mới sinh, **phiên cũ tự vô hiệu** — chống replay token cũ |
| H4 revoke_all | Owner đuổi mọi phiên của một user một phát; danh sách sessions xem được ai/ở đâu |
| H5 email_verify | Mã 6 số (chỉ lưu hash, 15'), gửi qua dev_outbox — seam thay mail provider thật; mã sai chặn |
| H6 forgot_reset | Quên mật khẩu qua **email đã verify**: reset xong pass cũ chết, pass mới sống, **mọi phiên bị thu hồi**; response chống dò tài khoản |
| H7 owner_reissue | Mất token 13 ký tự → xin recovery → owner cấp lại tay: token mới 13 ký tự sống, **token cũ + mọi phiên vô hiệu** |
| H8 owner_2fa | TOTP RFC6238 thuần crypto: bật 2FA → login `chaunacha` trả `mfa_required` (KHÔNG có jwt), mã sai 401, mã đúng mới ra JWT full quyền; mfa-token không xài thay JWT được |

### TRẬN AUDIT VẬN HÀNH (v1.4) — "chuẩn run" được tra tấn thật
**Tải (24 luồng, 350 req):** 190 req/s · 0 lỗi 5xx · p50/p95: map 45/61ms · accept 89/239ms · transition 75/168ms · **bất biến sổ cái DƯỚI TẢI**: reconcile lệch 0, ví âm 0, deal Σ≠0: 0.
**🔥 Bug production thật #1 — deadlock AB-BA:** race HTTP để lộ `accept_offer` khóa offer→drop trong khi winner giữ drop→void offers → chu trình chờ, Postgres giết bằng `deadlock detected` (phập phù theo timing — unit race 10 luồng từng pass 5+ lần vẫn không lộ). Fix: khóa CHA→CON (drop trước, offer sau) ở cả 002 & 007. Sau fix: **race ×6 vòng ×15 accept = (1 thắng, 14 conflict) tuyệt đối**.
**🔥 Bug production thật #2 — DB chết là server chết theo:** pool `error` không handler + route async không try/catch (Express 4 không tự đỡ). Fix 5 lớp: async wrapper toàn cục tại điểm đăng ký route, pool error-handler + connectionTimeout 3s, LISTEN tự nối lại, worker chống rơi, graceful shutdown. Probe sau fix: DB chết → **500 problem+json trong <3s, server sống**; DB hồi → **tự phục hồi không cần đụng tay**.
**Diễn tập backup–restore:** pg_dump 300K → restore 0 lỗi → 177 plumpers / 36 deals / 348 bút toán / escrow 315.000 **khớp từng đồng**, reconcile bản khôi phục = 0.
**Chuỗi cung ứng:** `npm audit` = **0 lỗ hổng**. Suite sau vá giáp còn nhanh gấp đôi (48/48 trong ~5s).
**Hạ tầng chạy thật mới thêm:** Dockerfile + docker-compose (migrate tự động, production-mode, secrets bắt buộc) + GitHub Actions CI (migrate → 48 test → load test mỗi push).

### CHIẾN DỊCH PRODUCTION v1.5 — 7 mặt trận, mỗi beat đều audit thật
**B1 TLS+Secrets:** HTTPS native khi có cert (probe self-signed PASS) · secrets đọc từ `*_FILE` (Docker secrets) — xoay admin key bằng file: key cũ 403, key file 200 · Caddyfile auto-TLS cho production.
**B2 Observability:** access-log JSON + `x-request-id` mọi response · `/metrics` Prometheus: histogram latency, requests theo route/status, **gauge tiền bạc** (`plump_ledger_mismatch`=0, escrow, jobs queued, ws clients) · `ops/alerts.yml`: LedgerMismatch=critical, ErrorRate, P95.
**B3 Multi-instance:** rate-limit store chuyển vào Postgres — test 6 lượt ở A + 4 ở B → lượt 11 bị 429 ở B (đếm CHUNG) · worker tách `api/worker.js` (A/B đều ENABLE_WORKER=0, exam vẫn xong) · **WebSocket đa node**: event sinh ở A tới client cắm ở B qua pg NOTIFY fan-out.
**B4 JWKS+KMS:** verify RS256 qua JWKS URL có cache + kid (token RSA ký đúng vào `/v1/me`, sửa 1 ký tự chữ ký → 401) · khóa mandate **envelope AES-256-GCM**: cột bản rõ = NULL, chỉ còn ciphertext, attestation vẫn verify.
**B5 Seam đối tác:** nạp tiền = intent + **webhook HMAC-SHA256, idempotent theo provider_ref** (replay → duplicate:true, ví cộng đúng MỘT lần; sai chữ ký 401) · eKYC callback ký HMAC tự duyệt verified · trang `/terms` `/privacy` tiếng Việt bám PDPL.
**B6 Trust & Safety:** từ cấm chặn tại SQL (422) · report → admin gỡ tin/treo tài khoản (treo là mọi hành động 403, phiên bị đuổi) · **radar thông đồng**: cùng cặp settle 4 deal/ngày → fraud_flag tự cắm · AI moderation trong worker (Fable 5 thật khi có key, mock khi không): tin bẩn tự gỡ trong <8s, tin sạch được duyệt · phanh velocity 30 tin/giờ.
**B7 Soak 75s @32 luồng:** 6463 vòng op (86/s) · **0 lỗi thật** · p95 746ms, trôi ×1.20 (ổn) · RAM +45MB (không rò) · **3005 deal settle — reconcile vẫn = 0, không một ví âm**. Vui: bản soak đầu "fail" vì phanh velocity cắn 1866 lần — tức phanh chống spam hoạt động thật.
**Bug bắt & diệt trong chiến dịch:** SQL notify moderation bị băm chuỗi → đầu độc hàng đợi (tin flagged chặn cả tin sạch) — sửa parameterized + xử theo lô 5.

### Beat cuối — Preflight & gói bàn giao
- **Preflight khởi động:** ở `NODE_ENV=production`, server **từ chối boot** nếu còn dev-uuid/OWNER_TOKEN mặc định/ADMIN_KEY yếu/JWT yếu không JWKS/MASTER_KEY trống/webhook secret yếu/thiếu TLS — kiểm thử: cấu hình sơ hở liệt kê đủ 8 lỗi & exit 1; cấu hình chuẩn lên xanh, dev-uuid bị chặn 401.
- **Bắt bug thật:** topupLimiter dùng IP trực tiếp không an toàn IPv6 → sửa bằng `ipKeyGenerator` helper.
- **Sinh secret production:** `scripts/gen-secrets.sh` → `.env.production` chmod 600.
- **Tài liệu bàn giao:** ARCHITECTURE · RUNBOOK (deploy/backup/playbook sự cố) · SECURITY · GO_LIVE_CHECKLIST · DPIA_TEMPLATE · README hub · Makefile · .gitignore.
- **62/62 vẫn xanh** sau khi thêm preflight.

### NHÓM · CHANNEL · STATUS · CẤP ĐỘ (v1.9 — 10/10 test mới)
| Test | Chứng minh |
|---|---|
| G1 group_chat | Tạo nhóm (invite code 8 ký tự), cả nhóm nhắn/đọc, người ngoài 403 |
| G2 connected_only | **Luật quen-qua-việc khắc vào nhóm**: thêm người lạ → 403 `member_not_connected` |
| G3 channel_readonly | Channel = kênh phát: owner đăng, member theo dõi **chỉ đọc** (403 khi đăng) |
| G4 discovery_code | Channel công khai lên danh bạ; channel kín vào bằng mã, mã sai 404 |
| G5 leave_rules | Member rời được (mất quyền đọc ngay); **owner không bỏ rơi nhóm** (409) |
| G6 location_msg | Gửi **VỊ TRÍ** (kind location), inbox hiện "📍 Vị trí" |
| G7 inbox_v2 | Nhóm hiện title + member_count + đếm chưa đọc riêng |
| G8 status_presence | Đăng **status 24h** → hiện trên `/v1/map/presence` kèm level + trang bị |
| G9 level_labor | **Cấp độ từ lao động**: 0 kèo Lv1, settle xong lên Lv2 (50+ = Lv5 Mận Kim Cương) |
| G10 code_privacy | Mã mời chỉ owner/admin thấy — member bị giấu |

**Demo UI (165 onclick audit sạch):** 🗺️ toggle **Bản đồ Mận ↔ Bản đồ thật** (phố xá, đường vàng, sông Sài Gòn, nhãn quận) · **7 mini Plumper đi lại trên map, màu + sóng aura theo cấp** (Lv4 vàng 1 vòng, Lv5 hồng-kim 2 vòng) · click mini → **sheet inspect kiểu game**: avatar ghép trang bị thật, badge cấp, status, **lưới trang bị 6 ô viền theo rarity**, đánh giá + lịch sử, nút Nhắn tin (mở DM luôn) & Tổ Mận · Chat: **nhóm có tên người gửi, channel khóa input "chỉ admin đăng"**, sheet ＋ gửi **ảnh/vị trí/🧧 tip 🍑200 ngay trong chat**, sheet Tạo nhóm/channel/tham gia bằng mã.

### HỆ NHẮN TIN THẬT (v1.8) — telegram-style giữa các Plumper (14/14)
| Test | Chứng minh |
|---|---|
| M1 real_accounts | Tài khoản THẬT (regnick→token→username+password), ví demo **seed 100k Nara + 100k Plump**, login lại bằng username+password bền |
| M2 dm_gated | **Không DM lạnh**: chưa quen → 403; quen qua deal SETTLED → mở; get-or-create **idempotent** |
| M3 two_way | Nhắn **HAI CHIỀU thật**: 3 tin qua lại, đúng thứ tự, đúng người gửi |
| M4 inbox_unread | Inbox + **đếm chưa đọc** + con trỏ đã đọc; người gửi không tự thấy chưa đọc |
| M5 reply_edit_revoke | Reply có preview tin gốc · sửa (chỉ chủ, ≤15') · **thu hồi** (body về NULL) · người khác không sửa được |
| M6 typing_attach | Đang gõ (TTL 6s) + gửi **ảnh/đính kèm** |
| M7 non_member | Người ngoài hội thoại KHÔNG đọc/gửi được (403) |
| M8 realtime_msg | **Tin bay qua WebSocket <3s** tới người đang mở hội thoại (pg NOTIFY→ws) |
| M9 realtime_badge | Badge inbox realtime tới kênh user của người nhận |
| M10 deal_conv | Chat trong deal: tự tạo hội thoại 2 bên |

**Farm Plump mở rộng (4/4):** khách thưởng sau deal (F1) · nhiệm vụ công ích cap ngày (F2) · giúp Plumper mới thưởng một lần (F3) · **thưởng bảng xếp hạng theo kỳ, chống cấp trùng** (F4). Nguồn Plump giờ: settle deal · thưởng khách · công ích · dìu người mới · top leaderboard — tất cả bằng lao động, không nạp được.

**Bug thật bắt trong beat này:** KYC gate chặn regnick chưa eKYC (đúng luật) · BIGINT unread trả string · **revoke set body+attachment NULL vi phạm CHECK → nới CHECK cho tin thu hồi** · leaderboard grant thiếu ORDER BY trong row_number.

**UI Tin nhắn trong demo (v1.8.1):** màn Inbox + Chat đầy đủ (bong bóng, đang gõ, chưa đọc, reply, thu hồi) — lối vào 💬 topbar bản đồ (badge) & PlumpLife. 150 onclick audit sạch.

**2 theme mới trong demo:** 🛸 "Tương Lai 2088" (siêu ngầu hologram tím-lam) + 🍭 "Kẹo Bông Mận" (cartoon pastel bo tròn) — đổi cả nền app qua data-theme. Ví demo seed 100k mỗi loại.

### HỆ VẬT PHẨM & TỔ MẬN (v1.7) — kiếm tiền mà không phản bội uy tín
**Nguyên tắc vàng khắc vào SQL:** đẹp mua bằng Nara, oai chỉ đổi bằng lao động — hai track không hoán đổi.
| Test | Chứng minh |
|---|---|
| I1 buy_nara | Mua đồ Nara = **bút toán kép** (user→platform, kind `purchase`), ví trừ đúng, **reconcile vẫn 0**, mua trùng chặn |
| I2 insufficient | Thiếu Nara / thiếu Plump → chặn đúng loại |
| I3 buy_plump | Đồ "oai nhẹ" mua bằng Plump — điểm farm từ deal, bút toán âm append-only |
| I4 slot_guard | Đội sai slot 400, đồ chưa sở hữu 403, đúng thì 200 |
| I5 room | Set slot phòng, khách xem `/plumpers/:id/room` thấy đúng |
| I6 milestone | Settle đủ mốc → **Chổi Vàng tự mọc trên kệ** (via=earned); đồ earned KHÔNG bán được (409) |
| I7 gift | Tặng phải **quen qua việc**, chỉ đồ nara-giftable, chuyển sở hữu sạch (gỡ cả equip/room) |
| I8 guestbook | Sổ khách chỉ ai **từng deal chung** mới viết; tự viết cho mình bị chặn |
| I9 prestige_decay | Aura 5★ đạt chuẩn thì thắp; **rating tụt là RỤNG + tự tháo khỏi người** — danh vọng có decay thật |
| I10 twin_skin | Skin twin mua được nhưng **nhãn AI khóa vĩnh viễn** |

**UI Tổ Mận (demo):** avatar "Mận nhân" ghép lớp SVG (thân/mặt/nón/vật-cầm-theo-nghề/aura), ngủ khi offline; phòng 2.5D với cửa sổ view Sài Gòn, kệ thành tựu tự mọc, góc twin gõ phím khi có job, sổ khách. Vào từ PlumpLife → 🏠 Tổ Mận. 141 onclick audit sạch, mọi handler có hàm.

### GO-LIVE KIT (v1.6) — phóng có cổng kiểm soát, không phóng bằng niềm tin
**🔥 Lỗ hổng go-live bắt được:** `/v1/wallet/topups` nạp thẳng = **máy in tiền miễn phí nếu lọt lên production** → đã niêm phong: prod trả 403 `use_payment_intent`, chỉ còn đường intent + webhook đối tác ký HMAC.
**Boot-guard (có sẵn trong server, 9 cổng):** production TỰ TỪ CHỐI KHỞI ĐỘNG nếu ALLOW_DEV_UUID bật, OWNER_TOKEN mặc định/ngắn <16, ADMIN_KEY yếu, JWT secret yếu mà không JWKS, thiếu MASTER_KEY, webhook secret dev, không TLS/proxy. Đã kiểm chứng: token 13 ký tự bị chê → nâng owner lên 26 ký tự (user thường vẫn 13 đúng spec regnick).
**`scripts/gen-secrets.sh`:** sinh trọn bộ secrets thật (.env.production, chmod 600) — owner token 26 ký tự cùng bảng chữ regnick.
**`scripts/preflight.py` — cổng go-live từ bên ngoài, 19 mục:** dev surface đóng · dev-uuid chết · `chaunacha`/`plump-admin` chết · owner/admin key mới sống · **route in-tiền niêm phong** · webhook chặn chữ ký sai · /terms /privacy · metrics + **sổ cái khớp**. Audit hai chiều: server dính đồ dev → **bắt 7 vi phạm, exit 1 (CẤM MỞ CỬA)**; server production sạch → **19 ✓ / 0 ✗ → ĐƯỢC PHÉP GO-LIVE**.
**`scripts/smoke.py` — đường tiền production thật:** regnick 2 người → eKYC (không ảnh giấy tờ) → **nạp 200.000 qua intent + webhook HMAC** → deal trọn vòng → executor +95.000, dropper −105.000 đúng từng đồng → `ledger_mismatch 0`. PASS.
**`scripts/backup.sh`** cron hàng ngày giữ 7 bản · **LAUNCH_RUNBOOK.md** 4 phase từ VPS trắng → live, kèm rollback + 72h incident.

### Còn lại — thuần chữ ký & hạ tầng bên ngoài
Ký đối tác trung gian thanh toán + eKYC (driver đã sẵn, chỉ đổi secret & URL) · domain + trỏ Caddy (config sẵn) · cloud KMS thay MASTER_KEY file · nộp hồ sơ DPIA (template sẵn trong docs/) + bổ nhiệm DPO · pen-test độc lập trước public.
