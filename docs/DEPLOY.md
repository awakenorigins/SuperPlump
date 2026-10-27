# DEPLOY.md — Đường ra production
1. **Database:** Supabase project → chạy `db/001→005` trong SQL Editor (PostGIS bật sẵn). RLS 003 khớp mô hình `auth.uid()` — thay hàm `uid()` bằng `auth.uid()` của Supabase.
2. **API:** hai đường: (a) giữ `api/server.js` deploy Railway/Fly/Render, đổi auth dev-Bearer → verify JWT Supabase (jose), Pool trỏ connection string Supabase; hoặc (b) bỏ Express, expose thẳng các hàm SQL qua Supabase RPC/PostgREST — Endpoint Map ↔ hàm đã 1:1.
3. **Scheduler:** `auto_confirm_overdue()` chạy pg_cron mỗi 5 phút (hiện có endpoint `/v1/admin/jobs/auto-confirm` để chạy tay).
4. **Agents:** set `ANTHROPIC_API_KEY`; model mặc định `claude-fable-5` (đổi qua `ANTHROPIC_MODEL`).
5. **Web:** `prototype/` là spec sống của UI — dựng Next.js + MapLibre theo đúng luồng này, gọi API ở trên.
6. **Trước khi nhận tiền thật:** checkpoint pháp lý trung gian thanh toán (đối tác có giấy phép) — nút thắt duy nhất ngoài code.

## 7 · Docker & CI (v1.4)
- `docker compose up` = Postgres/PostGIS + migrate tự động (initdb chạy `db/` theo thứ tự) + API production-mode (dev-uuid TẮT, secrets bắt buộc qua env).
- `.github/workflows/ci.yml`: mỗi push chạy migrate → 48 test → load test + bất biến sổ cái. Merge đỏ là không có chuyện lên main.
- Server đã có: pool error-handler + timeout 3s (fail-fast), async wrapper toàn cục, LISTEN tự nối lại, graceful shutdown SIGTERM.
