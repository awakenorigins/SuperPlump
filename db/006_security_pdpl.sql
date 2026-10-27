-- ============================================================
-- 006 · TẦNG A — SECURITY + PDPL PACK (Luật 91/2025/QH15 + NĐ 356/2025)
-- ============================================================

-- ---------- REALTIME HOOK: _log giờ phát pg_notify cho lớp WebSocket ----------
CREATE OR REPLACE FUNCTION _log(a_type TEXT, a_id UUID, e_type TEXT, p JSONB, act UUID)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO events(aggregate_type,aggregate_id,event_type,payload,actor)
  VALUES (a_type,a_id,e_type,COALESCE(p,'{}'::jsonb),act);
  PERFORM pg_notify('plump_events',
    json_build_object('agg',a_type,'id',a_id,'type',e_type)::text);
END $$;

-- ---------- CONSENT GRANULAR (Điều 4: quyền đồng ý / rút lại) ----------
CREATE TABLE consents (
  owner UUID NOT NULL REFERENCES plumpers(id),
  purpose TEXT NOT NULL CHECK (purpose IN
    ('location','marketing','twin_training','analytics','cross_border')),
  granted BOOLEAN NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (owner, purpose)
);
CREATE OR REPLACE FUNCTION set_consent(p_actor UUID, p_purpose TEXT, p_granted BOOLEAN)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO consents(owner,purpose,granted) VALUES (p_actor,p_purpose,p_granted)
  ON CONFLICT (owner,purpose) DO UPDATE SET granted=p_granted, updated_at=now();
  PERFORM _log('consent',p_actor, CASE WHEN p_granted THEN 'granted' ELSE 'withdrawn' END,
    jsonb_build_object('purpose',p_purpose), p_actor);
END $$;
CREATE OR REPLACE FUNCTION has_consent(p_actor UUID, p_purpose TEXT)
RETURNS BOOLEAN LANGUAGE sql STABLE AS
$$ SELECT COALESCE((SELECT granted FROM consents WHERE owner=p_actor AND purpose=p_purpose), false) $$;

-- Gate consent vị trí cho drop 'local' — bật/tắt bằng config để không phá dữ liệu cũ
INSERT INTO config VALUES ('pdpl','{"enforce_location_consent":false}')
  ON CONFLICT (key) DO NOTHING;
CREATE OR REPLACE FUNCTION create_drop(p_actor UUID, p_kind TEXT, p_title TEXT,
  p_desc TEXT, p_price BIGINT, p_lng FLOAT, p_lat FLOAT) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE v UUID;
BEGIN
  PERFORM _require_verified(p_actor);
  IF p_kind='local'
     AND (SELECT (val->>'enforce_location_consent')::bool FROM config WHERE key='pdpl')
     AND NOT has_consent(p_actor,'location')
  THEN RAISE EXCEPTION 'consent_required:location'; END IF;
  INSERT INTO drops(owner,kind,title,description,price,location)
  VALUES (p_actor,p_kind,p_title,COALESCE(p_desc,''),p_price,
    CASE WHEN p_lng IS NULL THEN NULL
         ELSE ST_SetSRID(ST_MakePoint(p_lng,p_lat),4326)::geography END)
  RETURNING id INTO v;
  PERFORM _log('drop',v,'created',jsonb_build_object('price',p_price,'kind',p_kind),p_actor);
  RETURN v;
END $$;

-- ---------- QUYỀN CHỦ THỂ DỮ LIỆU (truy cập / xóa / rút / hạn chế) ----------
CREATE TABLE data_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner UUID NOT NULL REFERENCES plumpers(id),
  kind TEXT NOT NULL CHECK (kind IN ('access','delete','withdraw','restrict')),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done','rejected')),
  note TEXT DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ
);
CREATE OR REPLACE FUNCTION submit_data_request(p_actor UUID, p_kind TEXT, p_note TEXT)
RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE v UUID;
BEGIN
  INSERT INTO data_requests(owner,kind,note) VALUES (p_actor,p_kind,COALESCE(p_note,''))
  RETURNING id INTO v;
  PERFORM _log('data_request',v,'submitted',jsonb_build_object('kind',p_kind),p_actor);
  RETURN v;
END $$;
-- "Quyền được lãng quên": scrub PII, GIỮ sổ tiền/sự kiện (nghĩa vụ kế toán)
CREATE OR REPLACE FUNCTION process_data_request(p_req UUID, p_admin TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN
  SELECT * INTO r FROM data_requests WHERE id=p_req FOR UPDATE;
  IF r.status<>'pending' THEN RAISE EXCEPTION 'request_not_pending'; END IF;
  IF r.kind='delete' THEN
    UPDATE plumpers SET display_name='Đã xóa theo yêu cầu',
      handle='deleted_'||substr(md5(random()::text),1,10), kyc_status='none'
      WHERE id=r.owner;
    UPDATE kyc_records SET provider_ref=NULL, doc_url='', selfie_url='' WHERE plumper_id=r.owner;
  END IF;
  UPDATE data_requests SET status='done', processed_at=now() WHERE id=p_req;
  PERFORM _log('data_request',p_req,'processed',jsonb_build_object('kind',r.kind,'by',p_admin),NULL);
END $$;

-- ---------- SỰ CỐ 72 GIỜ (Điều 23.1) ----------
CREATE TABLE incidents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  severity TEXT NOT NULL CHECK (severity IN ('low','high','critical')),
  summary TEXT NOT NULL,
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  authority_deadline TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '72 hours'),
  reported_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','reported','closed'))
);

-- ---------- eKYC THEO ĐIỀU 29: KHÔNG tự thu ảnh giấy tờ ----------
ALTER TABLE kyc_records
  ALTER COLUMN doc_url SET DEFAULT '', ALTER COLUMN doc_url DROP NOT NULL,
  ALTER COLUMN selfie_url SET DEFAULT '', ALTER COLUMN selfie_url DROP NOT NULL,
  ADD COLUMN IF NOT EXISTS provider TEXT,
  ADD COLUMN IF NOT EXISTS provider_ref TEXT;
CREATE OR REPLACE FUNCTION kyc_submit_ekyc(p_actor UUID, p_provider TEXT, p_ref TEXT)
RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE v UUID;
BEGIN
  IF p_provider NOT IN ('vneid','vnpt_ekyc','fpt_ekyc') THEN RAISE EXCEPTION 'bad_provider'; END IF;
  INSERT INTO kyc_records(plumper_id,provider,provider_ref) VALUES (p_actor,p_provider,p_ref)
  RETURNING id INTO v;
  UPDATE plumpers SET kyc_status='pending' WHERE id=p_actor AND kyc_status IN ('none','rejected');
  PERFORM _log('kyc',v,'submitted_ekyc',jsonb_build_object('provider',p_provider),p_actor);
  RETURN v;
END $$;

-- ---------- IDEMPOTENCY TTL ----------
CREATE OR REPLACE FUNCTION cleanup_idempotency(p_hours INT DEFAULT 48) RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE n INT;
BEGIN
  DELETE FROM idempotency_keys WHERE created_at < now() - make_interval(hours=>p_hours);
  GET DIAGNOSTICS n = ROW_COUNT; RETURN n;
END $$;
