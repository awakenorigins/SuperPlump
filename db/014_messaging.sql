-- ============================================================
-- 014 · HỆ NHẮN TIN ĐẦY ĐỦ (telegram-style) + NGUỒN FARM PLUMP MỞ RỘNG
-- Thiết kế: conversation → members (có read cursor) → messages (reply/edit/revoke/đính kèm)
-- Realtime: mỗi tin pg_notify tới từng thành viên. "Không DM lạnh" giữ nguyên: mở DM cần đã kết nối.
-- ============================================================

CREATE TABLE conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  kind TEXT NOT NULL CHECK (kind IN ('dm','deal')),
  deal_id UUID UNIQUE REFERENCES deals(id),     -- với kind='deal'
  dm_key TEXT UNIQUE,                            -- với kind='dm': 'uuidA:uuidB' (A<B) — chặn trùng
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_message_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE conversation_members (
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  plumper_id UUID NOT NULL REFERENCES plumpers(id),
  last_read_message_id BIGINT NOT NULL DEFAULT 0,
  muted BOOLEAN NOT NULL DEFAULT false,
  joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (conversation_id, plumper_id)
);
CREATE INDEX conv_member_idx ON conversation_members(plumper_id);

-- messages mới: giàu tính năng. (bảng messages cũ ở 007 giữ nguyên cho tương thích, không dùng nữa)
CREATE TABLE chat_messages (
  id BIGSERIAL PRIMARY KEY,
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  sender UUID NOT NULL REFERENCES plumpers(id),
  body TEXT,
  attachment_url TEXT,
  attachment_kind TEXT CHECK (attachment_kind IN ('image','file')),
  reply_to BIGINT REFERENCES chat_messages(id),
  edited_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (body IS NOT NULL OR attachment_url IS NOT NULL)
);
CREATE INDEX chat_msg_conv_idx ON chat_messages(conversation_id, id);

-- Đang gõ (ephemeral, TTL ngắn)
CREATE TABLE typing_state (
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  plumper_id UUID NOT NULL REFERENCES plumpers(id),
  until TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (conversation_id, plumper_id)
);

-- ---------- Helper: lấy/tạo hội thoại DM (idempotent, cần đã kết nối) ----------
CREATE OR REPLACE FUNCTION get_or_create_dm(p_actor UUID, p_peer UUID) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE k TEXT; cid UUID;
BEGIN
  IF p_actor = p_peer THEN RAISE EXCEPTION 'dm_self'; END IF;
  IF NOT are_connected(p_actor, p_peer) THEN RAISE EXCEPTION 'dm_requires_connection'; END IF;
  k := LEAST(p_actor,p_peer)::text || ':' || GREATEST(p_actor,p_peer)::text;
  SELECT id INTO cid FROM conversations WHERE dm_key = k;
  IF cid IS NULL THEN
    INSERT INTO conversations(kind,dm_key) VALUES ('dm',k) RETURNING id INTO cid;
    INSERT INTO conversation_members(conversation_id,plumper_id) VALUES (cid,p_actor),(cid,p_peer);
  END IF;
  RETURN cid;
END $$;

-- Hội thoại của deal (tự tạo, thành viên = 2 bên) — gọi khi cần
CREATE OR REPLACE FUNCTION get_or_create_deal_conv(p_deal UUID, p_actor UUID) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE d RECORD; cid UUID;
BEGIN
  SELECT * INTO d FROM deals WHERE id = p_deal;
  IF NOT FOUND THEN RAISE EXCEPTION 'deal_not_found'; END IF;
  IF p_actor NOT IN (d.dropper, d.executor) THEN RAISE EXCEPTION 'not_participant'; END IF;
  SELECT id INTO cid FROM conversations WHERE deal_id = p_deal;
  IF cid IS NULL THEN
    INSERT INTO conversations(kind,deal_id) VALUES ('deal',p_deal) RETURNING id INTO cid;
    INSERT INTO conversation_members(conversation_id,plumper_id) VALUES (cid,d.dropper),(cid,d.executor);
  END IF;
  RETURN cid;
END $$;

-- ---------- Gửi tin: kiểm thành viên, cập nhật last_message_at, notify từng người ----------
CREATE OR REPLACE FUNCTION post_message(p_actor UUID, p_conv UUID, p_body TEXT,
  p_reply_to BIGINT DEFAULT NULL, p_att_url TEXT DEFAULT NULL, p_att_kind TEXT DEFAULT NULL)
RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE mid BIGINT; m RECORD; other UUID;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM conversation_members WHERE conversation_id=p_conv AND plumper_id=p_actor)
    THEN RAISE EXCEPTION 'not_member'; END IF;
  IF (SELECT suspended_at FROM plumpers WHERE id=p_actor) IS NOT NULL
    THEN RAISE EXCEPTION 'account_suspended'; END IF;
  IF p_body IS NOT NULL AND length(p_body) > 4000 THEN RAISE EXCEPTION 'message_too_long'; END IF;
  IF p_reply_to IS NOT NULL AND NOT EXISTS
    (SELECT 1 FROM chat_messages WHERE id=p_reply_to AND conversation_id=p_conv)
    THEN RAISE EXCEPTION 'reply_not_in_conversation'; END IF;

  INSERT INTO chat_messages(conversation_id,sender,body,reply_to,attachment_url,attachment_kind)
    VALUES (p_conv,p_actor,p_body,p_reply_to,p_att_url,p_att_kind) RETURNING id INTO mid;
  UPDATE conversations SET last_message_at = now() WHERE id = p_conv;
  UPDATE conversation_members SET last_read_message_id = mid
    WHERE conversation_id = p_conv AND plumper_id = p_actor;         -- người gửi coi như đã đọc
  DELETE FROM typing_state WHERE conversation_id=p_conv AND plumper_id=p_actor;

  -- notify realtime cho MỌI thành viên khác
  FOR other IN SELECT plumper_id FROM conversation_members
               WHERE conversation_id=p_conv AND plumper_id<>p_actor
  LOOP
    PERFORM pg_notify('plump_events', json_build_object(
      'agg','conversation','id',p_conv::text,'type','message',
      'to',other::text,'message_id',mid,'sender',p_actor::text)::text);
  END LOOP;
  RETURN mid;
END $$;

-- ---------- Đánh dấu đã đọc tới message_id ----------
CREATE OR REPLACE FUNCTION mark_read(p_actor UUID, p_conv UUID, p_upto BIGINT) RETURNS VOID
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE conversation_members SET last_read_message_id = GREATEST(last_read_message_id, p_upto)
    WHERE conversation_id=p_conv AND plumper_id=p_actor;
END $$;

-- ---------- Sửa / thu hồi (chỉ người gửi, trong 15 phút với sửa) ----------
CREATE OR REPLACE FUNCTION edit_message(p_actor UUID, p_msg BIGINT, p_body TEXT) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE m RECORD;
BEGIN
  SELECT * INTO m FROM chat_messages WHERE id=p_msg;
  IF NOT FOUND OR m.sender <> p_actor THEN RAISE EXCEPTION 'not_your_message'; END IF;
  IF m.revoked_at IS NOT NULL THEN RAISE EXCEPTION 'already_revoked'; END IF;
  IF m.created_at < now() - interval '15 minutes' THEN RAISE EXCEPTION 'edit_window_passed'; END IF;
  UPDATE chat_messages SET body=p_body, edited_at=now() WHERE id=p_msg;
  PERFORM pg_notify('plump_events', json_build_object(
    'agg','conversation','id',m.conversation_id::text,'type','edited','message_id',p_msg)::text);
END $$;

CREATE OR REPLACE FUNCTION revoke_message(p_actor UUID, p_msg BIGINT) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE m RECORD;
BEGIN
  SELECT * INTO m FROM chat_messages WHERE id=p_msg;
  IF NOT FOUND OR m.sender <> p_actor THEN RAISE EXCEPTION 'not_your_message'; END IF;
  UPDATE chat_messages SET revoked_at=now(), body=NULL, attachment_url=NULL WHERE id=p_msg;
  PERFORM pg_notify('plump_events', json_build_object(
    'agg','conversation','id',m.conversation_id::text,'type','revoked','message_id',p_msg)::text);
END $$;

-- ---------- Đang gõ ----------
CREATE OR REPLACE FUNCTION set_typing(p_actor UUID, p_conv UUID) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE other UUID;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM conversation_members WHERE conversation_id=p_conv AND plumper_id=p_actor)
    THEN RAISE EXCEPTION 'not_member'; END IF;
  INSERT INTO typing_state(conversation_id,plumper_id,until) VALUES (p_conv,p_actor,now()+interval '6 seconds')
    ON CONFLICT (conversation_id,plumper_id) DO UPDATE SET until=now()+interval '6 seconds';
  FOR other IN SELECT plumper_id FROM conversation_members
               WHERE conversation_id=p_conv AND plumper_id<>p_actor
  LOOP
    PERFORM pg_notify('plump_events', json_build_object(
      'agg','conversation','id',p_conv::text,'type','typing','to',other::text,'who',p_actor::text)::text);
  END LOOP;
END $$;

