-- ============================================================
-- 013 · HỆ VẬT PHẨM — "Đẹp mua bằng Nara, Oai đổi bằng lao động"
-- Bất biến: mua Nara = bút toán kép (reconcile vẫn 0) · đồ oai chỉ earned + có decay
-- ============================================================

CREATE TABLE items (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('avatar','room','map','twin')),
  slot TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('nara','plump','earned','event')),
  price BIGINT,                    -- nara (đồng) hoặc plump (điểm) tùy source; NULL với earned
  giftable BOOLEAN NOT NULL DEFAULT false,
  rarity TEXT NOT NULL DEFAULT 'common' CHECK (rarity IN ('common','rare','epic','legend')),
  meta JSONB NOT NULL DEFAULT '{}',
  CHECK (source NOT IN ('nara','plump') OR price > 0)
);

CREATE TABLE inventory (
  owner UUID NOT NULL REFERENCES plumpers(id),
  item_id TEXT NOT NULL REFERENCES items(id),
  via TEXT NOT NULL CHECK (via IN ('buy','earned','gift','event')),
  granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ,
  PRIMARY KEY (owner, item_id)
);

CREATE TABLE equipped (
  owner UUID NOT NULL REFERENCES plumpers(id),
  slot TEXT NOT NULL,
  item_id TEXT NOT NULL REFERENCES items(id),
  PRIMARY KEY (owner, slot)
);
CREATE TABLE room_slots (
  owner UUID NOT NULL REFERENCES plumpers(id),
  slot TEXT NOT NULL,
  item_id TEXT NOT NULL REFERENCES items(id),
  PRIMARY KEY (owner, slot)
);
CREATE TABLE guestbook (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  room_owner UUID NOT NULL REFERENCES plumpers(id),
  author UUID NOT NULL REFERENCES plumpers(id),
  body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 200),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO config VALUES ('items',
  '{"milestone_broom":10,"aura_min_rating":4.9,"aura_min_reviews":5}')
  ON CONFLICT (key) DO NOTHING;

-- ---------- CATALOG SEED (khớp docs/ITEM_DESIGN_V1.md) ----------
INSERT INTO items (id,name,kind,slot,source,price,giftable,rarity,meta) VALUES
 ('non_la_neon','Nón lá Neon','avatar','head','nara',25000,true,'common','{}'),
 ('mu_chrome','Mũ bảo hiểm Chrome','avatar','head','nara',35000,true,'rare','{}'),
 ('beret_designer','Beret Designer','avatar','head','nara',30000,true,'common','{}'),
 ('frame_man_bong','Khung Mận Bông','avatar','frame','nara',30000,true,'rare','{}'),
 ('twin_skin_holo','Skin Twin Hologram','twin','twin_skin','nara',45000,false,'epic','{"ai_label_locked":true}'),
 ('wp_neon','Tường Neon Sài Gòn','room','wallpaper','nara',40000,true,'rare','{}'),
 ('wp_lantern','Tường Đèn Lồng','room','wallpaper','nara',30000,true,'common','{}'),
 ('floor_go','Sàn Gỗ Ấm','room','floor','nara',20000,true,'common','{}'),
 ('win_landmark','Cửa sổ Landmark 81','room','window','nara',80000,true,'legend','{}'),
 ('win_nhieuloc','Cửa sổ Kênh Nhiêu Lộc','room','window','nara',60000,true,'epic','{}'),
 ('win_benthanh','Cửa sổ Chợ Bến Thành','room','window','nara',70000,true,'epic','{}'),
 ('lamp_neon','Đèn Neon Mận','room','lamp','nara',25000,true,'common','{}'),
 ('music_lofi','Lo-fi Sài Gòn','room','music','nara',15000,true,'common','{}'),
 ('music_mua','Tiếng Mưa Đêm','room','music','nara',15000,true,'common','{}'),
 ('pin_caphe','Ghim Ly Cà Phê','map','pin_style','nara',20000,false,'common','{}'),
 ('pin_toolbox','Ghim Hộp Đồ Nghề','map','pin_style','nara',20000,false,'common','{}'),
 ('hand_caphe','Tay cầm Cà Phê Sữa','avatar','hand','plump',800,false,'common','{}'),
 ('hand_tovit','Tay cầm Tuốc-nơ-vít','avatar','hand','plump',800,false,'common','{}'),
 ('hand_co','Tay cầm Cọ Vẽ','avatar','hand','plump',800,false,'common','{}'),
 ('face_cuoi','Mặt Cười Tít','avatar','face','plump',500,false,'common','{}'),
 ('pinfx_lap_lanh','Hiệu ứng Ghim Lấp Lánh','map','pin_effect','plump',1200,false,'rare','{}'),
 ('choi_vang','Cây Chổi Vàng','room','shelf','earned',NULL,false,'epic','{"milestone":"broom"}'),
 ('aura_5sao','Aura Vàng 5★','avatar','aura','earned',NULL,false,'legend','{"decay":true}'),
 ('canh_man','Cánh Mận','avatar','aura','earned',NULL,false,'legend','{"monthly":true}');

