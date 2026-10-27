# CHANGELOG
## v2.8.1 — Demo: Widget giá gợi ý (Beat 7) · 🎉 FINAL
- Màn Cấp bậc thêm 💡 Giá gợi ý thị trường: chọn loại việc → hiện Thấp/Điển hình/Cao + cỡ mẫu + phạm vi (khu+giờ/khu/toàn quốc), kèm câu "nền tảng KHÔNG đặt giá, bạn tự quyết". Test browser 3/3.
## v2.8.0 — BEAT 7: Giá gợi ý tinh tế (chiếu đèn, KHÔNG ép) — 150 test · 🎉 HOÀN THÀNH 7 BEAT
- **Migration 022:** price_hint(category, kind, lng, lat) trả khoảng phân vị p25/median/p75 + cỡ mẫu + phạm vi. Nền tảng KHÔNG đặt giá — chỉ soi sáng "khu này giờ này thường bao nhiêu".
- **Chiếu đèn theo phạm vi hẹp→rộng:** cùng khu+giờ (±3h, 2km) → cùng khu → toàn quốc, chọn phạm vi hẹp nhất đủ mẫu (min 5). Dưới ngưỡng → "chưa đủ dữ liệu", không bịa.
- **Chỉ tính việc THẬT:** origin='client', giá ≥ sàn tuyệt đối, trong 90 ngày. Civic/dưới-sàn KHÔNG kéo gợi ý (test chứng minh).
- **KHÔNG ép:** test đăng giá gấp 10 lần gợi ý VÀ giá bèo — cả hai đều được (giá tự do tuyệt đối giữ nguyên). Gợi ý kèm câu "chỉ là tham khảo — bạn tự quyết giá".
- API: GET /v1/price-hint?category=&kind=&lng=&lat=. Drop detail vẫn giữ price_reference (tương thích).
- Audit: 7/7 test giá gợi ý + 149/150 toàn đội hình (1 flaky worker), clean-room 001→022 × 2 DB-sạch.

