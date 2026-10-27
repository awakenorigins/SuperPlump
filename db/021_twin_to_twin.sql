-- ============================================================
-- 021 · BEAT 6 · TWIN-TO-TWIN (chợ việc số giữa các twin)
-- Twin A (chủ Lv5) đăng việc số nhỏ → twin B (đủ điều kiện) nhận → hai chủ cùng có lợi.
-- BƯỚC 1 (thận trọng): thanh toán cần CHỦ ĐĂNG DUYỆT LẦN ĐẦU với mỗi cặp chủ; sau đó tự động.
-- Agent tiêu tiền tự động không giám sát là chỗ dễ cháy → đi chậm ở đúng khúc này.
-- ============================================================

INSERT INTO config VALUES ('twin_market',
  '{"min_poster_level":5,"min_price_plump":50,"max_price_plump":100000}')
  ON CONFLICT (key) DO NOTHING;
-- min_poster_level: chỉ chủ Lv5 (Mận Kim Cương) mới được đăng việc twin-to-twin.
-- giá tính bằng Plump (lao động số giữa agent). Khoảng giá hợp lệ.

-- Việc số do twin đăng cho twin khác làm
CREATE TABLE twin_market_drops (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  poster_twin  UUID NOT NULL REFERENCES twins(id),
  poster_owner UUID NOT NULL REFERENCES plumpers(id),
  category TEXT NOT NULL,
  title TEXT NOT NULL,
  brief TEXT NOT NULL DEFAULT '',
  price_plump BIGINT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','matched','done','cancelled')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_tmkt_open ON twin_market_drops(status) WHERE status='open';

-- Giao dịch twin-to-twin
CREATE TABLE twin_market_deals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  market_drop_id UUID NOT NULL REFERENCES twin_market_drops(id),
  taker_twin  UUID NOT NULL REFERENCES twins(id),
  taker_owner UUID NOT NULL REFERENCES plumpers(id),
  price_plump BIGINT NOT NULL,
  state TEXT NOT NULL DEFAULT 'PENDING_APPROVAL'
    CHECK (state IN ('PENDING_APPROVAL','APPROVED','SETTLED','REJECTED')),
  needs_first_approval BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  settled_at TIMESTAMPTZ
);

-- Ghi nhớ cặp chủ ĐÃ duyệt lần đầu → lần sau tự động (không cần duyệt lại)
CREATE TABLE twin_market_trusted_pairs (
  poster_owner UUID NOT NULL REFERENCES plumpers(id),
  taker_owner  UUID NOT NULL REFERENCES plumpers(id),
  first_approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (poster_owner, taker_owner)
);

-- Đăng việc twin-to-twin (gate Lv5)
CREATE OR REPLACE FUNCTION post_twin_market(p_owner UUID, p_twin UUID, p_category TEXT,
                                            p_title TEXT, p_brief TEXT, p_price BIGINT) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE cfg JSONB; minlv INT; tw RECORD; new_id UUID;
BEGIN
  SELECT val INTO cfg FROM config WHERE key='twin_market';
  minlv := (cfg->>'min_poster_level')::INT;
  SELECT * INTO tw FROM twins WHERE id=p_twin;
  IF tw.owner <> p_owner THEN RAISE EXCEPTION 'not_twin_owner'; END IF;
  IF plump_level(p_owner) < minlv THEN
    RAISE EXCEPTION 'twin_market_requires_level:% (bạn Lv%)', minlv, plump_level(p_owner);
  END IF;
  IF p_price < (cfg->>'min_price_plump')::BIGINT OR p_price > (cfg->>'max_price_plump')::BIGINT THEN
    RAISE EXCEPTION 'twin_market_price_out_of_range';
  END IF;
  PERFORM _twin_can_work(p_twin);   -- twin đăng cũng phải không bị treo/xoá
  INSERT INTO twin_market_drops(poster_twin,poster_owner,category,title,brief,price_plump)
    VALUES (p_twin,p_owner,p_category,p_title,p_brief,p_price) RETURNING id INTO new_id;
  RETURN new_id;
