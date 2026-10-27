-- 003_rls.sql · Cách ly dữ liệu ở tầng DB (mô phỏng auth.uid() của Supabase bằng GUC app.uid)
CREATE ROLE authenticated NOLOGIN;
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT SELECT ON wallets, ledger_entries, drops_public, deal_reviews_visible, events TO authenticated;
CREATE OR REPLACE FUNCTION uid() RETURNS UUID LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.uid', true),'')::uuid $$;
ALTER TABLE wallets ENABLE ROW LEVEL SECURITY;
CREATE POLICY wallet_owner_only ON wallets FOR SELECT TO authenticated USING (owner = uid());
ALTER TABLE ledger_entries ENABLE ROW LEVEL SECURITY;
CREATE POLICY ledger_owner_only ON ledger_entries FOR SELECT TO authenticated
  USING (wallet_id IN (SELECT id FROM wallets WHERE owner = uid()));
