/* SUPERPLUMP API V2 · Tầng A+B+C
 * A: JWT (HS256, fallback dev-uuid có cờ) · zod · rate-limit · helmet/cors · PDPL endpoints
 * B: WebSocket realtime (pg LISTEN) · chat · notifications · moments · điểm Plump · leaderboard
 *    · twin worker + phòng thi chạy trong tiến trình (engine claude-fable-5, có MOCK mode)
 * C: mandate ký số Ed25519 cho twin · attestation + verify · feed agent-readable · KYA-lite
 */
const express = require("express");
const http = require("http");
const https = require("https");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { Pool, Client } = require("pg");
const jwt = require("jsonwebtoken");
const { z } = require("zod");
const rateLimit = require("express-rate-limit");
const { ipKeyGenerator } = require("express-rate-limit");
const helmet = require("helmet");
const cors = require("cors");
const { WebSocketServer } = require("ws");

/* Secrets: ưu tiên FILE (Docker secrets) rồi mới env — không bao giờ log giá trị */
function secret(name, dflt) {
  const f = process.env[name + "_FILE"];
  if (f) { try { return fs.readFileSync(f, "utf8").trim(); } catch {} }
  return process.env[name] ?? dflt;
}
const PG = {
  host: process.env.PGHOST || "127.0.0.1",
  user: process.env.PGUSER || "plump",
  password: secret("PGPASSWORD", "plump"),
  database: process.env.PGDATABASE || "superplump",
};
const pool = new Pool({ ...PG, connectionTimeoutMillis: 3000, max: 10 });
pool.on("error", (e) => console.error("[pool] idle client error:", e.message));   // KHÔNG crash
const ADMIN_KEY = secret("ADMIN_KEY", "plump-admin");
const JWT_SECRET = secret("SUPABASE_JWT_SECRET", "dev-jwt-secret");
const OWNER_TOKEN = secret("OWNER_TOKEN", "chaunacha");   // DEV default — production PHẢI đổi qua env
const DEV = (process.env.NODE_ENV || "dev") !== "production";
const ALLOW_DEV_UUID = DEV && process.env.ALLOW_DEV_UUID !== "0";
const MODEL = process.env.ANTHROPIC_MODEL || "claude-fable-5";
const PUBLIC_DOMAIN = (process.env.PUBLIC_DOMAIN || "superplump1a.62.146.238.213.sslip.io").replace(/^https?:\/\//, "").replace(/\/$/, "");
const DEFAULT_ALLOWED_ORIGINS = [`https://${PUBLIC_DOMAIN}`];
const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS || DEFAULT_ALLOWED_ORIGINS.join(","))
  .split(",").map(s => s.trim()).filter(Boolean);
function corsOrigin(origin, cb) {
  // Allow no-Origin clients (mobile apps, curl, server-to-server, health checks).
  if (!origin) return cb(null, true);
  if (ALLOWED_ORIGINS.includes(origin)) return cb(null, true);
  return cb(new Error("cors_origin_denied"));
}

const app = express();
/* ===== OBSERVABILITY: request-id · access log JSON · Prometheus /metrics ===== */
const MET = { req: new Map(), err: 0, bounds: [5,10,25,50,100,250,500,1000,2500],
              hist: new Array(10).fill(0), histSum: 0, histN: 0, ws: 0 };
app.use((req, res, next) => {
  req.id = crypto.randomUUID(); res.setHeader("x-request-id", req.id);
  const t0 = process.hrtime.bigint();
  res.on("finish", () => {
    const ms = Number(process.hrtime.bigint() - t0) / 1e6;
    const route = (req.baseUrl || "") + (req.route?.path || req.path.replace(/[0-9a-f-]{20,}/g, ":id"));
    const k = req.method + " " + route + " " + Math.floor(res.statusCode / 100) + "xx";
    MET.req.set(k, (MET.req.get(k) || 0) + 1);
    if (res.statusCode >= 500) MET.err++;
    let i = MET.bounds.findIndex(b => ms <= b); if (i < 0) i = MET.bounds.length;
    MET.hist[i]++; MET.histSum += ms; MET.histN++;
    if (!["/metrics", "/health", "/status"].includes(req.path))
      console.log(JSON.stringify({ t: new Date().toISOString(), id: req.id, m: req.method,
        p: req.path, st: res.statusCode, ms: +ms.toFixed(1), uid: req.uid || null }));
  });
  next();
});
app.get("/metrics", async (_q, res) => {
  const L = [];
  L.push("# TYPE plump_http_requests_total counter");
  for (const [k, v] of MET.req) {
    const [m, route, st] = k.split(" ");
    L.push(`plump_http_requests_total{method="${m}",route="${route}",status="${st}"} ${v}`);
  }
  L.push("# TYPE plump_http_errors_total counter", `plump_http_errors_total ${MET.err}`);
  L.push("# TYPE plump_http_duration_ms histogram");
  let cum = 0;
  MET.bounds.forEach((b, i) => { cum += MET.hist[i]; L.push(`plump_http_duration_ms_bucket{le="${b}"} ${cum}`); });
  L.push(`plump_http_duration_ms_bucket{le="+Inf"} ${MET.histN}`,
         `plump_http_duration_ms_sum ${MET.histSum.toFixed(1)}`,
         `plump_http_duration_ms_count ${MET.histN}`);
  try {
    const [[st], [esc], rec, [wq]] = await Promise.all([
      fn("SELECT count(*) n FROM deals WHERE state='SETTLED'"),
      fn("SELECT balance FROM wallets WHERE kind='escrow'"),
      fn("SELECT count(*) n FROM reconcile()"),
      fn("SELECT count(*) n FROM twin_jobs WHERE status='queued'"),
    ]);
    L.push("# TYPE plump_deals_settled_total counter", `plump_deals_settled_total ${st.n}`);
    L.push("# TYPE plump_escrow_balance gauge", `plump_escrow_balance ${esc.balance}`);
    L.push("# TYPE plump_ledger_mismatch gauge", `plump_ledger_mismatch ${rec[0].n}`);
    L.push("# TYPE plump_twin_jobs_queued gauge", `plump_twin_jobs_queued ${wq.n}`);
    L.push("# TYPE plump_ws_clients gauge", `plump_ws_clients ${MET.ws}`);
  } catch {}
  res.type("text/plain").send(L.join("\n") + "\n");
});
app.set("trust proxy", 1);
app.use(helmet({ contentSecurityPolicy: false }));
app.use(cors({ origin: corsOrigin, credentials: true, maxAge: 86400 }));
app.use((err, _req, res, next) => {
  if (err?.message === "cors_origin_denied")
    return problem(res, 403, "cors_origin_denied", "Origin is not allowed");
  return next(err);
});
app.use(express.json({ limit: "200kb", verify: (req, _res, buf) => { req.rawBody = buf; } }));

/* ---------- helpers ---------- */
const problem = (res, status, title, detail = "") =>
  res.status(status).type("application/problem+json")
     .json({ type: "https://superplump.vn/errors/" + title, title, status, detail });
const JWKS_URL = secret("JWKS_URL");
let _jwksCache = { t: 0, keys: [] };
async function jwksKey(kid) {
  if (!JWKS_URL) throw new Error("no_jwks");
  if (Date.now() - _jwksCache.t > 300_000) {
    const r = await fetch(JWKS_URL); _jwksCache = { t: Date.now(), keys: (await r.json()).keys || [] };
  }
  const jwk = _jwksCache.keys.find(k => k.kid === kid);
  if (!jwk) { _jwksCache.t = 0; throw new Error("kid_not_found"); }
  return crypto.createPublicKey({ key: jwk, format: "jwk" });
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const fn = async (sql, args) => (await pool.query(sql, args)).rows;

const sha256 = (t) => crypto.createHash("sha256").update(t).digest("hex");
const TOKEN_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";        // bỏ I L O 0 1 dễ nhầm
function genToken13() {
  const b = crypto.randomBytes(13); let out = "";
  for (let i = 0; i < 13; i++) out += TOKEN_ALPHABET[b[i] % TOKEN_ALPHABET.length];
  return out;
}
function hashPassword(pw) {
  const salt = crypto.randomBytes(16).toString("hex");
  return "s2:" + salt + ":" + crypto.scryptSync(pw, salt, 64).toString("hex");
}
function verifyPassword(pw, stored) {
  try { const [, salt, h] = stored.split(":");
    return crypto.timingSafeEqual(Buffer.from(h, "hex"), crypto.scryptSync(pw, salt, 64));
  } catch { return false; }
}
const PAYMENT_WEBHOOK_SECRET = secret("PAYMENT_WEBHOOK_SECRET", "dev-payment-secret");
const EKYC_WEBHOOK_SECRET = secret("EKYC_WEBHOOK_SECRET", "dev-ekyc-secret");
const hmacOk = (req, key) => {
  const sig = String(req.headers["x-signature"] || "");
  const want = crypto.createHmac("sha256", key).update(req.rawBody || Buffer.alloc(0)).digest("hex");
  return sig.length === want.length && crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(want));
};
const MASTER_KEY = secret("MASTER_KEY");
const kmsKey = MASTER_KEY ? crypto.createHash("sha256").update(MASTER_KEY).digest() : null;
function encPriv(b64) {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv("aes-256-gcm", kmsKey, iv);
  const ct = Buffer.concat([c.update(Buffer.from(b64)), c.final()]);
  return Buffer.concat([iv, c.getAuthTag(), ct]).toString("base64");
}
function decPriv(enc) {
  const b = Buffer.from(enc, "base64");
  const d = crypto.createDecipheriv("aes-256-gcm", kmsKey, b.subarray(0, 12));
  d.setAuthTag(b.subarray(12, 28));
  return Buffer.concat([d.update(b.subarray(28)), d.final()]).toString();
}
const signJwt = (id, role, jti) => jwt.sign({ sub: id, role, jti }, JWT_SECRET, { expiresIn: "7d" });
const signMfa = (id) => jwt.sign({ sub: id, mfa: true }, JWT_SECRET, { expiresIn: "5m" });
async function createSession(uid, role, req) {
  const r = await fn(
    `INSERT INTO sessions(plumper_id,user_agent,ip,expires_at)
     VALUES ($1,$2,$3,now()+interval '7 days') RETURNING jti`,
    [uid, String(req.headers["user-agent"] || "").slice(0, 200), req.ip || ""]);
  return signJwt(uid, role, r[0].jti);
}
async function recordAttempt(ip, account, success) {
  await fn("INSERT INTO login_attempts(ip,account,success) VALUES ($1,$2,$3)", [ip, account, success]);
}
async function sendCode(uid, email, purpose) {                  // seam: prod thay bằng mail provider
  const code = ("" + (crypto.randomInt(100000, 1000000)));
  await fn("INSERT INTO email_codes(plumper_id,email,purpose,code_hash) VALUES ($1,$2,$3,$4)",
           [uid, email, purpose, sha256(code)]);
  await fn("INSERT INTO dev_outbox(to_email,subject,code) VALUES ($1,$2,$3)",
           [email, purpose === "verify" ? "Mã xác minh SuperPlump" : "Mã đặt lại mật khẩu", code]);
}
async function consumeCode(uid, purpose, code) {
  const r = await fn(
    `UPDATE email_codes SET used_at=now()
     WHERE id = (SELECT id FROM email_codes WHERE plumper_id=$1 AND purpose=$2
                 AND code_hash=$3 AND used_at IS NULL AND expires_at>now()
                 ORDER BY created_at DESC LIMIT 1)
     RETURNING email`, [uid, purpose, sha256(code)]);
  return r[0]?.email || null;
}
/* TOTP RFC6238 (SHA1, 30s, 6 số) — thuần crypto */
const B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
function b32encode(buf) {
  let bits = 0, val = 0, out = "";
  for (const byte of buf) { val = (val << 8) | byte; bits += 8;
    while (bits >= 5) { out += B32[(val >>> (bits - 5)) & 31]; bits -= 5; } }
  if (bits > 0) out += B32[(val << (5 - bits)) & 31];
  return out;
}
function b32decode(str) {
  let bits = 0, val = 0; const out = [];
  for (const ch of str.replace(/=+$/, "").toUpperCase()) {
    const i = B32.indexOf(ch); if (i < 0) continue;
    val = (val << 5) | i; bits += 5;
    if (bits >= 8) { out.push((val >>> (bits - 8)) & 255); bits -= 8; } }
  return Buffer.from(out);
}
function totpCode(secretB32, t = Date.now()) {
  const counter = Math.floor(t / 30000);
  const msg = Buffer.alloc(8); msg.writeBigUInt64BE(BigInt(counter));
  const h = crypto.createHmac("sha1", b32decode(secretB32)).update(msg).digest();
  const o = h[h.length - 1] & 0xf;
  const num = ((h[o] & 0x7f) << 24) | (h[o+1] << 16) | (h[o+2] << 8) | h[o+3];
  return String(num % 1_000_000).padStart(6, "0");
}
const totpVerify = (secret, code) =>
  [0, -30000, 30000].some(d => totpCode(secret, Date.now() + d) === String(code));

