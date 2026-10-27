-- ============================================================
-- 019 · BEAT 4 · SLOT TWIN THEO CẤP + PHÍ DUY TRÌ TĂNG DẦN (chống lạm phát #3)
-- Số slot twin mở theo cấp CHỦ. Twin thứ N tốn phí mở + phí duy trì TĂNG DẦN.
-- Van xả lạm phát: nuôi nhiều twin không free → chủ phải cân "có đáng không".
-- Cũng là điểm doanh thu (bán slot bằng Nara).
-- ============================================================

INSERT INTO config VALUES ('twin_slots',
  '{"slots_by_level":[1,1,2,3,5],
    "open_fee_nara":[0,0,50000,150000,400000],
    "maintenance_nara":[0,0,20000,50000,120000],
    "maintenance_period_days":30}')
  ON CONFLICT (key) DO NOTHING;
-- slots_by_level: số twin tối đa theo cấp chủ Lv1..5 → Lv1-2:1, Lv3:2, Lv4:3, Lv5:5.
-- open_fee_nara: phí MỞ twin thứ n (index 0 = twin đầu miễn phí, twin thứ 3 tốn 50k...).
-- maintenance_nara: phí DUY TRÌ mỗi chu kỳ cho twin thứ n (twin đầu free, thứ 3 tốn 20k/tháng...).
-- Càng nhiều twin, chi phí biên càng cao → phanh tự nhiên.

-- Cột theo dõi phí duy trì
ALTER TABLE twins ADD COLUMN IF NOT EXISTS slot_index INT;                 -- twin thứ mấy của chủ (1-based)
ALTER TABLE twins ADD COLUMN IF NOT EXISTS maintenance_due_at TIMESTAMPTZ; -- hạn đóng phí duy trì kế
ALTER TABLE twins ADD COLUMN IF NOT EXISTS suspended_unpaid BOOLEAN NOT NULL DEFAULT false;

-- Cho phép trạng thái 'deleted' (để đếm slot loại twin đã xoá)
ALTER TABLE twins DROP CONSTRAINT IF EXISTS twins_status_check;
ALTER TABLE twins ADD CONSTRAINT twins_status_check
  CHECK (status IN ('draft','sandbox','live','paused','suspended','deleted'));

-- Số slot tối đa theo cấp chủ
CREATE OR REPLACE FUNCTION twin_slot_limit(p_owner UUID) RETURNS INT
LANGUAGE plpgsql STABLE AS $$
DECLARE arr JSONB; lv INT;
BEGIN
  SELECT (val->'slots_by_level') INTO arr FROM config WHERE key='twin_slots';
  lv := plump_level(p_owner);
  RETURN (arr->>(lv-1))::INT;
END $$;

-- Số twin đang hoạt động (không tính đã xoá/suspended vĩnh viễn)
CREATE OR REPLACE FUNCTION twin_active_count(p_owner UUID) RETURNS INT
LANGUAGE sql STABLE AS $$
  SELECT count(*)::INT FROM twins WHERE owner=p_owner AND status <> 'deleted'
$$;

-- Phí mở twin thứ n (n = số twin hiện có + 1)
CREATE OR REPLACE FUNCTION twin_open_fee(p_owner UUID) RETURNS BIGINT
LANGUAGE plpgsql STABLE AS $$
DECLARE arr JSONB; n INT; idx INT;
BEGIN
  SELECT (val->'open_fee_nara') INTO arr FROM config WHERE key='twin_slots';
  n := twin_active_count(p_owner) + 1;
  idx := LEAST(n, jsonb_array_length(arr)) - 1;   -- clamp vào mảng
  RETURN (arr->>idx)::BIGINT;
END $$;

-- Phí duy trì cho twin ở slot_index cho trước
CREATE OR REPLACE FUNCTION twin_maintenance_fee(p_slot_index INT) RETURNS BIGINT
LANGUAGE plpgsql STABLE AS $$
DECLARE arr JSONB; idx INT;
BEGIN
  SELECT (val->'maintenance_nara') INTO arr FROM config WHERE key='twin_slots';
  idx := LEAST(p_slot_index, jsonb_array_length(arr)) - 1;
  RETURN (arr->>idx)::BIGINT;
END $$;

-- Tạo twin CÓ kiểm slot + thu phí mở (thay luồng INSERT trần ở API)
CREATE OR REPLACE FUNCTION create_twin(p_owner UUID, p_name TEXT, p_model TEXT) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE lim INT; cnt INT; fee BIGINT; sidx INT; period INT; new_id UUID;
BEGIN
  PERFORM _require_verified(p_owner);
  lim := twin_slot_limit(p_owner);
  cnt := twin_active_count(p_owner);
  IF cnt >= lim THEN
    RAISE EXCEPTION 'twin_slot_limit_reached:%/% (cấp % chỉ mở % slot)', cnt, lim, plump_level(p_owner), lim;
  END IF;
  fee := twin_open_fee(p_owner);
  IF fee > 0 THEN
    PERFORM spend_nara(p_owner, fee, 'twin_slot', NULL);   -- lỗi nếu thiếu Nara
  END IF;
  sidx := cnt + 1;
  SELECT (val->>'maintenance_period_days')::INT INTO period FROM config WHERE key='twin_slots';
  INSERT INTO twins(owner,name,status,engine_model,slot_index,maintenance_due_at)
    VALUES (p_owner, p_name, 'live', p_model, sidx,
            CASE WHEN twin_maintenance_fee(sidx) > 0 THEN now() + (period || ' days')::interval ELSE NULL END)
    RETURNING id INTO new_id;
  RETURN new_id;
END $$;

-- Đóng phí duy trì (gia hạn 1 chu kỳ). Trả hạn mới.
CREATE OR REPLACE FUNCTION pay_maintenance(p_twin UUID, p_actor UUID) RETURNS TIMESTAMPTZ
LANGUAGE plpgsql AS $$
DECLARE ownr UUID; sidx INT; fee BIGINT; period INT; newdue TIMESTAMPTZ;
BEGIN
  SELECT owner, slot_index INTO ownr, sidx FROM twins WHERE id=p_twin FOR UPDATE;
  IF ownr IS NULL THEN RAISE EXCEPTION 'twin_not_found'; END IF;
  IF ownr <> p_actor THEN RAISE EXCEPTION 'not_twin_owner'; END IF;
  fee := twin_maintenance_fee(sidx);
  SELECT (val->>'maintenance_period_days')::INT INTO period FROM config WHERE key='twin_slots';
  IF fee > 0 THEN PERFORM spend_nara(ownr, fee, 'twin_maintenance', p_twin); END IF;
  newdue := now() + (period || ' days')::interval;
  UPDATE twins SET maintenance_due_at = newdue, suspended_unpaid = false WHERE id=p_twin;
  RETURN newdue;
END $$;

-- Quét twin quá hạn phí → treo (suspended_unpaid). Worker gọi định kỳ. Trả số twin bị treo.
CREATE OR REPLACE FUNCTION sweep_unpaid_twins() RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE n INT;
BEGIN
  UPDATE twins SET suspended_unpaid = true
    WHERE maintenance_due_at IS NOT NULL AND maintenance_due_at < now()
      AND suspended_unpaid = false AND status <> 'deleted';
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $$;

-- Chi tiết slot (API)
CREATE OR REPLACE FUNCTION twin_slot_detail(p_owner UUID)
RETURNS TABLE(active INT, limit_slots INT, next_open_fee BIGINT, owner_level INT)
LANGUAGE sql STABLE AS $$
  SELECT twin_active_count(p_owner), twin_slot_limit(p_owner),
         twin_open_fee(p_owner), plump_level(p_owner)
$$;

-- Twin bị treo phí KHÔNG được nhận việc: thêm chặn vào accept_offer (twin nhánh)
-- (bổ sung guard; giữ nguyên phần còn lại từ 018)
CREATE OR REPLACE FUNCTION _twin_can_work(p_twin UUID) RETURNS VOID
LANGUAGE plpgsql STABLE AS $$
DECLARE st TEXT; unpaid BOOLEAN;
BEGIN
  SELECT status, suspended_unpaid INTO st, unpaid FROM twins WHERE id=p_twin;
  IF unpaid THEN RAISE EXCEPTION 'twin_suspended_unpaid'; END IF;
  IF st = 'deleted' THEN RAISE EXCEPTION 'twin_deleted'; END IF;
END $$;

-- Cập nhật accept_offer: thêm guard _twin_can_work trước khi twin nhận việc (kế thừa 018)
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
    PERFORM _twin_can_work(o.twin_id);                      -- Beat 4: chặn twin bị treo phí / đã xoá
    PERFORM apply_energy_regen(o.twin_id);
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

-- Cập nhật create_offer_twin: thêm guard _twin_can_work (chặn twin treo phí/đã xoá) ngay khi offer
CREATE OR REPLACE FUNCTION create_offer_twin(p_owner UUID, p_twin UUID, p_drop UUID, p_amount BIGINT)
RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE v UUID; d RECORD; tw RECORD; m twin_mandates;
BEGIN
  PERFORM _require_verified(p_owner);
  SELECT * INTO tw FROM twins WHERE id=p_twin;
  IF tw.owner <> p_owner THEN RAISE EXCEPTION 'not_twin_owner'; END IF;
  PERFORM _twin_can_work(p_twin);                        -- Beat 4: chặn twin bị treo phí duy trì / đã xoá
  PERFORM apply_energy_regen(p_twin);
  IF (SELECT energy FROM twins WHERE id=p_twin) < twin_job_cost(p_twin)
    THEN RAISE EXCEPTION 'twin_no_energy'; END IF;
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