-- ---------- MUA: Nara đi bút toán kép · Plump đi bút toán âm ----------
CREATE OR REPLACE FUNCTION buy_item(p_actor UUID, p_item TEXT) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE it RECORD;
BEGIN
  PERFORM _require_verified(p_actor);
  SELECT * INTO it FROM items WHERE id = p_item;
  IF NOT FOUND THEN RAISE EXCEPTION 'item_not_found'; END IF;
  IF it.source NOT IN ('nara','plump') THEN RAISE EXCEPTION 'item_not_for_sale'; END IF;
  IF EXISTS (SELECT 1 FROM inventory WHERE owner=p_actor AND item_id=p_item) THEN
    RAISE EXCEPTION 'already_owned'; END IF;

  IF it.source = 'nara' THEN
    -- két platform nhận Nara: kế toán kép, CHECK balance>=0 tự gác thiếu tiền
    BEGIN
      PERFORM _move(NULL, _wallet(p_actor,'user'), _wallet(NULL,'platform'), it.price, 'purchase');
    EXCEPTION WHEN check_violation THEN RAISE EXCEPTION 'insufficient_nara'; END;
  ELSE
    IF plump_balance(p_actor) < it.price THEN RAISE EXCEPTION 'insufficient_plump'; END IF;
    INSERT INTO plump_points(owner,amount,reason) VALUES (p_actor, -it.price, 'buy_'||p_item);
  END IF;

  INSERT INTO inventory(owner,item_id,via) VALUES (p_actor,p_item,'buy');
  PERFORM _log('item', p_actor, 'bought',
    jsonb_build_object('item',p_item,'source',it.source,'price',it.price), p_actor);
END $$;

-- ---------- TRANG BỊ (avatar/map) & PHÒNG — check sở hữu + đúng slot + còn hạn ----------
CREATE OR REPLACE FUNCTION _check_owned_slot(p_actor UUID, p_item TEXT, p_slot TEXT, p_kinds TEXT[])
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE it RECORD; inv RECORD;
BEGIN
  SELECT * INTO it FROM items WHERE id=p_item;
  IF NOT FOUND THEN RAISE EXCEPTION 'item_not_found'; END IF;
  IF it.slot <> p_slot OR NOT (it.kind = ANY(p_kinds)) THEN RAISE EXCEPTION 'slot_mismatch'; END IF;
  SELECT * INTO inv FROM inventory WHERE owner=p_actor AND item_id=p_item;
  IF NOT FOUND THEN RAISE EXCEPTION 'not_owned'; END IF;
  IF inv.expires_at IS NOT NULL AND inv.expires_at < now() THEN RAISE EXCEPTION 'item_expired'; END IF;
END $$;

CREATE OR REPLACE FUNCTION equip_item(p_actor UUID, p_slot TEXT, p_item TEXT) RETURNS VOID
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM _check_owned_slot(p_actor, p_item, p_slot, ARRAY['avatar','map','twin']);
  INSERT INTO equipped(owner,slot,item_id) VALUES (p_actor,p_slot,p_item)
  ON CONFLICT (owner,slot) DO UPDATE SET item_id=p_item;
