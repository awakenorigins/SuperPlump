-- ============================================================
-- 008 · TẦNG C — TWIN MANDATE (AP2-style) + AGENT-READY
-- Mandate = "giấy ủy quyền" ký số: twin chỉ được hành động trong phạm vi chủ cho phép.
-- ============================================================

CREATE TABLE twin_mandates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  twin_id UUID NOT NULL REFERENCES twins(id),
  categories TEXT[] NOT NULL,
  max_price BIGINT NOT NULL CHECK (max_price > 0),
  expires_at TIMESTAMPTZ NOT NULL,
  pubkey TEXT NOT NULL,          -- Ed25519 public key (base64) — verify công khai được
  privkey TEXT NOT NULL,         -- DEMO ONLY: production đưa vào KMS/HSM
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX mandate_twin_idx ON twin_mandates(twin_id) WHERE revoked_at IS NULL;

CREATE OR REPLACE FUNCTION active_mandate(p_twin UUID)
RETURNS twin_mandates LANGUAGE sql STABLE AS $$
  SELECT * FROM twin_mandates
  WHERE twin_id=p_twin AND revoked_at IS NULL AND expires_at > now()
  ORDER BY created_at DESC LIMIT 1 $$;

-- Siết create_offer_twin: KHÔNG mandate hợp lệ = twin không được ra chợ
CREATE OR REPLACE FUNCTION create_offer_twin(p_owner UUID, p_twin UUID, p_drop UUID, p_amount BIGINT)
RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE v UUID; d RECORD; tw RECORD; m twin_mandates;
BEGIN
  PERFORM _require_verified(p_owner);
  SELECT * INTO tw FROM twins WHERE id=p_twin;
  IF tw.owner <> p_owner THEN RAISE EXCEPTION 'not_twin_owner'; END IF;
  IF tw.energy < 5 THEN RAISE EXCEPTION 'twin_no_energy'; END IF;
  SELECT * INTO d FROM drops WHERE id=p_drop;
  IF d.status <> 'open' THEN RAISE EXCEPTION 'drop_not_open'; END IF;
  IF d.owner = p_owner THEN RAISE EXCEPTION 'cannot_offer_own_drop'; END IF;
  IF d.kind <> 'digital' THEN RAISE EXCEPTION 'twin_digital_only'; END IF;
  IF NOT EXISTS (SELECT 1 FROM qualifications q
                 WHERE q.twin_id=p_twin AND q.category=d.category AND q.revoked_at IS NULL)
  THEN RAISE EXCEPTION 'twin_not_qualified:%', d.category; END IF;

  m := active_mandate(p_twin);
  IF m.id IS NULL THEN RAISE EXCEPTION 'mandate_missing'; END IF;
  IF NOT (d.category = ANY(m.categories)) THEN RAISE EXCEPTION 'mandate_scope_violation:%', d.category; END IF;
  IF p_amount > m.max_price THEN RAISE EXCEPTION 'mandate_price_violation:% > %', p_amount, m.max_price; END IF;

  INSERT INTO offers(drop_id,from_id,amount,twin_id) VALUES (p_drop,p_owner,p_amount,p_twin)
    RETURNING id INTO v;
  PERFORM _log('drop',p_drop,'offered_by_twin',
    jsonb_build_object('amount',p_amount,'twin',p_twin,'mandate',m.id),p_owner);
  RETURN v;
END $$;

-- KYA-lite: ghi vết agent bên ngoài ghé chợ (Signature-Agent style header)
CREATE TABLE agent_visits (
  id BIGSERIAL PRIMARY KEY,
  signature_agent TEXT NOT NULL,
  user_agent TEXT DEFAULT '',
  path TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
