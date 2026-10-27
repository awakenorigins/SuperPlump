-- ============================================================
-- 009 · AUTH — regnick token 13 ký tự + username/password + role owner
-- Nguyên tắc: token & password KHÔNG BAO GIỜ lưu bản rõ (chỉ hash).
-- ============================================================

ALTER TABLE plumpers
  ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'plumper'
    CHECK (role IN ('plumper','owner')),
  ADD COLUMN IF NOT EXISTS token_hash TEXT UNIQUE,          -- sha256(token 13 ký tự)
  ADD COLUMN IF NOT EXISTS password_hash TEXT,              -- s2:<salt>:<scrypt>
  ADD COLUMN IF NOT EXISTS email TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS onboarded BOOLEAN NOT NULL DEFAULT false;

-- Handle giữ UNIQUE sẵn có; danh sách tên cấm đặt (giữ cho hệ thống)
CREATE TABLE IF NOT EXISTS reserved_handles (handle TEXT PRIMARY KEY);
INSERT INTO reserved_handles VALUES ('owner'),('admin'),('superplump'),('chaunacha'),('plump'),('system')
  ON CONFLICT DO NOTHING;

-- Đặt username (một lần, lúc onboarding): unique + không đụng tên cấm
CREATE OR REPLACE FUNCTION set_username(p_actor UUID, p_handle TEXT) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE cur RECORD;
BEGIN
  SELECT * INTO cur FROM plumpers WHERE id = p_actor FOR UPDATE;
  IF cur.onboarded THEN RAISE EXCEPTION 'already_onboarded'; END IF;
  IF p_handle !~ '^[a-z0-9_]{3,20}$' THEN RAISE EXCEPTION 'bad_username_format'; END IF;
  IF EXISTS (SELECT 1 FROM reserved_handles WHERE handle = p_handle) THEN
    RAISE EXCEPTION 'username_reserved'; END IF;
  IF EXISTS (SELECT 1 FROM plumpers WHERE handle = p_handle AND id <> p_actor) THEN
    RAISE EXCEPTION 'username_taken'; END IF;
  UPDATE plumpers SET handle = p_handle, display_name = p_handle, onboarded = true
    WHERE id = p_actor;
  PERFORM _log('plumper', p_actor, 'username_set', jsonb_build_object('handle',p_handle), p_actor);
END $$;
