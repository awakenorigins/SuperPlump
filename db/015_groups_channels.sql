-- ============================================================
-- 015 · NHÓM & CHANNEL & STATUS & CẤP ĐỘ
-- Triết lý giữ nguyên: nhóm chỉ thêm được người "quen qua việc"; channel công khai ai verified cũng theo dõi được
-- ============================================================

-- ---------- Mở rộng conversations: group + channel ----------
ALTER TABLE conversations DROP CONSTRAINT conversations_kind_check;
ALTER TABLE conversations ADD CONSTRAINT conversations_kind_check
  CHECK (kind IN ('dm','deal','group','channel'));
ALTER TABLE conversations
  ADD COLUMN title TEXT,
  ADD COLUMN owner UUID REFERENCES plumpers(id),
  ADD COLUMN invite_code TEXT UNIQUE,
  ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE conversation_members
  ADD COLUMN role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner','admin','member'));

-- Vị trí là loại đính kèm thứ ba
ALTER TABLE chat_messages DROP CONSTRAINT chat_messages_attachment_kind_check;
ALTER TABLE chat_messages ADD CONSTRAINT chat_messages_attachment_kind_check
  CHECK (attachment_kind IN ('image','file','location'));

-- ---------- Tạo NHÓM: chỉ thêm người đã quen qua việc, cap 50 ----------
CREATE OR REPLACE FUNCTION create_group(p_actor UUID, p_title TEXT, p_members UUID[])
RETURNS TABLE(conversation_id UUID, invite_code TEXT) LANGUAGE plpgsql AS $$
DECLARE cid UUID; code TEXT; m UUID;
BEGIN
  PERFORM _require_verified(p_actor);
  IF array_length(p_members,1) > 49 THEN RAISE EXCEPTION 'group_full'; END IF;
  code := upper(substr(md5(random()::text),1,8));
  INSERT INTO conversations(kind,title,owner,invite_code)
    VALUES ('group',p_title,p_actor,code) RETURNING id INTO cid;
  INSERT INTO conversation_members(conversation_id,plumper_id,role) VALUES (cid,p_actor,'owner');
  FOREACH m IN ARRAY COALESCE(p_members,'{}') LOOP
    IF m = p_actor THEN CONTINUE; END IF;
    IF NOT are_connected(p_actor,m) THEN RAISE EXCEPTION 'member_not_connected'; END IF;
    INSERT INTO conversation_members(conversation_id,plumper_id,role) VALUES (cid,m,'member')
      ON CONFLICT DO NOTHING;
    PERFORM notify_user(m,'group','Bạn được thêm vào nhóm "'||p_title||'"',NULL);
  END LOOP;
  RETURN QUERY SELECT cid, code;
END $$;

-- ---------- Tạo CHANNEL: chủ + admin đăng, member chỉ đọc ----------
CREATE OR REPLACE FUNCTION create_channel(p_actor UUID, p_title TEXT, p_public BOOLEAN)
RETURNS TABLE(conversation_id UUID, invite_code TEXT) LANGUAGE plpgsql AS $$
DECLARE cid UUID; code TEXT;
BEGIN
  PERFORM _require_verified(p_actor);
  code := upper(substr(md5(random()::text),1,8));
  INSERT INTO conversations(kind,title,owner,invite_code,is_public)
    VALUES ('channel',p_title,p_actor,code,p_public) RETURNING id INTO cid;
  INSERT INTO conversation_members(conversation_id,plumper_id,role) VALUES (cid,p_actor,'owner');
  RETURN QUERY SELECT cid, code;
END $$;

-- ---------- Tham gia: channel công khai vào thẳng; nhóm/channel kín vào bằng mã ----------
CREATE OR REPLACE FUNCTION join_conversation(p_actor UUID, p_conv UUID) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE c RECORD;
BEGIN
  PERFORM _require_verified(p_actor);
  SELECT * INTO c FROM conversations WHERE id=p_conv;
  IF NOT FOUND OR c.kind <> 'channel' OR NOT c.is_public THEN RAISE EXCEPTION 'not_public'; END IF;
  INSERT INTO conversation_members(conversation_id,plumper_id) VALUES (p_conv,p_actor)
    ON CONFLICT DO NOTHING;
END $$;

CREATE OR REPLACE FUNCTION join_by_code(p_actor UUID, p_code TEXT) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE c RECORD;
BEGIN
  PERFORM _require_verified(p_actor);
  SELECT * INTO c FROM conversations WHERE invite_code = upper(p_code) AND kind IN ('group','channel');
  IF NOT FOUND THEN RAISE EXCEPTION 'bad_invite_code'; END IF;
  INSERT INTO conversation_members(conversation_id,plumper_id) VALUES (c.id,p_actor)
    ON CONFLICT DO NOTHING;
  RETURN c.id;
END $$;

CREATE OR REPLACE FUNCTION leave_conversation(p_actor UUID, p_conv UUID) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE r TEXT;
BEGIN
  SELECT role INTO r FROM conversation_members WHERE conversation_id=p_conv AND plumper_id=p_actor;
  IF r IS NULL THEN RAISE EXCEPTION 'not_member'; END IF;
  IF r = 'owner' THEN RAISE EXCEPTION 'owner_cannot_leave'; END IF;
  DELETE FROM conversation_members WHERE conversation_id=p_conv AND plumper_id=p_actor;
END $$;

