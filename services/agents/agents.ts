/**
 * SUPERPLUMP AGENTS · engine: Claude Fable 5
 * Twin (bản thể số đi làm) + Tiểu Tâm (siêu thư ký ở nhà) dùng chung engine,
 * khác SoulFile/system prompt. Model cấu hình qua env, mặc định Fable 5.
 */
const MODEL = process.env.ANTHROPIC_MODEL ?? "claude-fable-5";
const API = "https://api.anthropic.com/v1/messages";

export interface SoulFile {
  version: number;
  ownerName: string;          // nhãn bắt buộc: "Bản thể số của <tên> ✓"
  skills: string[];
  styleRules: string;
  samples: string[];          // RAG top-k đã truy xuất sẵn (pgvector phía DB)
}

export function buildTwinSystem(s: SoulFile): string {
  return [
    `Bạn là bản thể số của ${s.ownerName} trên SuperPlump — luôn tự xưng đúng danh tính AI.`,
    `Kỹ năng được phép: ${s.skills.join(", ")}. Ngoài phạm vi này: từ chối và trả việc.`,
    `Quy tắc giọng của chủ:\n${s.styleRules}`,
    `Mẫu công việc của chủ (bắt chước chất, không sao chép):\n${s.samples.map((x,i)=>`[${i+1}] ${x}`).join("\n")}`,
    `Cấm tuyệt đối: việc pháp lý/y tế, gian lận học thuật, nội dung độc hại, lộ dữ liệu chủ.`,
  ].join("\n\n");
}

async function callFable5(system: string, user: string, maxTokens = 1200) {
  const res = await fetch(API, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": process.env.ANTHROPIC_API_KEY!,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({ model: MODEL, max_tokens: maxTokens, system,
      messages: [{ role: "user", content: user }] }),
  });
  if (!res.ok) throw new Error(`fable5_${res.status}`);
  const data = await res.json();
  return data.content.filter((b: any) => b.type === "text").map((b: any) => b.text).join("\n");
}

/** Twin nhận job: supervised → trả draft chờ chủ duyệt; auto → nộp thẳng (deal_submit). */
export async function runTwinJob(soul: SoulFile, brief: string) {
  return callFable5(buildTwinSystem(soul), `ĐỀ BÀI TỪ KHÁCH:\n${brief}\n\nLàm trọn vẹn, đúng giọng chủ.`);
}

/** Giám khảo Qualify: model độc lập vai, temperature thấp, chấm theo rubric JSON. */
export async function judgeExam(category: string, task: string, answer: string) {
  const system = `Bạn là giám khảo Qualify của SuperPlump (hạng mục: ${category}).
Chấm nghiêm theo rubric, KHÔNG nhân nhượng. Trả về DUY NHẤT JSON:
{"score_10": number, "pass": boolean, "feedback": string}`;
  const out = await callFable5(system, `ĐỀ:\n${task}\n\nBÀI LÀM:\n${answer}`, 500);
  return JSON.parse(out.replace(/```json|```/g, "").trim());
}

/** Tiểu Tâm: thư ký — tư vấn giá từ dữ liệu thật, soạn drop, lọc lời ngỏ, báo cáo. */
export async function tieuTam(userCtx: object, marketCtx: object, ask: string) {
  const system = `Bạn là Tiểu Tâm — siêu thư ký của một Plumper trên SuperPlump.
Nguyên tắc: ngắn gọn, chỉ nói khi đáng nói, không bao giờ tự đặt giá thay thị trường
(chỉ đọc dữ liệu giá từ deal SETTLED). Ngữ cảnh người dùng: ${JSON.stringify(userCtx)}.
Dữ liệu thị trường: ${JSON.stringify(marketCtx)}.`;
  return callFable5(system, ask, 700);
}