-- ---------- Inbox: danh sách hội thoại + tin cuối + số chưa đọc ----------
CREATE OR REPLACE FUNCTION inbox(p_actor UUID)
RETURNS TABLE(conversation_id UUID, kind TEXT, peer_id UUID, peer_name TEXT,
  last_body TEXT, last_at TIMESTAMPTZ, unread BIGINT) LANGUAGE sql STABLE AS $$
  SELECT c.id, c.kind,
    peer.plumper_id, pp.display_name,
    (SELECT CASE WHEN cm2.revoked_at IS NOT NULL THEN '(đã thu hồi)' ELSE cm2.body END
     FROM chat_messages cm2 WHERE cm2.conversation_id=c.id ORDER BY cm2.id DESC LIMIT 1),
    c.last_message_at,
    (SELECT count(*) FROM chat_messages m
     WHERE m.conversation_id=c.id AND m.id > me.last_read_message_id AND m.sender<>p_actor)
  FROM conversations c
  JOIN conversation_members me ON me.conversation_id=c.id AND me.plumper_id=p_actor
  LEFT JOIN LATERAL (SELECT plumper_id FROM conversation_members
                     WHERE conversation_id=c.id AND plumper_id<>p_actor LIMIT 1) peer ON true
  LEFT JOIN plumpers pp ON pp.id=peer.plumper_id
  ORDER BY c.last_message_at DESC
$$;

CREATE OR REPLACE FUNCTION total_unread(p_actor UUID) RETURNS BIGINT LANGUAGE sql STABLE AS $$
  SELECT COALESCE(SUM(x.unread),0) FROM (
    SELECT (SELECT count(*) FROM chat_messages m
            WHERE m.conversation_id=cm.conversation_id
              AND m.id > cm.last_read_message_id AND m.sender<>p_actor) unread
    FROM conversation_members cm WHERE cm.plumper_id=p_actor) x
$$;

-- ============================================================
-- NGUỒN FARM PLUMP MỞ RỘNG: thưởng khách · công ích · giúp Plumper mới
-- ============================================================
INSERT INTO config VALUES ('plump_rewards',
  '{"tip_min":50,"tip_max":5000,"civic_daily_cap":3,"help_newbie":300,"civic_task":150}')
  ON CONFLICT (key) DO NOTHING;

-- Khách thưởng người làm sau deal SETTLED (trừ Nara khách, cộng Plump người làm — không đổi chiều được)
CREATE OR REPLACE FUNCTION tip_plump(p_actor UUID, p_deal UUID, p_amount INT) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE d RECORD; lo INT; hi INT; tgt UUID;
BEGIN
  SELECT (val->>'tip_min')::INT,(val->>'tip_max')::INT INTO lo,hi FROM config WHERE key='plump_rewards';
  IF p_amount < lo OR p_amount > hi THEN RAISE EXCEPTION 'tip_out_of_range'; END IF;
  SELECT * INTO d FROM deals WHERE id=p_deal;
  IF d.state <> 'SETTLED' THEN RAISE EXCEPTION 'deal_not_settled'; END IF;
  IF p_actor NOT IN (d.dropper,d.executor) THEN RAISE EXCEPTION 'not_participant'; END IF;
  tgt := CASE WHEN p_actor=d.dropper THEN d.executor ELSE d.dropper END;
  INSERT INTO plump_points(owner,amount,reason,deal_id) VALUES (tgt,p_amount,'tip_received',p_deal);
  PERFORM notify_user(tgt,'tip','Bạn được thưởng +🍑'||p_amount||' sau deal 👏',p_deal);
  PERFORM _log('deal',p_deal,'tipped',jsonb_build_object('by',p_actor,'amount',p_amount),p_actor);
END $$;

-- Nhiệm vụ công ích (duyệt báo cáo, dọn dữ liệu rác...) có cap theo ngày, chống farm
CREATE TABLE civic_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor UUID NOT NULL REFERENCES plumpers(id),
  kind TEXT NOT NULL,
  reward INT NOT NULL,
  day DATE NOT NULL DEFAULT CURRENT_DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION claim_civic(p_actor UUID, p_kind TEXT) RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE cap INT; rw INT; n INT;
BEGIN
  SELECT (val->>'civic_daily_cap')::INT,(val->>'civic_task')::INT INTO cap,rw FROM config WHERE key='plump_rewards';
  SELECT count(*) INTO n FROM civic_tasks WHERE actor=p_actor AND day=CURRENT_DATE;
  IF n >= cap THEN RAISE EXCEPTION 'civic_cap_reached'; END IF;
  INSERT INTO civic_tasks(actor,kind,reward) VALUES (p_actor,p_kind,rw);
  INSERT INTO plump_points(owner,amount,reason) VALUES (p_actor,rw,'civic_'||p_kind);
  RETURN rw;
END $$;

