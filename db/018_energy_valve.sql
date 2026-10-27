-- ============================================================
-- 018 · BEAT 3 · VAN NĂNG LƯỢNG (chống lạm phát #1)
-- Energy có TRẦN (theo cấp chủ). Twin cấp cao TỐN ÍT energy hơn mỗi việc.
-- NẠP từ 4 nguồn hợp lệ: mua (Nara) · nhặt (map) · việc khách chấm XUẤT SẮC (5★) · event.
-- Hồi phục thụ động chậm theo thời gian (regen).
-- ============================================================

INSERT INTO config VALUES ('energy',
  '{"base_cap":50,"cap_per_level":20,"cost_by_level":[10,10,8,6,4],
    "regen_per_hour":2,"excellent_refill":15,"gather_refill":8,
    "buy_rate_nara_per_energy":2000,"event_refill":25}')
  ON CONFLICT (key) DO NOTHING;
-- base_cap 50 + cap_per_level×(cấp chủ-1): Lv1→50, Lv3→90, Lv5→130. Chủ giỏi → twin bền hơn.
-- cost_by_level: việc tốn energy theo cấp TWIN (Lv1..5): 10,10,8,6,4. Twin giỏi hiệu suất cao.
-- regen_per_hour: hồi 2⚡/giờ thụ động (twin nghỉ thì tự hồi, có trần).
-- excellent_refill: việc được khách chấm 5★ hoàn lại 15⚡ (thưởng chất lượng).
-- gather/buy/event: nhặt map / mua bằng Nara / sự kiện.

-- Thêm cột mốc thời gian energy (cho regen) + energy_max động
ALTER TABLE twins ADD COLUMN IF NOT EXISTS energy_updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Trần energy động theo cấp CHỦ
CREATE OR REPLACE FUNCTION twin_energy_cap(p_twin UUID) RETURNS INT
LANGUAGE plpgsql STABLE AS $$
DECLARE ownr UUID; base INT; per INT; olv INT;
BEGIN
  SELECT owner INTO ownr FROM twins WHERE id=p_twin;
  SELECT (val->>'base_cap')::INT, (val->>'cap_per_level')::INT INTO base, per FROM config WHERE key='energy';
  olv := plump_level(ownr);
  RETURN base + per * (olv - 1);
END $$;

-- Chi phí energy cho MỘT việc, theo cấp TWIN
CREATE OR REPLACE FUNCTION twin_job_cost(p_twin UUID) RETURNS INT
LANGUAGE plpgsql STABLE AS $$
DECLARE arr JSONB; lv INT;
BEGIN
  SELECT (val->'cost_by_level') INTO arr FROM config WHERE key='energy';
  lv := twin_level(p_twin);
  RETURN (arr->>(lv-1))::INT;
END $$;

-- Áp regen thụ động: cập nhật energy dựa trên thời gian trôi từ energy_updated_at (có trần)
CREATE OR REPLACE FUNCTION apply_energy_regen(p_twin UUID) RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE rate INT; cap INT; cur INT; last TIMESTAMPTZ; gained INT; newval INT;
BEGIN
  SELECT (val->>'regen_per_hour')::INT INTO rate FROM config WHERE key='energy';
  SELECT energy, energy_updated_at INTO cur, last FROM twins WHERE id=p_twin FOR UPDATE;
  cap := twin_energy_cap(p_twin);
  gained := FLOOR(EXTRACT(EPOCH FROM (now()-last))/3600.0 * rate)::INT;
  IF gained <= 0 THEN RETURN cur; END IF;
  newval := LEAST(cur + gained, cap);
  UPDATE twins SET energy=newval, energy_updated_at=now() WHERE id=p_twin;
  RETURN newval;
END $$;

-- Nạp energy (không vượt trần). source: buy|gather|excellent|event. Trả energy mới.
CREATE OR REPLACE FUNCTION refill_energy(p_twin UUID, p_source TEXT, p_actor UUID DEFAULT NULL) RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE cfg JSONB; cap INT; cur INT; add INT; cost_nara BIGINT; ownr UUID;
BEGIN
  SELECT val INTO cfg FROM config WHERE key='energy';
  SELECT owner, energy INTO ownr, cur FROM twins WHERE id=p_twin FOR UPDATE;
  IF ownr IS NULL THEN RAISE EXCEPTION 'twin_not_found'; END IF;
  cap := twin_energy_cap(p_twin);
  add := CASE p_source
    WHEN 'excellent' THEN (cfg->>'excellent_refill')::INT
    WHEN 'gather'    THEN (cfg->>'gather_refill')::INT
    WHEN 'event'     THEN (cfg->>'event_refill')::INT
    WHEN 'buy'       THEN (cfg->>'buy_amount')::INT   -- xem nhánh buy phía dưới
    ELSE 0 END;

  IF p_source = 'buy' THEN
    -- mua 1 gói = nạp đầy tới cap, trả Nara theo số ⚡ thiếu
    add := cap - cur;
    IF add <= 0 THEN RETURN cur; END IF;
    cost_nara := add * (cfg->>'buy_rate_nara_per_energy')::BIGINT;
    IF p_actor IS DISTINCT FROM ownr THEN RAISE EXCEPTION 'only_owner_buys'; END IF;
    PERFORM spend_nara(ownr, cost_nara, 'twin_energy', p_twin);   -- trừ ví; lỗi nếu thiếu
  END IF;

  UPDATE twins SET energy = LEAST(cur + add, cap), energy_updated_at=now() WHERE id=p_twin;
  RETURN LEAST(cur + add, cap);
END $$;

-- Helper trừ Nara (dùng ví user). RAISE nếu không đủ.
-- Mở rộng CHECK kind của ledger_entries để chấp nhận chi tiêu nội tệ (twin_energy, slot...).
ALTER TABLE ledger_entries DROP CONSTRAINT IF EXISTS ledger_entries_kind_check;
ALTER TABLE ledger_entries ADD CONSTRAINT ledger_entries_kind_check CHECK (kind IN
  ('topup','hold','release_net','fee','refund','withdraw','purchase',
   'twin_energy','twin_slot','twin_maintenance'));

CREATE OR REPLACE FUNCTION spend_nara(p_user UUID, p_amount BIGINT, p_reason TEXT, p_ref UUID DEFAULT NULL) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE bal BIGINT; w UUID;
BEGIN
  SELECT id, balance INTO w, bal FROM wallets WHERE owner=p_user AND kind='user' FOR UPDATE;
  IF bal < p_amount THEN RAISE EXCEPTION 'insufficient_nara'; END IF;
  UPDATE wallets SET balance = balance - p_amount WHERE id=w;
  INSERT INTO ledger_entries(wallet_id,deal_id,kind,amount)
    VALUES (w, NULL, p_reason, -p_amount);
END $$;

-- ---- Đổi chi phí việc twin từ hằng 5 sang twin_job_cost() + hoàn 5★ ----
-- Sửa accept_offer: dùng twin_job_cost thay cho -5 cứng.
CREATE OR REPLACE FUNCTION accept_offer(p_offer UUID, p_actor UUID) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE o RECORD; d RECORD; v_fee_d BIGINT; v_hold BIGINT; v_deal UUID; v_dropid UUID; v_cost INT; v_cur INT;
BEGIN
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
    PERFORM apply_energy_regen(o.twin_id);                    -- hồi thụ động trước khi trừ
    v_cost := twin_job_cost(o.twin_id);
    SELECT energy INTO v_cur FROM twins WHERE id=o.twin_id FOR UPDATE;
    IF v_cur < v_cost THEN RAISE EXCEPTION 'twin_no_energy'; END IF;
    UPDATE twins SET energy = energy - v_cost, energy_updated_at=now() WHERE id = o.twin_id;
    PERFORM deal_start(v_deal, o.from_id);
    INSERT INTO twin_jobs(twin_id,deal_id,brief)
      VALUES (o.twin_id, v_deal, d.title || E'\n' || d.description);
    PERFORM notify_user(o.from_id,'twin_job','Twin nhận việc "'||d.title||'" — chờ draft',v_deal);
  END IF;
  RETURN v_deal;
END $$;

-- Hoàn energy khi khách chấm việc twin 5★ (gọi trong submit_review nếu deal là twin & rating=5)
CREATE OR REPLACE FUNCTION _maybe_refill_excellent(p_deal UUID, p_rating INT, p_author UUID) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE tw UUID; drpr UUID;
BEGIN
  IF p_rating < 5 THEN RETURN; END IF;
  -- chỉ tính khi KHÁCH (dropper) chấm việc, không phải chủ twin tự chấm
  SELECT twin_id, dropper INTO tw, drpr FROM deals WHERE id=p_deal AND executor_kind='twin';
  IF tw IS NOT NULL AND p_author = drpr THEN PERFORM refill_energy(tw, 'excellent'); END IF;
END $$;

-- Bọc submit_review để hoàn energy 5★ (giữ nguyên logic cũ + thêm 1 dòng)
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
  PERFORM _maybe_refill_excellent(p_deal, p_rating, p_author);   -- Beat 3: hoàn energy nếu 5★
END $$;
