-- ============================================================
-- 017 · BEAT 2 · TWIN CÓ CẤP — chặn trần bởi cấp CHỦ (Phương án B)
-- twin_raw_level: tính từ điểm khách chấm các việc twin THỰC THI (qua twin_jobs→deal→reviews).
-- twin_level = MIN(twin_raw_level, plump_level(chủ))  → Twin không bao giờ giỏi hơn cấp chủ.
--   Giữ con người ở trung tâm: muốn Twin giỏi, chủ phải tự giỏi.
-- ============================================================

INSERT INTO config VALUES ('twin_leveling',
  '{"tiers":[0,3,8,18,36],"min_rated_jobs":1}')
  ON CONFLICT (key) DO NOTHING;
-- tiers: ngưỡng điểm cho twin Lv1..Lv5 (thấp hơn Plumper vì twin làm việc số nhỏ, nhiều)

-- Đánh dấu job đã hoàn tất & được chấm: job.status='approved' + deal SETTLED + có review cho executor(=twin owner đại diện)
-- twin_score = số job hợp lệ × (điểm TB việc twin/5) × √(số khách khác nhau, cap 15)
CREATE OR REPLACE FUNCTION twin_score(p_twin UUID) RETURNS NUMERIC
LANGUAGE plpgsql STABLE AS $$
DECLARE n_jobs INT; n_clients INT; avg_rat NUMERIC; sc NUMERIC;
BEGIN
  WITH jobs AS (
    SELECT j.deal_id, d.dropper AS client,
           (SELECT rating FROM reviews r WHERE r.deal_id=d.id AND r.target=d.executor LIMIT 1) AS rating
    FROM twin_jobs j
    JOIN deals d ON d.id = j.deal_id
    WHERE j.twin_id = p_twin AND j.status='approved' AND d.state='SETTLED'
      AND d.executor_kind='twin'
  ),
  rated AS (SELECT * FROM jobs WHERE rating IS NOT NULL)
  SELECT count(*), count(DISTINCT client), COALESCE(ROUND(AVG(rating),3),3.0)
    INTO n_jobs, n_clients, avg_rat FROM rated;
  IF n_jobs = 0 THEN RETURN 0; END IF;
  sc := n_jobs * (avg_rat/5.0) * sqrt(GREATEST(LEAST(n_clients,15),1));
  RETURN ROUND(sc,2);
END $$;

-- Cấp thô của twin (chưa chặn trần)
CREATE OR REPLACE FUNCTION twin_raw_level(p_twin UUID) RETURNS INT
LANGUAGE plpgsql STABLE AS $$
DECLARE t JSONB; sc NUMERIC;
BEGIN
  SELECT (val->'tiers') INTO t FROM config WHERE key='twin_leveling';
  sc := twin_score(p_twin);
  RETURN CASE
    WHEN sc >= (t->>4)::NUMERIC THEN 5
    WHEN sc >= (t->>3)::NUMERIC THEN 4
    WHEN sc >= (t->>2)::NUMERIC THEN 3
    WHEN sc >= (t->>1)::NUMERIC THEN 2
    ELSE 1 END;
END $$;

-- Cấp THẬT của twin = min(cấp thô, cấp chủ). ĐÂY LÀ TRẦN (Phương án B).
CREATE OR REPLACE FUNCTION twin_level(p_twin UUID) RETURNS INT
LANGUAGE plpgsql STABLE AS $$
DECLARE ownr UUID; raw INT; owner_lv INT;
BEGIN
  SELECT owner INTO ownr FROM twins WHERE id = p_twin;
  IF ownr IS NULL THEN RETURN 1; END IF;
  raw := twin_raw_level(p_twin);
  owner_lv := plump_level(ownr);
  RETURN LEAST(raw, owner_lv);
END $$;

-- Chi tiết cấp twin (API): có cả cấp thô, trần chủ, và cấp thật + có bị trần chặn không
CREATE OR REPLACE FUNCTION twin_level_detail(p_twin UUID)
RETURNS TABLE(twin_level INT, raw_level INT, owner_level INT, capped BOOLEAN,
              score NUMERIC, rated_jobs BIGINT)
LANGUAGE plpgsql STABLE AS $$
DECLARE ownr UUID; raw INT; olv INT;
BEGIN
  SELECT owner INTO ownr FROM twins WHERE id=p_twin;
  raw := twin_raw_level(p_twin); olv := plump_level(ownr);
  RETURN QUERY SELECT LEAST(raw,olv), raw, olv, (raw > olv), twin_score(p_twin),
    (SELECT count(*) FROM twin_jobs j JOIN deals d ON d.id=j.deal_id
     WHERE j.twin_id=p_twin AND j.status='approved' AND d.state='SETTLED'
       AND EXISTS(SELECT 1 FROM reviews r WHERE r.deal_id=d.id AND r.target=d.executor));
END $$;
