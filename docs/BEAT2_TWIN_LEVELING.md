# BEAT 2 · Twin có cấp — chặn trần bởi cấp chủ (Phương án B)

## Công thức
```
twin_score = n_job_twin × (avg_rating_việc_twin / 5) × √(min(distinct_clients, 15))
twin_raw_level = map(twin_score → 1..5) theo tiers [0,3,8,18,36]
twin_level = MIN(twin_raw_level, plump_level(owner))    ← TRẦN
```

## Vì sao Phương án B
Twin bị chặn trần bởi cấp CHỦ: người Lv3 → twin tối đa Lv3. Buộc chủ tự giỏi thì AI mới giỏi.
Tránh viễn cảnh "người lười nuôi AI giỏi rồi ngồi không hưởng" — con người luôn ở trung tâm.
Khi chủ lên cấp, trần nới ra, twin được phép lên theo (tới mức raw của nó).

## Điều kiện twin nhận việc (đã có sẵn từ 007, Beat 2 dựa trên)
Twin muốn nhận việc phải: (1) **qualified** cho category (đỗ sát hạch), (2) có **mandate** còn hiệu lực (chủ ký uỷ quyền Ed25519), (3) còn **energy** (van năng lượng — Beat 3).

## API
GET /v1/twins/:id → thêm: twin_level, raw_level, owner_level, capped_by_owner, level_score, rated_jobs.
