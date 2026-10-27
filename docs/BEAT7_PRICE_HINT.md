# BEAT 7 · Giá gợi ý tinh tế — chiếu đèn, KHÔNG ép

## Triết lý (ranh giới mày đã vạch)
Nền tảng KHÔNG đặt giá. Chỉ soi sáng thông tin: "khu này giờ này thường 45k".
Grab ÉP giá; SuperPlump CHIẾU ĐÈN rồi để người quyết. Tự do CÓ TRỢ LỰC, không phải tự do trần trụi.
Giữ nguyên 2 bất biến — đây là bổ trợ thông tin, không phải can thiệp giá.

## Cơ chế
price_hint(category, kind, lng, lat):
- Chọn phạm vi hẹp nhất đủ mẫu: **khu+giờ** (2km, ±3h) → **khu** → **toàn quốc**.
- Trả p25 (thấp) / median (điển hình) / p75 (cao) + cỡ mẫu + tên phạm vi.
- CHỈ việc thật: origin='client', giá ≥ sàn tuyệt đối (10k), trong 90 ngày.
- Dưới min_sample (5) → "chưa đủ dữ liệu", không bịa giá.

## Không ép
Sau khi xem gợi ý, người vẫn đăng giá BẤT KỲ (gấp 10 lần hay bèo hơn — đều được).
Người lười: nhìn median bấm phát ăn ngay (như Grab). Người muốn mặc cả: cứ tự do.

## API
GET /v1/price-hint?category=&kind=&lng=&lat= → {sample, scope, suggestion:{low,typical,high}, enough_data, note}