END $$;

CREATE OR REPLACE FUNCTION set_room_slot(p_actor UUID, p_slot TEXT, p_item TEXT) RETURNS VOID
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM _check_owned_slot(p_actor, p_item, p_slot, ARRAY['room']);
  INSERT INTO room_slots(owner,slot,item_id) VALUES (p_actor,p_slot,p_item)
  ON CONFLICT (owner,slot) DO UPDATE SET item_id=p_item;
END $$;

-- ---------- TẶNG: một chiều, chỉ đồ nara-giftable, phải từng deal chung ----------
CREATE OR REPLACE FUNCTION gift_item(p_actor UUID, p_to UUID, p_item TEXT) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE it RECORD;
BEGIN
  SELECT * INTO it FROM items WHERE id=p_item;
  IF NOT FOUND THEN RAISE EXCEPTION 'item_not_found'; END IF;
  IF NOT it.giftable OR it.source <> 'nara' THEN RAISE EXCEPTION 'not_giftable'; END IF;
  IF NOT are_connected(p_actor, p_to) THEN RAISE EXCEPTION 'gift_requires_connection'; END IF;
  IF EXISTS (SELECT 1 FROM inventory WHERE owner=p_to AND item_id=p_item) THEN
    RAISE EXCEPTION 'already_owned'; END IF;
  DELETE FROM inventory WHERE owner=p_actor AND item_id=p_item;
  IF NOT FOUND THEN RAISE EXCEPTION 'not_owned'; END IF;
  DELETE FROM equipped WHERE owner=p_actor AND item_id=p_item;
  DELETE FROM room_slots WHERE owner=p_actor AND item_id=p_item;
  INSERT INTO inventory(owner,item_id,via) VALUES (p_to,p_item,'gift');
  PERFORM notify_user(p_to,'gift','Bạn được tặng "'||it.name||'" 🎁',NULL);
  PERFORM _log('item', p_actor, 'gifted', jsonb_build_object('item',p_item,'to',p_to), p_actor);
END $$;

-- ---------- SỔ KHÁCH: chỉ ai từng deal chung ----------
CREATE OR REPLACE FUNCTION guestbook_write(p_actor UUID, p_owner UUID, p_body TEXT) RETURNS UUID
LANGUAGE plpgsql AS $$
DECLARE v UUID;
BEGIN
  IF p_actor = p_owner THEN RAISE EXCEPTION 'guestbook_self'; END IF;
  IF NOT are_connected(p_actor, p_owner) THEN RAISE EXCEPTION 'guestbook_requires_deal'; END IF;
  INSERT INTO guestbook(room_owner,author,body) VALUES (p_owner,p_actor,p_body) RETURNING id INTO v;
  RETURN v;
END $$;

-- ---------- MỐC LAO ĐỘNG: settle thứ N tự cấp đồ (nối vào trigger settle) ----------
CREATE OR REPLACE FUNCTION _grant_milestones(p_owner UUID) RETURNS VOID
LANGUAGE plpgsql AS $$
DECLARE n INT; lim INT;
BEGIN
  SELECT (val->>'milestone_broom')::INT INTO lim FROM config WHERE key='items';
  SELECT count(*) INTO n FROM deals WHERE executor=p_owner AND state='SETTLED';
  IF n >= lim THEN
    INSERT INTO inventory(owner,item_id,via) VALUES (p_owner,'choi_vang','earned')
    ON CONFLICT DO NOTHING;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION _after_settle() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE t TEXT; n_pair INT;