### 🏁 TỔNG KẾT 7 BEAT (v2.2→v2.8)
- B1 cấp bậc chất lượng + chống cày 3 lớp · B2 twin có cấp chặn trần chủ (Ph.án B) · B3 van năng lượng · B4 slot twin + phí duy trì · B5 twin chỉ ăn việc thật · B6 twin-to-twin (chủ duyệt lần đầu) · B7 giá gợi ý.
- 22 migration · 150 test · mỗi beat clean-room 001→N × nhiều lượt DB-sạch, chỉ 1 flaky worker-timing không liên quan.
## v2.7.1 — Demo: Chợ Twin-to-Twin (Beat 6)
- Màn 💞 Chợ Twin-to-Twin (vào từ Twin): Lv<5 thấy khoá, Lv5 thấy danh sách việc twin đăng với badge phân biệt "✓ Cặp tin cậy tự duyệt" vs "⚠️ Lần đầu cần duyệt". Thuê twin cặp tin cậy → tự làm ngay; lần đầu → chờ duyệt. Ghi chú hai chủ cùng có lợi.
- Test browser 5/5: gate Lv5, badge đúng, thuê rời chợ ✓.
## v2.7.0 — BEAT 6: Twin-to-Twin (chợ việc số giữa các twin) — 143 test
- **Migration 021:** tầng kinh tế agent-to-agent. Twin A (chủ Lv5) đăng việc số → twin B nhận → hai chủ cùng có lợi (chủ nhận +Plump tiền công, chủ đăng được việc hoàn thành).
- **BƯỚC 1 thận trọng:** lần đầu mỗi cặp chủ giao dịch → CẦN CHỦ ĐĂNG DUYỆT (PENDING_APPROVAL). Duyệt xong ghi cặp tin cậy → lần sau TỰ ĐỘNG. Đi chậm vì agent tiêu tiền tự động không giám sát là chỗ dễ cháy.
- **3 bảng:** twin_market_drops, twin_market_deals (PENDING_APPROVAL→APPROVED→SETTLED / REJECTED), twin_market_trusted_pairs.
- Taker twin phải qua MỌI guard việc (qualified + mandate + energy + không treo phí). Chặn self-dealing (2 twin cùng chủ). Chủ đăng thiếu Plump → chặn nhận. Từ chối → việc mở lại.
- Thanh toán Plump hai chiều, sổ minh bạch 2 phía (giữ 2 bất biến). Chỉ Lv5 mở (thang cấp Beat 1).
- API: POST /v1/twin-market · GET /v1/twin-market · POST /v1/twin-market/:id/take · /deals/:id/approve · /deals/:id/settle.
- Audit: 9/9 test twin-to-twin + 142/143 toàn đội hình (1 flaky worker), clean-room 001→021 × 2 DB-sạch.
## v2.6.1 — Demo: ghi chú "Twin chỉ ăn việc thật" (Beat 5)
- Màn Twin thêm khối minh bạch: twin chỉ nhận việc khách thật đăng & trả qua ký quỹ (≥10k), không farm việc công ích/tự tạo/của chính chủ — giữ nội tệ khỏi lạm phát.
## v2.6.0 — BEAT 5: Twin chỉ ăn việc thật (van chống lạm phát #2 — CỐT LÕI) — 134 test
- **Migration 020:** twin CHỈ kiếm tiền & lên cấp từ VIỆC THẬT. Số twin nhiều tới đâu, tiền vẫn bị chặn bởi NHU CẦU THẬT.
- **Cột drops.origin** ('client'|'civic'|'self_generated'). Twin từ chối offer nếu: origin≠client · giá < ngưỡng thật (10k) · người đăng là chính chủ twin (self-dealing, lớp 2 sau cannot_offer_own_drop).
- **twin_score siết:** chỉ tính deal origin='client' + hold_amount>0 (escrow thật) + giá≥ngưỡng → farm civic/tự-tạo/không-escrow KHÔNG lên cấp twin (test đục DB chứng minh score=0).
- Guard _twin_real_work_only + _twin_escrow_backed. API drop nhận origin (mặc định client).
- Vì sao cốt lõi: đây là van chặn "quân đoàn twin tự bơm tiền cho nhau". Twin muốn kiếm phải có khách THẬT trả tiền THẬT cho việc số có đầu ra THẬT.
- Audit: 8/8 test việc-thật + 133/134 toàn đội hình (1 flaky worker), clean-room 001→020 × 2 DB-sạch.
## v2.5.1 — Demo: Quản lý slot twin khớp Beat 4
- Màn Twin thêm khu 🎰 Slot Twin: số slot đang dùng / trần theo cấp, nút mở twin mới hiện phí tăng dần (twin 2 free, 3:50k, 4:150k...), chặn khi đủ slot (cần lên cấp). Trừ Nara đúng khi mở. Ghi chú van chống lạm phát.
- Test browser 6/6: Lv4→3 slot, twin 3 phí 50k, mở trừ đúng, đầy slot chặn ✓.
## v2.5.0 — BEAT 4: Slot twin theo cấp + phí duy trì tăng dần (chống lạm phát #3) — 126 test
- **Migration 019:** số slot twin theo cấp chủ (Lv1-2:1, Lv3:2, Lv4:3, Lv5:5). Phí MỞ twin thứ n tăng dần (twin 1-2 free, 3:50k, 4:150k, 5:400k Nara). Phí DUY TRÌ mỗi 30 ngày theo slot (twin 3:20k, 4:50k, 5:120k).
- **Van xả lạm phát:** nuôi nhiều twin không free → chủ phải cân "có đáng không". Cũng là điểm doanh thu (bán slot bằng Nara).
- Twin quá hạn phí → treo (suspended_unpaid) → KHÔNG nhận việc; đóng phí thì hết treo. sweep_unpaid_twins() worker quét định kỳ.
- create_twin() kiểm slot + thu phí; guard _twin_can_work chặn twin treo/xoá ngay khi offer.
- API: GET /v1/me/twin-slots (active/limit/next_open_fee) · POST /v1/twins/:id/maintenance/pay. Slot nới khi chủ lên cấp.
- **Bug bắt được:** thêm mapping insufficient_nara→402 làm vỡ test cũ vốn kỳ vọng 409 (mã này đã có nghĩa 409 sẵn). Đã bỏ mapping trùng. Bài học: kiểm error code đã tồn tại trước khi thêm.
- Cũng xác nhận: lỗi "core/ledger" khi chạy 2 lượt liên tiếp là do tích luỹ trạng thái, KHÔNG phải regression — clean-room đúng là mỗi lượt DB mới. 125/126 (1 flaky worker).
## v2.4.1 — Demo: Van năng lượng khớp Beat 3
- Màn Twin: energy cap ĐỘNG theo cấp chủ (Lv4→110), chi phí việc theo cấp twin (hiện "mỗi việc tốn 8⚡"), 3 nút nạp (◈ Mua đầy / ✨ Nhặt +8 / 🎉 Event +25) + ghi chú 5★ hoàn 15⚡ & regen 2⚡/giờ. Công thức JS khớp backend.
- Test browser 8/8: cap 110, cost 8, mua trừ (need×2000) Nara, không vượt cap ✓.
## v2.4.0 — BEAT 3: Van năng lượng (chống lạm phát #1) — 118 test
- **Migration 018:** energy có TRẦN theo cấp chủ (50 + 20×(cấp-1): Lv1→50, Lv5→130); chi phí việc GIẢM theo cấp twin (Lv1→10, Lv5→4) — twin giỏi hiệu suất cao.
- **4 nguồn nạp hợp lệ:** mua bằng Nara (nạp đầy tới cap, giá (cap-cur)×2000/⚡) · nhặt map (+8, free) · việc khách chấm **5★ hoàn 15⚡** (thưởng chất lượng) · event (+25). Regen thụ động 2⚡/giờ (có trần).
- Hết energy → twin KHÔNG nhận việc (twin_no_energy). Việc trừ đúng twin_job_cost. 5★ mới hoàn (3★ không). Refill không vượt cap.
- API: GET /v1/twins/:id thêm energy/energy_cap/job_cost (áp regen khi đọc) · POST /v1/twins/:id/energy/refill {source:buy|gather|event}.
- **Bug bắt được khi build:** migration 018 DROP constraint kind của ledger_entries rồi ADD lại nhưng QUÊN 'purchase' (thêm ở 013) → mua đồ vỡ. Đã gộp đủ mọi kind cũ + mới. Bài học: khi động vào constraint đã bị migration trước sửa, phải gộp tất cả giá trị.
- Audit: 10/10 test energy + 117/118 toàn đội hình (1 flaky worker-timing không liên quan), clean-room 001→018 × 3 lượt.
## v2.3.1 — Demo: Twin có cấp + chỉ báo chặn trần (khớp Beat 2)
- Màn Bản thể số: badge **Cấp Twin** (Lv + tên + điểm), và **ô cảnh báo chặn trần** — nếu twin raw cao hơn cấp chủ thì báo bị chặn ở cấp chủ; nếu chưa chạm thì báo xanh. Công thức JS twinScore = jobs×(rating/5)×√distinct + twinLevel = min(raw, owner) khớp backend.
- Test browser: score 12.61 → raw Lv3; hạ chủ về Lv1 → twin bị kéo về Lv1 (trần Phương án B sống) ✓.
## v2.3.0 — BEAT 2: Twin có cấp, chặn trần bởi cấp chủ (Phương án B) — 108 test
- **Migration 017:** `twin_level = MIN(twin_raw_level, plump_level(chủ))`. Twin không bao giờ giỏi hơn cấp chủ → giữ con người ở trung tâm.
- **twin_score** = số việc twin (approved+SETTLED+executor_kind=twin) × (điểm khách chấm/5) × √(khách khác nhau, cap 15). Cùng triết lý chất lượng như Plumper nhưng tiers thấp hơn (việc số nhỏ, nhiều).
- **twin_raw_level**: cấp thô theo điểm; **twin_level**: cấp thật sau khi chặn trần. API GET /v1/twins/:id thêm twin_level, raw_level, owner_level, capped_by_owner, level_score, rated_jobs.
- BẤT BIẾN cốt lõi (test SQL trực tiếp): twin_level == min(raw, owner_level); capped == (raw > owner). Chủ Lv1 → twin bị kéo về Lv1 bất kể raw.
- Twin lên cấp qua điểm khách chấm (test luồng thật: 8 việc 5★ → raw Lv3+); việc dối 2★ không lên cấp cao.
- Audit: 5/5 test twin + 108/108 toàn đội hình (clean-room 001→017, đa instance).
## v2.2.1 — Demo: màn Cấp bậc (phản chiếu công thức Beat 1)
- **🏅 Màn Cấp bậc** (vào từ PlumpLife): badge Lv + tên (Mầm Mận→Mận Kim Cương), thanh tiến độ tới cấp sau, 3 ô điểm thành phần (kèo hợp lệ · điểm TB · khách khác nhau), **hiện công thức sống** score = validDeals × (rating/5) × √distinct, ghi chú chống cày (kèo giá thấp không tính, chỉ khách khác nhau), thang 5 cấp kèo quyền Twin mở khoá (Lv3 đề xuất · Lv4 mandate · Lv5 twin-to-twin).
- Công thức JS khớp chính xác backend (test browser: 11×4.8/5×√9 = 31.68 → Lv4 ✓).
## v2.2.0 — BEAT 1: Cấp bậc Plumper có trọng số chất lượng + chống cày (103 test)
- **Migration 016:** thay plump_level "đếm deal" bằng `level_score = f(kèo_hợp_lệ × ĐG/5 × √đa_dạng_khách)`.
- **CHỐNG CÀY 3 lớp:** (1) chỉ tính khách KHÁC NHAU (diversity_cap chặn cày qua nhiều acc phụ); (2) kèo giá bất thường thấp (< 30% median loại đó HOẶC < sàn tuyệt đối 10k) không tính điểm cấp, chỉ ân hạn 'grace' kèo đầu cho người mới; (3) **median chỉ tính trên kèo ≥ sàn tuyệt đối** → diệt lỗ hổng tự-đầu-độc-median bằng cách cày hàng loạt kèo 1.000đ.
- **Chất lượng thắng số lượng** (test chứng minh): 5 kèo 5★ áp đảo 5 kèo 2★; 6 khách khác nhau > 6 lần cùng 1 khách; 30 kèo giá 1k → score 2.0, vẫn Lv1.
- API: GET /v1/me/level (score, valid_deals, distinct_clients, avg_rating, to_next) · profile công khai +level +level_score.
- Tiers hiệu chỉnh: 5 kèo thật 5★ → Lv3 · ~15 đa dạng → Lv4 · ~40 → Lv5. Tất cả ngưỡng ở config['leveling'], chỉnh được.
- Audit: 7/7 test cấp bậc + 103/103 toàn đội hình (clean-room 001→016, đa instance).
## v2.1.0 — Map vô tận ×5 + Popup mở quà + Tặng trong chat + Loa server
- **Map ×5** (WORLD 3.2→7.0) + **INFINITY WRAP trục X**: camX modulo chiều rộng thế giới, vẽ 2 bản giáp biên liền mạch, toạ độ chạm wrap theo — kéo hoài không tới mép, qua biên hiện lại mặt bên kia. Y vẫn kẹp biên. (Test browser thật: camX 2725→195 khi qua biên ✓)
- **Popup mở quà**: hộp 🎁 rung 3 nhịp rồi bung (boxPop), tia sáng xoay, **spark bay số lượng theo độ hiếm**; Nara hiện số + "Túi [độ hiếm]"; item hiện tên + badge + **thẻ info (loại/độ hiếm/mô tả)**. Nhặt ✨🎁 trên map là popup tự mở.
- **Loa chúc mừng toàn server** (#serverFeed top màn): 4 cấp màu Thường/Hiếm💙/Sử Thi💜/Huyền Thoại👑 — legend có glow đập + đứng lâu hơn. Túi Nara nhỏ (common) không loa cho đỡ spam; server còn giả lập người khác mở quà cho sinh động.
- **Tặng trong chat**: nút ＋ → ◈ Tặng Nara (1k–20k) / 🎁 Tặng vật phẩm (chọn từ túi, chỉ đồ giftable) → trừ ví/rời túi, bong bóng quà vàng, người nhận tự cảm ơn.
- Audit browser thật 8/8 ✓ · 0 lỗi console.
## v2.0.2 — Map KÉO & ZOOM chạy thật (test bằng trình duyệt thật, không đoán)
Tự test như user bằng Playwright (Chromium, viewport iPhone, has_touch) — lôi ra 3 bug thật mà audit syntax không thấy:
1. **camX/camY = NaN**: khởi tạo `camX=WW()*0.30` chạy khi `W` còn undefined → NaN đóng băng camera vĩnh viễn. Fix: init camera trong resize() khi W đã có.
2. **#splash nuốt toàn bộ chạm**: class `.hide` chỉ set opacity/visibility, splash vẫn phủ toàn màn với pointer-events:auto ở z-index 60 → chặn sạch kéo/zoom/tap trên map. Fix: `.hide` thêm `pointer-events:none!important` + `display:none` sau fade.
3. **Nút zoom bị Tiểu Tâm orb che**: dời #zoomCtl lên bottom 260 thoát khỏi tamOrb.
- **Thêm ZOOM đầy đủ**: pinch 2 ngón (giữ tâm), con lăn chuột, nút ＋/－/⊙ reset — tất cả giữ điểm focal cố định.
- Kết quả test thật: kéo 185px ✓ · nút zoom in/out ✓ · wheel ✓ · pinch tới 2.6× ✓ · reset về 1.0 ✓ · đổi bản đồ thật ✓ · kéo trong bản đồ thật ✓ · 0 lỗi console.
- Kèm prototype/browser_test.py để tái kiểm mọi lần sau.
## v2.0.1 — Fix kéo map trên mobile + Phòng thay đồ Mận Nhân
- **Fix kéo map không di chuyển**: canvas thiếu `touch-action:none` nên trình duyệt mobile giành cử chỉ vuốt → pointermove bị pointercancel giết. Thêm touch-action:none + pointercancel reset + preventDefault khi kéo — pan mượt trên iOS/Telegram webview.
- **🧍 Màn Mận Nhân** (vào từ PlumpLife hoặc nút trong Tổ Mận): chibi preview to trên bệ sáng · **lưới Trang bị 6 ô tương tác** — chạm ô xoay vòng đồ (Đầu/Tay/Aura/Khung/Ghim map/Skin twin), chạm tiếp để tháo, viền rarity; **Aura khóa 🔒 tới khi có kèo đầu** (lao động mới mở) · **Trang phục & Style** (skin/outfit/pet/xe) dùng chung wardrobeRows với sheet Trang trí — đổi ở đâu preview cũng nhảy theo · khung vàng frame hiện quanh chibi.
## v2.0.0 — THẾ GIỚI MẬN: map ×10 kéo được + loot + chibi avatar
- **Fix pill đổi map**: bị display:none chờ show('map') mà lúc khởi động không ai gọi → giờ hiện mặc định góc trái dưới ("🗺️ Xem bản đồ thật" ↔ "🌌 Về Đêm Mận").
- **Map ×10 (WORLD=3.2 mỗi chiều)**: camera kéo pan mượt (pointer capture, clamp biên), mở drop tự pan tới nơi.
- **18 kiến trúc Sài Gòn** (Nhà thờ Đức Bà, Bến Thành, Landmark 81, Cầu Ánh Sao, chợ nổi, Thảo Cầm Viên…) + **5 event sống** (Hội chợ Mận, Giờ Vàng ×2, Boss Mận khu phố, Sinh nhật khu, Lễ hội đèn nước) — tap ra mô tả; đèn lồng dọc sông.
- **Loot khám phá**: ✨ Nara (500–3.000) + 🎁 túi mù (mở ra item Shop ngẫu nhiên) rơi rải khắp thế giới — **kéo map quét ngang là lượm luôn**, tap cũng lượm; tự mọc lại. Plumper siêng kéo map = siêng có quà.
- **Kèo CỦA BẠN dấu hiệu riêng**: vòng vàng + vòng hồng gạch đứt + nhãn "🍑 CỦA BẠN".
- **＋ Kết bạn** trong bảng info Plumper (⏳ chờ quen qua việc — giữ triết lý).
- **CHIBI AVATAR toàn thân** (kiến trúc layer kiểu DiceBear/dress-up): 4 skin gradient, 4 trang phục (Áo dài/Hoodie/Vest/Pijama — thay là đổi dáng), 5 pet nhún nhảy, 5 xe (ngồi lên là đổi tư thế, có ☁️ mây bay) — tủ đồ đầy đủ trong "✦ Trang trí"; phòng + bảng info Plumper đều dùng chibi; 3 mini trên map mặc đồ riêng.
## v1.9.2 — Mổ tận gốc lỗi sheet (từ screenshot thực máy #2)
- **Nguyên nhân gốc:** 3 sheet mới (Gửi kèm / Info Plumper / Trang trí Tổ Mận) dùng thẳng class `.sheet` (tấm card KHÔNG có trạng thái ẩn) + class `sheetcard` không tồn tại + đặt ngoài khung `#app` → hiện vĩnh viễn từ lúc load, xếp chồng cuối trang, ✕ bấm vô nghĩa.
- **Fix:** dựng lại đúng kiến trúc gốc `sheet-wrap` (ẩn mặc định) + `scrim` chạm-là-tắt + `.sheet` card, đặt trong khung app cạnh notiSheet. Gỡ override `.sheet{z-index}` từng đè sheet gốc, gỡ listener backdrop thừa lạc trong openChat, trả `position:relative` cho locmap.
- Audit: 11/11 mục ✓ (kiến trúc, vị trí trong khung, không class bịa, HTML cân, 168 onclick đủ hàm, 2 script syntax sạch).
## v1.9.1 — UX overhaul từ review thực tế trên máy thật (2 screenshot)
- **Đổi map**: bỏ icon câm, thay pill có nhãn "🗺️ Xem bản đồ thật / 🌌 Về Đêm Mận" nổi góc trái bản đồ.
- **Chuẩn Telegram**: "Tạo / Tham gia" chuyển từ sheet nổi → **màn con trong Tin nhắn** (✏️ ở header Inbox, back chuẩn stack).
- **Sheet fix trọn bộ**: CSS .sheethead/.x (nút ✕ tròn 36px bấm được thật) · **chạm nền tối để đóng** mọi sheet · z-index 320 đè trên mọi pill · pill Twin/livepill/orb **tự ẩn khi sheet mở** (hết cảnh đè lên bảng info Plumper).
- Tạo nhóm/channel/join xong tự rời màn con và mở thẳng chat.
## v1.9.0 — Nhóm/Channel + Map sống + Cấp độ (96 test)
- **Migration 015:** conversations mở rộng group/channel (role owner/admin/member, invite_code, is_public) · join/leave/add-members với luật quen-qua-việc · post_message v2 chặn member đăng channel · inbox v2 (title, member_count, icon đính kèm) · attachment 'location' · plumper_status 24h · plump_level (5 bậc từ deal SETTLED).
- **API mới:** POST /v1/conversations/group|channel · GET /v1/channels · /join · /join-by-code · /leave · /members · GET /v1/conversations/{id} · POST /v1/me/status · GET /v1/map/presence.
- **Demo:** bản đồ thật toggle, mini Plumper theo cấp độ + inspect trang bị kiểu game, chat nhóm/channel/ảnh/vị trí/tip.
- Fix: zod thiếu 'location', member_count BIGINT.
## v1.8.1 — UI Tin nhắn trong demo (vá thiếu sót: backend có, demo chưa có màn)
- Màn **Inbox**: danh sách hội thoại + tin cuối + pill chưa đọc + chú thích "không DM lạnh".
- Màn **Chat**: bong bóng 2 chiều, **đang gõ…**, reply có preview tin gốc, **thu hồi** (hiện "(đã thu hồi)"), mốc thời gian, auto-scroll.
- Lối vào: nút **💬 (badge đỏ số chưa đọc)** trên topbar bản đồ + PlumpLife → Tin nhắn.
- Gửi tin → bên kia "đang gõ" ~1.4s rồi trả lời; nếu đang ở màn khác thì badge tự tăng. 150 onclick audit sạch.
## v1.8.0 — Nhắn tin thật (telegram-style) + farm mở rộng (86 test, +18)
- **Hệ nhắn tin đầy đủ** (migration 014): conversations (dm/deal) · members có read cursor · chat_messages (reply/edit/revoke/đính kèm) · typing · inbox + đếm chưa đọc · realtime từng tin qua WebSocket (kênh conversation:{id} + badge user:{id}). Giữ "không DM lạnh": mở DM cần đã kết nối.
- API: /v1/inbox(+unread-count) · /v1/conversations/dm · /v1/deals/{id}/conversation · GET|POST /v1/conversations/{id}/messages · /read · /typing · PATCH /v1/messages/{id} · /revoke.
- **Farm Plump mở rộng:** tip sau deal · civic tasks (cap ngày) · help-newbie (một lần) · grant-leaderboard theo kỳ (chống trùng). 
- **Ví demo seed 100k Nara + 100k Plump** mỗi tài khoản (chỉ DEV).
- **2 theme mới**: "Tương Lai 2088" (cyber) + "Kẹo Bông Mận" (candy) trong demo.
- Fix: revoke CHECK constraint, BIGINT unread coercion, leaderboard row_number ORDER BY.
## v1.7.0 — Hệ vật phẩm & Tổ Mận (72 test, +10 item tests)
- Migration 013: catalog 24 vật phẩm, inventory/equipped/room_slots/guestbook · buy_item (Nara→ledger kép kind purchase / Plump→điểm âm) · equip/room slot guards · gift một chiều gate connection · guestbook gate deal · mốc lao động tự cấp (Chổi Vàng) · **aura 5★ có decay: refresh_prestige grant+revoke+auto-unequip**.
- API: /v1/shop, /v1/me/inventory|equip|room, /v1/me/inventory/:id/gift, /v1/plumpers/:id/room, /v1/plumpers/:id/guestbook, /v1/admin/jobs/refresh-prestige.
- Demo UI: màn Tổ Mận — avatar ghép lớp SVG + phòng 2.5D + kệ thành tựu + góc twin + sổ khách.
- Nguyên tắc vàng: đẹp mua bằng Nara, oai chỉ farm bằng lao động; đồ soulbound (né NĐ 52). Doc: docs/ITEM_DESIGN_V1.md.
## v1.6.0 — Go-Live Kit (preflight 19 gates + smoke tiền thật PASS)
- **Niêm phong máy in tiền:** /v1/wallet/topups chỉ còn ở dev; production bắt buộc intent + webhook đối tác.
- gen-secrets.sh (owner token 26 ký tự) · preflight.py 19 cổng (audit 2 chiều: chặn server bẩn 7✗, thả server sạch 19✓) · smoke.py golden-path tiền thật qua webhook HMAC · backup.sh cron giữ 7 bản · LAUNCH_RUNBOOK.md 4 phase.
- Compose: TRUST_PROXY_TLS khai báo Caddy gánh TLS. Boot-guard 9 cổng kiểm chứng hoạt động.
## v1.5.0 — Chiến dịch Production 7 mặt trận (62 test đa-instance + soak PASS)
B1 TLS native + secrets *_FILE + Caddyfile · B2 /metrics Prometheus (gauge sổ cái!) + access-log JSON + request-id + alerts.yml · B3 rate-limit store Postgres (đếm chung N instance) + worker tách tiến trình + WS đa node qua pg NOTIFY · B4 JWKS RS256 + KMS envelope khóa mandate · B5 payment intent + webhook HMAC idempotent + eKYC callback + /terms /privacy · B6 banned words + reports + suspend + fraud radar cặp + AI moderation (Fable 5/mock) + velocity brake · B7 soak 75s: 3005 settle, 0 lỗi, sổ cái khớp tuyệt đối · compose topology proxy+2api+worker · CI chạy đủ đội hình.
## v1.4.0 — Ops-readiness: trận audit vận hành
- Load test 190 req/s 0 lỗi + bất biến sổ cái dưới tải · race HTTP ×6 vòng chuẩn tuyệt đối.
- **Fix deadlock AB-BA** trong accept_offer (khóa cha→con) — bug thật do load test HTTP phát hiện.
- **Fix crash khi DB chết**: async wrapper toàn cục, pool error-handler + fail-fast 3s, LISTEN tự nối lại, worker guard, graceful shutdown → server sống qua DB restart, tự hồi phục.
- Diễn tập backup–restore: khớp từng đồng, reconcile 0.
- Dockerfile + docker-compose (migrate tự động) + GitHub Actions CI (48 test + load mỗi push) · npm audit 0 lỗ hổng.
## v1.3.0 — Auth hardening: trả đủ 5 nợ (48 test × 4 lượt)
1. **Recovery:** quên pass → reset qua email đã verify (mã hash-only 15'); mất token 13 ký tự → owner cấp lại tay, token cũ + mọi phiên vô hiệu.
2. **Verify email:** mã 6 số qua outbox (seam mail provider), email đổi là mất verify.
3. **Sessions:** JWT mang jti · logout/thu hồi từng phiên · refresh rotation · owner revoke-all · JWT không jti (Supabase-style) vẫn nhận.
4. **Lockout:** 5 fail/15' theo tài khoản, 50/15' theo IP, regnick 30/phút/IP ở production.
5. **2FA TOTP** (RFC6238, thuần node crypto): setup/confirm/disable, login owner thành 2 bước.
## v1.2.0 — Auth "regnick" (40 test × 3 lượt)
- Đăng ký cấp **token 13 ký tự** (một lần duy nhất, DB chỉ lưu sha256) → login token → onboarding đặt **username** (unique, chặn tên hệ thống, một lần) → tạo **password** (scrypt+salt) → **email bổ sung sau** trong settings.
- **Dual login:** token 13 ký tự HOẶC username+password — cả hai sống song song.
- **Role owner:** token owner (env `OWNER_TOKEN`, dev default `chaunacha`) → full quyền: mọi route /v1/admin/* nhận JWT owner, không cần x-admin-key. Tự seed + re-hash mỗi boot.
- JWT có claim role, hạn 7 ngày · reserved_handles · migration 009.
## v1.1.0 — Tầng A+B+C (audit 34 test × 4 lượt)
**A · Security + PDPL:** JWT HS256 (dev-uuid có cờ tắt) · zod validation · rate-limit nạp · helmet/CORS · idempotency claim-first + TTL cleanup · consents granular + gate vị trí (cờ PDPL) · data-requests (quyền lãng quên: scrub PII, giữ ledger) · eKYC Điều 29 (không ảnh giấy tờ) · incidents 72h.
**B · Social + Realtime + Twin economy:** WebSocket `/realtime` (pg LISTEN→broadcast kênh map/deal/user) · chat neo deal + DM mở-sau-kết-nối · notifications · moments + peach · điểm Plump append-only + leaderboard tie-break · profile công khai từ dữ liệu thật · twin: exam→qualification (worker chấm), offer theo category, accept auto-start + queue job, energy −5, draft (Fable 5 thật khi có API key, mock khi không) · approve → deal_submit.
**C · Mandate + Agent-ready:** mandate Ed25519 (scope + trần giá + hạn) chặn 3 kiểu vi phạm ở tầng SQL · attestation ký số + `/v1/agent/verify` · `/.well-known/superplump.json` · feed `GET /v1/agent/drops` (chỉ tọa độ mờ) · KYA-lite ghi vết Signature-Agent.
**PWA:** manifest + service worker (offline shell, API network-first).
## v1.0.0 — Core (18 test)
Escrow kế toán kép · máy trạng thái chống race · review mù · riêng tư vị trí · event log · RLS · Admin console.
