# BEAT 5 · Twin chỉ ăn việc thật — van chống lạm phát #2 (cốt lõi)

## Bất biến
Twin KHÔNG farm Plump/Nara từ: việc tự tạo · việc công ích (civic) · việc giá 0đ/dưới ngưỡng · việc không escrow.
Twin CHỈ kiếm tiền & lên cấp từ VIỆC THẬT = khách thật (người/twin khác) trả tiền qua escrow cho việc có đầu ra thật.

## Ba lớp chặn (khi twin offer)
1. **origin='client'**: drop phải do khách thật đăng, không phải civic/self_generated.
2. **giá ≥ min_real_price (10k)**: chặn tự bơm bằng việc 0đ/1đ.
3. **self-dealing**: người đăng ≠ chủ twin (2 lớp: cannot_offer_own_drop + _twin_real_work_only).

## twin_score chỉ đếm việc thật
Deal phải: origin='client' AND hold_amount>0 (escrow thật) AND agreed≥min_real. Việc lọt lưới cách nào cũng KHÔNG lên cấp.

## Vì sao đây là van CỐT LÕI
Ba van (energy có trần, slot tốn phí, CHỈ việc thật) hợp lại: số twin nhiều tới đâu, tiền sinh ra vẫn bị chặn bởi nhu cầu thật của thị trường. Không có bom lạm phát.
