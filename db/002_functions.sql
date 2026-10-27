-- ============================================================
-- SUPERPLUMP CORE V1 · 002_functions.sql
-- Luật: client không bao giờ được tin — mọi transition đi qua đây.
-- ============================================================

-- ---------- HELPERS ----------
CREATE OR REPLACE FUNCTION _fee_bps(side TEXT) RETURNS INT LANGUAGE sql STABLE AS
$$ SELECT (val->>CASE WHEN side='dropper' THEN 'fee_bps_dropper' ELSE 'fee_bps_executor' END)::INT
   FROM config WHERE key='fees' $$;

CREATE OR REPLACE FUNCTION _wallet(p_owner UUID, p_kind TEXT) RETURNS UUID LANGUAGE sql STABLE AS
$$ SELECT id FROM wallets WHERE (owner = p_owner OR (owner IS NULL AND p_owner IS NULL)) AND kind = p_kind $$;

CREATE OR REPLACE FUNCTION _log(a_type TEXT, a_id UUID, e_type TEXT, p JSONB, act UUID)
RETURNS VOID LANGUAGE sql AS
$$ INSERT INTO events(aggregate_type,aggregate_id,event_type,payload,actor)
   VALUES (a_type,a_id,e_type,COALESCE(p,'{}'::jsonb),act) $$;