async function auth(req, res, next) {
  const tok = (req.headers.authorization || "").replace(/^Bearer\s+/i, "");
  if (!tok) return problem(res, 401, "unauthorized", "Thiếu Bearer token");
  if (UUID.test(tok)) {
    if (!ALLOW_DEV_UUID) return problem(res, 401, "unauthorized", "Dev-uuid bị tắt ở production");
    req.uid = tok; return next();
  }
  try {
    const hdr = jwt.decode(tok, { complete: true })?.header;
    const p = (hdr?.alg === "RS256")
      ? jwt.verify(tok, await jwksKey(hdr.kid), { algorithms: ["RS256"] })
      : jwt.verify(tok, JWT_SECRET);
    if (p.mfa) return problem(res, 401, "mfa_token_only", "Token này chỉ dùng cho bước 2FA");
    if (!UUID.test(p.sub)) throw 0;
    if (p.jti) {
      const ok = await fn("SELECT session_valid($1) v", [p.jti]);
      if (!ok[0].v) return problem(res, 401, "session_revoked", "Phiên đã bị thu hồi/hết hạn");
      req.jti = p.jti;
    }
    req.uid = p.sub; next();
  } catch (e) {
    console.warn("[auth] JWT rejected:", e?.message || "unknown");
    return problem(res, 401, "unauthorized", "JWT không hợp lệ");
  }
}
async function admin(req, res, next) {
  if (req.headers["x-admin-key"] === ADMIN_KEY) return next();
  const tok = (req.headers.authorization || "").replace(/^Bearer\s+/i, "");
  let uid = null;
  if (UUID.test(tok)) { if (ALLOW_DEV_UUID) uid = tok; }
  else { try { uid = jwt.verify(tok, JWT_SECRET).sub; } catch {} }
  if (uid) {
    const r = await fn("SELECT role FROM plumpers WHERE id=$1", [uid]);
    if (r[0]?.role === "owner") { req.uid = uid; return next(); }
  }
  return problem(res, 403, "admin_only", "Cần x-admin-key hoặc tài khoản owner");
}
function val(schema) {
  return (req, res, next) => {
    const r = schema.safeParse(req.body || {});
    if (!r.success) return problem(res, 400, "validation_error",
      r.error.issues.map(i => i.path.join(".") + ": " + i.message).join("; "));
    req.body = r.data; next();
  };
}
function sqlErr(res, e) {
  const m = e.message || "";
  const map = [
    ["kyc_required", 403], ["pilot_wait_required", 403], ["consent_required", 403], ["location_denied", 403],
    ["not_participant", 403], ["only_", 403], ["not_twin_owner", 403],
    ["dm_requires_connection", 403], ["twin_no_energy", 403],
    ["only_owner_buys", 403], ["twin_not_found", 404],
    ["twin_slot_limit_reached", 403],
    ["twin_suspended_unpaid", 403], ["twin_deleted", 403], ["not_twin_owner", 403],
    ["twin_real_work_only", 403],
    ["twin_market_requires_level", 403], ["twin_market_self_dealing", 403],
    ["not_poster_owner", 403], ["poster_insufficient_plump", 409],
    ["twin_market_not_open", 409], ["twin_market_not_pending", 409],
    ["twin_market_not_approved", 409], ["twin_market_price_out_of_range", 409],
    ["twin_market_deal_not_found", 404],
    ["twin_not_qualified", 403], ["mandate_missing", 403],
    ["mandate_scope_violation", 403], ["mandate_price_violation", 403],
    ["invalid_transition", 409], ["drop_not_open", 409], ["offer_not_pending", 409],
    ["kyc_not_pending", 409], ["deal_not_settled", 409], ["cannot_offer_own_drop", 409],
    ["twin_digital_only", 409], ["job_not_drafted", 409], ["request_not_pending", 409],
    ["duplicate key", 409], ["one_active_deal", 409],
    ["deal_not_found", 404], ["moment_not_found", 404], ["bad_provider", 400],
    ["account_suspended", 403], ["content_blocked", 422], ["velocity_limited", 429],
    ["item_not_found", 404], ["slot_mismatch", 400], ["not_owned", 403],
    ["gift_requires_connection", 403], ["guestbook_requires_deal", 403],
    ["item_not_for_sale", 409], ["already_owned", 409], ["not_giftable", 409],
    ["insufficient_nara", 409], ["insufficient_plump", 409], ["item_expired", 409],
    ["guestbook_self", 409],
    ["not_member", 403], ["dm_self", 409], ["message_too_long", 422],
    ["reply_not_in_conversation", 409], ["not_your_message", 403],
    ["already_revoked", 409], ["edit_window_passed", 409],
    ["tip_out_of_range", 422], ["civic_cap_reached", 429], ["help_self", 409],
    ["already_helped", 409],
    ["member_not_connected", 403], ["channel_readonly", 403], ["not_public", 403],
    ["not_admin", 403], ["not_group", 400], ["bad_invite_code", 404],
    ["owner_cannot_leave", 409], ["group_full", 409],
    ["already_onboarded", 409], ["username_taken", 409], ["username_reserved", 409],
    ["bad_username_format", 400],
  ];
  for (const [k, s] of map) if (m.includes(k))
    return problem(res, s, m.split(":")[0].trim().replace(/\s+/g, "_"), m);
  return problem(res, 500, "internal", m);
}

/* An toàn async toàn cục: Express 4 không tự bắt rejection — bọc tại điểm đăng ký */
{
  const wrap = (h) => typeof h === "function"
    ? (req, res, next) => Promise.resolve(h(req, res, next))
        .catch((e) => { if (!res.headersSent) sqlErr(res, e); })
    : h;
  for (const m of ["get", "post", "patch", "put", "delete", "use"]) {
    const orig = app[m].bind(app);
    app[m] = (...args) => orig(...args.map(wrap));
  }
}
process.on("unhandledRejection", (e) => console.error("[unhandled]", e?.message || e));

/* KYA-lite: agent bên ngoài tự xưng qua Signature-Agent → ghi vết */
app.use((req, _res, next) => {
  const sig = req.headers["signature-agent"];
  if (sig) fn("INSERT INTO agent_visits(signature_agent,user_agent,path) VALUES ($1,$2,$3)",
              [String(sig).slice(0, 500), String(req.headers["user-agent"] || "").slice(0, 300),
               req.path]).catch(() => {});
  next();
});

/* Idempotency-Key cho POST /v1/* */
app.use("/v1", async (req, res, next) => {
  if (req.method !== "POST") return next();
  const key = req.headers["idempotency-key"];
  if (!key) return next();
  const claim = await fn(
    "INSERT INTO idempotency_keys(key,status,body) VALUES ($1,0,'{}') ON CONFLICT DO NOTHING RETURNING key", [key]);
  if (!claim.length) {                       // key đã có chủ: replay (chờ nếu đang bay)
    for (let i = 0; i < 25; i++) {
      const row = await fn("SELECT status, body FROM idempotency_keys WHERE key=$1", [key]);
      if (row.length && row[0].status > 0) return res.status(row[0].status).json(row[0].body);
      await new Promise(r => setTimeout(r, 80));
    }
    return problem(res, 409, "idempotency_in_flight", "Request cùng key đang xử lý");
  }
  const orig = res.json.bind(res);
  res.json = (body) => {
    fn("UPDATE idempotency_keys SET status=$2, body=$3 WHERE key=$1",
       [key, res.statusCode, body]).catch(() => {});
    return orig(body);
  };
  next();
});

/* Rate-limit store dùng chung qua Postgres — đúng số đếm dù chạy N instance */
class PgStore {
  constructor(prefix) { this.prefix = prefix; }
  init(opts) { this.windowMs = opts.windowMs; }
  async increment(key) {
    const r = await pool.query(
      `INSERT INTO rate_limits(key,hits,expires_at) VALUES ($1,1,now()+($2::int||' milliseconds')::interval)
       ON CONFLICT (key) DO UPDATE SET
         hits = CASE WHEN rate_limits.expires_at < now() THEN 1 ELSE rate_limits.hits + 1 END,
         expires_at = CASE WHEN rate_limits.expires_at < now()
                      THEN now()+($2::int||' milliseconds')::interval ELSE rate_limits.expires_at END
       RETURNING hits, expires_at`, [this.prefix + key, this.windowMs]);
    return { totalHits: +r.rows[0].hits, resetTime: new Date(r.rows[0].expires_at) };
  }
  async decrement(key) { await pool.query("UPDATE rate_limits SET hits=GREATEST(hits-1,0) WHERE key=$1", [this.prefix+key]).catch(()=>{}); }
  async resetKey(key) { await pool.query("DELETE FROM rate_limits WHERE key=$1", [this.prefix+key]).catch(()=>{}); }
}
const topupLimiter = rateLimit({ windowMs: 60_000, max: 10, standardHeaders: true, store: new PgStore("topup:"),
  keyGenerator: (req) => req.uid || ipKeyGenerator(req.ip),
  handler: (_q, res) => problem(res, 429, "rate_limited", "Tối đa 10 lần nạp/phút") });

/* ---------- zod schemas ---------- */
const DropIn = z.object({
  kind: z.enum(["local", "digital"]),
  title: z.string().min(3).max(120),
  description: z.string().max(2000).optional().default(""),
  category: z.string().min(2).max(40).optional().default("general"),
  price: z.number().int().min(1000).max(50_000_000),
  lng: z.number().min(102).max(110).optional(), lat: z.number().min(8).max(24).optional(),
  origin: z.enum(["client","civic","self_generated"]).optional(),
});
const AmountIn = z.object({ amount: z.number().int().min(1000).max(50_000_000) });
const TwinMarketIn = z.object({
  twin_id: z.string().uuid(),
  category: z.string().min(2).max(40).optional(),
  title: z.string().min(3).max(120),
  brief: z.string().max(2000).optional(),
  price_plump: z.number().int().min(50).max(100000),
});
const ReviewIn = z.object({ rating: z.number().int().min(1).max(5), body: z.string().max(1000).optional().default("") });
const MsgIn = z.object({ body: z.string().min(1).max(2000) });
const ConsentIn = z.object({ purpose: z.enum(["location","marketing","twin_training","analytics","cross_border"]), granted: z.boolean() });
const DataReqIn = z.object({ kind: z.enum(["access","delete","withdraw","restrict"]), note: z.string().max(500).optional().default("") });
const EkycIn = z.object({ provider: z.enum(["vneid","vnpt_ekyc","fpt_ekyc"]), ref: z.string().min(4).max(120) });
const TwinIn = z.object({ name: z.string().min(2).max(60) });
const TwinOfferIn = z.object({ twin_id: z.string().regex(UUID), amount: z.number().int().min(1000).max(50_000_000) });
const ExamIn = z.object({ category: z.string().min(2).max(40) });
const MandateIn = z.object({ categories: z.array(z.string().min(2).max(40)).min(1).max(10),
  max_price: z.number().int().min(1000).max(50_000_000), hours: z.number().int().min(1).max(24*90).optional().default(24*30) });
const VerifyIn = z.object({ payload: z.string().min(2).max(5000), signature: z.string().min(10), pubkey: z.string().min(10) });
const LoginIn = z.object({ token: z.string().min(6).max(64).optional(),
  username: z.string().min(3).max(20).optional(), password: z.string().min(8).max(72).optional() })
  .refine(v => v.token || (v.username && v.password), { message: "cần token hoặc username+password" });
const UsernameIn = z.object({ username: z.string().regex(/^[a-z0-9_]{3,20}$/) });
const PasswordIn = z.object({ password: z.string().min(8).max(72) });
const EmailIn = z.object({ email: z.string().email().max(120) });
const ReportIn = z.object({ target_kind: z.enum(["drop","plumper","moment","message"]),
  target_id: z.string().regex(UUID), reason: z.string().min(3).max(500) });
const IntentIn = z.object({ amount: z.number().int().min(10000).max(50_000_000) });
const EquipIn = z.object({ slot: z.string().min(2).max(20), item_id: z.string().min(2).max(40) });
const GiftIn = z.object({ to: z.string().regex(UUID) });
const GuestIn = z.object({ body: z.string().min(1).max(200) });
const MomentIn = z.object({ deal_id: z.string().regex(UUID).optional(),
  title: z.string().min(3).max(120), quote: z.string().max(500).optional().default("") });
