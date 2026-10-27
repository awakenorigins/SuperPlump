# RUNBOOK — Vận hành & Go-Live SuperPlump

## 0. Kiến trúc
Caddy (TLS) → 2× API (Express, stateless) → PostgreSQL 16 + PostGIS. Worker chạy tiến trình riêng (`api/worker.js`). Realtime & rate-limit chia sẻ qua chính Postgres (pg NOTIFY + bảng rate_limits) nên thêm/bớt instance thoải mái. Agents engine `claude-fable-5`.

## 1. Chạy local (dev)
```bash
./run.sh            # dựng DB + migrate 001→012 + boot + 62 test
# App: http://localhost:8386/app · Admin: /admin · Metrics: /metrics
```

## 2. Sinh secret production
```bash
./scripts/gen-secrets.sh .env.production   # tạo bộ khóa mạnh, chmod 600
# Lưu OWNER_TOKEN vào password manager. KHÔNG commit .env.production.
```

## 3. Deploy (một máy, Docker)
```bash
docker compose --env-file .env.production up -d --build   # db + 2 api + worker + caddy
docker compose logs -f api                                 # xem "[preflight] cấu hình OK (production)"
```
Preflight sẽ **từ chối khởi động** nếu còn secret dev/khóa yếu ở production — đây là tính năng, không phải lỗi.

## 4. Trước khi mở cho tiền thật (đường găng ngoài code)
- [ ] Ký hợp đồng **trung gian thanh toán** có giấy phép NHNN (NĐ 52/2024). Đổi driver `/v1/payments/webhook` sang provider; set `PAYMENT_WEBHOOK_SECRET`.
- [ ] Ký **eKYC** (VNeID/VNPT/FPT). Nối `/v1/kyc/webhook`; set `EKYC_WEBHOOK_SECRET`.
- [ ] Bổ nhiệm **DPO**, điền & nộp **DPIA** (`docs/DPIA_TEMPLATE.md`).
- [ ] Trỏ domain vào Caddy; xác nhận HTTPS + HSTS.
- [ ] Chuyển `MASTER_KEY` sang **cloud KMS** (hiện là envelope AES-GCM bằng biến môi trường).
- [ ] Nối JWT: đặt `JWKS_URL` (RS256) hoặc `SUPABASE_JWT_SECRET` mạnh.
- [ ] **Pen-test độc lập** + rà lại quyền RLS.

## 5. Backup & khôi phục (diễn tập định kỳ)
```bash
# Sao lưu:
docker compose exec -T db pg_dump -U plump superplump | gzip > backup_$(date +%F).sql.gz
# Khôi phục ra DB thử rồi đối chiếu reconcile() = rỗng trước khi tin:
gunzip -c backup_YYYY-MM-DD.sql.gz | docker compose exec -T db psql -U plump -d superplump_restore
```
Đã diễn tập: dump→restore khớp từng đồng, `reconcile()` = 0.

## 6. Giám sát (cắm Prometheus vào /metrics)
Còi phải bật (xem `ops/alerts.yml`): **`plump_ledger_mismatch > 0` = CRITICAL** → đóng băng giao dịch, điều tra ngay. Theo dõi thêm: tỉ lệ 5xx, p95 latency, `plump_twin_jobs_queued`, `plump_escrow_balance`.

## 7. Playbook sự cố
- **Sổ cái lệch:** tạm dừng tất toán → chạy `SELECT * FROM reconcile()` tìm ví lệch → truy `ledger_entries` theo deal → không bao giờ UPDATE tay (sổ append-only), sửa bằng bút toán bù có log.
- **Nghi gian lận:** `GET /v1/admin/fraud-flags`; treo tài khoản `POST /v1/admin/plumpers/:id/suspend` (tự đuổi mọi phiên).
- **Rò dữ liệu:** tạo incident (`POST /v1/admin/incidents`) — deadline báo cơ quan 72h tự sinh; theo mục 5 PRIVACY_PACK.
- **Owner mất token:** vào DB đổi `token_hash` = sha256(token mới), hoặc xoay `OWNER_TOKEN` rồi restart (tự re-hash).

## 8. Vận hành định kỳ
`POST /v1/admin/jobs/auto-confirm` (hoặc pg_cron 5') · `POST /v1/admin/jobs/cleanup-idempotency` (dọn idempotency + auth cũ). Production nên đưa hai job này vào pg_cron.

## Beat 3 pilot production hardening

- **CORS:** production must set `PUBLIC_DOMAIN` or `ALLOWED_ORIGINS` (comma separated). Defaults preserve current `superplump.vn` and `www.superplump.vn`. Requests without an `Origin` header remain allowed for mobile apps, CLI tools, health checks, and server-to-server clients.
- **Runtime:** compose sets `NODE_ENV=production`; preflight refuses production boot if dev UUID auth, weak secrets, missing TLS proxy acknowledgement, or missing CORS domain configuration are detected. ChauNacha owner semantics are preserved, but production requires non-default strong owner/admin/JWT/KMS/webhook secrets.
- **Backups:** run `scripts/backup.sh` from your scheduler of choice; this repository intentionally does not edit crontab/systemd. Set `BACKUP_DIR`, `BACKUP_RETENTION_DAYS`, and preferably `BACKUP_AGE_RECIPIENT` for encrypted `.age` output. Files are written under `umask 077` with 0600/0700 permissions.
- **Restore verification:** run `BACKUP_AGE_IDENTITY=/path/to/key scripts/restore-verify.sh backups/superplump-YYYY.sql.gz.age` (or pass an unencrypted `.sql.gz`). The script restores into a disposable PostGIS container and runs a schema sanity query.
- **Monitoring:** start with `docker compose --profile monitoring up -d prometheus alertmanager`. Prometheus scrapes `/metrics`; alerts cover API down, ledger mismatch, and 5xx spikes. Configure Alertmanager receivers before pilot traffic.
- **Status endpoint:** `/status` returns only coarse app/db status and environment class; it does not expose secrets, counts, or configuration.
- **Payments/KYC:** real-money topups and payment webhooks remain disabled for pilot. eKYC surfaces are existing pilot seams only; do not connect a real provider until legal/ops approval.
- **Secret scanning:** GitHub CI includes Gitleaks. Treat findings as blockers; rotate any exposed value rather than suppressing by default.
