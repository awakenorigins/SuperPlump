-- 005 · KYC + Idempotency + cổng hành động (KYC gate nằm ở TẦNG DB)
CREATE TABLE kyc_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plumper_id UUID NOT NULL REFERENCES plumpers(id),
  doc_url TEXT NOT NULL, selfie_url TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  note TEXT DEFAULT '', reviewed_by TEXT, reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE idempotency_keys (
  key TEXT PRIMARY KEY, status INT NOT NULL, body JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION _require_verified(p UUID) RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN IF (SELECT kyc_status FROM plumpers WHERE id=p) IS DISTINCT FROM 'verified'
  THEN RAISE EXCEPTION 'kyc_required'; END IF; END $$;

CREATE OR REPLACE FUNCTION create_drop(p_actor UUID, p_kind TEXT, p_title TEXT,
  p_desc TEXT, p_price BIGINT, p_lng FLOAT, p_lat FLOAT) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE v UUID;
BEGIN
  PERFORM _require_verified(p_actor);
  INSERT INTO drops(owner,kind,title,description,price,location)
  VALUES (p_actor,p_kind,p_title,COALESCE(p_desc,''),p_price,
    CASE WHEN p_lng IS NULL THEN NULL
         ELSE ST_SetSRID(ST_MakePoint(p_lng,p_lat),4326)::geography END)
  RETURNING id INTO v;
  PERFORM _log('drop',v,'created',jsonb_build_object('price',p_price,'kind',p_kind),p_actor);
  RETURN v;
END $$;

CREATE OR REPLACE FUNCTION create_offer(p_actor UUID, p_drop UUID, p_amount BIGINT)
RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE v UUID; d RECORD;
BEGIN
  PERFORM _require_verified(p_actor);
  SELECT * INTO d FROM drops WHERE id=p_drop;
  IF d.status <> 'open' THEN RAISE EXCEPTION 'drop_not_open'; END IF;
  IF d.owner = p_actor THEN RAISE EXCEPTION 'cannot_offer_own_drop'; END IF;
  INSERT INTO offers(drop_id,from_id,amount) VALUES (p_drop,p_actor,p_amount) RETURNING id INTO v;
  PERFORM _log('drop',p_drop,'offered',jsonb_build_object('amount',p_amount),p_actor);
  RETURN v;
END $$;

CREATE OR REPLACE FUNCTION kyc_submit(p_actor UUID, p_doc TEXT, p_selfie TEXT) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE v UUID;
BEGIN
  INSERT INTO kyc_records(plumper_id,doc_url,selfie_url) VALUES (p_actor,p_doc,p_selfie) RETURNING id INTO v;
  UPDATE plumpers SET kyc_status='pending' WHERE id=p_actor AND kyc_status IN ('none','rejected');
  PERFORM _log('kyc',v,'submitted','{}',p_actor); RETURN v;
END $$;

CREATE OR REPLACE FUNCTION kyc_review(p_record UUID, p_approve BOOLEAN, p_admin TEXT) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN
  SELECT * INTO r FROM kyc_records WHERE id=p_record FOR UPDATE;
  IF r.status <> 'pending' THEN RAISE EXCEPTION 'kyc_not_pending'; END IF;
  UPDATE kyc_records SET status=CASE WHEN p_approve THEN 'approved' ELSE 'rejected' END,
    reviewed_by=p_admin, reviewed_at=now() WHERE id=p_record;
  UPDATE plumpers SET kyc_status=CASE WHEN p_approve THEN 'verified' ELSE 'rejected' END
    WHERE id=r.plumper_id;
  PERFORM _log('kyc',p_record, CASE WHEN p_approve THEN 'approved' ELSE 'rejected' END,'{}',NULL);
END $$;

CREATE OR REPLACE FUNCTION price_reference(p_kind TEXT)
RETURNS TABLE(n BIGINT, p_min BIGINT, p_max BIGINT) LANGUAGE sql STABLE AS $$
  SELECT count(*), COALESCE(min(agreed),0), COALESCE(max(agreed),0)
  FROM deals dl JOIN drops d ON d.id=dl.drop_id
  WHERE dl.state='SETTLED' AND d.kind=p_kind $$;