const SendMsgIn = z.object({ body: z.string().min(1).max(4000).optional(),
  reply_to: z.number().int().positive().optional(),
  attachment_url: z.string().url().max(500).optional(),
  attachment_kind: z.enum(["image","file","location"]).optional() })
  .refine(v => v.body || v.attachment_url, { message: "cần body hoặc attachment" });
const EditMsgIn = z.object({ body: z.string().min(1).max(4000) });
const ReadIn = z.object({ upto: z.number().int().positive() });
const DmStartIn = z.object({ peer: z.string().regex(UUID) });
const TipIn = z.object({ amount: z.number().int().min(50).max(5000) });
const GroupIn = z.object({ title: z.string().min(2).max(60),
  members: z.array(z.string().regex(UUID)).max(49).default([]) });
const ChannelIn = z.object({ title: z.string().min(2).max(60), is_public: z.boolean().default(true) });
const CodeIn = z.object({ code: z.string().min(4).max(12) });
const MembersIn = z.object({ members: z.array(z.string().regex(UUID)).min(1).max(20) });
const StatusIn = z.object({ body: z.string().min(1).max(80), emoji: z.string().max(8).optional() });

/* ================= PUBLIC ================= */
app.get("/health", async (_q, res) => {
  const r = await fn("SELECT count(*) n FROM plumpers");
  res.json({ ok: true, plumpers: +r[0].n, engine_agents: MODEL, realtime: "ws:/realtime" });
});
app.get("/status", async (_q, res) => {
  try {
    await fn("SELECT 1");
    res.json({ ok: true, db: "ok", env: process.env.NODE_ENV === "production" ? "production" : "non-production" });
  } catch {
    res.status(503).json({ ok: false, db: "down" });
  }
});
app.get("/v1/map/drops", async (req, res) => {
  const [a, b, c, d] = (req.query.bbox || "106.5,10.6,106.95,10.95").split(",").map(Number);
  const rows = await fn(
    `SELECT p.*, dr.category FROM drops_public p JOIN drops dr ON dr.id = p.id
     WHERE p.status='open' AND (dr.location IS NULL OR
       dr.location && ST_MakeEnvelope($1,$2,$3,$4,4326)::geography) LIMIT 200`, [a, b, c, d]);
  res.json({ items: rows });
});
app.get("/v1/drops", async (req, res) => {
  const limit = Math.min(Math.max(parseInt(req.query.limit || "50", 10) || 50, 1), 100);
  const rows = await fn(
    `SELECT p.*, dr.category, pl.display_name owner_name
     FROM drops_public p
     JOIN drops dr ON dr.id = p.id
     JOIN plumpers pl ON pl.id = dr.owner
     WHERE ($1::text IS NULL OR p.status=$1)
       AND ($2::text IS NULL OR p.kind=$2)
       AND ($3::text IS NULL OR dr.category=$3)
     ORDER BY p.created_at DESC LIMIT $4`,
    [req.query.status || "open", req.query.kind || null, req.query.category || null, limit]);
  res.json({ items: rows });
});
app.get("/v1/drops/:id", async (req, res) => {
  const d = await fn("SELECT p.*, dr.category FROM drops_public p JOIN drops dr ON dr.id=p.id WHERE p.id=$1", [req.params.id]);
  if (!d.length) return problem(res, 404, "not_found");
  const ref = (await fn("SELECT * FROM price_reference($1)", [d[0].kind]))[0];
  res.json({ ...d[0], price_reference: ref });
});
app.get("/v1/leaderboard", async (req, res) => {
  const p = ["day","week","month"].includes(req.query.period) ? req.query.period : "week";
  res.json({ period: p, items: await fn("SELECT * FROM leaderboard($1)", [p]) });
});
app.get("/v1/plumpers/:id/profile", async (req, res) => {
  const pr = await fn("SELECT * FROM public_profile($1)", [req.params.id]);
  if (!pr.length || pr[0].display_name === null) return problem(res, 404, "not_found");
  const mo = await fn("SELECT id,title,quote,peaches,created_at FROM moments WHERE owner=$1 ORDER BY created_at DESC LIMIT 5", [req.params.id]);
  const p0 = pr[0];
  const ld = (await fn("SELECT * FROM level_detail($1)", [req.params.id]))[0];
  res.json({ display_name: p0.display_name, done: +p0.done, dropped: +p0.dropped,
    avg_rating: p0.avg_rating === null ? null : +p0.avg_rating,
    connections: +p0.connections, plump: +p0.plump,
    level: ld.level, level_score: +ld.score, moments: mo });
});
// Chi tiết cấp của chính mình (điểm, khách khác nhau, còn bao nhiêu tới cấp sau)
app.get("/v1/me/level", auth, async (req, res) => {
  const d = (await fn("SELECT * FROM level_detail($1)", [req.uid]))[0];
  res.json({ level: d.level, score: +d.score,
    valid_deals: +d.valid_deals, distinct_clients: +d.distinct_clients,
    avg_rating: d.avg_rating === null ? null : +d.avg_rating,
    next_tier: d.next_tier === null ? null : +d.next_tier,
    to_next: d.to_next === null ? null : +d.to_next });
});
app.get("/v1/moments", async (req, res) => {
  const rows = await fn(
    `SELECT m.id,m.owner,p.display_name owner_name,m.deal_id,m.title,m.quote,m.peaches,m.created_at
     FROM moments m JOIN plumpers p ON p.id=m.owner
     ORDER BY m.created_at DESC LIMIT 50`);
  res.json({ items: rows });
});
app.post("/v1/moments", auth, val(MomentIn), async (req, res) => {
  try { const r = await fn("SELECT create_moment($1,$2,$3,$4) id",
      [req.uid, req.body.deal_id || null, req.body.title, req.body.quote || ""]);
    res.status(201).json({ moment_id: r[0].id });
  } catch (e) { sqlErr(res, e); }
});
app.get("/v1/moments/:id", async (req, res) => {
  const r = await fn(
    `SELECT m.id,m.owner,p.display_name owner_name,m.deal_id,m.title,m.quote,m.peaches,m.created_at
     FROM moments m JOIN plumpers p ON p.id=m.owner WHERE m.id=$1`, [req.params.id]);
  if (!r.length) return problem(res, 404, "not_found");
  res.json(r[0]);
});
app.post("/v1/moments/:id/peach", auth, async (req, res) => {
  try { res.json({ peaches: (await fn("SELECT peach_moment_once($1,$2) n", [req.uid, req.params.id]))[0].n }); }
  catch (e) { sqlErr(res, e); }
});

/* ================= AUTH · regnick token 13 ký tự ================= */
const registerLimiter = rateLimit({ windowMs: 60_000, max: DEV ? 1000 : 30, store: new PgStore("reg:"),   // prod: 30 regnick/phút/IP
  handler: (_q, res) => problem(res, 429, "rate_limited") });

app.post("/v1/auth/register", registerLimiter, async (_q, res) => {
  const token = genToken13();
  // One DB transaction creates identity + wallet + the one-time 1,313 Nara grant.
  const r = await fn("SELECT register_pilot_account($1) id", [sha256(token)]);
  res.status(201).json({ plumper_id: r[0].id, token,
    note: "Token 13 ký tự — HIỆN MỘT LẦN DUY NHẤT, hệ thống chỉ lưu hash. Dùng token này để đăng nhập." });
});

app.post("/v1/auth/login", val(LoginIn), async (req, res) => {
  const ip = req.ip || "?";
  const account = req.body.username ? req.body.username.toLowerCase() : null;
  const locked = await fn("SELECT check_lockout($1,$2) s", [ip, account]);
  if (locked[0].s > 0)
    return problem(res, 429, "locked_out", "Thử sai quá nhiều — chờ " + locked[0].s + "s");
  let row;
  if (req.body.token) {
    row = (await fn("SELECT id,role,onboarded,password_hash FROM plumpers WHERE token_hash=$1",
                    [sha256(req.body.token)]))[0];
    if (!row) { await recordAttempt(ip, null, false);
      return problem(res, 401, "bad_token", "Token không đúng"); }
  } else {
    row = (await fn("SELECT id,role,onboarded,password_hash FROM plumpers WHERE handle=$1", [account]))[0];
    if (!row || !row.password_hash || !verifyPassword(req.body.password, row.password_hash)) {
      await recordAttempt(ip, account, false);
      return problem(res, 401, "bad_credentials", "Sai username hoặc password");
    }
  }
  await recordAttempt(ip, account, true);
  const mfa = await fn("SELECT 1 FROM totp_secrets WHERE plumper_id=$1 AND confirmed", [row.id]);
  if (mfa.length)
    return res.json({ mfa_required: true, mfa_token: signMfa(row.id),
                      note: "Gửi mã 6 số TOTP vào /v1/auth/mfa" });
  res.json({ jwt: await createSession(row.id, row.role, req), plumper_id: row.id,
             role: row.role, onboarded: row.onboarded, has_password: !!row.password_hash });
});

app.post("/v1/auth/mfa", async (req, res) => {
  let p; try { p = jwt.verify(String(req.body?.mfa_token || ""), JWT_SECRET); } catch { p = null; }
  if (!p?.mfa) return problem(res, 401, "bad_mfa_token");
  const sec = await fn("SELECT secret_b32 FROM totp_secrets WHERE plumper_id=$1 AND confirmed", [p.sub]);
  if (!sec.length || !totpVerify(sec[0].secret_b32, req.body?.code))
    return problem(res, 401, "bad_totp", "Mã 2FA sai");
  const u = (await fn("SELECT id,role,onboarded,password_hash FROM plumpers WHERE id=$1", [p.sub]))[0];
  res.json({ jwt: await createSession(u.id, u.role, req), plumper_id: u.id,
             role: u.role, onboarded: u.onboarded, has_password: !!u.password_hash });
});

app.post("/v1/auth/username", auth, val(UsernameIn), async (req, res) => {
  try { await fn("SELECT set_username($1,$2)", [req.uid, req.body.username]);
        res.json({ username: req.body.username, onboarded: true }); }
  catch (e) { sqlErr(res, e); }
});
app.post("/v1/auth/password", auth, val(PasswordIn), async (req, res) => {
  await fn("UPDATE plumpers SET password_hash=$2 WHERE id=$1", [req.uid, hashPassword(req.body.password)]);
  res.json({ ok: true, note: "Giờ login được bằng username+password HOẶC token 13 ký tự" });
});
/* ---- Sessions: xem / thu hồi / refresh / logout ---- */
app.get("/v1/me/sessions", auth, async (req, res) => {
  res.json({ items: await fn(
    `SELECT jti,user_agent,ip,created_at,expires_at,revoked_at,(jti=$2) AS current
     FROM sessions WHERE plumper_id=$1 ORDER BY created_at DESC LIMIT 20`, [req.uid, req.jti || null]) });
});
app.post("/v1/me/sessions/:jti/revoke", auth, async (req, res) => {
  const r = await fn("UPDATE sessions SET revoked_at=now() WHERE jti=$1 AND plumper_id=$2 AND revoked_at IS NULL RETURNING jti",
                     [req.params.jti, req.uid]);
  if (!r.length) return problem(res, 404, "not_found");
  res.json({ revoked: true });
});
app.post("/v1/auth/logout", auth, async (req, res) => {
  if (!req.jti) return problem(res, 409, "no_session", "Token này không gắn phiên");
  await fn("UPDATE sessions SET revoked_at=now() WHERE jti=$1", [req.jti]);
  res.json({ ok: true });
});
app.post("/v1/auth/refresh", auth, async (req, res) => {          // rotation: phiên cũ chết, phiên mới sinh
  if (!req.jti) return problem(res, 409, "no_session");
  const u = (await fn("SELECT id,role FROM plumpers WHERE id=$1", [req.uid]))[0];
  const njwt = await createSession(u.id, u.role, req);
  await fn("UPDATE sessions SET revoked_at=now() WHERE jti=$1", [req.jti]);
  res.json({ jwt: njwt });
});