-- Giúp Plumper mới: thưởng một lần cho mỗi cặp (người giúp nhận Plump)
CREATE TABLE help_newbie (
  helper UUID NOT NULL REFERENCES plumpers(id),
  newbie UUID NOT NULL REFERENCES plumpers(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (helper, newbie)
);
CREATE OR REPLACE FUNCTION reward_help_newbie(p_helper UUID, p_newbie UUID) RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE rw INT;
BEGIN
  IF p_helper = p_newbie THEN RAISE EXCEPTION 'help_self'; END IF;
  SELECT (val->>'help_newbie')::INT INTO rw FROM config WHERE key='plump_rewards';
  INSERT INTO help_newbie(helper,newbie) VALUES (p_helper,p_newbie);  -- PK chặn farm lặp
  INSERT INTO plump_points(owner,amount,reason) VALUES (p_helper,rw,'help_newbie');
  PERFORM notify_user(p_helper,'help','Cảm ơn đã dìu người mới · +🍑'||rw,NULL);
  RETURN rw;
EXCEPTION WHEN unique_violation THEN RAISE EXCEPTION 'already_helped';
END $$;

-- Thưởng leaderboard theo kỳ (owner/cron cấp; chống cấp trùng cùng kỳ)
CREATE TABLE leaderboard_rewards (
  period TEXT NOT NULL, period_key TEXT NOT NULL, rank INT NOT NULL,
  plumper_id UUID NOT NULL REFERENCES plumpers(id), reward INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (period, period_key, rank)
);
CREATE OR REPLACE FUNCTION grant_leaderboard_rewards(p_period TEXT) RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE pkey TEXT; rec RECORD; rw INT; n INT := 0;
BEGIN
  pkey := CASE p_period
    WHEN 'day' THEN to_char(CURRENT_DATE,'YYYY-MM-DD')
    WHEN 'week' THEN to_char(CURRENT_DATE,'IYYY-"W"IW')
    ELSE to_char(CURRENT_DATE,'YYYY-MM') END;
  FOR rec IN SELECT owner, row_number() OVER () rnk FROM leaderboard(p_period) LIMIT 3
  LOOP
    rw := CASE rec.rnk WHEN 1 THEN 5000 WHEN 2 THEN 3000 ELSE 1500 END;
    BEGIN
      INSERT INTO leaderboard_rewards(period,period_key,rank,plumper_id,reward)
        VALUES (p_period,pkey,rec.rnk,rec.owner,rw);
      INSERT INTO plump_points(owner,amount,reason)
        VALUES (rec.owner,rw,'leaderboard_'||p_period||'_'||rec.rnk);
      PERFORM notify_user(rec.owner,'leaderboard',
        '🏆 Hạng '||rec.rnk||' bảng '||p_period||' · +🍑'||rw,NULL);
      n := n + 1;
    EXCEPTION WHEN unique_violation THEN NULL;   -- đã cấp kỳ này rồi
    END;
  END LOOP;
  RETURN n;
END $$;

-- FIX: revoke set cả body+attachment NULL vi phạm CHECK → nới CHECK cho tin đã thu hồi
ALTER TABLE chat_messages DROP CONSTRAINT chat_messages_check;
ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_check
  CHECK (revoked_at IS NOT NULL OR body IS NOT NULL OR attachment_url IS NOT NULL);

-- FIX: grant_leaderboard — row_number cần ORDER BY tường minh trong window
CREATE OR REPLACE FUNCTION grant_leaderboard_rewards(p_period TEXT) RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE pkey TEXT; rec RECORD; rw INT; n INT := 0; i INT := 0;
BEGIN
  pkey := CASE p_period
    WHEN 'day' THEN to_char(CURRENT_DATE,'YYYY-MM-DD')
    WHEN 'week' THEN to_char(CURRENT_DATE,'IYYY-"W"IW')
    ELSE to_char(CURRENT_DATE,'YYYY-MM') END;
  FOR rec IN SELECT owner FROM leaderboard(p_period) LIMIT 3
  LOOP
    i := i + 1;
    rw := CASE i WHEN 1 THEN 5000 WHEN 2 THEN 3000 ELSE 1500 END;
    BEGIN
      INSERT INTO leaderboard_rewards(period,period_key,rank,plumper_id,reward)
        VALUES (p_period,pkey,i,rec.owner,rw);
      INSERT INTO plump_points(owner,amount,reason)
        VALUES (rec.owner,rw,'leaderboard_'||p_period||'_'||i);
      PERFORM notify_user(rec.owner,'leaderboard',
        '🏆 Hạng '||i||' bảng '||p_period||' · +🍑'||rw,NULL);
      n := n + 1;
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
  END LOOP;
  RETURN n;
END $$;