-- Thêm thành viên vào NHÓM (owner/admin, người mới phải quen actor)
CREATE OR REPLACE FUNCTION add_members(p_actor UUID, p_conv UUID, p_members UUID[]) RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE c RECORD; r TEXT; m UUID; n INT := 0;
BEGIN
  SELECT * INTO c FROM conversations WHERE id=p_conv;
  IF c.kind <> 'group' THEN RAISE EXCEPTION 'not_group'; END IF;
  SELECT role INTO r FROM conversation_members WHERE conversation_id=p_conv AND plumper_id=p_actor;
  IF r NOT IN ('owner','admin') THEN RAISE EXCEPTION 'not_admin'; END IF;
  FOREACH m IN ARRAY p_members LOOP
    IF NOT are_connected(p_actor,m) THEN RAISE EXCEPTION 'member_not_connected'; END IF;
    INSERT INTO conversation_members(conversation_id,plumper_id) VALUES (p_conv,m)
      ON CONFLICT DO NOTHING;
    n := n + 1;
    PERFORM notify_user(m,'group','Bạn được thêm vào "'||c.title||'"',NULL);
  END LOOP;
  RETURN n;
END $$;

-- ---------- post_message v2: channel chỉ owner/admin được đăng ----------
CREATE OR REPLACE FUNCTION post_message(p_actor UUID, p_conv UUID, p_body TEXT,
  p_reply_to BIGINT DEFAULT NULL, p_att_url TEXT DEFAULT NULL, p_att_kind TEXT DEFAULT NULL)
RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE mid BIGINT; other UUID; my RECORD; c RECORD;
BEGIN
  SELECT cm.role, co.kind INTO my
    FROM conversation_members cm JOIN conversations co ON co.id=cm.conversation_id
    WHERE cm.conversation_id=p_conv AND cm.plumper_id=p_actor;
  IF NOT FOUND THEN RAISE EXCEPTION 'not_member'; END IF;
  IF my.kind='channel' AND my.role NOT IN ('owner','admin') THEN RAISE EXCEPTION 'channel_readonly'; END IF;
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
    WHERE conversation_id = p_conv AND plumper_id = p_actor;
  DELETE FROM typing_state WHERE conversation_id=p_conv AND plumper_id=p_actor;
  FOR other IN SELECT plumper_id FROM conversation_members
               WHERE conversation_id=p_conv AND plumper_id<>p_actor
  LOOP
    PERFORM pg_notify('plump_events', json_build_object(
      'agg','conversation','id',p_conv::text,'type','message',
      'to',other::text,'message_id',mid,'sender',p_actor::text)::text);
  END LOOP;
  RETURN mid;
END $$;

-- ---------- inbox v2: có title + member_count cho nhóm/channel ----------
DROP FUNCTION inbox(UUID);
CREATE FUNCTION inbox(p_actor UUID)
RETURNS TABLE(conversation_id UUID, kind TEXT, title TEXT, peer_id UUID, peer_name TEXT,
  member_count BIGINT, last_body TEXT, last_at TIMESTAMPTZ, unread BIGINT, my_role TEXT)
LANGUAGE sql STABLE AS $$
  SELECT c.id, c.kind,
    COALESCE(c.title, pp.display_name),
    peer.plumper_id, pp.display_name,
    (SELECT count(*) FROM conversation_members x WHERE x.conversation_id=c.id),
    (SELECT CASE WHEN cm2.revoked_at IS NOT NULL THEN '(đã thu hồi)'
                 WHEN cm2.attachment_kind='image' THEN '🖼️ Ảnh'
                 WHEN cm2.attachment_kind='location' THEN '📍 Vị trí'
                 ELSE cm2.body END
     FROM chat_messages cm2 WHERE cm2.conversation_id=c.id ORDER BY cm2.id DESC LIMIT 1),
    c.last_message_at,
    (SELECT count(*) FROM chat_messages m
     WHERE m.conversation_id=c.id AND m.id > me.last_read_message_id AND m.sender<>p_actor),
    me.role
  FROM conversations c
  JOIN conversation_members me ON me.conversation_id=c.id AND me.plumper_id=p_actor
  LEFT JOIN LATERAL (SELECT plumper_id FROM conversation_members
                     WHERE conversation_id=c.id AND plumper_id<>p_actor
                     AND c.kind IN ('dm','deal') LIMIT 1) peer ON true
  LEFT JOIN plumpers pp ON pp.id=peer.plumper_id
  ORDER BY c.last_message_at DESC
$$;

-- ---------- STATUS: Plumper đăng trạng thái ngắn (24h) hiện trên map ----------
CREATE TABLE plumper_status (
  owner UUID PRIMARY KEY REFERENCES plumpers(id),
  body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 80),
  emoji TEXT NOT NULL DEFAULT '💬',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '24 hours'
);
CREATE OR REPLACE FUNCTION set_status(p_actor UUID, p_body TEXT, p_emoji TEXT) RETURNS VOID
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO plumper_status(owner,body,emoji) VALUES (p_actor,p_body,COALESCE(p_emoji,'💬'))
  ON CONFLICT (owner) DO UPDATE SET body=EXCLUDED.body, emoji=EXCLUDED.emoji,
    created_at=now(), expires_at=now()+interval '24 hours';
END $$;

-- ---------- CẤP ĐỘ: từ số deal SETTLED (lao động, không mua được) ----------
CREATE OR REPLACE FUNCTION plump_level(p UUID) RETURNS INT LANGUAGE sql STABLE AS $$
  SELECT CASE WHEN n >= 50 THEN 5 WHEN n >= 15 THEN 4 WHEN n >= 5 THEN 3
              WHEN n >= 1 THEN 2 ELSE 1 END
  FROM (SELECT count(*) n FROM deals WHERE state='SETTLED' AND (executor=p OR dropper=p)) x
$$;