/* ---- Email: verify + quên mật khẩu qua email đã verify ---- */
app.post("/v1/me/email/verify-request", auth, async (req, res) => {
  const r = await fn("SELECT email FROM plumpers WHERE id=$1", [req.uid]);
  if (!r[0]?.email) return problem(res, 409, "no_email", "Thêm email trong settings trước");
  await sendCode(req.uid, r[0].email, "verify");
  res.json({ sent: true });
});
app.post("/v1/me/email/verify", auth, async (req, res) => {
  const email = await consumeCode(req.uid, "verify", String(req.body?.code || ""));
  if (!email) return problem(res, 401, "bad_code", "Mã sai hoặc hết hạn");
  await fn("UPDATE plumpers SET email_verified_at=now() WHERE id=$1 AND email=$2", [req.uid, email]);
  res.json({ verified: true });
});
app.post("/v1/auth/forgot", async (req, res) => {
  const em = String(req.body?.email || "").toLowerCase();
  const r = await fn("SELECT id,email FROM plumpers WHERE email=$1 AND email_verified_at IS NOT NULL", [em]);
  if (r.length) await sendCode(r[0].id, r[0].email, "reset");
  res.json({ ok: true, note: "Nếu email tồn tại & đã verify, mã đặt lại đã được gửi" });   // chống dò tài khoản
});
app.post("/v1/auth/reset", async (req, res) => {
  const em = String(req.body?.email || "").toLowerCase();
  const pw = String(req.body?.password || "");
  if (pw.length < 8 || pw.length > 72) return problem(res, 400, "validation_error", "password 8-72 ký tự");
  const u = (await fn("SELECT id FROM plumpers WHERE email=$1", [em]))[0];
  if (!u) return problem(res, 401, "bad_code");
  const ok = await consumeCode(u.id, "reset", String(req.body?.code || ""));
  if (!ok) return problem(res, 401, "bad_code", "Mã sai hoặc hết hạn");
  await fn("UPDATE plumpers SET password_hash=$2 WHERE id=$1", [u.id, hashPassword(pw)]);
  await fn("UPDATE sessions SET revoked_at=now() WHERE plumper_id=$1 AND revoked_at IS NULL", [u.id]);
  res.json({ reset: true, note: "Mọi phiên cũ đã bị thu hồi" });
});

/* ---- Recovery: mất token → xin owner cấp lại ---- */
app.post("/v1/auth/recovery", async (req, res) => {
  const uname = String(req.body?.username || "").toLowerCase();
  const u = (await fn("SELECT id FROM plumpers WHERE handle=$1", [uname]))[0];
  if (!u) return res.status(201).json({ ok: true });               // không lộ tồn tại
  const r = await fn("INSERT INTO recovery_requests(plumper_id,kind,note) VALUES ($1,'token_reissue',$2) RETURNING id",
                     [u.id, String(req.body?.note || "").slice(0, 300)]);
  res.status(201).json({ ok: true, request_id: r[0].id });
});

/* ---- 2FA TOTP (chủ yếu cho owner) ---- */
app.post("/v1/auth/2fa/setup", auth, async (req, res) => {
  const secret = b32encode(crypto.randomBytes(20));
  await fn(`INSERT INTO totp_secrets(plumper_id,secret_b32,confirmed) VALUES ($1,$2,false)
            ON CONFLICT (plumper_id) DO UPDATE SET secret_b32=$2, confirmed=false`, [req.uid, secret]);
  res.json({ secret, otpauth: "otpauth://totp/SuperPlump?secret=" + secret + "&issuer=SuperPlump" });
});
app.post("/v1/auth/2fa/confirm", auth, async (req, res) => {
  const r = await fn("SELECT secret_b32 FROM totp_secrets WHERE plumper_id=$1", [req.uid]);
  if (!r.length || !totpVerify(r[0].secret_b32, req.body?.code))
    return problem(res, 401, "bad_totp");
  await fn("UPDATE totp_secrets SET confirmed=true WHERE plumper_id=$1", [req.uid]);
  res.json({ enabled: true });
});
app.post("/v1/auth/2fa/disable", auth, async (req, res) => {
  const r = await fn("SELECT secret_b32 FROM totp_secrets WHERE plumper_id=$1 AND confirmed", [req.uid]);
  if (!r.length || !totpVerify(r[0].secret_b32, req.body?.code))
    return problem(res, 401, "bad_totp");
  await fn("DELETE FROM totp_secrets WHERE plumper_id=$1", [req.uid]);
  res.json({ disabled: true });
});

app.get("/v1/me/pilot", auth, async (req, res) => {
  const r = (await fn(`SELECT created_at, role, suspended_at,
      GREATEST(0, CEIL(EXTRACT(EPOCH FROM (created_at + interval '5 minutes' - now()))))::int AS wait_seconds,
      pilot_access_eligible(id) AS eligible
    FROM plumpers WHERE id=$1`, [req.uid]))[0];
  if (!r) return problem(res, 404, "not_found");
  res.json({ eligible: !!r.eligible, wait_seconds: +r.wait_seconds || 0, created_at: r.created_at, role: r.role, suspended: !!r.suspended_at });
});

app.get("/v1/me", auth, async (req, res) => {
  const r = await fn("SELECT id,handle,display_name,role,email,onboarded,kyc_status FROM plumpers WHERE id=$1", [req.uid]);
  if (!r.length) return problem(res, 404, "not_found");
  res.json(r[0]);
});

app.get("/v1/me/deals", auth, async (req, res) => {
  const rows = await fn(
    `SELECT d.id,d.drop_id,d.dropper,d.executor,d.agreed,d.hold_amount,d.state,
            d.locked_at,d.started_at,d.submitted_at,d.settled_at,
            dr.title AS drop_title, dr.kind AS drop_kind, dr.status AS drop_status,
            CASE WHEN d.dropper=$1 THEN 'dropper' ELSE 'executor' END AS role
     FROM deals d
     JOIN drops dr ON dr.id=d.drop_id
     WHERE $1 IN (d.dropper,d.executor)
     ORDER BY COALESCE(d.settled_at,d.submitted_at,d.started_at,d.locked_at) DESC
     LIMIT 100`, [req.uid]);
  res.json({ items: rows });
});

app.get("/v1/me/profile", auth, async (req, res) => {
  const pr = (await fn("SELECT * FROM public_profile($1)", [req.uid]))[0];
  if (!pr || pr.display_name === null) return problem(res, 404, "not_found");
  const ld = (await fn("SELECT * FROM level_detail($1)", [req.uid]))[0];
  res.json({ id: req.uid, display_name: pr.display_name, done: +pr.done, dropped: +pr.dropped,
    avg_rating: pr.avg_rating === null ? null : +pr.avg_rating, connections: +pr.connections,
    plump: +pr.plump, level: ld.level, level_score: +ld.score });
});
app.patch("/v1/me/settings", auth, val(EmailIn), async (req, res) => {
  try { await fn("UPDATE plumpers SET email=$2, email_verified_at=NULL WHERE id=$1",
                 [req.uid, req.body.email.toLowerCase()]);
        res.json({ email: req.body.email.toLowerCase(), verified: false }); }
  catch (e) {
    if ((e.message||"").includes("duplicate")) return problem(res, 409, "email_taken");
    sqlErr(res, e);
  }
});

/* ================= A · PDPL & KYC ================= */
app.post("/v1/kyc/ekyc", auth, val(EkycIn), async (_req, res) => {
  return problem(res, 403, "kyc_disabled", "Pilot access uses the 5-minute account-age gate; KYC is disabled.");
});
app.get("/v1/kyc/status", auth, async (req, res) => {
  const r = await fn("SELECT kyc_status FROM plumpers WHERE id=$1", [req.uid]);
  res.json({ status: r[0]?.kyc_status || "none" });
});
app.post("/v1/me/consents", auth, val(ConsentIn), async (req, res) => {
  await fn("SELECT set_consent($1,$2,$3)", [req.uid, req.body.purpose, req.body.granted]);
  res.status(201).json({ purpose: req.body.purpose, granted: req.body.granted });
});
app.get("/v1/me/consents", auth, async (req, res) => {
  res.json({ items: await fn("SELECT purpose,granted,updated_at FROM consents WHERE owner=$1", [req.uid]) });
});
app.post("/v1/me/data-requests", auth, val(DataReqIn), async (req, res) => {
  const r = await fn("SELECT submit_data_request($1,$2,$3) id", [req.uid, req.body.kind, req.body.note]);
  res.status(201).json({ request_id: r[0].id, status: "pending", sla: "xử lý theo thời hạn luật định" });
});
app.get("/v1/me/data-requests", auth, async (req, res) => {
  res.json({ items: await fn("SELECT id,kind,status,created_at,processed_at FROM data_requests WHERE owner=$1 ORDER BY created_at DESC", [req.uid]) });
});

/* ================= CHỢ (giữ V1, thêm category) ================= */
app.post("/v1/drops", auth, val(DropIn), async (req, res) => {
  const { kind, title, description, price, lng, lat, category, origin } = req.body;
  try {
    const r = await fn("SELECT create_drop($1,$2,$3,$4,$5,$6,$7) id",
      [req.uid, kind, title, description, price, lng ?? null, lat ?? null]);
    await fn("UPDATE drops SET category=$2, origin=COALESCE($3,'client') WHERE id=$1",
      [r[0].id, category, origin ?? null]);
    res.status(201).json({ drop_id: r[0].id });
  } catch (e) { sqlErr(res, e); }
});
app.post("/v1/drops/:id/offers", auth, val(AmountIn), async (req, res) => {
  try { const r = await fn("SELECT create_offer($1,$2,$3) id", [req.uid, req.params.id, req.body.amount]);
        res.status(201).json({ offer_id: r[0].id }); } catch (e) { sqlErr(res, e); }
});
app.get("/v1/drops/:id/offers", auth, async (req, res) => {
  const own = await fn("SELECT owner FROM drops WHERE id=$1", [req.params.id]);
  if (!own.length) return problem(res, 404, "not_found");
  const rows = await fn(
    `SELECT o.id,o.drop_id,o.from_id,o.amount,o.status,o.created_at,o.twin_id,p.display_name from_name
     FROM offers o JOIN plumpers p ON p.id=o.from_id
     WHERE o.drop_id=$1 AND ($2::uuid = $3::uuid OR o.from_id=$2)
     ORDER BY o.created_at DESC`, [req.params.id, req.uid, own[0].owner]);
  res.json({ items: rows });
});
app.post("/v1/drops/:id/twin-offers", auth, val(TwinOfferIn), async (req, res) => {
  try { const r = await fn("SELECT create_offer_twin($1,$2,$3,$4) id",
        [req.uid, req.body.twin_id, req.params.id, req.body.amount]);
        res.status(201).json({ offer_id: r[0].id, by: "twin" }); } catch (e) { sqlErr(res, e); }
});
app.post("/v1/offers/:id/accept", auth, async (req, res) => {
  try { const r = await fn("SELECT accept_offer($1,$2) id", [req.params.id, req.uid]);
        res.status(201).json({ deal_id: r[0].id }); } catch (e) { sqlErr(res, e); }
});
app.get("/v1/offers/:id", auth, async (req, res) => {
  const r = await fn(
    `SELECT o.*, d.owner drop_owner, d.title drop_title
     FROM offers o JOIN drops d ON d.id=o.drop_id
     WHERE o.id=$1 AND ($2::uuid IN (o.from_id,d.owner))`, [req.params.id, req.uid]);
  if (!r.length) return problem(res, 404, "not_found");
  res.json(r[0]);
});
const transition = (f, okState) => [auth, async (req, res) => {
  try { await fn(`SELECT ${f}($1,$2${f === "deal_submit" ? ",$3" : ""})`,
      f === "deal_submit" ? [req.params.id, req.uid, req.body?.proof || null] : [req.params.id, req.uid]);
    res.json({ ok: true, state: okState }); } catch (e) { sqlErr(res, e); }
}];
app.post("/v1/deals/:id/start", ...transition("deal_start","IN_PROGRESS"));
app.post("/v1/deals/:id/submit", ...transition("deal_submit","SUBMITTED"));
app.post("/v1/deals/:id/confirm", ...transition("deal_confirm","SETTLED"));
app.post("/v1/deals/:id/disputes", auth, async (req, res) => {
  try { const r = await fn("SELECT open_dispute($1,$2,$3) id", [req.params.id, req.uid, req.body?.reason || "khác"]);
        res.status(201).json({ dispute_id: r[0].id }); } catch (e) { sqlErr(res, e); }
});
app.get("/v1/deals/:id", auth, async (req, res) => {
  const d = await fn("SELECT * FROM deals WHERE id=$1 AND $2 IN (dropper,executor)", [req.params.id, req.uid]);
  if (!d.length) return problem(res, 404, "not_found");
  const ev = await fn("SELECT event_type,payload,created_at FROM events WHERE aggregate_id=$1 ORDER BY id", [req.params.id]);
  res.json({ ...d[0], timeline: ev });
});
app.get("/v1/deals/:id/location", auth, async (req, res) => {
  try { res.json((await fn("SELECT * FROM exact_location($1,$2)", [req.params.id, req.uid]))[0]); }
  catch (e) { sqlErr(res, e); }
});
app.post("/v1/deals/:id/reviews", auth, val(ReviewIn), async (req, res) => {
  try { await fn("SELECT submit_review($1,$2,$3,$4)", [req.params.id, req.uid, req.body.rating, req.body.body]);
        res.status(201).json({ blind: true }); } catch (e) { sqlErr(res, e); }
});
app.get("/v1/deals/:id/reviews", async (req, res) => {
  res.json({ items: await fn("SELECT author,target,rating,body FROM deal_reviews_visible WHERE deal_id=$1", [req.params.id]) });
});