-- BÚT TOÁN KÉP: một lần chuyển = hai dòng đối ứng, tổng luôn = 0
CREATE OR REPLACE FUNCTION _move(p_deal UUID, p_from UUID, p_to UUID, p_amount BIGINT, p_kind TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
  IF p_amount <= 0 THEN RAISE EXCEPTION 'move_amount_invalid'; END IF;
  UPDATE wallets SET balance = balance - p_amount WHERE id = p_from;  -- CHECK(balance>=0) tự gác số âm
  UPDATE wallets SET balance = balance + p_amount WHERE id = p_to;
  INSERT INTO ledger_entries(deal_id,wallet_id,kind,amount) VALUES
    (p_deal, p_from, p_kind, -p_amount),
    (p_deal, p_to,   p_kind,  p_amount);
END $$;

-- ---------- NẠP ----------
CREATE OR REPLACE FUNCTION topup(p_user UUID, p_amount BIGINT) RETURNS VOID
LANGUAGE plpgsql AS $$
BEGIN
  IF p_amount <= 0 THEN RAISE EXCEPTION 'invalid_amount'; END IF;
  UPDATE wallets SET balance = balance + p_amount WHERE id = _wallet(p_user,'user');
  INSERT INTO ledger_entries(wallet_id,kind,amount) VALUES (_wallet(p_user,'user'),'topup',p_amount);
  PERFORM _log('wallet', p_user, 'topup', jsonb_build_object('amount',p_amount), p_user);
END $$;

-- ---------- ACCEPT OFFER: transaction nguyên tử, chống race ----------
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

  INSERT INTO deals(drop_id,dropper,executor,agreed,hold_amount)
    VALUES (d.id, d.owner, o.from_id, o.amount, v_hold)
    RETURNING id INTO v_deal;                                       -- unique index gác lần 2

  PERFORM _move(v_deal, _wallet(d.owner,'user'), _wallet(NULL,'escrow'), v_hold, 'hold');
  UPDATE drops  SET status='matched'  WHERE id = d.id;
  UPDATE offers SET status='accepted' WHERE id = p_offer;
  UPDATE offers SET status='void' WHERE drop_id = d.id AND id <> p_offer AND status='pending';
  PERFORM _log('deal', v_deal, 'locked',
    jsonb_build_object('agreed',o.amount,'hold',v_hold,'executor',o.from_id), p_actor);
  RETURN v_deal;
END $$;

-- ---------- TRANSITIONS ----------
CREATE OR REPLACE FUNCTION deal_start(p_deal UUID, p_actor UUID) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE d RECORD;
BEGIN
  SELECT * INTO d FROM deals WHERE id = p_deal FOR UPDATE;
  IF d.executor <> p_actor THEN RAISE EXCEPTION 'only_executor_starts'; END IF;
  IF d.state <> 'LOCKED' THEN RAISE EXCEPTION 'invalid_transition:%',d.state; END IF;
  UPDATE deals SET state='IN_PROGRESS', started_at=now() WHERE id=p_deal;
  PERFORM _log('deal',p_deal,'started','{}',p_actor);
END $$;

CREATE OR REPLACE FUNCTION deal_submit(p_deal UUID, p_actor UUID, p_media TEXT DEFAULT NULL)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE d RECORD;
BEGIN
  SELECT * INTO d FROM deals WHERE id = p_deal FOR UPDATE;
  IF d.executor <> p_actor THEN RAISE EXCEPTION 'only_executor_submits'; END IF;
  IF d.state <> 'IN_PROGRESS' THEN RAISE EXCEPTION 'invalid_transition:%',d.state; END IF;
  IF p_media IS NOT NULL THEN
    INSERT INTO proofs(deal_id,uploader,media_url) VALUES (p_deal,p_actor,p_media);
  END IF;
  UPDATE deals SET state='SUBMITTED', submitted_at=now() WHERE id=p_deal;
  PERFORM _log('deal',p_deal,'submitted',jsonb_build_object('proof',p_media),p_actor);
END $$;

-- Tất toán (dùng chung cho confirm / auto-confirm / release theo phán quyết)
CREATE OR REPLACE FUNCTION _settle(p_deal UUID, p_actor UUID, p_via TEXT) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE d RECORD; v_fee_e BIGINT; v_net BIGINT; v_plat BIGINT;
BEGIN
  SELECT * INTO d FROM deals WHERE id = p_deal;
  v_fee_e := d.agreed * _fee_bps('executor') / 10000;
  v_net   := d.agreed - v_fee_e;
  v_plat  := d.hold_amount - v_net;   -- fee_dropper + fee_executor, két về 0 tuyệt đối
  PERFORM _move(p_deal, _wallet(NULL,'escrow'), _wallet(d.executor,'user'), v_net,  'release_net');
  PERFORM _move(p_deal, _wallet(NULL,'escrow'), _wallet(NULL,'platform'),   v_plat, 'fee');
  UPDATE deals SET state='SETTLED', settled_at=now() WHERE id=p_deal;
  PERFORM _log('deal',p_deal,'settled',
    jsonb_build_object('net',v_net,'platform_fee',v_plat,'via',p_via), p_actor);
END $$;

CREATE OR REPLACE FUNCTION deal_confirm(p_deal UUID, p_actor UUID) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE d RECORD;
BEGIN
  SELECT * INTO d FROM deals WHERE id = p_deal FOR UPDATE;
  IF d.dropper <> p_actor THEN RAISE EXCEPTION 'only_dropper_confirms'; END IF;
  IF d.state <> 'SUBMITTED' THEN RAISE EXCEPTION 'invalid_transition:%',d.state; END IF;
  PERFORM _settle(p_deal, p_actor, 'confirm');
END $$;

-- Bảo vệ người làm: im lặng quá hạn → hệ thống xác nhận
CREATE OR REPLACE FUNCTION auto_confirm_overdue() RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE r RECORD; n INT := 0; hrs INT;
BEGIN
  SELECT (val->>'autoconfirm_hours')::INT INTO hrs FROM config WHERE key='deal';
  FOR r IN SELECT id FROM deals
           WHERE state='SUBMITTED' AND submitted_at < now() - make_interval(hours=>hrs)
           FOR UPDATE SKIP LOCKED
  LOOP
    PERFORM _settle(r.id, NULL, 'auto_confirm'); n := n + 1;
  END LOOP;
  RETURN n;
END $$;

-- ---------- TRANH CHẤP ----------
CREATE OR REPLACE FUNCTION open_dispute(p_deal UUID, p_actor UUID, p_reason TEXT) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE d RECORD; v UUID;
BEGIN
  SELECT * INTO d FROM deals WHERE id = p_deal FOR UPDATE;
  IF p_actor NOT IN (d.dropper, d.executor) THEN RAISE EXCEPTION 'not_participant'; END IF;
  IF d.state NOT IN ('LOCKED','IN_PROGRESS','SUBMITTED') THEN
    RAISE EXCEPTION 'invalid_transition:%',d.state; END IF;
  UPDATE deals SET state='DISPUTED' WHERE id=p_deal;
  INSERT INTO disputes(deal_id,opened_by,reason) VALUES (p_deal,p_actor,p_reason) RETURNING id INTO v;
  PERFORM _log('deal',p_deal,'disputed',jsonb_build_object('reason',p_reason),p_actor);
  RETURN v;
END $$;

CREATE OR REPLACE FUNCTION resolve_dispute(p_deal UUID, p_outcome TEXT, p_admin UUID) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE d RECORD; half BIGINT;
BEGIN
  SELECT * INTO d FROM deals WHERE id = p_deal FOR UPDATE;
  IF d.state <> 'DISPUTED' THEN RAISE EXCEPTION 'invalid_transition:%',d.state; END IF;
  IF p_outcome = 'release' THEN
    PERFORM _settle(p_deal, p_admin, 'dispute_release');
  ELSIF p_outcome = 'refund' THEN
    PERFORM _move(p_deal, _wallet(NULL,'escrow'), _wallet(d.dropper,'user'), d.hold_amount, 'refund');
    UPDATE deals SET state='CANCELLED' WHERE id=p_deal;
  ELSIF p_outcome = 'split' THEN
    half := d.hold_amount / 2;
    PERFORM _move(p_deal, _wallet(NULL,'escrow'), _wallet(d.executor,'user'), half, 'release_net');
    PERFORM _move(p_deal, _wallet(NULL,'escrow'), _wallet(d.dropper,'user'), d.hold_amount - half, 'refund');
    UPDATE deals SET state='SETTLED', settled_at=now() WHERE id=p_deal;
  ELSE RAISE EXCEPTION 'bad_outcome';
  END IF;
  UPDATE disputes SET status='resolved', resolution=p_outcome, resolved_by=p_admin, resolved_at=now()
    WHERE deal_id=p_deal AND status='open';
  PERFORM _log('deal',p_deal,'dispute_resolved',jsonb_build_object('outcome',p_outcome),p_admin);
END $$;

-- ---------- ĐÁNH GIÁ MÙ ----------
CREATE OR REPLACE FUNCTION submit_review(p_deal UUID, p_author UUID, p_rating INT, p_body TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE d RECORD; tgt UUID;
BEGIN
  SELECT * INTO d FROM deals WHERE id = p_deal;
  IF d.state NOT IN ('SETTLED') THEN RAISE EXCEPTION 'deal_not_settled'; END IF;
  IF p_author NOT IN (d.dropper, d.executor) THEN RAISE EXCEPTION 'not_participant'; END IF;
  tgt := CASE WHEN p_author = d.dropper THEN d.executor ELSE d.dropper END;
  INSERT INTO reviews(deal_id,author,target,rating,body) VALUES (p_deal,p_author,tgt,p_rating,p_body);
  PERFORM _log('deal',p_deal,'review_submitted',jsonb_build_object('by',p_author),p_author);
END $$;

-- Luật mù nằm ở TẦNG DỮ LIỆU: chỉ lộ khi cả hai đã nộp
CREATE OR REPLACE VIEW deal_reviews_visible AS
SELECT r.* FROM reviews r
WHERE (SELECT count(*) FROM reviews r2 WHERE r2.deal_id = r.deal_id) = 2;

-- ---------- RIÊNG TƯ VỊ TRÍ ----------
-- View công khai: tọa độ LUÔN bị snap lưới ~300m
CREATE OR REPLACE VIEW drops_public AS
SELECT d.id, d.kind, d.title, d.description, d.price, d.status, d.created_at,
  ST_X(ST_SnapToGrid(d.location::geometry,
      (SELECT (val->>'fuzz_grid_deg')::float FROM config WHERE key='deal'))) AS fuzzy_lng,
  ST_Y(ST_SnapToGrid(d.location::geometry,
      (SELECT (val->>'fuzz_grid_deg')::float FROM config WHERE key='deal'))) AS fuzzy_lat
FROM drops d;

-- Tọa độ thật: CHỈ hai bên của deal đã LOCKED trở lên
CREATE OR REPLACE FUNCTION exact_location(p_deal UUID, p_actor UUID)
RETURNS TABLE(lng FLOAT, lat FLOAT) LANGUAGE plpgsql AS $$
DECLARE d RECORD;
BEGIN
  SELECT dl.*, dr.location AS loc INTO d
  FROM deals dl JOIN drops dr ON dr.id = dl.drop_id WHERE dl.id = p_deal;
  IF NOT FOUND THEN RAISE EXCEPTION 'deal_not_found'; END IF;
  IF p_actor NOT IN (d.dropper, d.executor) THEN RAISE EXCEPTION 'location_denied'; END IF;
  RETURN QUERY SELECT ST_X(d.loc::geometry), ST_Y(d.loc::geometry);
END $$;

-- ---------- ĐỐI SOÁT: ví phải = Σ sổ ----------
CREATE OR REPLACE FUNCTION reconcile() RETURNS TABLE(wallet_id UUID, wallet_bal BIGINT, ledger_sum BIGINT)
LANGUAGE sql AS $$
  SELECT w.id, w.balance, COALESCE(SUM(l.amount),0)
  FROM wallets w LEFT JOIN ledger_entries l ON l.wallet_id = w.id
  GROUP BY w.id, w.balance
  HAVING w.balance <> COALESCE(SUM(l.amount),0)
$$;