END $$;

-- Twin B nhận việc twin-to-twin. Kiểm mọi guard việc (qualified/mandate/energy/không treo).
-- Tạo deal PENDING_APPROVAL nếu cặp chủ chưa từng duyệt; nếu đã tin nhau → APPROVED luôn.
CREATE OR REPLACE FUNCTION take_twin_market(p_taker_owner UUID, p_taker_twin UUID, p_market_drop UUID) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE md RECORD; tw RECORD; m twin_mandates; trusted BOOLEAN; new_deal UUID; v_cost INT;
BEGIN
  PERFORM _require_verified(p_taker_owner);
  SELECT * INTO md FROM twin_market_drops WHERE id=p_market_drop FOR UPDATE;
  IF md.status <> 'open' THEN RAISE EXCEPTION 'twin_market_not_open'; END IF;
  IF md.poster_owner = p_taker_owner THEN RAISE EXCEPTION 'twin_market_self_dealing'; END IF;

  SELECT * INTO tw FROM twins WHERE id=p_taker_twin;
  IF tw.owner <> p_taker_owner THEN RAISE EXCEPTION 'not_twin_owner'; END IF;
  PERFORM _twin_can_work(p_taker_twin);                 -- không treo/xoá
  PERFORM apply_energy_regen(p_taker_twin);
  v_cost := twin_job_cost(p_taker_twin);
  IF (SELECT energy FROM twins WHERE id=p_taker_twin) < v_cost THEN RAISE EXCEPTION 'twin_no_energy'; END IF;

  -- twin nhận phải qualified đúng category + mandate phủ category
  IF NOT EXISTS (SELECT 1 FROM qualifications q
                 WHERE q.twin_id=p_taker_twin AND q.category=md.category AND q.revoked_at IS NULL)
  THEN RAISE EXCEPTION 'twin_not_qualified:%', md.category; END IF;
  m := active_mandate(p_taker_twin);
  IF m.id IS NULL THEN RAISE EXCEPTION 'mandate_missing'; END IF;
  IF NOT (md.category = ANY(m.categories)) THEN RAISE EXCEPTION 'mandate_scope_violation:%', md.category; END IF;
  IF md.price_plump > m.max_price THEN RAISE EXCEPTION 'mandate_price_violation'; END IF;

  -- chủ đăng đủ Plump trả?
  IF plump_balance(md.poster_owner) < md.price_plump THEN RAISE EXCEPTION 'poster_insufficient_plump'; END IF;

  SELECT EXISTS(SELECT 1 FROM twin_market_trusted_pairs
                WHERE poster_owner=md.poster_owner AND taker_owner=p_taker_owner) INTO trusted;

  -- trừ energy twin nhận (nó đang làm việc)
  UPDATE twins SET energy = energy - v_cost, energy_updated_at=now() WHERE id=p_taker_twin;
  UPDATE twin_market_drops SET status='matched' WHERE id=p_market_drop;

  INSERT INTO twin_market_deals(market_drop_id,taker_twin,taker_owner,price_plump,state,needs_first_approval)
    VALUES (p_market_drop,p_taker_twin,p_taker_owner,md.price_plump,
            CASE WHEN trusted THEN 'APPROVED' ELSE 'PENDING_APPROVAL' END,
            NOT trusted)
    RETURNING id INTO new_deal;

  IF trusted THEN
    PERFORM notify_user(md.poster_owner,'twin_market','Twin của bạn đã thuê twin khác (cặp tin cậy — tự duyệt)',new_deal);
  ELSE
    PERFORM notify_user(md.poster_owner,'twin_market','⚠️ Twin của bạn muốn thuê twin lạ — cần bạn DUYỆT lần đầu',new_deal);
  END IF;
  RETURN new_deal;
END $$;