/* ================= B · CHAT / NOTI / VÍ ================= */
app.post("/v1/deals/:id/messages", auth, val(MsgIn), async (req, res) => {
  try { const r = await fn("SELECT send_message($1,$2,NULL,$3) id", [req.uid, req.params.id, req.body.body]);
        res.status(201).json({ message_id: +r[0].id }); } catch (e) { sqlErr(res, e); }
});
app.get("/v1/deals/:id/messages", auth, async (req, res) => {
  const rows = await fn(
    `SELECT m.id,m.sender,m.body,m.created_at FROM messages m JOIN deals d ON d.id=m.deal_id
     WHERE m.deal_id=$1 AND $2 IN (d.dropper,d.executor) ORDER BY m.id LIMIT 100`,
    [req.params.id, req.uid]);
  res.json({ items: rows });
});
app.post("/v1/dm/:peer/messages", auth, val(MsgIn), async (req, res) => {
  try { const r = await fn("SELECT send_message($1,NULL,$2,$3) id", [req.uid, req.params.peer, req.body.body]);
        res.status(201).json({ message_id: +r[0].id }); } catch (e) { sqlErr(res, e); }
});
app.get("/v1/dm/:peer/messages", auth, async (req, res) => {
  const rows = await fn(
    `SELECT id,sender,body,created_at FROM messages
     WHERE dm_a=LEAST($1::uuid,$2::uuid) AND dm_b=GREATEST($1::uuid,$2::uuid) ORDER BY id LIMIT 100`,
    [req.uid, req.params.peer]);
  res.json({ items: rows });
});
app.get("/v1/notifications", auth, async (req, res) => {
  res.json({ items: await fn("SELECT id,kind,body,ref,read_at,created_at FROM notifications WHERE owner=$1 ORDER BY id DESC LIMIT 50", [req.uid]) });
});
app.post("/v1/notifications/:id/read", auth, async (req, res) => {
  await fn("UPDATE notifications SET read_at=now() WHERE id=$1 AND owner=$2", [req.params.id, req.uid]);
  res.json({ ok: true });
});
app.get("/v1/wallet", auth, async (req, res) => {
  const r = await fn("SELECT balance FROM wallets WHERE owner=$1 AND kind='user'", [req.uid]);
  const p = await fn("SELECT plump_balance($1) b", [req.uid]);
  const nara = +(r[0]?.balance ?? 0);
  res.json({ available: nara, nara_available: nara, plump: +p[0].b });
});
app.get("/v1/wallet/entries", auth, async (req, res) => {
  res.json({ items: await fn(
    `SELECT l.deal_id,l.kind,l.amount,l.created_at FROM ledger_entries l
     JOIN wallets w ON w.id=l.wallet_id WHERE w.owner=$1 ORDER BY l.id DESC LIMIT 50`, [req.uid]) });
});
app.post("/v1/wallet/topups", auth, topupLimiter, val(AmountIn), async (_req, res) => {
  return problem(res, 403, "topup_disabled",
    "Pilot Beat 1: direct self topup/mint is disabled.");
});

/* ================= B · TWINS ================= */
app.post("/v1/twins", auth, val(TwinIn), async (req, res) => {
  try {
    const r = await fn("SELECT create_twin($1,$2,$3) id", [req.uid, req.body.name, MODEL]);
    const e = await fn("SELECT energy FROM twins WHERE id=$1", [r[0].id]);
    res.status(201).json({ twin_id: r[0].id, energy: e[0].energy, engine: MODEL });
  } catch (e) { sqlErr(res, e); }
});
// Chi tiết slot twin của chủ (đang có / trần / phí mở tiếp)
app.get("/v1/me/twin-slots", auth, async (req, res) => {
  const d = (await fn("SELECT * FROM twin_slot_detail($1)", [req.uid]))[0];
  res.json({ active: +d.active, limit: +d.limit_slots,
    next_open_fee: +d.next_open_fee, owner_level: +d.owner_level,
    can_open_more: +d.active < +d.limit_slots });
});
// Đóng phí duy trì twin (gia hạn 1 chu kỳ)
app.post("/v1/twins/:id/maintenance/pay", auth, async (req, res) => {
  try {
    const r = await fn("SELECT pay_maintenance($1,$2) due", [req.params.id, req.uid]);
    res.json({ maintenance_due_at: r[0].due });
  } catch (e) { sqlErr(res, e); }
});

// ===== BEAT 7 · GIÁ GỢI Ý TINH TẾ (chiếu đèn, không ép) =====
// Gọi trước khi đăng việc để tham khảo "khu này giờ này thường bao nhiêu".
app.get("/v1/price-hint", auth, async (req, res) => {
  const category = req.query.category || "general";
  const kind = req.query.kind || null;
  const lng = req.query.lng != null ? Number(req.query.lng) : null;
  const lat = req.query.lat != null ? Number(req.query.lat) : null;
  try {
    const r = (await fn("SELECT * FROM price_hint($1,$2,$3,$4,NULL)",
      [category, kind, lng, lat]))[0];
    const enough = +r.sample >= 5;
    res.json({
      sample: +r.sample,
      scope: r.scope,
      hour_of_day: r.hour_of_day,
      enough_data: enough,
      suggestion: enough ? { low: +r.p25, typical: +r.median, high: +r.p75 } : null,
      note: enough
        ? `Khu này ${r.scope} thường ${(+r.median).toLocaleString('vi')}đ (khoảng ${(+r.p25).toLocaleString('vi')}–${(+r.p75).toLocaleString('vi')}). Chỉ là tham khảo — bạn tự quyết giá.`
        : "Chưa đủ dữ liệu cho gợi ý — bạn cứ tự đặt giá bạn thấy hợp lý.",
    });
  } catch (e) { sqlErr(res, e); }
});

// ===== BEAT 6 · CHỢ TWIN-TO-TWIN =====
// Đăng việc số cho twin khác làm (chỉ chủ Lv5)
app.post("/v1/twin-market", auth, val(TwinMarketIn), async (req, res) => {
  const { twin_id, category, title, brief, price_plump } = req.body;
  try {
    const r = await fn("SELECT post_twin_market($1,$2,$3,$4,$5,$6) id",
      [req.uid, twin_id, category ?? "general", title, brief ?? "", price_plump]);
    res.status(201).json({ market_drop_id: r[0].id });
  } catch (e) { sqlErr(res, e); }
});
// Xem chợ (việc twin đang mở)
app.get("/v1/twin-market", auth, async (req, res) => {
  const items = await fn(
    `SELECT id, poster_twin, category, title, brief, price_plump, created_at
     FROM twin_market_drops WHERE status='open' ORDER BY created_at DESC LIMIT 50`, []);
  const can = (await fn("SELECT twin_market_can_post($1) c", [req.uid]))[0].c;
  res.json({ items, can_post: can });
});
// Twin nhận việc từ chợ
app.post("/v1/twin-market/:id/take", auth, async (req, res) => {
  const { twin_id } = req.body;
  try {
    const r = await fn("SELECT take_twin_market($1,$2,$3) id", [req.uid, twin_id, req.params.id]);
    const st = (await fn("SELECT state FROM twin_market_deals WHERE id=$1", [r[0].id]))[0].state;
    res.status(201).json({ market_deal_id: r[0].id, state: st });
  } catch (e) { sqlErr(res, e); }
});
// Chủ đăng duyệt lần đầu (ok=true/false)
app.post("/v1/twin-market/deals/:id/approve", auth, async (req, res) => {
  try {
    const r = await fn("SELECT approve_twin_market($1,$2,$3) result",
      [req.params.id, req.uid, req.body?.ok !== false]);
    res.json({ result: r[0].result });
  } catch (e) { sqlErr(res, e); }
});
// Kết toán (chuyển Plump, hai chủ cùng có lợi)
app.post("/v1/twin-market/deals/:id/settle", auth, async (req, res) => {
  try {
    await fn("SELECT settle_twin_market($1,$2)", [req.params.id, req.uid]);
    res.json({ ok: true });
  } catch (e) { sqlErr(res, e); }
});
app.get("/v1/twins/:id", auth, async (req, res) => {
  const t = await fn("SELECT id,name,status,autonomy,energy,engine_model FROM twins WHERE id=$1 AND owner=$2", [req.params.id, req.uid]);
  if (!t.length) return problem(res, 404, "not_found");
  const q = await fn("SELECT category,level FROM qualifications WHERE twin_id=$1 AND revoked_at IS NULL", [req.params.id]);
  const m = await fn("SELECT id,categories,max_price,expires_at FROM twin_mandates WHERE twin_id=$1 AND revoked_at IS NULL AND expires_at>now()", [req.params.id]);
  const ld = (await fn("SELECT * FROM twin_level_detail($1)", [req.params.id]))[0];
  const en = (await fn("SELECT apply_energy_regen($1) e, twin_energy_cap($1) cap, twin_job_cost($1) cost", [req.params.id]))[0];
  res.json({ ...t[0], energy: +en.e, energy_cap: +en.cap, job_cost: +en.cost,
    qualifications: q, mandates: m,
    twin_level: ld.twin_level, raw_level: ld.raw_level, owner_level: ld.owner_level,
    capped_by_owner: ld.capped, level_score: +ld.score, rated_jobs: +ld.rated_jobs });
});
// Nạp energy cho twin: buy (trừ Nara) · gather (nhặt map) · event
app.post("/v1/twins/:id/energy/refill", auth, async (req, res) => {
  const src = req.body?.source;
  if (!["buy","gather","event"].includes(src))
    return problem(res, 400, "validation_error", "source phải là buy|gather|event");
  const own = await fn("SELECT 1 FROM twins WHERE id=$1 AND owner=$2", [req.params.id, req.uid]);
  if (!own.length) return problem(res, 403, "not_twin_owner");
  try {
    await fn("SELECT apply_energy_regen($1)", [req.params.id]);
    const r = await fn("SELECT refill_energy($1,$2,$3) e", [req.params.id, src, req.uid]);
    res.json({ energy: +r[0].e, source: src });
  } catch (e) { sqlErr(res, e); }
});
app.post("/v1/twins/:id/exams", auth, val(ExamIn), async (req, res) => {
  const own = await fn("SELECT 1 FROM twins WHERE id=$1 AND owner=$2", [req.params.id, req.uid]);
  if (!own.length) return problem(res, 403, "not_twin_owner");
  const r = await fn("INSERT INTO exam_runs(twin_id,category) VALUES ($1,$2) RETURNING id", [req.params.id, req.body.category]);
  res.status(201).json({ exam_id: r[0].id, status: "queued", judge: MODEL });
});
app.get("/v1/exam-runs/:id", auth, async (req, res) => {
  const r = await fn(`SELECT e.* FROM exam_runs e JOIN twins t ON t.id=e.twin_id WHERE e.id=$1 AND t.owner=$2`, [req.params.id, req.uid]);
  if (!r.length) return problem(res, 404, "not_found");
  res.json(r[0]);
});
app.get("/v1/twin-jobs", auth, async (req, res) => {
  res.json({ items: await fn(
    `SELECT j.id,j.deal_id,j.status,j.brief,j.draft,j.created_at FROM twin_jobs j
     JOIN twins t ON t.id=j.twin_id WHERE t.owner=$1 AND ($2::text IS NULL OR j.status=$2)
     ORDER BY j.created_at DESC LIMIT 50`, [req.uid, req.query.status || null]) });
});
app.post("/v1/twin-jobs/:id/approve", auth, async (req, res) => {
  try { await fn("SELECT approve_twin_job($1,$2)", [req.params.id, req.uid]); res.json({ submitted: true }); }
  catch (e) { sqlErr(res, e); }
});
app.post("/v1/twin-jobs/:id/reject", auth, async (req, res) => {
  const r = await fn(`UPDATE twin_jobs j SET status='rejected' FROM twins t
    WHERE j.id=$1 AND t.id=j.twin_id AND t.owner=$2 AND j.status='drafted' RETURNING j.id`, [req.params.id, req.uid]);
  if (!r.length) return problem(res, 409, "job_not_drafted");
  res.json({ rejected: true, note: "correction sẽ nuôi lại SoulFile" });
});

