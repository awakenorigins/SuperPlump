# ✅ GO-LIVE CHECKLIST — SuperPlump

## A · Kỹ thuật (tự làm được ngay)
- [x] 62 test tự động xanh (6 nhóm: core, api, security/PDPL, social/agents, auth, auth-hardening, production, multi)
- [x] Chạy đa instance (2 API + worker riêng) — rate-limit & realtime chia sẻ qua PG
- [x] Load 190 req/s + soak 75s (3005 deal, 0 lỗi, sổ cái khớp)
- [x] Sống sót DB chết + tự hồi phục; backup→restore diễn tập khớp từng đồng
- [x] TLS native / proxy · secrets từ file · preflight chặn boot nếu cấu hình yếu
- [x] Metrics + còi báo lệch sổ · npm 0 lỗ hổng
- [ ] `./scripts/gen-secrets.sh` sinh secret thật, nạp vào deploy
- [ ] `docker compose --env-file .env.production up -d` trên VPS/cloud thật
- [ ] Domain + DNS trỏ Caddy; xác nhận HTTPS + HSTS
- [ ] Prometheus + Alertmanager cắm vào /metrics; thử bắn cảnh báo
- [ ] pg_cron cho auto-confirm + cleanup
- [ ] Backup tự động hằng ngày + thử khôi phục

## B · Pháp lý & đối tác (đường găng — khởi động NGAY, tính bằng tuần)
- [ ] Hợp đồng trung gian thanh toán có giấy phép NHNN (NĐ 52/2024) → **chưa xong thì KHÔNG nhận tiền thật**
- [ ] Hợp đồng eKYC (VNeID/VNPT/FPT) → thay mock ở /v1/kyc/*
- [ ] Bổ nhiệm DPO + điền & nộp DPIA (template có sẵn)
- [ ] Đăng ký doanh nghiệp, ToS/Privacy rà bởi luật sư (bản nháp có sẵn /terms /privacy)
- [ ] Quy trình xử lý yêu cầu dữ liệu (đã có endpoint) + đầu mối cơ quan chức năng

## C · An toàn trước khi mở cửa người lạ
- [ ] Pen-test độc lập
- [ ] Cloud KMS thật thay MASTER_KEY biến môi trường
- [ ] WAF/rate-limit tầng proxy; secret scanning trong CI
- [ ] Kế hoạch on-call + kênh báo sự cố

## Kết luận trạng thái
**Phần mềm: sẵn sàng.** Còn lại là **hạ tầng (ngày) + pháp lý/đối tác (tuần)**. Không có mục B thì chạy được ở chế độ pilot không-tiền-thật; đủ mục B mới bật dòng tiền.
