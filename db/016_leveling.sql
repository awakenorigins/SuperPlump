-- ============================================================
-- 016 · BEAT 1 · CẤP BẬC PLUMPER CÓ TRỌNG SỐ CHẤT LƯỢNG + CHỐNG CÀY
-- Thay plump_level "đếm deal" (015) bằng level_score = f(kèo × ĐG × đa dạng khách).
-- CHỐNG CÀY: chỉ tính khách KHÁC NHAU · kèo giá bất thường thấp không tính điểm cấp.
-- Giữ nguyên tên hàm plump_level() để mọi nơi đang gọi vẫn chạy (backward-compatible).
-- ============================================================

-- Ngưỡng cấu hình (chỉnh được, không hard-code rải rác)
INSERT INTO config VALUES ('leveling',
  '{"min_price_ratio":0.30,"tiers":[1,4,10,26,60],
    "diversity_cap":25,"low_price_grace":2,"abs_floor":10000}')
  ON CONFLICT (key) DO NOTHING;
-- abs_floor: sàn giá tuyệt đối (VND). Kèo dưới sàn LUÔN coi là giá-thấp → chống hạ median về 0
--   bằng cách cày hàng loạt kèo 1.000đ (median tự-tham-chiếu không cứu nổi kẻ gian nữa).
-- tiers hiệu chỉnh: 5 kèo thật 5★ (score ~11.2) → Lv3; ~15 kèo đa dạng 5★ → Lv4; ~40 → Lv5.
-- min_price_ratio: kèo có giá < 30% giá trung vị cùng loại → coi là "giá bất thường thấp", KHÔNG tính điểm cấp
-- tiers: ngưỡng level_score cho Lv1..Lv5 (điểm, không phải số kèo)
-- diversity_cap: trần số khách-khác-nhau được tính (chống 1 người cày vô hạn qua nhiều acc phụ)
-- low_price_grace: cho phép vài kèo giá thấp đầu (người mới cày cấp) vẫn tính, quá số này mới siết

-- ---------- Giá trung vị theo loại việc (để phát hiện kèo bất thường thấp) ----------
-- Dùng cho cả leveling lẫn Beat 7 (giá gợi ý). Trả NULL nếu chưa đủ mẫu.
CREATE OR REPLACE FUNCTION median_price_for_kind(p_kind TEXT) RETURNS BIGINT
LANGUAGE sql STABLE AS $$
  -- Chỉ tính trung vị trên kèo >= sàn tuyệt đối → cày hàng loạt kèo 1.000đ KHÔNG kéo được median xuống.
  SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY d.agreed)::BIGINT
  FROM deals d JOIN drops dr ON dr.id = d.drop_id
  WHERE dr.kind = p_kind AND d.state = 'SETTLED'
    AND d.agreed >= (SELECT (val->>'abs_floor')::BIGINT FROM config WHERE key='leveling')
$$;

-- ---------- level_score: điểm cấp có trọng số chất lượng ----------
-- Công thức (giải thích trong docs):
--   base   = số kèo SETTLED hợp lệ (loại kèo giá bất thường thấp vượt grace)
--   qual   = điểm đánh giá trung bình người này NHẬN (thang 1..5) / 5  → hệ số 0.2..1.0
--   divers = min(số khách KHÁC NHAU, diversity_cap) — thưởng đa dạng, chặn cày 1 cặp
--   score  = base_hợp_lệ × qual × sqrt(divers)   (sqrt để đa dạng có ích nhưng không áp đảo)
CREATE OR REPLACE FUNCTION level_score(p UUID) RETURNS NUMERIC
LANGUAGE plpgsql STABLE AS $$
DECLARE
  min_ratio NUMERIC; grace INT; dcap INT; afloor BIGINT;
  n_valid INT; n_distinct INT; avg_rat NUMERIC; sc NUMERIC;
