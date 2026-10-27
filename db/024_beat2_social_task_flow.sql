-- 024 · BEAT 2 — pilot social/task flow usability
-- Adds the missing DB seams for explicit user-created moments and keeps
-- social content persisted (no mock state). Existing escrow/deal functions remain authoritative.

CREATE OR REPLACE FUNCTION create_moment(p_actor UUID, p_deal UUID, p_title TEXT, p_quote TEXT DEFAULT '')
RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE v UUID; d RECORD;
BEGIN
  PERFORM _require_verified(p_actor);
  IF p_deal IS NOT NULL THEN
    SELECT * INTO d FROM deals WHERE id=p_deal;
    IF NOT FOUND THEN RAISE EXCEPTION 'deal_not_found'; END IF;
    IF p_actor NOT IN (d.dropper, d.executor) THEN RAISE EXCEPTION 'not_participant'; END IF;
    IF d.state <> 'SETTLED' THEN RAISE EXCEPTION 'deal_not_settled'; END IF;
  END IF;
  INSERT INTO moments(owner,deal_id,title,quote)
    VALUES (p_actor,p_deal,p_title,COALESCE(p_quote,''))
    RETURNING id INTO v;
  PERFORM _log('moment',v,'created',jsonb_build_object('deal_id',p_deal),p_actor);
  RETURN v;
END $$;

CREATE INDEX IF NOT EXISTS moments_feed_idx ON moments(created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS offers_from_idx ON offers(from_id, created_at DESC);

-- One authenticated peach per user per moment. The counter remains denormalized
-- for fast feed reads, but this table is the anti-spam source of truth.
CREATE TABLE IF NOT EXISTS moment_peaches (
  moment_id UUID NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
  actor UUID NOT NULL REFERENCES plumpers(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (moment_id, actor)
);

CREATE OR REPLACE FUNCTION peach_moment_once(p_actor UUID, p_id UUID)
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE n INT; inserted INT;
BEGIN
  PERFORM _require_verified(p_actor);
  IF NOT EXISTS (SELECT 1 FROM moments WHERE id=p_id) THEN
    RAISE EXCEPTION 'moment_not_found';
  END IF;
  INSERT INTO moment_peaches(moment_id,actor) VALUES (p_id,p_actor)
    ON CONFLICT DO NOTHING;
  GET DIAGNOSTICS inserted = ROW_COUNT;
  IF inserted = 1 THEN
    UPDATE moments SET peaches=peaches+1 WHERE id=p_id RETURNING peaches INTO n;
  ELSE
    SELECT peaches INTO n FROM moments WHERE id=p_id;
  END IF;
  RETURN n;
END $$;
