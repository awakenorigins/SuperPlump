-- 023 · PILOT ACCESS GATE (Beat 1)
-- Replace KYC gating for privileged task/market/social actions with a pilot-age gate.
-- Idempotent: only CREATE OR REPLACE functions; preserves existing rows/data.

-- Atomic account bootstrap: identity + wallet + one-time 1,313 Nara grant.
-- The API supplies only a hash of the random token; plaintext is never stored.
CREATE OR REPLACE FUNCTION register_pilot_account(p_token_hash TEXT)
RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE uid UUID := gen_random_uuid();
BEGIN
  -- UUID-derived handle removes the random()/10-hex collision window.
  INSERT INTO plumpers(id,handle,display_name,kyc_status,token_hash)
  VALUES (uid,'p_'||replace(uid::text,'-',''),'Plumper mới','none',p_token_hash);

  INSERT INTO wallets(owner,kind) VALUES (uid,'user');
  PERFORM topup(uid,1313);
  RETURN uid;
END $$;

CREATE OR REPLACE FUNCTION _require_verified(p UUID) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN
  SELECT role, created_at, suspended_at INTO r FROM plumpers WHERE id=p;
  IF NOT FOUND THEN RAISE EXCEPTION 'account_not_found'; END IF;
  IF r.suspended_at IS NOT NULL THEN RAISE EXCEPTION 'account_suspended'; END IF;
  -- Owner/admin bootstrap behavior is unchanged; ordinary accounts wait 5 minutes.
  IF r.role IS DISTINCT FROM 'owner' AND r.created_at > now() - interval '5 minutes' THEN
    RAISE EXCEPTION 'pilot_wait_required';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION pilot_access_eligible(p UUID) RETURNS BOOLEAN LANGUAGE plpgsql AS $$
DECLARE ok BOOLEAN;
BEGIN
  SELECT ((role = 'owner' OR created_at <= now() - interval '5 minutes') AND suspended_at IS NULL)
    INTO ok
  FROM plumpers
  WHERE id = p;
  RETURN COALESCE(ok, false);
END $$;
