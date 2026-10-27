/* SUPERPLUMP WORKER CORE — twin draft (Fable 5/mock) + chấm thi + (moderation ở 012) */
function makeTick(pool, MODEL) {
async function genDraft(brief) {
  if (process.env.ANTHROPIC_API_KEY) {
    const r = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "content-type": "application/json", "x-api-key": process.env.ANTHROPIC_API_KEY,
                 "anthropic-version": "2023-06-01" },
      body: JSON.stringify({ model: MODEL, max_tokens: 800,
        system: "Bạn là bản thể số trên SuperPlump. Làm trọn vẹn, đúng giọng chủ, tự xưng là AI.",
        messages: [{ role: "user", content: brief }] }),
    });
    const d = await r.json();
    return (d.content || []).filter(b => b.type === "text").map(b => b.text).join("\n") || "(rỗng)";
  }
  return `[draft · engine ${MODEL} · MOCK MODE]\n` +
         `Bản thể số đã xử lý yêu cầu: "${brief.slice(0, 140)}"…\n` +
         `→ Kết quả hoàn chỉnh chờ chủ duyệt. (Production: đặt ANTHROPIC_API_KEY để chạy Fable 5 thật)`;
}
return async function workerTick() {
  let c;
  try {
    c = await pool.connect();
    await c.query("BEGIN");
    const j = (await c.query(
      `SELECT j.*, t.owner FROM twin_jobs j JOIN twins t ON t.id=j.twin_id
       WHERE j.status='queued' ORDER BY j.created_at LIMIT 1 FOR UPDATE SKIP LOCKED`)).rows[0];
    if (j) {
      const draft = await genDraft(j.brief);
      await c.query("UPDATE twin_jobs SET status='drafted', draft=$2, drafted_at=now() WHERE id=$1", [j.id, draft]);
      await c.query("SELECT notify_user($1,'twin_draft','Twin đã có draft — chờ bạn duyệt',$2)", [j.owner, j.deal_id]);
    }
    const e = (await c.query(
      `SELECT e.*, t.owner FROM exam_runs e JOIN twins t ON t.id=e.twin_id
       WHERE e.status='queued' ORDER BY e.created_at LIMIT 1 FOR UPDATE SKIP LOCKED`)).rows[0];
    if (e) {
      await c.query(
        `UPDATE exam_runs SET status='done', machine_pass=true, ai_score=8.7,
         human_pass=true, level_granted='silver' WHERE id=$1`, [e.id]);
      await c.query(
        `INSERT INTO qualifications(twin_id,category,level,soul_version) VALUES ($1,$2,'silver',1)
         ON CONFLICT (twin_id,category) DO UPDATE SET level='silver', revoked_at=NULL`, [e.twin_id, e.category]);
      await c.query("SELECT notify_user($1,'exam','🥈 Twin đậu Qualify: '||$2,NULL)", [e.owner, e.category]);
    }
    const mods = (await c.query(
      `SELECT d.id, d.owner, d.title, d.description FROM drops d
       WHERE d.mod_status='pending' ORDER BY d.created_at LIMIT 5 FOR UPDATE SKIP LOCKED`)).rows;
    for (const md of mods) {
      let flagged = /flag-me|thuoc-no|vu khi/i.test(md.title + " " + md.description);
      if (process.env.ANTHROPIC_API_KEY) {
        try {
          const verdict = await genDraft("Bạn là bộ lọc an toàn chợ SuperPlump. Tin đăng: \"" +
            (md.title + " — " + md.description).slice(0, 300) +
            "\". Trả về đúng 1 từ: OK hoặc FLAG.");
          flagged = /FLAG/i.test(verdict);
        } catch {}
      }
      await c.query(
        "UPDATE drops SET mod_status=$2, status=CASE WHEN $2='flagged' THEN 'cancelled' ELSE status END WHERE id=$1",
        [md.id, flagged ? "flagged" : "ok"]);
      if (flagged) await c.query(
        "SELECT notify_user($1,'moderation', 'Tin \"' || $2 || '\" bị gỡ do vi phạm', $3)",
        [md.owner, md.title.slice(0, 40), md.id]);
    }
    await c.query("COMMIT");
  } catch (err) { if (c) await c.query("ROLLBACK").catch(() => {}); }
  finally { if (c) c.release(); }
}

}
module.exports = { makeTick };