/* ================= C · MANDATE + ATTESTATION + AGENT-READY ================= */
app.post("/v1/twins/:id/mandates", auth, val(MandateIn), async (req, res) => {
  const own = await fn("SELECT 1 FROM twins WHERE id=$1 AND owner=$2", [req.params.id, req.uid]);
  if (!own.length) return problem(res, 403, "not_twin_owner");
  const { publicKey, privateKey } = crypto.generateKeyPairSync("ed25519");
  const pub = publicKey.export({ type: "spki", format: "der" }).toString("base64");
  const prv = privateKey.export({ type: "pkcs8", format: "der" }).toString("base64");
  const r = await fn(
    `INSERT INTO twin_mandates(twin_id,categories,max_price,expires_at,pubkey,privkey,privkey_enc)
     VALUES ($1,$2,$3,now()+make_interval(hours=>$4),$5,$6,$7) RETURNING id,expires_at`,
    [req.params.id, req.body.categories, req.body.max_price, req.body.hours, pub,
     kmsKey ? null : prv, kmsKey ? encPriv(prv) : null]);
  res.status(201).json({ mandate_id: r[0].id, pubkey: pub, expires_at: r[0].expires_at,
    scope: req.body.categories, max_price: req.body.max_price });
});
app.post("/v1/mandates/:id/revoke", auth, async (req, res) => {
  const r = await fn(`UPDATE twin_mandates m SET revoked_at=now() FROM twins t
    WHERE m.id=$1 AND t.id=m.twin_id AND t.owner=$2 AND m.revoked_at IS NULL RETURNING m.id`,
    [req.params.id, req.uid]);
  if (!r.length) return problem(res, 404, "not_found");
  res.json({ revoked: true });
});
app.get("/v1/twin-jobs/:id/attestation", auth, async (req, res) => {
  const r = await fn(
    `SELECT j.id,j.deal_id,j.twin_id,j.draft,m.pubkey,m.privkey,m.privkey_enc,m.id mandate_id
     FROM twin_jobs j JOIN twins t ON t.id=j.twin_id
     JOIN LATERAL (SELECT * FROM active_mandate(j.twin_id)) m ON true
     WHERE j.id=$1 AND t.owner=$2 AND j.status IN ('drafted','approved')`, [req.params.id, req.uid]);
  if (!r.length) return problem(res, 404, "not_found", "Cần job đã drafted + mandate còn hiệu lực");
  const row = r[0];
  const payload = JSON.stringify({
    job_id: row.id, deal_id: row.deal_id, twin_id: row.twin_id, mandate_id: row.mandate_id,
    draft_sha256: crypto.createHash("sha256").update(row.draft || "").digest("hex"),
    engine: MODEL, ts: new Date().toISOString(),
  });
  const prvB64 = row.privkey_enc ? decPriv(row.privkey_enc) : row.privkey;
  const key = crypto.createPrivateKey({ key: Buffer.from(prvB64, "base64"), type: "pkcs8", format: "der" });
  const signature = crypto.sign(null, Buffer.from(payload), key).toString("base64");
  res.json({ payload, signature, pubkey: row.pubkey, alg: "Ed25519" });
});
app.post("/v1/agent/verify", val(VerifyIn), (req, res) => {
  try {
    const key = crypto.createPublicKey({ key: Buffer.from(req.body.pubkey, "base64"), type: "spki", format: "der" });
    const ok = crypto.verify(null, Buffer.from(req.body.payload),
                             key, Buffer.from(req.body.signature, "base64"));
    res.json({ valid: ok });
  } catch { res.json({ valid: false }); }
});
app.get("/.well-known/superplump.json", (_q, res) => res.json({
  name: "SuperPlump", version: "1.1", kind: "time-marketplace",
  description: "Chợ thời gian tự do — người thật và bản thể số cùng làm việc",
  agents: { engine: MODEL, credentialing: "qualify-exams", authorization: "signed-mandates(Ed25519)" },
  feeds: { open_drops: "/v1/agent/drops" },
  verify: "/v1/agent/verify",
  policies: { location_privacy: "public coords snapped ~300m", pdpl: "Luật 91/2025/QH15 compliant-by-design" },
}));
app.get("/v1/agent/drops", async (req, res) => {
  const rows = await fn(
    `SELECT p.id, p.title, dr.category, p.kind, p.price AS price_vnd,
            p.fuzzy_lat, p.fuzzy_lng, p.created_at
     FROM drops_public p JOIN drops dr ON dr.id=p.id
     WHERE p.status='open' ORDER BY p.created_at DESC LIMIT 100`);
  res.json({ schema: "superplump.drop.v1", currency: "VND",
    offer_endpoint: "/v1/drops/{id}/offers", items: rows });
});

/* ============ ĐỐI TÁC: nạp tiền qua trung gian licensed (seam) ============ */
app.post("/v1/wallet/topups/intent", auth, val(IntentIn), async (_req, res) => {
  return problem(res, 403, "payments_disabled",
    "Pilot Beat 1: real-money payment flow is not enabled.");
});
app.post("/v1/payments/webhook", async (req, res) => {
  return problem(res, 403, "payments_disabled",
    "Pilot Beat 1: payment webhooks cannot credit Nara.");
});
app.post("/v1/kyc/webhook", async (req, res) => {
  return problem(res, 403, "kyc_disabled", "Pilot KYC callbacks are disabled.");
});

/* ============ HỆ NHẮN TIN ĐẦY ĐỦ (telegram-style) ============ */
app.get("/v1/inbox", auth, async (req, res) => {
  const [items, unread] = await Promise.all([
    fn("SELECT * FROM inbox($1)", [req.uid]),
    fn("SELECT total_unread($1) n", [req.uid]),
  ]);
  const conv = items.map(c => ({ ...c, unread: +c.unread, member_count: +c.member_count }));
  res.json({ conversations: conv, total_unread: +unread[0].n });
});
app.get("/v1/inbox/unread-count", auth, async (req, res) => {
  res.json({ total_unread: +(await fn("SELECT total_unread($1) n", [req.uid]))[0].n });
});

// Mở (hoặc lấy) hội thoại DM với một người — cần đã kết nối (quen qua việc)
app.post("/v1/conversations/dm", auth, val(DmStartIn), async (req, res) => {
  try { const r = await fn("SELECT get_or_create_dm($1,$2) id", [req.uid, req.body.peer]);
        res.status(201).json({ conversation_id: r[0].id }); } catch (e) { sqlErr(res, e); }
});
// NHÓM: tạo (chỉ thêm người quen qua việc) — trả invite_code để mời thêm
app.post("/v1/conversations/group", auth, val(GroupIn), async (req, res) => {
  try { const r = await fn("SELECT * FROM create_group($1,$2,$3)",
          [req.uid, req.body.title, req.body.members]);
        res.status(201).json({ conversation_id: r[0].conversation_id, invite_code: r[0].invite_code });
  } catch (e) { sqlErr(res, e); }
});
// CHANNEL: tạo (broadcast — chỉ owner/admin đăng)
app.post("/v1/conversations/channel", auth, val(ChannelIn), async (req, res) => {
  try { const r = await fn("SELECT * FROM create_channel($1,$2,$3)",
          [req.uid, req.body.title, req.body.is_public]);
        res.status(201).json({ conversation_id: r[0].conversation_id, invite_code: r[0].invite_code });
  } catch (e) { sqlErr(res, e); }
});
// Danh bạ channel công khai
app.get("/v1/channels", auth, async (_q, res) => {
  res.json({ items: await fn(
    `SELECT c.id, c.title, c.created_at,
       (SELECT count(*) FROM conversation_members m WHERE m.conversation_id=c.id) member_count
     FROM conversations c WHERE c.kind='channel' AND c.is_public
     ORDER BY member_count DESC LIMIT 30`) });
});
app.post("/v1/conversations/:id/join", auth, async (req, res) => {
  try { await fn("SELECT join_conversation($1,$2)", [req.uid, req.params.id]);
        res.status(201).json({ joined: true }); } catch (e) { sqlErr(res, e); }
});
app.post("/v1/conversations/join-by-code", auth, val(CodeIn), async (req, res) => {
  try { const r = await fn("SELECT join_by_code($1,$2) id", [req.uid, req.body.code]);
        res.status(201).json({ conversation_id: r[0].id }); } catch (e) { sqlErr(res, e); }
});
app.post("/v1/conversations/:id/leave", auth, async (req, res) => {
  try { await fn("SELECT leave_conversation($1,$2)", [req.uid, req.params.id]);
        res.json({ left: true }); } catch (e) { sqlErr(res, e); }
});
app.post("/v1/conversations/:id/members", auth, val(MembersIn), async (req, res) => {
  try { const r = await fn("SELECT add_members($1,$2,$3) n", [req.uid, req.params.id, req.body.members]);
        res.status(201).json({ added: +r[0].n }); } catch (e) { sqlErr(res, e); }
});
// Thông tin hội thoại + thành viên (cho màn cài đặt nhóm)
app.get("/v1/conversations/:id", auth, async (req, res) => {
  const me = await fn("SELECT role FROM conversation_members WHERE conversation_id=$1 AND plumper_id=$2",
                      [req.params.id, req.uid]);
  if (!me.length) return problem(res, 403, "not_member");
  const [c, members] = await Promise.all([
    fn("SELECT id,kind,title,is_public,invite_code,owner,created_at FROM conversations WHERE id=$1", [req.params.id]),
    fn(`SELECT m.plumper_id, m.role, p.display_name, plump_level(m.plumper_id) level
        FROM conversation_members m JOIN plumpers p ON p.id=m.plumper_id
        WHERE m.conversation_id=$1 ORDER BY m.role, m.joined_at LIMIT 60`, [req.params.id]),
  ]);
  const info = { ...c[0], my_role: me[0].role, members };
  if (me[0].role === "member") delete info.invite_code;   // mã mời chỉ owner/admin thấy
  res.json(info);
});

/* ---- STATUS + PRESENCE trên map ---- */
app.post("/v1/me/status", auth, val(StatusIn), async (req, res) => {
  await fn("SELECT set_status($1,$2,$3)", [req.uid, req.body.body, req.body.emoji || null]);
  res.status(201).json({ status: req.body.body });
});
app.get("/v1/map/presence", async (_q, res) => {
  res.json({ items: await fn(
    `SELECT p.id, p.display_name, plump_level(p.id) level,
       s.body status, s.emoji,
       (SELECT item_id FROM equipped e WHERE e.owner=p.id AND e.slot='head') head,
       (SELECT item_id FROM equipped e WHERE e.owner=p.id AND e.slot='hand') hand,
       (SELECT ROUND(AVG(v.rating),1) FROM deal_reviews_visible v WHERE v.target=p.id) rating
     FROM plumpers p
     LEFT JOIN plumper_status s ON s.owner=p.id AND s.expires_at>now()
     WHERE p.role='plumper' AND p.suspended_at IS NULL
     ORDER BY (s.created_at IS NULL), s.created_at DESC, p.created_at DESC LIMIT 12`) });
});

// Mở (hoặc lấy) hội thoại của một deal
app.post("/v1/deals/:id/conversation", auth, async (req, res) => {
  try { const r = await fn("SELECT get_or_create_deal_conv($1,$2) id", [req.params.id, req.uid]);
        res.status(201).json({ conversation_id: r[0].id }); } catch (e) { sqlErr(res, e); }
});

// Đọc tin trong hội thoại (phân trang bằng before_id)
app.get("/v1/conversations/:id/messages", auth, async (req, res) => {
  const member = await fn("SELECT 1 FROM conversation_members WHERE conversation_id=$1 AND plumper_id=$2",
                          [req.params.id, req.uid]);
  if (!member.length) return problem(res, 403, "not_member");
  const before = req.query.before ? +req.query.before : null;
  const rows = await fn(
    `SELECT m.id, m.sender, m.body, m.attachment_url, m.attachment_kind, m.reply_to,
            m.edited_at, m.revoked_at, m.created_at,
            (SELECT body FROM chat_messages r WHERE r.id=m.reply_to) reply_preview
     FROM chat_messages m
     WHERE m.conversation_id=$1 AND ($2::bigint IS NULL OR m.id < $2)
     ORDER BY m.id DESC LIMIT 40`, [req.params.id, before]);
  const typing = await fn(
    `SELECT plumper_id FROM typing_state WHERE conversation_id=$1 AND plumper_id<>$2 AND until>now()`,
    [req.params.id, req.uid]);
  const items = rows.reverse().map(m => ({ ...m, id: +m.id,
    reply_to: m.reply_to === null ? null : +m.reply_to }));
  res.json({ items, typing: typing.map(t => t.plumper_id) });
});

