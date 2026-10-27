# SUPERPLUMP · THIẾT KẾ HỆ VẬT PHẨM V1 — "Đẹp mua bằng Nara, Oai đổi bằng lao động"

## 0 · Nguyên tắc vàng (bất khả xâm phạm)
1. **Hai track không hoán đổi:** Nara (nạp) mua *thẩm mỹ*; Plump & thành tích (chỉ farm bằng lao động) đổi *danh vọng*. Tiền không bao giờ mua được thứ trông-giống-uy-tín.
2. **Không bán vị trí:** thứ hạng hiển thị trên map/list theo relevance + uy tín. Chỉ bán *style* của ghim, không bán độ to/độ ưu tiên.
3. **Danh vọng có decay:** vật phẩm oai phải rụng được (tụt rating → mất aura; hết tháng → trả cánh). Danh vọng thật thì phải giữ mới còn.
4. **Soulbound V1:** không trade P2P (né chợ đen quy đổi Nara→tiền mặt → NĐ 52). Chỉ *tặng một chiều* đồ Nara cho người đã từng deal chung.
5. **Mua bằng Nara = bút toán kép:** user → platform, kind `purchase`. `reconcile()` phải luôn = 0 kể cả khi shop cháy hàng.
6. **Twin luôn lộ AI:** skin twin mua thoải mái, khung nhãn AI không tháo được.

## 1 · AVATAR — "Mận nhân" (SVG ghép lớp)
Slots: `body_color` · `face` · `head` · `hand` · `frame` · `aura`
- `hand` gắn nghề (cầm ly cà phê sữa / tuốc-nơ-vít / cọ vẽ) → nhìn avatar đoán nghề = trang trí có ích cho chợ. Nguồn: **Plump**.
- `aura` chỉ có nguồn **earned**, có decay.
- Trạng thái sống (render theo state, không phải item): ngủ khi offline · tai nghe khi đang trong deal.
- Avatar twin = biến thể hologram của avatar chủ + khung nhãn AI cố định.

## 2 · PHÒNG — "Tổ Mận" (hồ sơ dạng không gian)
Slots mua được: `wallpaper` · `floor` · `window` · `lamp` · `music`
Thành phần tự sinh (KHÔNG bán):
- **Kệ thành tích:** vật mọc từ deal thật (mốc kèo, hạng mục, twin gold). Là PlumpLife vật chất hóa.
- **Góc twin:** bàn nhỏ, twin gõ phím khi có job đang chạy thật.
- **Sổ khách:** chỉ ai *từng deal chung* mới được viết — bằng chứng xã hội không fake được.
Phòng kiêm storefront: drop đang mở treo poster + nút "Thuê tôi".

## 3 · MAP PRESENCE
Bán style: `pin_style` (ghim theo nghề) · `pin_effect` (Plump). Earned: đèn hiệu khu (top tuần/quận — V2), pháo hoa mận tại điểm settle (mặc định, miễn phí — quảng cáo sống cho chợ).

## 4 · CATALOG SEED V1 (24 vật phẩm)
| ID | Tên | Slot | Nguồn | Giá | Ghi chú |
|---|---|---|---|---|---|
| non_la_neon | Nón lá Neon | head | nara | 25.000 | giftable |
| mu_chrome | Mũ bảo hiểm Chrome | head | nara | 35.000 | giftable |
| beret_designer | Beret Designer | head | nara | 30.000 | giftable |
| frame_man_bong | Khung Mận Bông | frame | nara | 30.000 | giftable |
| twin_skin_holo | Skin Twin Hologram | twin_skin | nara | 45.000 | nhãn AI giữ nguyên |
| wp_neon | Tường Neon Sài Gòn | wallpaper | nara | 40.000 | giftable |
| wp_lantern | Tường Đèn Lồng | wallpaper | nara | 30.000 | giftable |
| floor_go | Sàn Gỗ Ấm | floor | nara | 20.000 | giftable |
| win_landmark | Cửa sổ Landmark 81 | window | nara | 80.000 | flagship |
| win_nhieuloc | Cửa sổ Kênh Nhiêu Lộc | window | nara | 60.000 | |
| win_benthanh | Cửa sổ Chợ Bến Thành | window | nara | 70.000 | |
| lamp_neon | Đèn Neon Mận | lamp | nara | 25.000 | |
| music_lofi | Lo-fi Sài Gòn | music | nara | 15.000 | |
| music_mua | Tiếng Mưa Đêm | music | nara | 15.000 | |
| pin_caphe | Ghim Ly Cà Phê | pin_style | nara | 20.000 | |
| pin_toolbox | Ghim Hộp Đồ Nghề | pin_style | nara | 20.000 | |
| hand_caphe | Tay cầm Cà Phê Sữa | hand | plump | 🍑800 | |
| hand_tovit | Tay cầm Tuốc-nơ-vít | hand | plump | 🍑800 | |
| hand_co | Tay cầm Cọ Vẽ | hand | plump | 🍑800 | |
| face_cuoi | Mặt Cười Tít | face | plump | 🍑500 | |
| pinfx_lap_lanh | Hiệu ứng Ghim Lấp Lánh | pin_effect | plump | 🍑1.200 | |
| choi_vang | Cây Chổi Vàng | shelf | **earned** | mốc 10 kèo | tự cấp |
| aura_5sao | Aura Vàng 5★ | aura | **earned** | rating ≥4.9, ≥N review | **decay: tụt là rụng + tự tháo** |
| canh_man | Cánh Mận | aura | **earned** | top 10 tháng | hết hạn cuối tháng sau (V2 grant) |

## 5 · Mechanics
- **Crafting hai track (V2):** khung Nara + đủ 50 kèo → bản khắc số kèo.
- **Tặng sau deal:** một chiều, chỉ đồ nara-giftable, gate `are_connected`, log + notify.
- **Đồ mùa:** Tết/Trung thu/mùa mưa — cửa hàng theo event window.
- **Doanh thu sạch:** bán cosmetics không đụng giấy phép trung gian thanh toán.

## 6 · Ánh xạ kỹ thuật (migration 013)
`items` (catalog, meta JSONB, giftable, decay_rule) · `inventory` (owner, item, expires_at, via) · `equipped(owner,slot)` · `room_slots(owner,slot)` · `guestbook` (gate connections) · `buy_item()` = ledger `purchase` hoặc bút toán Plump âm · trigger settle cấp mốc · `refresh_prestige()` grant/revoke aura + auto-unequip · shop/inventory/equip/room/guestbook/gift API. Avatar client: SVG layer + CSS var, hợp hệ đêm mận.
