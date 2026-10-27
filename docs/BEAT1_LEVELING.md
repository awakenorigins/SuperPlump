# BEAT 1 · Cấp bậc Plumper — Thiết kế & Chống cày

## Công thức level_score
```
score = n_valid × (avg_rating / 5) × √(min(distinct_clients, diversity_cap))
```
- **n_valid**: số kèo SETTLED HỢP LỆ (loại kèo giá bất thường thấp vượt ân hạn).
- **avg_rating/5**: hệ số chất lượng 0.2–1.0 (điểm khách chấm, thang 1–5).
- **√distinct_clients**: thưởng đa dạng khách, sqrt để có ích nhưng không áp đảo số lượng.

## Ba lớp chống cày
1. **Đa dạng khách**: chỉ đếm khách KHÁC NHAU, trần `diversity_cap=25`. Cày 1 cặp vô hạn = distinct_clients kẹt 1 → √1 = 1.
2. **Giá bất thường thấp không tính**: kèo < `min_price_ratio×median` HOẶC < `abs_floor` (10k) → không tính điểm cấp; chỉ ân hạn `low_price_grace=2` kèo đầu (cho người mới cày cấp thật).
3. **Median chống đầu độc**: `median_price_for_kind` chỉ tính trên kèo ≥ abs_floor → cày hàng loạt kèo 1.000đ KHÔNG kéo được median xuống để "hợp thức hoá" giá bèo.

## Tiers (config['leveling'].tiers = [1,4,10,26,60])
| Cấp | Tên | Ngưỡng score | Ví dụ đạt được |
|-----|-----|--------------|----------------|
| Lv1 | Mầm Mận | 0 | người mới |
| Lv2 | Mận Xanh | ≥4 | vài kèo đầu |
| Lv3 | Mận Bạc | ≥10 | ~5 kèo thật 5★ |
| Lv4 | Mận Vàng | ≥26 | ~15 kèo đa dạng 5★ |
| Lv5 | Mận Kim Cương | ≥60 | ~40 kèo đa dạng 5★ |

Cấp mở khoá quyền Twin (Beat 2+): Lv3 twin đề xuất · Lv4 mandate · Lv5 twin-to-twin.