// Gửi tin
app.post("/v1/conversations/:id/messages", auth, val(SendMsgIn), async (req, res) => {
  try {
    const r = await fn("SELECT post_message($1,$2,$3,$4,$5,$6) id",
      [req.uid, req.params.id, req.body.body || null, req.body.reply_to || null,
       req.body.attachment_url || null, req.body.attachment_kind || null]);
    res.status(201).json({ message_id: +r[0].id });
  } catch (e) { sqlErr(res, e); }
});
// Đánh dấu đã đọc
app.post("/v1/conversations/:id/read", auth, val(ReadIn), async (req, res) => {
  await fn("SELECT mark_read($1,$2,$3)", [req.uid, req.params.id, req.body.upto]);
  res.json({ ok: true });
});
// Đang gõ
app.post("/v1/conversations/:id/typing", auth, async (req, res) => {
  try { await fn("SELECT set_typing($1,$2)", [req.uid, req.params.id]); res.json({ ok: true }); }
  catch (e) { sqlErr(res, e); }
});
// Sửa / thu hồi
app.patch("/v1/messages/:id", auth, val(EditMsgIn), async (req, res) => {
  try { await fn("SELECT edit_message($1,$2,$3)", [req.uid, req.params.id, req.body.body]);
        res.json({ edited: true }); } catch (e) { sqlErr(res, e); }
});
app.post("/v1/messages/:id/revoke", auth, async (req, res) => {
  try { await fn("SELECT revoke_message($1,$2)", [req.uid, req.params.id]);
        res.json({ revoked: true }); } catch (e) { sqlErr(res, e); }
});

/* ============ FARM PLUMP MỞ RỘNG ============ */
app.post("/v1/deals/:id/tip", auth, val(TipIn), async (req, res) => {
  try { await fn("SELECT tip_plump($1,$2,$3)", [req.uid, req.params.id, req.body.amount]);
        res.status(201).json({ tipped: req.body.amount }); } catch (e) { sqlErr(res, e); }
});
app.post("/v1/civic/:kind/claim", auth, async (req, res) => {
  try { const r = await fn("SELECT claim_civic($1,$2) rw", [req.uid, req.params.kind]);
        res.status(201).json({ earned: +r[0].rw }); } catch (e) { sqlErr(res, e); }
});
app.post("/v1/help-newbie/:id", auth, async (req, res) => {
  try { const r = await fn("SELECT reward_help_newbie($1,$2) rw", [req.uid, req.params.id]);
        res.status(201).json({ earned: +r[0].rw }); } catch (e) { sqlErr(res, e); }
});
app.post("/v1/admin/jobs/grant-leaderboard/:period", admin, async (req, res) => {
  const p = ["day","week","month"].includes(req.params.period) ? req.params.period : "week";
  res.json({ granted: (await fn("SELECT grant_leaderboard_rewards($1) n", [p]))[0].n });
});

/* ============ HỆ VẬT PHẨM: shop / trang bị / phòng / tặng / sổ khách ============ */
app.get("/v1/shop", auth, async (req, res) => {
  res.json({ items: await fn(
    `SELECT i.*, (inv.item_id IS NOT NULL) AS owned
     FROM items i LEFT JOIN inventory inv ON inv.item_id=i.id AND inv.owner=$1
     ORDER BY i.source, i.price NULLS LAST`, [req.uid]) });
});
app.post("/v1/shop/:id/buy", auth, async (req, res) => {
  try { await fn("SELECT buy_item($1,$2)", [req.uid, req.params.id]);
        res.status(201).json({ bought: req.params.id }); } catch (e) { sqlErr(res, e); }
});
app.get("/v1/me/inventory", auth, async (req, res) => {
  const [inv, eq, room] = await Promise.all([
    fn(`SELECT inv.item_id, inv.via, inv.granted_at, inv.expires_at, i.name, i.slot, i.kind, i.source
        FROM inventory inv JOIN items i ON i.id=inv.item_id WHERE inv.owner=$1`, [req.uid]),
    fn("SELECT slot,item_id FROM equipped WHERE owner=$1", [req.uid]),
    fn("SELECT slot,item_id FROM room_slots WHERE owner=$1", [req.uid]),
  ]);
  res.json({ inventory: inv, equipped: eq, room: room });
});
app.post("/v1/me/equip", auth, val(EquipIn), async (req, res) => {
  try { await fn("SELECT equip_item($1,$2,$3)", [req.uid, req.body.slot, req.body.item_id]);
        res.json({ equipped: req.body }); } catch (e) { sqlErr(res, e); }
});
app.post("/v1/me/room", auth, val(EquipIn), async (req, res) => {
  try { await fn("SELECT set_room_slot($1,$2,$3)", [req.uid, req.body.slot, req.body.item_id]);
        res.json({ room: req.body }); } catch (e) { sqlErr(res, e); }
});
app.post("/v1/me/inventory/:id/gift", auth, val(GiftIn), async (req, res) => {
  try { await fn("SELECT gift_item($1,$2,$3)", [req.uid, req.body.to, req.params.id]);
        res.json({ gifted: req.params.id, to: req.body.to }); } catch (e) { sqlErr(res, e); }
});
app.get("/v1/plumpers/:id/room", async (req, res) => {
  const pid = req.params.id;
  const [pr, eq, room, shelf, gb, drops, twinBusy] = await Promise.all([
    fn("SELECT display_name FROM plumpers WHERE id=$1", [pid]),
    fn("SELECT e.slot, e.item_id, i.name FROM equipped e JOIN items i ON i.id=e.item_id WHERE e.owner=$1", [pid]),
    fn("SELECT r.slot, r.item_id, i.name FROM room_slots r JOIN items i ON i.id=r.item_id WHERE r.owner=$1", [pid]),
    fn(`SELECT inv.item_id, i.name FROM inventory inv JOIN items i ON i.id=inv.item_id
        WHERE inv.owner=$1 AND inv.via='earned'`, [pid]),
    fn(`SELECT g.body, g.created_at, p.display_name author FROM guestbook g
        JOIN plumpers p ON p.id=g.author WHERE g.room_owner=$1 ORDER BY g.id DESC LIMIT 10`, [pid]),
    fn("SELECT id,title,price FROM drops WHERE owner=$1 AND status='open' LIMIT 5", [pid]),
    fn(`SELECT EXISTS(SELECT 1 FROM twin_jobs j JOIN twins t ON t.id=j.twin_id
        WHERE t.owner=$1 AND j.status IN ('queued','drafted')) busy`, [pid]),
  ]);
  if (!pr.length) return problem(res, 404, "not_found");
  const done = await fn("SELECT count(*) n FROM deals WHERE executor=$1 AND state='SETTLED'", [pid]);
  res.json({ display_name: pr[0].display_name, equipped: eq, room: room,
    shelf: shelf, done: +done[0].n, guestbook: gb, open_drops: drops,
    twin_working: twinBusy[0].busy });
});
app.post("/v1/plumpers/:id/guestbook", auth, val(GuestIn), async (req, res) => {
  try { const r = await fn("SELECT guestbook_write($1,$2,$3) id", [req.uid, req.params.id, req.body.body]);
        res.status(201).json({ entry_id: r[0].id }); } catch (e) { sqlErr(res, e); }
});
app.post("/v1/admin/jobs/refresh-prestige", admin, async (_q, res) => {
  const r = (await fn("SELECT * FROM refresh_prestige()"))[0];
  res.json({ granted: +r.granted, revoked: +r.revoked });
});

/* ============ TRUST & SAFETY ============ */
app.post("/v1/reports", auth, val(ReportIn), async (req, res) => {
  const r = await fn("SELECT submit_report($1,$2,$3,$4) id",
    [req.uid, req.body.target_kind, req.body.target_id, req.body.reason]);
  res.status(201).json({ report_id: r[0].id });
});
app.get("/v1/admin/reports", admin, async (req, res) => {
  res.json({ items: await fn(
    `SELECT r.*, p.handle reporter_handle FROM reports r JOIN plumpers p ON p.id=r.reporter
     WHERE r.status=$1 ORDER BY r.created_at`, [req.query.status || "open"]) });
});
app.post("/v1/admin/reports/:id/action", admin, async (req, res) => {
  const act = req.body?.action;
  const r = (await fn("SELECT * FROM reports WHERE id=$1 AND status='open'", [req.params.id]))[0];
  if (!r) return problem(res, 409, "request_not_pending");
  if (act === "hide_target" && r.target_kind === "drop")
    await fn("UPDATE drops SET status='cancelled', mod_status='flagged' WHERE id=$1", [r.target_id]);
  else if (act === "suspend_user" && r.target_kind === "plumper")
    await fn("UPDATE plumpers SET suspended_at=now() WHERE id=$1", [r.target_id]);
  else if (act !== "dismiss") return problem(res, 400, "validation_error", "action không hợp lệ với target");
  await fn("UPDATE reports SET status=$2, actioned_at=now(), action=$3 WHERE id=$1",
    [r.id, act === "dismiss" ? "dismissed" : "actioned", act]);
  res.json({ done: act });
});
app.post("/v1/admin/plumpers/:id/suspend", admin, async (req, res) => {
  await fn("UPDATE plumpers SET suspended_at=now() WHERE id=$1", [req.params.id]);
  await fn("UPDATE sessions SET revoked_at=now() WHERE plumper_id=$1 AND revoked_at IS NULL", [req.params.id]);
  res.json({ suspended: true });
});
app.post("/v1/admin/plumpers/:id/unsuspend", admin, async (req, res) => {
  await fn("UPDATE plumpers SET suspended_at=NULL WHERE id=$1", [req.params.id]);
  res.json({ suspended: false });
});
app.get("/v1/admin/fraud-flags", admin, async (_q, res) => {
  res.json({ items: await fn("SELECT * FROM fraud_flags ORDER BY created_at DESC LIMIT 50") });
});