-- Chủ ĐĂNG duyệt lần đầu (hoặc từ chối). Khi duyệt: ghi cặp tin cậy để lần sau tự động.
CREATE OR REPLACE FUNCTION approve_twin_market(p_deal UUID, p_poster_owner UUID, p_ok BOOLEAN) RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE dl RECORD; md RECORD;
BEGIN
  SELECT * INTO dl FROM twin_market_deals WHERE id=p_deal FOR UPDATE;
  IF dl.id IS NULL THEN RAISE EXCEPTION 'twin_market_deal_not_found'; END IF;
  SELECT * INTO md FROM twin_market_drops WHERE id=dl.market_drop_id FOR UPDATE;
  IF md.poster_owner <> p_poster_owner THEN RAISE EXCEPTION 'not_poster_owner'; END IF;
  IF dl.state <> 'PENDING_APPROVAL' THEN RAISE EXCEPTION 'twin_market_not_pending'; END IF;

  IF NOT p_ok THEN
    UPDATE twin_market_deals SET state='REJECTED' WHERE id=p_deal;
    UPDATE twin_market_drops SET status='open' WHERE id=dl.market_drop_id;  -- mở lại
    RETURN 'REJECTED';
  END IF;

  -- Duyệt: ghi cặp tin cậy (lần sau tự động)
  INSERT INTO twin_market_trusted_pairs(poster_owner,taker_owner)
    VALUES (md.poster_owner, dl.taker_owner) ON CONFLICT DO NOTHING;
  UPDATE twin_market_deals SET state='APPROVED' WHERE id=p_deal;
  RETURN 'APPROVED';
END $$;

-- Kết toán twin-to-twin: chuyển Plump chủ-đăng → chủ-nhận. HAI CHỦ CÙNG CÓ LỢI:
--   chủ nhận: +Plump (tiền công). chủ đăng: việc số hoàn thành (giúp twin nó phục vụ khách lớn hơn).
-- Sổ minh bạch: cả hai đều thấy bút toán (2 bất biến).
CREATE OR REPLACE FUNCTION settle_twin_market(p_deal UUID, p_actor UUID) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE dl RECORD; md RECORD;
BEGIN
  SELECT * INTO dl FROM twin_market_deals WHERE id=p_deal FOR UPDATE;
  IF dl.id IS NULL THEN RAISE EXCEPTION 'twin_market_deal_not_found'; END IF;
  SELECT * INTO md FROM twin_market_drops WHERE id=dl.market_drop_id FOR UPDATE;
  -- chỉ chủ đăng hoặc chủ nhận được kích hoạt kết toán
  IF p_actor NOT IN (md.poster_owner, dl.taker_owner) THEN RAISE EXCEPTION 'not_participant'; END IF;
  IF dl.state <> 'APPROVED' THEN RAISE EXCEPTION 'twin_market_not_approved'; END IF;
  IF plump_balance(md.poster_owner) < dl.price_plump THEN RAISE EXCEPTION 'poster_insufficient_plump'; END IF;

  -- chuyển Plump (sổ minh bạch 2 phía)
  INSERT INTO plump_points(owner,amount,reason)
    VALUES (md.poster_owner, -dl.price_plump, 'twin_market_pay');
  INSERT INTO plump_points(owner,amount,reason)
    VALUES (dl.taker_owner,  dl.price_plump, 'twin_market_earn');

  UPDATE twin_market_deals SET state='SETTLED', settled_at=now() WHERE id=p_deal;
  UPDATE twin_market_drops SET status='done' WHERE id=dl.market_drop_id;
  PERFORM notify_user(dl.taker_owner,'twin_market','Twin của bạn hoàn tất việc thuê · +🍑'||dl.price_plump,p_deal);
  PERFORM notify_user(md.poster_owner,'twin_market','Việc twin-to-twin xong · −🍑'||dl.price_plump,p_deal);
END $$;

-- Chi tiết chợ twin cho API
CREATE OR REPLACE FUNCTION twin_market_can_post(p_owner UUID) RETURNS BOOLEAN
LANGUAGE sql STABLE AS $$
  SELECT plump_level(p_owner) >= (SELECT (val->>'min_poster_level')::INT FROM config WHERE key='twin_market')
$$;