BEGIN
  SELECT (val->>'min_price_ratio')::NUMERIC, (val->>'low_price_grace')::INT,
         (val->>'diversity_cap')::INT, (val->>'abs_floor')::BIGINT
    INTO min_ratio, grace, dcap, afloor FROM config WHERE key='leveling';

  -- "Giá thấp" = dưới min_ratio×trung vị HOẶC dưới sàn tuyệt đối (afloor).
  -- Chỉ 'grace' kèo giá-thấp ĐẦU TIÊN được ân hạn (người mới cày cấp); còn lại không tính điểm cấp.
  WITH my AS (
    SELECT d.id,
           CASE WHEN d.dropper = p THEN d.executor ELSE d.dropper END AS counterparty,
           d.agreed,
           (d.agreed < COALESCE(median_price_for_kind(dr.kind), d.agreed) * min_ratio
            OR d.agreed < afloor) AS is_low,
           d.settled_at
    FROM deals d JOIN drops dr ON dr.id = d.drop_id
    WHERE d.state='SETTLED' AND (d.executor = p OR d.dropper = p)
  ),
  ranked AS (
    SELECT *, row_number() OVER (PARTITION BY is_low ORDER BY settled_at) AS lowprice_rank FROM my
  ),
  valid AS (
    SELECT * FROM ranked
    WHERE is_low = false                     -- giá bình thường: tính
       OR lowprice_rank <= grace             -- hoặc trong số kèo giá-thấp đầu (ân hạn người mới)
  )
  SELECT count(*), count(DISTINCT counterparty),
         COALESCE((SELECT ROUND(AVG(rating),3) FROM deal_reviews_visible WHERE target=p), 3.0)
    INTO n_valid, n_distinct, avg_rat
    FROM valid;

  IF n_valid = 0 THEN RETURN 0; END IF;
  n_distinct := LEAST(n_distinct, dcap);
  sc := n_valid * (avg_rat/5.0) * sqrt(GREATEST(n_distinct,1));
  RETURN ROUND(sc, 2);
END $$;

-- ---------- plump_level: map score → 1..5 theo tiers (thay bản đếm-deal của 015) ----------
CREATE OR REPLACE FUNCTION plump_level(p UUID) RETURNS INT
LANGUAGE plpgsql STABLE AS $$
DECLARE t JSONB; sc NUMERIC;
BEGIN
  SELECT (val->'tiers') INTO t FROM config WHERE key='leveling';
  sc := level_score(p);
  RETURN CASE
    WHEN sc >= (t->>4)::NUMERIC THEN 5
    WHEN sc >= (t->>3)::NUMERIC THEN 4
    WHEN sc >= (t->>2)::NUMERIC THEN 3
    WHEN sc >= (t->>1)::NUMERIC THEN 2
    ELSE 1 END;
END $$;

-- ---------- Bảng chi tiết cấp (cho API /me/level & màn hồ sơ) ----------
CREATE OR REPLACE FUNCTION level_detail(p UUID)
RETURNS TABLE(level INT, score NUMERIC, valid_deals BIGINT, distinct_clients BIGINT,
              avg_rating NUMERIC, next_tier NUMERIC, to_next NUMERIC)
LANGUAGE plpgsql STABLE AS $$
DECLARE t JSONB; lv INT; sc NUMERIC; nt NUMERIC;
BEGIN
  SELECT (val->'tiers') INTO t FROM config WHERE key='leveling';
  lv := plump_level(p); sc := level_score(p);
  nt := CASE WHEN lv >= 5 THEN NULL ELSE (t->>lv)::NUMERIC END;  -- ngưỡng cấp kế tiếp
  RETURN QUERY
    WITH v AS (
      SELECT d.id, CASE WHEN d.dropper=p THEN d.executor ELSE d.dropper END cp
      FROM deals d WHERE d.state='SETTLED' AND (d.executor=p OR d.dropper=p)
    )
    SELECT lv, sc,
      (SELECT count(*) FROM v),
      (SELECT count(DISTINCT cp) FROM v),
      COALESCE((SELECT ROUND(AVG(rating),2) FROM deal_reviews_visible WHERE target=p), NULL),
      nt,
      CASE WHEN nt IS NULL THEN NULL ELSE GREATEST(nt - sc, 0) END;
END $$;