/* ============ TRANG PHÁP LÝ ============ */
const mdPage = (title, md) => `<!doctype html><html lang="vi"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title>
<style>body{background:#170A1D;color:#F6EDF5;font-family:-apple-system,'Segoe UI',sans-serif;max-width:760px;margin:0 auto;padding:40px 22px;line-height:1.75}
h1{color:#FF5FA8}h2{color:#F3B94D;margin-top:28px;font-size:17px}a{color:#FF5FA8}</style><body>` +
  md.replace(/^# (.+)$/gm, "<h1>$1</h1>").replace(/^## (.+)$/gm, "<h2>$2</h2>".replace("$2","$1"))
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").split(/\n\n+/).map(p => p.startsWith("<h") ? p : `<p>${p}</p>`).join("") + "</body></html>";
app.get("/terms",   (_q, res) => res.send(mdPage("Điều khoản — SuperPlump", fs.readFileSync(path.join(__dirname,"..","legal","TERMS.vi.md"),"utf8"))));
app.get("/privacy", (_q, res) => res.send(mdPage("Riêng tư — SuperPlump", fs.readFileSync(path.join(__dirname,"..","legal","PRIVACY.vi.md"),"utf8"))));

/* ================= ADMIN ================= */
app.get("/v1/admin/overview", admin, async (_q, res) => {
  const [[o], [esc], [plat], rec, [k]] = await Promise.all([
    fn(`SELECT (SELECT count(*) FROM plumpers) users,
               (SELECT count(*) FROM drops WHERE status='open') open_drops,
               (SELECT count(*) FROM deals WHERE state='SETTLED') settled,
               (SELECT count(*) FROM deals WHERE state='DISPUTED') disputed`),
    fn("SELECT balance FROM wallets WHERE kind='escrow'"),
    fn("SELECT balance FROM wallets WHERE kind='platform'"),
    fn("SELECT * FROM reconcile()"),
    fn("SELECT count(*) n FROM kyc_records WHERE status='pending'"),
  ]);
  res.json({ ...o, escrow: +esc.balance, platform_revenue: +plat.balance,
             ledger_ok: rec.length === 0, kyc_pending: +k.n });
});
app.get("/v1/admin/kyc", admin, async (req, res) => {
  res.json({ items: await fn(
    `SELECT k.id,k.plumper_id,p.display_name,COALESCE(k.provider,'legacy') provider,k.created_at
     FROM kyc_records k JOIN plumpers p ON p.id=k.plumper_id
     WHERE k.status=$1 ORDER BY k.created_at`, [req.query.status || "pending"]) });
});
app.post("/v1/admin/kyc/:id/:verdict", admin, async (req, res) => {
  try { await fn("SELECT kyc_review($1,$2,$3)", [req.params.id, req.params.verdict === "approve", "admin"]);
        res.json({ done: req.params.verdict }); } catch (e) { sqlErr(res, e); }
});
app.get("/v1/admin/disputes", admin, async (_q, res) => {
  res.json({ items: await fn(
    `SELECT d.id dispute_id,d.deal_id,d.reason,dl.hold_amount,
            pd.display_name dropper_name, pe.display_name executor_name
     FROM disputes d JOIN deals dl ON dl.id=d.deal_id
     JOIN plumpers pd ON pd.id=dl.dropper JOIN plumpers pe ON pe.id=dl.executor
     WHERE d.status='open' ORDER BY d.created_at`) });
});
app.post("/v1/admin/disputes/:dealId/resolve", admin, async (req, res) => {
  try { await fn("SELECT resolve_dispute($1,$2,NULL)", [req.params.dealId, req.body.outcome]);
        res.json({ outcome: req.body.outcome }); } catch (e) { sqlErr(res, e); }
});
app.post("/v1/admin/jobs/auto-confirm", admin, async (_q, res) => {
  res.json({ settled: (await fn("SELECT auto_confirm_overdue() n"))[0].n });
});
app.post("/v1/admin/jobs/cleanup-idempotency", admin, async (req, res) => {
  const idem = (await fn("SELECT cleanup_idempotency($1) n", [+(req.body?.hours || 48)]))[0].n;
  const auth_rows = (await fn("SELECT cleanup_auth(7) n"))[0].n;
  res.json({ deleted: idem, auth_cleaned: auth_rows });
});
app.get("/v1/admin/data-requests", admin, async (_q, res) => {
  res.json({ items: await fn(
    `SELECT d.id,d.kind,d.status,d.note,d.created_at,p.display_name
     FROM data_requests d JOIN plumpers p ON p.id=d.owner
     WHERE d.status='pending' ORDER BY d.created_at`) });
});
app.post("/v1/admin/data-requests/:id/process", admin, async (req, res) => {
  try { await fn("SELECT process_data_request($1,'admin')", [req.params.id]); res.json({ done: true }); }
  catch (e) { sqlErr(res, e); }
});
app.get("/v1/admin/recovery", admin, async (_q, res) => {
  res.json({ items: await fn(
    `SELECT r.id,r.kind,r.note,r.created_at,p.handle,p.display_name
     FROM recovery_requests r JOIN plumpers p ON p.id=r.plumper_id
     WHERE r.status='pending' ORDER BY r.created_at`) });
});
app.post("/v1/admin/recovery/:id/reissue-token", admin, async (req, res) => {
  const r = (await fn("SELECT plumper_id FROM recovery_requests WHERE id=$1 AND status='pending'", [req.params.id]))[0];
  if (!r) return problem(res, 409, "request_not_pending");
  const token = genToken13();
  await fn("UPDATE plumpers SET token_hash=$2 WHERE id=$1", [r.plumper_id, sha256(token)]);
  await fn("UPDATE sessions SET revoked_at=now() WHERE plumper_id=$1 AND revoked_at IS NULL", [r.plumper_id]);
  await fn("UPDATE recovery_requests SET status='done', processed_at=now() WHERE id=$1", [req.params.id]);
  res.json({ new_token: token, note: "Trao tay cho người dùng — token cũ & mọi phiên đã bị vô hiệu" });
});
app.post("/v1/admin/plumpers/:id/revoke-all", admin, async (req, res) => {
  const r = await fn("UPDATE sessions SET revoked_at=now() WHERE plumper_id=$1 AND revoked_at IS NULL RETURNING jti", [req.params.id]);
  res.json({ revoked: r.length });
});
app.post("/v1/admin/incidents", admin, async (req, res) => {
  const r = await fn(`INSERT INTO incidents(severity,summary) VALUES ($1,$2)
    RETURNING id,authority_deadline`, [req.body?.severity || "high", req.body?.summary || ""]);
  res.status(201).json({ incident_id: r[0].id, report_by_72h: r[0].authority_deadline });
});
app.get("/v1/admin/incidents", admin, async (_q, res) => {
  res.json({ items: await fn("SELECT * FROM incidents ORDER BY detected_at DESC LIMIT 50") });
});

/* ---------- dev-only ---------- */
let DEV_RSA = null;
if (DEV) {
  DEV_RSA = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
  app.get("/v1/dev/jwks", (_q, res) => {
    const jwk = DEV_RSA.publicKey.export({ format: "jwk" });
    res.json({ keys: [{ ...jwk, kid: "dev-rsa-1", use: "sig", alg: "RS256" }] });
  });
  app.post("/v1/dev/sign-rs256", (req, res) => {
    res.json({ token: jwt.sign({ sub: req.body?.sub, role: req.body?.role || "plumper" },
      DEV_RSA.privateKey, { algorithm: "RS256", keyid: "dev-rsa-1", expiresIn: "1h" }) });
  });
}
if (DEV) app.get("/v1/dev/mailbox", async (req, res) => {
  res.json({ items: await fn("SELECT to_email,subject,code,created_at FROM dev_outbox WHERE to_email=$1 ORDER BY id DESC LIMIT 5",
                             [String(req.query.to || "").toLowerCase()]) });
});
if (DEV) app.post("/v1/dev/users", async (req, res) => {
  const { handle = "dev", kyc = "verified", nara = 500000 } = req.body || {};
  const u = (await fn(
    "INSERT INTO plumpers(handle,display_name,kyc_status) VALUES ($1||substr(md5(random()::text),1,6),$1,$2) RETURNING id",
    [handle, kyc]))[0].id;
  await fn("INSERT INTO wallets(owner,kind) VALUES ($1,'user')", [u]);
  if (nara > 0) await fn("SELECT topup($1,$2)", [u, nara]);
  const plump = req.body?.plump ?? (DEV ? 100000 : 0);
  if (plump > 0) await fn("INSERT INTO plump_points(owner,amount,reason) VALUES ($1,$2,'demo_seed')", [u, plump]);
  res.status(201).json({ id: u, kyc });
});

/* ---------- static ---------- */
app.get("/admin", (_q, res) => res.sendFile(path.join(__dirname, "..", "admin", "admin.html")));
app.get("/app", (_q, res) => {
  res.set("Cache-Control", "no-store, no-cache, must-revalidate");
  res.sendFile(path.join(__dirname, "..", "prototype", "SuperPlump_Demo.html"));
});
app.get("/manifest.json", (_q, res) => res.sendFile(path.join(__dirname, "..", "prototype", "manifest.json")));
app.get("/sw.js", (_q, res) => {
  res.set("Cache-Control", "no-store, no-cache, must-revalidate");
  res.sendFile(path.join(__dirname, "..", "prototype", "sw.js"));
});

/* ================= REALTIME (pg LISTEN → WebSocket) ================= */
const TLS_CERT = secret("TLS_CERT_PATH"), TLS_KEY = secret("TLS_KEY_PATH");
const server = (TLS_CERT && TLS_KEY)
  ? https.createServer({ cert: fs.readFileSync(TLS_CERT), key: fs.readFileSync(TLS_KEY) }, app)
  : http.createServer(app);
const wss = new WebSocketServer({ server, path: "/realtime" });
wss.on("connection", (ws, req) => {
  MET.ws++; ws.on("close", () => MET.ws--);
  const u = new URL(req.url, "http://x");
  ws.channel = u.searchParams.get("channel") || "map";
  ws.send(JSON.stringify({ type: "subscribed", channel: ws.channel }));
});
function broadcast(channel, msg) {
  const s = JSON.stringify(msg);
  wss.clients.forEach((c) => { if (c.readyState === 1 && c.channel === channel) c.send(s); });
}
async function listenPg() {
  const c = new Client(PG);
  let retried = false;
  const retry = () => { if (retried) return; retried = true;
    try { c.end().catch(() => {}); } catch {} setTimeout(() => listenPg().catch(() => {}), 1500); };
  c.on("error", retry); c.on("end", retry);
  try { await c.connect(); await c.query("LISTEN plump_events"); }
  catch { return retry(); }
  console.log("[realtime] LISTEN plump_events ready");
  c.on("notification", (n) => {
    try {
      const e = JSON.parse(n.payload);
      if (e.agg === "drop") broadcast("map", e);
      if (e.agg === "deal") { broadcast("deal:" + e.id, e); broadcast("map", { ...e, agg: "deal" }); }
      if (e.agg === "user") broadcast("user:" + e.id, e);
      if (e.agg === "conversation") {
        broadcast("conversation:" + e.id, e);         // ai đang mở đúng hội thoại
        if (e.to) broadcast("user:" + e.to, e);       // + badge inbox cho người nhận
      }
    } catch {}
  });
}

/* Worker logic sống ở worker-core.js — server nhúng khi ENABLE_WORKER=1, hoặc chạy tách: node api/worker.js */
const { makeTick } = require("./worker-core");
const workerTick = makeTick(pool, MODEL);

/* ===== PREFLIGHT: chặn khởi động nếu cấu hình production còn sơ hở ===== */
function preflight() {
  const bad = [];
  const isProd = process.env.NODE_ENV === "production";
  const devish = (v) => !v || v.startsWith("dev-") || v.length < 16;
  if (isProd) {
    if (ALLOW_DEV_UUID) bad.push("ALLOW_DEV_UUID phải = 0 ở production (đang bật đường đăng nhập giả)");
    if (OWNER_TOKEN === "chaunacha") bad.push("OWNER_TOKEN vẫn là mặc định dev 'chaunacha'");
    if (OWNER_TOKEN.length < 16 && OWNER_TOKEN !== "ChauNacha") bad.push("OWNER_TOKEN quá ngắn (<16 ký tự)");
    if (ADMIN_KEY === "plump-admin" || ADMIN_KEY.length < 16) bad.push("ADMIN_KEY yếu/mặc định");
    if (devish(JWT_SECRET) && !JWKS_URL) bad.push("SUPABASE_JWT_SECRET yếu và không có JWKS_URL");
    if (!MASTER_KEY) bad.push("MASTER_KEY trống — khóa mandate sẽ lưu bản rõ (bắt buộc có KMS envelope)");
    if (devish(PAYMENT_WEBHOOK_SECRET)) bad.push("PAYMENT_WEBHOOK_SECRET yếu/mặc định");
    if (devish(EKYC_WEBHOOK_SECRET)) bad.push("EKYC_WEBHOOK_SECRET yếu/mặc định");
    if (!TLS_CERT && !process.env.TRUST_PROXY_TLS) bad.push("Không có TLS trực tiếp và chưa xác nhận TLS-terminating proxy (đặt TRUST_PROXY_TLS=1 nếu có Caddy/LB)");
    if (!process.env.ALLOWED_ORIGINS && !process.env.PUBLIC_DOMAIN) bad.push("Thiếu ALLOWED_ORIGINS/PUBLIC_DOMAIN để khóa CORS production");
  }
  if (bad.length) {
    console.error("\n╔═ PREFLIGHT THẤT BẠI — TỪ CHỐI KHỞI ĐỘNG (production) ═╗");
    bad.forEach((b, i) => console.error("  " + (i + 1) + ". " + b));
    console.error("╚═ Sửa cấu hình rồi chạy lại. Chi tiết: docs/RUNBOOK.md ═╝\n");
    process.exit(1);
  }
  console.log("[preflight] cấu hình OK (" + (isProd ? "production" : "dev") + ")");
}
preflight();

server.listen(process.env.PORT || 8386, () => {
  console.log(`SuperPlump API v2 ${(TLS_CERT&&TLS_KEY)?"https":"http"} :${process.env.PORT || 8386} · agents=${MODEL} · ws=/realtime`);
  listenPg().catch(() => {});
  ensureOwner().catch(e => console.error("ensureOwner:", e.message));
  if (process.env.ENABLE_WORKER !== "0") setInterval(workerTick, 600);
});

/* Owner "chaunacha" (env OWNER_TOKEN): gõ token là vào, full quyền admin */
async function ensureOwner() {
  const h = sha256(OWNER_TOKEN);
  const ex = await fn("SELECT id FROM plumpers WHERE role='owner' LIMIT 1");
  if (ex.length) { await fn("UPDATE plumpers SET token_hash=$2 WHERE id=$1", [ex[0].id, h]); return; }
  const r = await fn(
    `INSERT INTO plumpers(handle,display_name,kyc_status,role,token_hash,onboarded)
     VALUES ('owner','Chủ Chợ','verified','owner',$1,true) RETURNING id`, [h]);
  await fn("INSERT INTO wallets(owner,kind) VALUES ($1,'user')", [r[0].id]);
  console.log("Owner sẵn sàng · token qua env OWNER_TOKEN" +
    (process.env.OWNER_TOKEN ? "" : " (DEV default: chaunacha — ĐỔI TRƯỚC KHI RELEASE)"));
}

let workerTimer = null;
if (process.env.ENABLE_WORKER !== "0") { /* timer đã set ở trên — giữ tham chiếu để dọn */ }
for (const sig of ["SIGTERM", "SIGINT"]) process.on(sig, () => {
  console.log("[shutdown] " + sig + " — đóng êm");
  server.close(() => { pool.end().catch(() => {}); process.exit(0); });
  setTimeout(() => process.exit(0), 4000).unref();
});
