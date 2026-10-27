-- ============================================================
-- 020 · BEAT 5 · TWIN CHỈ ĂN VIỆC THẬT (van chống lạm phát #2 — CỐT LÕI)
-- Twin KHÔNG farm từ việc tự tạo / việc công ích / việc giá 0.
-- Twin chỉ kiếm tiền & lên cấp từ VIỆC THẬT: có khách thật (người/twin khác) trả tiền qua escrow.
-- Số twin nhiều tới đâu, tiền vẫn bị chặn bởi NHU CẦU THẬT.
-- ============================================================

INSERT INTO config VALUES ('twin_real_work',
  '{"min_real_price":10000,"require_escrow":true}')
  ON CONFLICT (key) DO NOTHING;
-- min_real_price: việc twin làm phải có giá ≥ ngưỡng này mới coi là "thật" (chặn việc 0đ/1đ tự bơm).
-- require_escrow: deal phải có escrow thật (khách đã khoá tiền) — không có tiền thật = không phải việc thật.

-- Đánh dấu nguồn gốc drop: 'client' (khách thật đăng) vs 'civic'/'self' (không sinh thu nhập cho twin)
ALTER TABLE drops ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'client'
  CHECK (origin IN ('client','civic','self_generated'));

-- Kiểm "việc thật" cho twin: RAISE nếu không đạt (gọi trong create_offer_twin)
CREATE OR REPLACE FUNCTION _twin_real_work_only(p_twin UUID, p_drop UUID, p_amount BIGINT) RETURNS VOID
LANGUAGE plpgsql STABLE AS $$
DECLARE cfg JSONB; d RECORD; ownr UUID;
BEGIN
  SELECT val INTO cfg FROM config WHERE key='twin_real_work';
  SELECT * INTO d FROM drops WHERE id = p_drop;
  SELECT owner INTO ownr FROM twins WHERE id = p_twin;

  -- 1) Không phải việc công ích / tự sinh
  IF d.origin <> 'client' THEN
    RAISE EXCEPTION 'twin_real_work_only:origin=%', d.origin;
  END IF;

  -- 2) Giá phải đạt ngưỡng "thật" (chặn tự bơm bằng việc 0đ/1đ)
  IF p_amount < (cfg->>'min_real_price')::BIGINT THEN
    RAISE EXCEPTION 'twin_real_work_only:price_below_real_min';
  END IF;

  -- 3) Khách đăng việc KHÔNG phải chính chủ twin (self-dealing) — lớp thứ 2 sau cannot_offer_own_drop
  IF d.owner = ownr THEN
    RAISE EXCEPTION 'twin_real_work_only:self_dealing';
  END IF;
END $$;

-- Kiểm escrow thật khi twin nhận việc (deal đã khoá tiền của khách)
CREATE OR REPLACE FUNCTION _twin_escrow_backed(p_deal UUID) RETURNS BOOLEAN
LANGUAGE sql STABLE AS $$
  SELECT hold_amount > 0 FROM deals WHERE id = p_deal
$$;

-- ---- Cập nhật create_offer_twin: thêm guard việc-thật (kế thừa 019) ----
CREATE OR REPLACE FUNCTION create_offer_twin(p_owner UUID, p_twin UUID, p_drop UUID, p_amount BIGINT)
RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE v UUID; d RECORD; tw RECORD; m twin_mandates;
BEGIN
  PERFORM _require_verified(p_owner);
  SELECT * INTO tw FROM twins WHERE id=p_twin;
  IF tw.owner <> p_owner THEN RAISE EXCEPTION 'not_twin_owner'; END IF;
  PERFORM _twin_can_work(p_twin);                        -- Beat 4: treo phí / xoá
  PERFORM apply_energy_regen(p_twin);
  IF (SELECT energy FROM twins WHERE id=p_twin) < twin_job_cost(p_twin)
    THEN RAISE EXCEPTION 'twin_no_energy'; END IF;
  SELECT * INTO d FROM drops WHERE id=p_drop;
  IF d.status <> 'open' THEN RAISE EXCEPTION 'drop_not_open'; END IF;
  IF d.owner = p_owner THEN RAISE EXCEPTION 'cannot_offer_own_drop'; END IF;
  IF d.kind <> 'digital' THEN RAISE EXCEPTION 'twin_digital_only'; END IF;

  PERFORM _twin_real_work_only(p_twin, p_drop, p_amount); -- Beat 5: CHỈ việc thật (origin/giá/self)

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

-- ---- twin_score chỉ tính việc THẬT (origin='client', escrow>0, giá đạt ngưỡng) ----
-- Kế thừa 017 nhưng siết điều kiện "việc thật" → farm civic/tự-tạo không lên cấp twin.
CREATE OR REPLACE FUNCTION twin_score(p_twin UUID) RETURNS NUMERIC
LANGUAGE plpgsql STABLE AS $$
DECLARE n_jobs INT; n_clients INT; avg_rat NUMERIC; sc NUMERIC; min_real BIGINT;
BEGIN
  SELECT (val->>'min_real_price')::BIGINT INTO min_real FROM config WHERE key='twin_real_work';
  WITH jobs AS (
    SELECT j.deal_id, d.dropper AS client,
           (SELECT rating FROM reviews r WHERE r.deal_id=d.id AND r.target=d.executor LIMIT 1) AS rating
    FROM twin_jobs j
    JOIN deals d ON d.id = j.deal_id
    JOIN drops dr ON dr.id = d.drop_id
    WHERE j.twin_id = p_twin AND j.status='approved' AND d.state='SETTLED'
      AND d.executor_kind='twin'
      AND dr.origin = 'client'          -- Beat 5: chỉ việc khách thật
      AND d.hold_amount > 0             -- có escrow thật
      AND d.agreed >= min_real          -- giá đạt ngưỡng thật
  ),
  rated AS (SELECT * FROM jobs WHERE rating IS NOT NULL)
  SELECT count(*), count(DISTINCT client), COALESCE(ROUND(AVG(rating),3),3.0)
    INTO n_jobs, n_clients, avg_rat FROM rated;
  IF n_jobs = 0 THEN RETURN 0; END IF;
  sc := n_jobs * (avg_rat/5.0) * sqrt(GREATEST(LEAST(n_clients,15),1));
  RETURN ROUND(sc,2);
END $$;
