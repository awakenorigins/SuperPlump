-- ============================================================
-- SUPERPLUMP CORE V1 · 001_schema.sql
-- Tiền: BIGINT (đồng, không thập phân). Mọi bảng tiền/uy tín: append-only.
-- ============================================================
CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------- CẤU HÌNH ----------
CREATE TABLE config (
  key TEXT PRIMARY KEY,
  val JSONB NOT NULL
);
INSERT INTO config VALUES
 ('fees', '{"fee_bps_dropper":500,"fee_bps_executor":500}'),
 ('deal', '{"autoconfirm_hours":12,"fuzz_grid_deg":0.003}');

-- ---------- DANH TÍNH ----------
CREATE TABLE plumpers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  handle TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL,
  kyc_status TEXT NOT NULL DEFAULT 'none'
    CHECK (kyc_status IN ('none','pending','verified','rejected')),
  locale TEXT NOT NULL DEFAULT 'vi',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- VÍ & SỔ KẾ TOÁN KÉP ----------
-- kind: user | escrow | platform  (escrow/platform là ví hệ thống, owner NULL)
CREATE TABLE wallets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner UUID REFERENCES plumpers(id),
  kind TEXT NOT NULL CHECK (kind IN ('user','escrow','platform')),
  balance BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
  UNIQUE (owner, kind)
);

CREATE TABLE ledger_entries (
  id BIGSERIAL PRIMARY KEY,
  deal_id UUID,
  wallet_id UUID NOT NULL REFERENCES wallets(id),
  kind TEXT NOT NULL CHECK (kind IN
    ('topup','hold','release_net','fee','refund','withdraw')),
  amount BIGINT NOT NULL,          -- (+) vào ví, (−) ra ví
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ledger_deal_idx ON ledger_entries(deal_id);
CREATE INDEX ledger_wallet_idx ON ledger_entries(wallet_id);
-- Sổ không sửa được:
REVOKE UPDATE, DELETE ON ledger_entries FROM PUBLIC;

-- ---------- CHỢ ----------
CREATE TABLE drops (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner UUID NOT NULL REFERENCES plumpers(id),
  kind TEXT NOT NULL CHECK (kind IN ('local','digital')),
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  price BIGINT NOT NULL CHECK (price > 0),
  location GEOGRAPHY(Point,4326),          -- CỘT NHẠY CẢM: chỉ đọc qua view/hàm
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open','matched','closed','cancelled','expired')),
  requires_proof BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ,
  CHECK (kind <> 'local' OR location IS NOT NULL)
);
CREATE INDEX drops_geo_idx ON drops USING GIST (location);
CREATE INDEX drops_status_idx ON drops(status);

CREATE TABLE offers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  drop_id UUID NOT NULL REFERENCES drops(id),
  from_id UUID NOT NULL REFERENCES plumpers(id),
  amount BIGINT NOT NULL CHECK (amount > 0),
  round INT NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','accepted','rejected','countered','void')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX offers_drop_idx ON offers(drop_id);

-- ---------- DEAL: MÁY TRẠNG THÁI ----------
CREATE TABLE deals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  drop_id UUID NOT NULL REFERENCES drops(id),
  dropper UUID NOT NULL REFERENCES plumpers(id),
  executor UUID NOT NULL REFERENCES plumpers(id),
  executor_kind TEXT NOT NULL DEFAULT 'human'
    CHECK (executor_kind IN ('human','twin')),
  agreed BIGINT NOT NULL CHECK (agreed > 0),
  hold_amount BIGINT NOT NULL,
  state TEXT NOT NULL DEFAULT 'LOCKED' CHECK (state IN
    ('LOCKED','IN_PROGRESS','SUBMITTED','SETTLED','DISPUTED','RESOLVED','CANCELLED')),
  locked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ, submitted_at TIMESTAMPTZ, settled_at TIMESTAMPTZ,
  CHECK (dropper <> executor)
);
-- CHẶN DOUBLE-ACCEPT TẬN GỐC: mỗi drop chỉ 1 deal còn sống
CREATE UNIQUE INDEX one_active_deal_per_drop ON deals(drop_id)
  WHERE state NOT IN ('CANCELLED');

CREATE TABLE proofs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deal_id UUID NOT NULL REFERENCES deals(id),
  uploader UUID NOT NULL REFERENCES plumpers(id),
  media_url TEXT NOT NULL,
  note TEXT DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE disputes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deal_id UUID NOT NULL REFERENCES deals(id),
  opened_by UUID NOT NULL REFERENCES plumpers(id),
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
  resolution TEXT CHECK (resolution IN ('release','refund','split')),
  resolved_by UUID REFERENCES plumpers(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

-- ---------- ĐÁNH GIÁ MÙ, BẤT BIẾN ----------
CREATE TABLE reviews (
  deal_id UUID NOT NULL REFERENCES deals(id),
  author UUID NOT NULL REFERENCES plumpers(id),
  target UUID NOT NULL REFERENCES plumpers(id),
  rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  body TEXT NOT NULL DEFAULT '',
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (deal_id, author)
);
REVOKE UPDATE, DELETE ON reviews FROM PUBLIC;

-- ---------- EVENT LOG: XƯƠNG SỐNG MINH BẠCH ----------
CREATE TABLE events (
  id BIGSERIAL PRIMARY KEY,
  aggregate_type TEXT NOT NULL,
  aggregate_id UUID NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}',
  actor UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX events_agg_idx ON events(aggregate_type, aggregate_id);
REVOKE UPDATE, DELETE ON events FROM PUBLIC;

-- ---------- BẢN THỂ SỐ (lõi tối thiểu V1) ----------
CREATE TABLE twins (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner UUID NOT NULL REFERENCES plumpers(id),
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft','sandbox','live','paused','suspended')),
  autonomy TEXT NOT NULL DEFAULT 'supervised'
    CHECK (autonomy IN ('supervised','semi','auto')),
  energy INT NOT NULL DEFAULT 50 CHECK (energy >= 0),
  engine_model TEXT NOT NULL DEFAULT 'claude-fable-5',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE qualifications (
  twin_id UUID NOT NULL REFERENCES twins(id),
  category TEXT NOT NULL,
  level TEXT NOT NULL CHECK (level IN ('bronze','silver','gold')),
  soul_version INT NOT NULL,
  granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at TIMESTAMPTZ,
  PRIMARY KEY (twin_id, category)
);
