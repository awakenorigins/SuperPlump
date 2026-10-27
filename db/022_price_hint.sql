-- ============================================================
-- 022 · BEAT 7 · GIÁ GỢI Ý TINH TẾ (chiếu đèn, KHÔNG ép)
-- Nền tảng KHÔNG đặt giá — chỉ soi sáng "khu này giờ này thường bao nhiêu".
-- Giá tự do CÓ TRỢ LỰC: người lười bấm phát ăn ngay, người muốn mặc cả thì mặc cả.
-- Giữ nguyên 2 bất biến: không trần/sàn áp đặt · chỉ cung cấp thông tin minh bạch.
-- ============================================================

INSERT INTO config VALUES ('price_hint',
  '{"min_sample":5,"radius_m":2000,"hour_window":3,"recent_days":90}')
  ON CONFLICT (key) DO NOTHING;
-- min_sample: dưới số mẫu này thì "chưa đủ dữ liệu" (không bịa giá từ 1-2 kèo).
-- radius_m: bán kính "cùng khu" cho việc local (2km). hour_window: ±3h. recent_days: 90 ngày.

-- Viết lại price_hint KHÔNG dùng temp table (dùng CTE, chọn scope bằng logic)
CREATE OR REPLACE FUNCTION price_hint(
  p_category TEXT,
  p_kind TEXT DEFAULT NULL,
  p_lng DOUBLE PRECISION DEFAULT NULL,
  p_lat DOUBLE PRECISION DEFAULT NULL,
  p_at TIMESTAMPTZ DEFAULT NULL)
RETURNS TABLE(
  sample INT, p25 BIGINT, median BIGINT, p75 BIGINT,
  scope TEXT, hour_of_day INT)
LANGUAGE plpgsql STABLE AS $$
DECLARE cfg JSONB; afloor BIGINT; rad INT; hwin INT; rdays INT;
        hr INT; mins INT; use_geo BOOLEAN;
        n_hg INT; n_khu INT; n_all INT;
BEGIN
  SELECT val INTO cfg FROM config WHERE key='price_hint';
  SELECT (val->>'abs_floor')::BIGINT INTO afloor FROM config WHERE key='leveling';
  rad  := (cfg->>'radius_m')::INT;
  hwin := (cfg->>'hour_window')::INT;
  rdays:= (cfg->>'recent_days')::INT;
  mins := (cfg->>'min_sample')::INT;
  hr   := EXTRACT(HOUR FROM COALESCE(p_at, now()))::INT;
  use_geo := (p_lng IS NOT NULL AND p_lat IS NOT NULL);

  -- Đếm mẫu ở từng phạm vi (từ hẹp tới rộng) trên tập việc THẬT gần đây
  IF use_geo THEN
    SELECT count(*) INTO n_hg FROM deals dl JOIN drops d ON d.id=dl.drop_id
     WHERE dl.state='SETTLED' AND d.category=p_category AND (p_kind IS NULL OR d.kind=p_kind)
       AND d.origin='client' AND dl.agreed>=afloor AND dl.settled_at>=now()-(rdays||' days')::interval
       AND d.location IS NOT NULL
       AND ST_DWithin(d.location, ST_MakePoint(p_lng,p_lat)::geography, rad)
       AND abs(EXTRACT(HOUR FROM d.created_at)::INT - hr) <= hwin;
    SELECT count(*) INTO n_khu FROM deals dl JOIN drops d ON d.id=dl.drop_id
     WHERE dl.state='SETTLED' AND d.category=p_category AND (p_kind IS NULL OR d.kind=p_kind)
       AND d.origin='client' AND dl.agreed>=afloor AND dl.settled_at>=now()-(rdays||' days')::interval
       AND d.location IS NOT NULL
       AND ST_DWithin(d.location, ST_MakePoint(p_lng,p_lat)::geography, rad);
  ELSE
    n_hg := 0; n_khu := 0;
  END IF;
  SELECT count(*) INTO n_all FROM deals dl JOIN drops d ON d.id=dl.drop_id
   WHERE dl.state='SETTLED' AND d.category=p_category AND (p_kind IS NULL OR d.kind=p_kind)
     AND d.origin='client' AND dl.agreed>=afloor AND dl.settled_at>=now()-(rdays||' days')::interval;

  -- Chọn phạm vi hẹp nhất đủ mẫu
  IF use_geo AND n_hg >= mins THEN
    RETURN QUERY
      SELECT n_hg,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY dl.agreed)::BIGINT,
        percentile_cont(0.5)  WITHIN GROUP (ORDER BY dl.agreed)::BIGINT,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY dl.agreed)::BIGINT,
        'khu+giờ'::TEXT, hr
      FROM deals dl JOIN drops d ON d.id=dl.drop_id
      WHERE dl.state='SETTLED' AND d.category=p_category AND (p_kind IS NULL OR d.kind=p_kind)
        AND d.origin='client' AND dl.agreed>=afloor AND dl.settled_at>=now()-(rdays||' days')::interval
        AND d.location IS NOT NULL
        AND ST_DWithin(d.location, ST_MakePoint(p_lng,p_lat)::geography, rad)
        AND abs(EXTRACT(HOUR FROM d.created_at)::INT - hr) <= hwin;
  ELSIF use_geo AND n_khu >= mins THEN
    RETURN QUERY
      SELECT n_khu,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY dl.agreed)::BIGINT,
        percentile_cont(0.5)  WITHIN GROUP (ORDER BY dl.agreed)::BIGINT,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY dl.agreed)::BIGINT,
        'khu'::TEXT, hr
      FROM deals dl JOIN drops d ON d.id=dl.drop_id
      WHERE dl.state='SETTLED' AND d.category=p_category AND (p_kind IS NULL OR d.kind=p_kind)
        AND d.origin='client' AND dl.agreed>=afloor AND dl.settled_at>=now()-(rdays||' days')::interval
        AND d.location IS NOT NULL
        AND ST_DWithin(d.location, ST_MakePoint(p_lng,p_lat)::geography, rad);
  ELSIF n_all >= mins THEN
    RETURN QUERY
      SELECT n_all,
        percentile_cont(0.25) WITHIN GROUP (ORDER BY dl.agreed)::BIGINT,
        percentile_cont(0.5)  WITHIN GROUP (ORDER BY dl.agreed)::BIGINT,
        percentile_cont(0.75) WITHIN GROUP (ORDER BY dl.agreed)::BIGINT,
        'toàn quốc'::TEXT, hr
      FROM deals dl JOIN drops d ON d.id=dl.drop_id
      WHERE dl.state='SETTLED' AND d.category=p_category AND (p_kind IS NULL OR d.kind=p_kind)
        AND d.origin='client' AND dl.agreed>=afloor AND dl.settled_at>=now()-(rdays||' days')::interval;
  ELSE
    RETURN QUERY SELECT n_all, NULL::BIGINT, NULL::BIGINT, NULL::BIGINT, 'chưa đủ dữ liệu'::TEXT, hr;
  END IF;
END $$;
