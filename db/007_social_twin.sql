-- ============================================================
-- 007 · TẦNG B — SOCIAL BACKEND + TWIN ECONOMY (chạy bằng trigger, không tin client)
-- ============================================================

-- ---------- CATEGORY cho chợ & Qualify khớp nhau ----------
ALTER TABLE drops ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'general';
ALTER TABLE deals ADD COLUMN IF NOT EXISTS twin_id UUID REFERENCES twins(id);
ALTER TABLE offers ADD COLUMN IF NOT EXISTS twin_id UUID REFERENCES twins(id);

-- ---------- SOCIAL TABLES ----------
CREATE TABLE connections (
  a UUID NOT NULL REFERENCES plumpers(id),
  b UUID NOT NULL REFERENCES plumpers(id),
  first_deal UUID REFERENCES deals(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (a,b), CHECK (a < b)
);
CREATE OR REPLACE FUNCTION are_connected(x UUID, y UUID) RETURNS BOOLEAN LANGUAGE sql STABLE AS
$$ SELECT EXISTS(SELECT 1 FROM connections WHERE a=LEAST(x,y) AND b=GREATEST(x,y)) $$;

CREATE TABLE messages (
  id BIGSERIAL PRIMARY KEY,
  deal_id UUID REFERENCES deals(id),            -- chat neo deal
  dm_a UUID, dm_b UUID,                          -- hoặc DM sau kết nối (a<b)
  sender UUID NOT NULL REFERENCES plumpers(id),
  body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ( (deal_id IS NOT NULL) <> (dm_a IS NOT NULL AND dm_b IS NOT NULL) )
);
CREATE INDEX msg_deal_idx ON messages(deal_id, id);
CREATE OR REPLACE FUNCTION send_message(p_actor UUID, p_deal UUID, p_peer UUID, p_body TEXT)
RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE d RECORD; v BIGINT;
BEGIN
  IF p_deal IS NOT NULL THEN
    SELECT * INTO d FROM deals WHERE id=p_deal;
    IF p_actor NOT IN (d.dropper,d.executor) THEN RAISE EXCEPTION 'not_participant'; END IF;
    INSERT INTO messages(deal_id,sender,body) VALUES (p_deal,p_actor,p_body) RETURNING id INTO v;
    PERFORM _log('deal',p_deal,'message',jsonb_build_object('by',p_actor),p_actor);
  ELSE
    IF NOT are_connected(p_actor,p_peer) THEN RAISE EXCEPTION 'dm_requires_connection'; END IF;
    INSERT INTO messages(dm_a,dm_b,sender,body)
      VALUES (LEAST(p_actor,p_peer),GREATEST(p_actor,p_peer),p_actor,p_body) RETURNING id INTO v;
    PERFORM _log('dm',p_actor,'message',jsonb_build_object('to',p_peer),p_actor);
  END IF;
  RETURN v;
END $$;

CREATE TABLE notifications (
  id BIGSERIAL PRIMARY KEY,
  owner UUID NOT NULL REFERENCES plumpers(id),
  kind TEXT NOT NULL, body TEXT NOT NULL, ref UUID,
  read_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX noti_owner_idx ON notifications(owner, id DESC);
CREATE OR REPLACE FUNCTION notify_user(p_owner UUID, p_kind TEXT, p_body TEXT, p_ref UUID)
RETURNS VOID LANGUAGE sql AS
$$ INSERT INTO notifications(owner,kind,body,ref) VALUES (p_owner,p_kind,p_body,p_ref);
   SELECT pg_notify('plump_events', json_build_object('agg','user','id',p_owner,'type','notification')::text) $$;

CREATE TABLE moments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner UUID NOT NULL REFERENCES plumpers(id),
  deal_id UUID REFERENCES deals(id),
  title TEXT NOT NULL, quote TEXT DEFAULT '',
  peaches INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION peach_moment(p_id UUID) RETURNS INT LANGUAGE plpgsql AS $$
DECLARE n INT; BEGIN UPDATE moments SET peaches=peaches+1 WHERE id=p_id RETURNING peaches INTO n;
IF NOT FOUND THEN RAISE EXCEPTION 'moment_not_found'; END IF; RETURN n; END $$;

-- ---------- ĐIỂM PLUMP: farm bằng lao động, không nạp được ----------
CREATE TABLE plump_points (
  id BIGSERIAL PRIMARY KEY,
  owner UUID NOT NULL REFERENCES plumpers(id),
  amount INT NOT NULL, reason TEXT NOT NULL, deal_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
REVOKE UPDATE, DELETE ON plump_points FROM PUBLIC;
CREATE OR REPLACE FUNCTION plump_balance(p UUID) RETURNS BIGINT LANGUAGE sql STABLE AS
$$ SELECT COALESCE(SUM(amount),0) FROM plump_points WHERE owner=p $$;
CREATE OR REPLACE FUNCTION leaderboard(p_period TEXT)
RETURNS TABLE(owner UUID, display_name TEXT, pts BIGINT) LANGUAGE sql STABLE AS $$
  SELECT pp.owner, p.display_name, SUM(pp.amount) pts
  FROM plump_points pp JOIN plumpers p ON p.id=pp.owner
  WHERE pp.created_at > now() - CASE p_period
    WHEN 'day' THEN interval '1 day' WHEN 'week' THEN interval '7 days'
    ELSE interval '30 days' END
  GROUP BY pp.owner, p.display_name
  ORDER BY pts DESC, MAX(pp.created_at) DESC LIMIT 20 $$;

-- ---------- TRIGGER SAU SETTLE: kết nối + khoảnh khắc + điểm + thông báo ----------
CREATE OR REPLACE FUNCTION _after_settle() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE t TEXT;
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
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_after_settle ON deals;
CREATE TRIGGER trg_after_settle AFTER UPDATE ON deals
  FOR EACH ROW EXECUTE FUNCTION _after_settle();

-- ---------- TWIN ECONOMY ----------
CREATE TABLE twin_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  twin_id UUID NOT NULL REFERENCES twins(id),
  deal_id UUID NOT NULL REFERENCES deals(id),
  brief TEXT NOT NULL, draft TEXT,
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','drafted','approved','rejected')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), drafted_at TIMESTAMPTZ
);
CREATE TABLE exam_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  twin_id UUID NOT NULL REFERENCES twins(id),
  category TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','failed')),
  machine_pass BOOLEAN, ai_score NUMERIC(3,1), human_pass BOOLEAN,
  level_granted TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Twin ngỏ lời: chủ thật đứng tên tiền, twin đứng tên lao động — cần Qualify đúng hạng mục + năng lượng
CREATE OR REPLACE FUNCTION create_offer_twin(p_owner UUID, p_twin UUID, p_drop UUID, p_amount BIGINT)
RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE v UUID; d RECORD; tw RECORD;
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
  INSERT INTO offers(drop_id,from_id,amount,twin_id) VALUES (p_drop,p_owner,p_amount,p_twin)
    RETURNING id INTO v;
  PERFORM _log('drop',p_drop,'offered_by_twin',
    jsonb_build_object('amount',p_amount,'twin',p_twin),p_owner);
  RETURN v;
END $$;

-- accept_offer v2: giữ nguyên toàn bộ luật cũ + nhánh twin (auto-start + xếp hàng job + trừ năng lượng)
CREATE OR REPLACE FUNCTION accept_offer(p_offer UUID, p_actor UUID) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE o RECORD; d RECORD; v_fee_d BIGINT; v_hold BIGINT; v_deal UUID; v_dropid UUID;
BEGIN
  -- THỨ TỰ KHÓA CHA→CON (chống deadlock AB-BA): drop trước, offer sau
  SELECT drop_id INTO v_dropid FROM offers WHERE id = p_offer;
  IF NOT FOUND THEN RAISE EXCEPTION 'offer_not_pending'; END IF;
  SELECT * INTO d FROM drops WHERE id = v_dropid FOR UPDATE;
  IF d.status <> 'open' THEN RAISE EXCEPTION 'drop_not_open'; END IF;
  SELECT * INTO o FROM offers WHERE id = p_offer FOR UPDATE;
  IF o.status <> 'pending' THEN RAISE EXCEPTION 'offer_not_pending'; END IF;
  IF d.owner <> p_actor THEN RAISE EXCEPTION 'only_dropper_accepts'; END IF;

  v_fee_d := o.amount * _fee_bps('dropper') / 10000;
  v_hold  := o.amount + v_fee_d;

  INSERT INTO deals(drop_id,dropper,executor,agreed,hold_amount,executor_kind,twin_id)
    VALUES (d.id, d.owner, o.from_id, o.amount, v_hold,
            CASE WHEN o.twin_id IS NULL THEN 'human' ELSE 'twin' END, o.twin_id)
    RETURNING id INTO v_deal;

  PERFORM _move(v_deal, _wallet(d.owner,'user'), _wallet(NULL,'escrow'), v_hold, 'hold');
  UPDATE drops  SET status='matched'  WHERE id = d.id;
  UPDATE offers SET status='accepted' WHERE id = p_offer;
  UPDATE offers SET status='void' WHERE drop_id = d.id AND id <> p_offer AND status='pending';
  PERFORM _log('deal', v_deal, 'locked',
    jsonb_build_object('agreed',o.amount,'hold',v_hold,'executor',o.from_id,
                       'executor_kind', CASE WHEN o.twin_id IS NULL THEN 'human' ELSE 'twin' END), p_actor);

  IF o.twin_id IS NOT NULL THEN
    UPDATE twins SET energy = energy - 5 WHERE id = o.twin_id;
    PERFORM deal_start(v_deal, o.from_id);       -- twin bắt tay ngay
    INSERT INTO twin_jobs(twin_id,deal_id,brief)
      VALUES (o.twin_id, v_deal, d.title || E'\n' || d.description);
    PERFORM notify_user(o.from_id,'twin_job','Twin nhận việc "'||d.title||'" — chờ draft',v_deal);
  END IF;
  RETURN v_deal;
END $$;

-- Chủ duyệt draft → nộp cho khách bằng chính máy trạng thái cũ
CREATE OR REPLACE FUNCTION approve_twin_job(p_job UUID, p_actor UUID) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE j RECORD; tw RECORD;
BEGIN
  SELECT * INTO j FROM twin_jobs WHERE id=p_job FOR UPDATE;
  SELECT * INTO tw FROM twins WHERE id=j.twin_id;
  IF tw.owner <> p_actor THEN RAISE EXCEPTION 'not_twin_owner'; END IF;
  IF j.status <> 'drafted' THEN RAISE EXCEPTION 'job_not_drafted'; END IF;
  UPDATE twin_jobs SET status='approved' WHERE id=p_job;
  PERFORM deal_submit(j.deal_id, p_actor, 'twin-draft://'||p_job);
END $$;

-- Hồ sơ công khai: dựng từ dữ liệu thật
CREATE OR REPLACE FUNCTION public_profile(p UUID)
RETURNS TABLE(display_name TEXT, done BIGINT, dropped BIGINT,
              avg_rating NUMERIC, connections BIGINT, plump BIGINT) LANGUAGE sql STABLE AS $$
  SELECT pl.display_name,
    (SELECT count(*) FROM deals WHERE executor=p AND state='SETTLED'),
    (SELECT count(*) FROM deals WHERE dropper=p AND state='SETTLED'),
    (SELECT ROUND(AVG(rating),2) FROM deal_reviews_visible WHERE target=p),
    (SELECT count(*) FROM connections WHERE a=p OR b=p),
    plump_balance(p)
  FROM plumpers pl WHERE pl.id=p $$;
