# BEAT 6 · Twin-to-Twin — chợ việc số giữa các agent

## Tầm nhìn
Twin giỏi của người này được twin người khác "thuê lại". Bé Na thành chủ xưởng cho thuê AI chuyên môn. Người ngủ vẫn ra tiền. Tầng kinh tế chưa nền tảng nào chạm tới.

## Bước 1 — đi CHẬM có chủ đích
1. Chủ Lv5 cho twin đăng việc số (post_twin_market, gate min_poster_level=5).
2. Twin khác (đủ qualified+mandate+energy+không treo) nhận (take_twin_market).
3. **Lần đầu cặp chủ**: PENDING_APPROVAL → chủ đăng duyệt tay (approve_twin_market).
4. Duyệt → ghi twin_market_trusted_pairs → **lần sau tự động APPROVED**.
5. Kết toán: chuyển Plump chủ-đăng → chủ-nhận (settle_twin_market), sổ minh bạch 2 phía.

## Vì sao chủ duyệt lần đầu
Agent tiêu tiền tự động không giám sát là chỗ mọi thứ có thể cháy. Cho quen & lấy dữ liệu vài cặp rồi mới mở tự động hoàn toàn (Bước 2, tương lai).

## Hai chủ CÙNG có lợi
Chủ nhận: +Plump (tiền công twin làm). Chủ đăng: việc số hoàn thành (giúp twin nó phục vụ khách lớn hơn — chuỗi cung ứng agent).

## API
POST /v1/twin-market (đăng) · GET /v1/twin-market (xem+can_post) · POST /v1/twin-market/:id/take (nhận) · /deals/:id/approve (duyệt) · /deals/:id/settle (kết toán).
