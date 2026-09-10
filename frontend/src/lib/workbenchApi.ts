/** 素材工作檯 API 型別與呼叫（票 workbench/03）。對應 `app/workbench/routes.py`。
 * 錯誤處理跟 `scheduleApi.ts` 的 `createSchedulePlan`（307-340 行）同一個寫法：`apiFetch`
 * 之後檢查 `res.ok`，不行就試著解析 `{"error": {...}}` 信封餵給 `errorMessageFrom`，
 * 解不出來就用預設訊息——這裡把那段抽成 `parseJsonOrThrow`/`ensureOk` 兩個小工具，8 支
 * 呼叫共用，不是換一套錯誤處理方式。
 *
 * 這支檔案只是型別＋fetch，還沒有任何畫面 import 它（ticket 04 才會）——
 * `.dependency-cruiser.cjs` 的規則只管 `src/components/<功能>/`，`lib/` 不算功能資料夾，
 * 沒有新規則要顧。 */
import { apiFetch, errorMessageFrom } from "./http";

export type WorkbenchBriefStatus = "active" | "closed" | "all";

/** CONSTITUTION.md 規則 5 的七個維度——這裡不生成、不驗證，照後端回什麼存什麼。 */
export interface WorkbenchCoordinates {
  audience?: string | null;
  pain?: string | null;
  angle?: string | null;
  hook?: string | null;
  proof?: string | null;
  offer?: string | null;
  format?: string | null;
}

export interface NewBriefRequest {
  use_brand_knowledge: boolean;
  free_text: string | null;
  image_prompt_count: number | null;
  video_script_count: number | null;
  // 只有 `BriefDetail.request` 的讀回形狀還在用這個鍵（`BriefDetail.tsx:263`）；新表單
  // （票 04）不再送這欄，改成 optional 讓兩邊共用同一個型別不用各自宣告一份
  // （票面「Not touched」段落，鍵與讀者留給 F01-T04-I02 一起刪）。
  on_image_texts?: string[] | null;
  parts: string[];
  copy_length: "short" | "medium" | "long";
}

export interface NewBrief {
  product_id: string | null;
  style_key: string;
  request: NewBriefRequest;
}

export interface WorkbenchPartSummary {
  latest_round: number;
  adopted_round: number | null;
  running: boolean;
}

export interface BriefSummary {
  id: string;
  kind: string;
  source_kind: string;
  source_ref: Record<string, unknown>;
  product_id: string | null;
  product_name: string | null;
  style_key: string;
  status: string;
  last_error: string | null;
  closed_at: string | null;
  created_at: string;
  parts: Record<string, WorkbenchPartSummary>;
}

export interface WorkbenchOutput {
  id: string;
  part: string;
  generation_round: number;
  adopted_at: string | null;
  body_json: Record<string, unknown>;
  coordinates_json: Record<string, unknown> | null;
  llm_task_id: string | null;
  created_at: string;
}

export interface BriefDetail extends BriefSummary {
  coordinates: WorkbenchCoordinates | null;
  visual_tone: string | null;
  visual_concept: string | null;
  request: NewBriefRequest;
  outputs: WorkbenchOutput[];
}

export interface ImageStyle {
  key: string;
  label: string;
  capture_line: string;
  authenticity_hint: string;
}

/** 三個固定長度的「什麼時候用」一句話——設計系統 §8：前端文案，不生成、不落地
 * （契約頁「Module-local」段）。工作檯（ticket 04）跟排程（ticket 05）兩個 feature
 * 資料夾都要顯示這句話，彼此不 import，所以放在 `lib/` 這個兩邊都能拿的地方，各自
 * 從這裡 import 一份，不是各自寫死一份。 */
export const LENGTH_HINTS = {
  short: "折疊前一口氣講完，適合再行銷、已認識品牌的人",
  medium: "痛點→證明→優惠，適合第一次看到你的人",
  long: "說故事，適合高單價、需要被說服的商品",
} as const;

export const LENGTH_LABELS = { short: "短版", medium: "中版", long: "長版" } as const;

async function ensureOk(res: Response, fallback: string): Promise<void> {
  if (res.ok) return;
  let message = fallback;
  try {
    const data = (await res.json()) as { error?: { message?: string } };
    message = errorMessageFrom(data, message);
  } catch {
    // 回應不是 JSON，用預設訊息。
  }
  throw new Error(message);
}

async function parseJsonOrThrow<T>(res: Response, fallback: string): Promise<T> {
  await ensureOk(res, fallback);
  return (await res.json()) as T;
}

const BASE = "/api/workbench";

export async function fetchStyles(): Promise<ImageStyle[]> {
  const res = await apiFetch(`${BASE}/styles`);
  const data = await parseJsonOrThrow<{ styles: ImageStyle[] }>(res, "讀取風格清單失敗。");
  return data.styles;
}

export async function fetchBriefs(
  brandId: string,
  status: WorkbenchBriefStatus = "active",
): Promise<BriefSummary[]> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/briefs?status=${encodeURIComponent(status)}`,
  );
  const data = await parseJsonOrThrow<{ briefs: BriefSummary[] }>(res, "讀取工單清單失敗。");
  return data.briefs;
}

export async function createBrief(brandId: string, input: NewBrief): Promise<BriefDetail> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/briefs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  const data = await parseJsonOrThrow<{ brief: BriefDetail }>(res, "建立工單失敗。");
  return data.brief;
}

export async function fetchBrief(brandId: string, id: string): Promise<BriefDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/briefs/${encodeURIComponent(id)}`,
  );
  const data = await parseJsonOrThrow<{ brief: BriefDetail }>(res, "讀取工單失敗。");
  return data.brief;
}

export async function runPart(
  brandId: string,
  id: string,
  part: string,
  count?: number,
): Promise<BriefDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/briefs/${encodeURIComponent(id)}/parts/`
      + `${encodeURIComponent(part)}/run`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(count === undefined ? {} : { count }),
    },
  );
  const data = await parseJsonOrThrow<{ brief: BriefDetail }>(res, "產出失敗。");
  return data.brief;
}

export async function adoptOutput(
  brandId: string,
  id: string,
  outputId: string,
): Promise<BriefDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/briefs/${encodeURIComponent(id)}/outputs/`
      + `${encodeURIComponent(outputId)}/adopt`,
    { method: "POST" },
  );
  const data = await parseJsonOrThrow<{ brief: BriefDetail }>(res, "採用失敗。");
  return data.brief;
}

export async function closeBrief(brandId: string, id: string): Promise<BriefDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/briefs/${encodeURIComponent(id)}/close`,
    { method: "POST" },
  );
  const data = await parseJsonOrThrow<{ brief: BriefDetail }>(res, "關閉失敗。");
  return data.brief;
}

export async function reopenBrief(brandId: string, id: string): Promise<BriefDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/briefs/${encodeURIComponent(id)}/reopen`,
    { method: "POST" },
  );
  const data = await parseJsonOrThrow<{ brief: BriefDetail }>(res, "重啟失敗。");
  return data.brief;
}

export async function deleteBrief(brandId: string, id: string): Promise<void> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/briefs/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
  await ensureOk(res, "刪除失敗。");
}
