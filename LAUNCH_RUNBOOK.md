# 🚀 LAUNCH RUNBOOK — SuperPlump từ zero → production
Thời lượng track kỹ thuật: ~nửa ngày. Track đối tác chạy song song (tính bằng tuần — khởi động NGAY).

## PHASE 0 · Chuẩn bị (30')
- [ ] VPS: 2 vCPU / 4GB RAM / 40GB SSD, Ubuntu 24 (khuyến nghị region VN — dữ liệu ở trong nước)
- [ ] Domain + DNS A record → IP VPS (vd `plump.example.vn`), mở port 80/443
- [ ] Máy cá nhân giữ: file zip release v1.6 + ví mật khẩu (1Password/Bitwarden)

## PHASE 1 · Dựng (60')
```bash
ssh root@<IP>
curl -fsSL https://get.docker.com | sh            # docker + compose plugin
mkdir -p /srv/superplump && cd /srv/superplump
# upload & giải nén release zip vào đây (scp/rsync)
./scripts/gen-secrets.sh .env.production          # sinh trọn bộ secrets thật
# → MỞ FILE, chép OWNER_TOKEN vào ví mật khẩu, KHÔNG gửi qua chat
sed -i 's/plump.example.vn/<DOMAIN THẬT>/' ops/Caddyfile
docker compose --env-file .env.production up -d --build
docker compose ps                                  # db healthy, api ×2, worker, caddy
```

## PHASE 2 · CỔNG GO-LIVE — preflight phải XANH TUYỆT ĐỐI
```bash
python3 scripts/preflight.py https://<DOMAIN> \
  --owner-token "$(grep OWNER_TOKEN .env.production | cut -d= -f2)" \
  --admin-key  "$(grep ADMIN_KEY  .env.production | cut -d= -f2)"
```
Preflight ✗ bất kỳ mục nào = **CẤM MỞ CỬA**. Nó soi: dev surface đóng, `chaunacha`/`plump-admin` đã chết, route in-tiền niêm phong, webhook đòi chữ ký, /terms /privacy sống, **sổ cái khớp**.

Rồi smoke đường tiền thật:
```bash
python3 scripts/smoke.py https://<DOMAIN> \
  --admin-key <ADMIN_KEY> --payment-secret <PAYMENT_WEBHOOK_SECRET> --ekyc-secret <EKYC_WEBHOOK_SECRET>
```

## PHASE 3 · Ngày đầu vận hành
- [ ] Backup: `crontab -e` → `0 3 * * * /srv/superplump/scripts/backup.sh` · diễn tập restore tuần 1 lần
- [ ] Xem log: `docker compose logs -f api worker` (JSON, có request-id) · dashboard `/metrics`
- [ ] Bật 2FA owner ngay: login → POST /v1/auth/2fa/setup → confirm
- [ ] Còi tiền: cắm Prometheus + `ops/alerts.yml` — `LedgerMismatch` là báo động đỏ dừng chợ
- [ ] Rollback: `docker compose down` → `gunzip -c backup.sql.gz | docker compose exec -T db psql -U plump superplump`
- [ ] Sự cố dữ liệu: tạo incident trong admin — deadline 72h tự đếm (Luật 91/2025)

## PHASE 4 · Track đối tác (song song, đường găng thật)
- [ ] Trung gian thanh toán licensed: ký → nhận secret + URL webhook thật → thay `PAYMENT_WEBHOOK_SECRET`, viết driver map format (seam sẵn)
- [ ] eKYC (VNeID/VNPT/FPT): tương tự với `EKYC_WEBHOOK_SECRET`
- [ ] MASTER_KEY → cloud KMS · Bổ nhiệm DPO + điền `docs/DPIA_TEMPLATE.md` nộp
- [ ] Pen-test độc lập trước khi chạy marketing
