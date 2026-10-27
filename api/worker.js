/* SuperPlump WORKER — tiến trình tách riêng (multi-instance): node api/worker.js */
const { Pool } = require("pg");
const { makeTick } = require("./worker-core");
const pool = new Pool({
  host: process.env.PGHOST || "127.0.0.1", user: process.env.PGUSER || "plump",
  password: process.env.PGPASSWORD || "plump", database: process.env.PGDATABASE || "superplump",
  connectionTimeoutMillis: 3000, max: 4,
});
pool.on("error", (e) => console.error("[worker pool]", e.message));
const MODEL = process.env.ANTHROPIC_MODEL || "claude-fable-5";
const tick = makeTick(pool, MODEL);
const timer = setInterval(() => tick().catch(() => {}), 600);
console.log("SuperPlump worker riêng đã chạy · engine=" + MODEL);
for (const sig of ["SIGTERM", "SIGINT"]) process.on(sig, () => {
  clearInterval(timer); pool.end().finally(() => process.exit(0));
});
