-- 011 · Multi-instance + KMS
-- Rate-limit dùng chung mọi instance (thay MemoryStore từng process)
CREATE TABLE rate_limits (
  key TEXT PRIMARY KEY,
  hits INT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL
);
-- Khóa mandate: bản rõ bị khai tử, chuyển envelope encryption (AES-256-GCM bọc bằng MASTER_KEY)
ALTER TABLE twin_mandates
  ALTER COLUMN privkey DROP NOT NULL,
  ADD COLUMN IF NOT EXISTS privkey_enc TEXT;
-- Dọn rate_limits hết hạn chung job cleanup
CREATE OR REPLACE FUNCTION cleanup_auth(p_days INT DEFAULT 7) RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE n INT := 0; m INT;
BEGIN
  DELETE FROM login_attempts WHERE created_at < now() - make_interval(days=>p_days);
  GET DIAGNOSTICS m = ROW_COUNT; n := n + m;
  DELETE FROM email_codes WHERE created_at < now() - make_interval(days=>p_days);
  GET DIAGNOSTICS m = ROW_COUNT; n := n + m;
  DELETE FROM sessions WHERE expires_at < now() - make_interval(days=>p_days);
  GET DIAGNOSTICS m = ROW_COUNT; n := n + m;
  DELETE FROM rate_limits WHERE expires_at < now();
  GET DIAGNOSTICS m = ROW_COUNT; RETURN n + m;
END $$;
