-- ============================================================
-- 010 · AUTH HARDENING — trả đủ 5 món nợ của v1.2
-- sessions thu hồi được · lockout chống dò · verify email · recovery · 2FA owner
-- ============================================================

-- ---------- 1 · SESSIONS: JWT mang jti, thu hồi/refresh được ----------
CREATE TABLE sessions (
  jti UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plumper_id UUID NOT NULL REFERENCES plumpers(id),
  user_agent TEXT DEFAULT '', ip TEXT DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ
);
CREATE INDEX sessions_owner_idx ON sessions(plumper_id, created_at DESC);

CREATE OR REPLACE FUNCTION session_valid(p_jti UUID) RETURNS BOOLEAN LANGUAGE sql STABLE AS
$$ SELECT EXISTS(SELECT 1 FROM sessions
   WHERE jti=p_jti AND revoked_at IS NULL AND expires_at > now()) $$;

-- ---------- 2 · LOCKOUT: đếm thất bại theo tài khoản & IP ----------
CREATE TABLE login_attempts (
  id BIGSERIAL PRIMARY KEY,
  ip TEXT NOT NULL,
  account TEXT,                    -- username thường; NULL với login bằng token
  success BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX attempts_acc_idx ON login_attempts(account, created_at DESC);
CREATE INDEX attempts_ip_idx  ON login_attempts(ip, created_at DESC);

-- Trả về số giây còn bị khóa (0 = tự do). Chính sách: 5 fail/15' theo tài khoản, 50 fail/15' theo IP.
CREATE OR REPLACE FUNCTION check_lockout(p_ip TEXT, p_account TEXT) RETURNS INT
LANGUAGE plpgsql STABLE AS $$
DECLARE n_acc INT; n_ip INT; last_fail TIMESTAMPTZ;
BEGIN
  SELECT count(*), max(created_at) INTO n_acc, last_fail FROM login_attempts
    WHERE account = p_account AND NOT success AND created_at > now() - interval '15 minutes';
  IF p_account IS NOT NULL AND n_acc >= 5 THEN
    RETURN GREATEST(1, 900 - EXTRACT(EPOCH FROM now() - last_fail)::INT); END IF;
  SELECT count(*), max(created_at) INTO n_ip, last_fail FROM login_attempts
    WHERE ip = p_ip AND NOT success AND created_at > now() - interval '15 minutes';
  IF n_ip >= 50 THEN
    RETURN GREATEST(1, 900 - EXTRACT(EPOCH FROM now() - last_fail)::INT); END IF;
  RETURN 0;
END $$;

-- ---------- 3 · VERIFY EMAIL + đặt lại mật khẩu qua email ----------
ALTER TABLE plumpers ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;
CREATE TABLE email_codes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plumper_id UUID NOT NULL REFERENCES plumpers(id),
  email TEXT NOT NULL,
  purpose TEXT NOT NULL CHECK (purpose IN ('verify','reset')),
  code_hash TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '15 minutes',
  used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX email_codes_idx ON email_codes(plumper_id, purpose, created_at DESC);

-- Hộp thư DEV: seam thay nhà cung cấp email thật ở production
CREATE TABLE dev_outbox (
  id BIGSERIAL PRIMARY KEY,
  to_email TEXT NOT NULL, subject TEXT NOT NULL, code TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- 4 · RECOVERY: mất token/quên pass → owner cấp tay ----------
CREATE TABLE recovery_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plumper_id UUID NOT NULL REFERENCES plumpers(id),
  kind TEXT NOT NULL CHECK (kind IN ('token_reissue','password_reset')),
  note TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done','rejected')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ
);

-- ---------- 5 · 2FA TOTP cho owner ----------
CREATE TABLE totp_secrets (
  plumper_id UUID PRIMARY KEY REFERENCES plumpers(id),
  secret_b32 TEXT NOT NULL,
  confirmed BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Dọn dẹp định kỳ (gọi chung job cleanup)
CREATE OR REPLACE FUNCTION cleanup_auth(p_days INT DEFAULT 7) RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE n INT := 0; m INT;
BEGIN
  DELETE FROM login_attempts WHERE created_at < now() - make_interval(days=>p_days);
  GET DIAGNOSTICS m = ROW_COUNT; n := n + m;
  DELETE FROM email_codes WHERE created_at < now() - make_interval(days=>p_days);
  GET DIAGNOSTICS m = ROW_COUNT; n := n + m;
  DELETE FROM sessions WHERE expires_at < now() - make_interval(days=>p_days);
  GET DIAGNOSTICS m = ROW_COUNT; RETURN n + m;
END $$;