BEGIN
  IF NEW.state='SETTLED' AND OLD.state IS DISTINCT FROM 'SETTLED' THEN
    INSERT INTO connections(a,b,first_deal)
      VALUES (LEAST(NEW.dropper,NEW.executor),GREATEST(NEW.dropper,NEW.executor),NEW.id)
      ON CONFLICT DO NOTHING;
    SELECT title INTO t FROM drops WHERE id=NEW.drop_id;
    INSERT INTO moments(owner,deal_id,title,quote) VALUES
      (NEW.executor,NEW.id,'Hoàn thành "'||t||'"','★ đang chờ mở mù'),
      (NEW.dropper, NEW.id,'Việc "'||t||'" xong đẹp','★ đang chờ mở mù');
    INSERT INTO plump_points(owner,amount,reason,deal_id) VALUES
      (NEW.executor,500,'settle_executor',NEW.id),
      (NEW.dropper, 200,'settle_dropper', NEW.id);
    PERFORM notify_user(NEW.executor,'settled','Tiền đã về ví · +🍑500',NEW.id);
    PERFORM notify_user(NEW.dropper,'settled','Deal hoàn tất · +🍑200 · đã kết nối',NEW.id);
    PERFORM _grant_milestones(NEW.executor);
    SELECT count(*) INTO n_pair FROM deals
      WHERE state='SETTLED' AND settled_at::date = CURRENT_DATE
        AND LEAST(dropper,executor)=LEAST(NEW.dropper,NEW.executor)
        AND GREATEST(dropper,executor)=GREATEST(NEW.dropper,NEW.executor);
    IF n_pair >= 4 THEN
      INSERT INTO fraud_flags(kind,a,b,deal_id,note)
      VALUES ('pair_velocity',LEAST(NEW.dropper,NEW.executor),GREATEST(NEW.dropper,NEW.executor),
              NEW.id, n_pair || ' deal cùng cặp trong ngày — nghi farm điểm/rửa phí')
      ON CONFLICT DO NOTHING;
    END IF;
  END IF;
  RETURN NEW;
END $$;

-- ---------- DANH VỌNG CÓ DECAY: aura 5★ — đạt thì cấp, tụt là RỤNG + tự tháo ----------
CREATE OR REPLACE FUNCTION refresh_prestige() RETURNS TABLE(granted INT, revoked INT)
LANGUAGE plpgsql AS $$
DECLARE g INT := 0; r INT := 0; min_r NUMERIC; min_n INT; rec RECORD;
BEGIN
  SELECT (val->>'aura_min_rating')::NUMERIC, (val->>'aura_min_reviews')::INT
    INTO min_r, min_n FROM config WHERE key='items';
  FOR rec IN
    SELECT p.id,
      COALESCE(AVG(v.rating),0) avg_r, COUNT(v.rating) n_r,
      EXISTS(SELECT 1 FROM inventory i WHERE i.owner=p.id AND i.item_id='aura_5sao') has_aura
    FROM plumpers p LEFT JOIN deal_reviews_visible v ON v.target=p.id
    GROUP BY p.id
  LOOP
    IF rec.avg_r >= min_r AND rec.n_r >= min_n AND NOT rec.has_aura THEN
      INSERT INTO inventory(owner,item_id,via) VALUES (rec.id,'aura_5sao','earned')
        ON CONFLICT DO NOTHING;
      PERFORM notify_user(rec.id,'prestige','🌟 Aura Vàng 5★ đã thắp — giữ chuẩn để giữ sáng',NULL);
      g := g + 1;
    ELSIF rec.has_aura AND (rec.avg_r < min_r OR rec.n_r < min_n) THEN
      DELETE FROM inventory WHERE owner=rec.id AND item_id='aura_5sao';
      DELETE FROM equipped  WHERE owner=rec.id AND item_id='aura_5sao';
      PERFORM notify_user(rec.id,'prestige','Aura Vàng 5★ đã tắt — rating tụt dưới chuẩn',NULL);
      r := r + 1;
    END IF;
  END LOOP;
  RETURN QUERY SELECT g, r;
END $$;

-- Nới CHECK kind của sổ cái: thêm 'purchase' (mua vật phẩm = Nara sink qua kế toán kép)
ALTER TABLE ledger_entries DROP CONSTRAINT ledger_entries_kind_check;
ALTER TABLE ledger_entries ADD CONSTRAINT ledger_entries_kind_check
  CHECK (kind IN ('topup','hold','release_net','fee','refund','withdraw','purchase'));
