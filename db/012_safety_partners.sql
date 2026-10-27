-- 012 · PARTNER SEAMS + TRUST & SAFETY
-- ---------- Thanh toán qua đối tác licensed (NĐ 52/2024): intent + webhook idempotent ----------
CREATE TABLE payment_intents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plumper_id UUID NOT NULL REFERENCES plumpers(id),
  amount BIGINT NOT NULL CHECK (amount > 0),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','paid','expired')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE payment_events (
  provider_ref TEXT PRIMARY KEY,          -- idempotency: mỗi giao dịch đối tác chỉ ghi có MỘT lần
  intent_id UUID NOT NULL REFERENCES payment_intents(id),
  amount BIGINT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- ---------- Trust & Safety ----------
ALTER TABLE plumpers ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMPTZ;
ALTER TABLE drops ADD COLUMN IF NOT EXISTS mod_status TEXT NOT NULL DEFAULT 'pending'
  CHECK (mod_status IN ('pending','ok','flagged'));
CREATE TABLE banned_words (word TEXT PRIMARY KEY);
INSERT INTO banned_words VALUES ('ma túy'),('vũ khí quân dụng'),('test-banned-word') ON CONFLICT DO NOTHING;
INSERT INTO config VALUES ('safety','{"max_drops_per_hour":30}') ON CONFLICT (key) DO NOTHING;

CREATE TABLE reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reporter UUID NOT NULL REFERENCES plumpers(id),
  target_kind TEXT NOT NULL CHECK (target_kind IN ('drop','plumper','moment','message')),
  target_id UUID NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','actioned','dismissed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  actioned_at TIMESTAMPTZ, action TEXT
);
CREATE TABLE fraud_flags (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind TEXT NOT NULL,
  a UUID NOT NULL, b UUID NOT NULL,
  deal_id UUID, note TEXT DEFAULT '',
  day DATE NOT NULL DEFAULT CURRENT_DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (kind, a, b, day)
);

-- Treo tài khoản chặn từ gốc: mọi hành động cần verified đều dính
CREATE OR REPLACE FUNCTION _require_verified(p UUID) RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN
  SELECT kyc_status, suspended_at INTO r FROM plumpers WHERE id=p;
  IF r.suspended_at IS NOT NULL THEN RAISE EXCEPTION 'account_suspended'; END IF;
  IF r.kyc_status IS DISTINCT FROM 'verified' THEN RAISE EXCEPTION 'kyc_required'; END IF;
END $$;

-- create_drop v3: consent gate (006) + lọc từ cấm + phanh tốc độ
CREATE OR REPLACE FUNCTION create_drop(p_actor UUID, p_kind TEXT, p_title TEXT,
  p_desc TEXT, p_price BIGINT, p_lng FLOAT, p_lat FLOAT) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE v UUID; n_hour INT; lim INT;
BEGIN
  PERFORM _require_verified(p_actor);
  IF p_kind='local'
     AND (SELECT (val->>'enforce_location_consent')::bool FROM config WHERE key='pdpl')
     AND NOT has_consent(p_actor,'location')
  THEN RAISE EXCEPTION 'consent_required:location'; END IF;
  IF EXISTS (SELECT 1 FROM banned_words w
             WHERE position(w.word IN lower(p_title || ' ' || COALESCE(p_desc,''))) > 0)
  THEN RAISE EXCEPTION 'content_blocked'; END IF;
  SELECT (val->>'max_drops_per_hour')::INT INTO lim FROM config WHERE key='safety';
  SELECT count(*) INTO n_hour FROM drops WHERE owner=p_actor AND created_at > now() - interval '1 hour';
  IF n_hour >= lim THEN RAISE EXCEPTION 'velocity_limited'; END IF;
  INSERT INTO drops(owner,kind,title,description,price,location)
  VALUES (p_actor,p_kind,p_title,COALESCE(p_desc,''),p_price,
    CASE WHEN p_lng IS NULL THEN NULL
         ELSE ST_SetSRID(ST_MakePoint(p_lng,p_lat),4326)::geography END)
  RETURNING id INTO v;
  PERFORM _log('drop',v,'created',jsonb_build_object('price',p_price,'kind',p_kind),p_actor);
  RETURN v;
END $$;

CREATE OR REPLACE FUNCTION submit_report(p_actor UUID, p_kind TEXT, p_target UUID, p_reason TEXT)
RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE v UUID;
BEGIN
  INSERT INTO reports(reporter,target_kind,target_id,reason) VALUES (p_actor,p_kind,p_target,p_reason)
  RETURNING id INTO v;
  PERFORM _log('report',v,'submitted',jsonb_build_object('kind',p_kind,'target',p_target),p_actor);
  RETURN v;
END $$;

-- Trigger settle v2: + radar thông đồng (cùng cặp settle ≥4 deal/ngày → cắm cờ)
CREATE OR REPLACE FUNCTION _after_settle() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE t TEXT; n_pair INT;
BEGIN
  IF NEW.state='SETTLED' AND OLD.state IS DISTINCT FROM 'SETTLED' THEN
    INSERT INTO connections(a,b,first_deal)
      VALUES (LEAST(NEW.dropper,NEW.executor),GREATEST(NEW.dropper,NEW.executor),NEW.id)
      ON CONFLICT DO NOTHING;
    SELECT title INTO t FROM drops WHERE id=NEW.drop_id;
    INSERT INTO moments(owner,deal_id,title,quote) VALUES
      (NEW.executor,NEW.id,'Hoàn thành "'||t||'"','★ đang chờ mở mù'),
      (NEW.dropper, NEW.id,'Việc "'||t||'" xong đẹp','★ đang chờ mở mù');
    INSERT INTO plump_points(owner,amount,reason,deal_id) VALUES
      (NEW.executor,500,'settle_executor',NEW.id),
      (NEW.dropper, 200,'settle_dropper', NEW.id);
    PERFORM notify_user(NEW.executor,'settled','Tiền đã về ví · +🍑500',NEW.id);
    PERFORM notify_user(NEW.dropper,'settled','Deal hoàn tất · +🍑200 · đã kết nối',NEW.id);
    SELECT count(*) INTO n_pair FROM deals
      WHERE state='SETTLED' AND settled_at::date = CURRENT_DATE
        AND LEAST(dropper,executor)=LEAST(NEW.dropper,NEW.executor)
        AND GREATEST(dropper,executor)=GREATEST(NEW.dropper,NEW.executor);
    IF n_pair >= 4 THEN
      INSERT INTO fraud_flags(kind,a,b,deal_id,note)
      VALUES ('pair_velocity',LEAST(NEW.dropper,NEW.executor),GREATEST(NEW.dropper,NEW.executor),
              NEW.id, n_pair || ' deal cùng cặp trong ngày — nghi farm điểm/rửa phí')
      ON CONFLICT DO NOTHING;
    END IF;
  END IF;
  RETURN NEW;
END $$;
