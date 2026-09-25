/** 素材工作檯 API 型別與呼叫（F02-I07，取代舊版 brief 形狀）。對應 `app/workbench/routes.py`
 * F02-I03 之後的介面：任務包 → 素材組 → 產物 → 版本。錯誤處理沿用既有寫法：`apiFetch` 之後
 * 檢查 `res.ok`，不行就試著解析 `{"error": {...}}` 信封餵給 `errorMessageFrom`，解不出來就用
 * 預設訊息——`parseJsonOrThrow`/`ensureOk` 兩個小工具全部呼叫共用。 */
import { apiFetch, errorMessageFrom } from "./http";

export type PackStatus = "pending" | "running" | "awaiting_approval" | "done";
export type PackListStatus = "all" | PackStatus;
export type PackSort = "updated" | "created" | "progress";
export type ProductPart = "copy" | "image_prompt" | "video_script";

export interface PackNextStep {
  set_id: string;
  set_name: string;
  part: ProductPart;
  label: string;
}

export interface PackCount {
  part: ProductPart;
  label: string;
  selected: number;
  required: number;
}

/** `GET /packs` 一張卡、`入口` 頁 pack 卡片與 list view 共用（`.work/tickets/F02-I07.md`
 * "list = table rows...same data, no new fields"）。 */
export interface PackCard {
  id: string;
  name: string;
  subtitle: string;
  source_kind: string;
  source_label: string;
  status: PackStatus;
  sets_total: number;
  sets_done: number;
  progress_pct: number;
  next_step: PackNextStep | null;
  counts: PackCount[];
  updated_at: string;
}

export interface PackCompletionItem {
  key: string;
  label: string;
  ok: boolean;
  overridden: boolean;
}

export interface PackSetCell {
  part: ProductPart;
  label: string;
  state: string;
  selected: number;
  required: number | null;
  text: string;
}

export interface PackSetRow {
  id: string;
  name: string;
  status: string;
  cells: PackSetCell[];
}

export interface PackDetail extends PackCard {
  created_at: string;
  source_ref: Record<string, unknown>;
  /** F03-I07: upstream-supplied, rendered verbatim — absent when the pack has no upstream
   * origin (自由創作), in which case `source_label` is used instead. */
  origin_label?: string | null;
  origin_href?: string | null;
  meta: { platform: string | null; goal: string | null; sets_required: number };
  summary: Partial<{
    situation: string;
    angle: string;
    style: string;
    audience: string;
    key_messages: string;
    reference_link: string;
  }>;
  completion: PackCompletionItem[];
  can_approve: boolean;
  blocking_text: string;
  sets: PackSetRow[];
  /** F07 Decision 29：探索風格佔比過低的提醒，永不影響 `can_approve`／`blocking_text`。 */
  image_exploration_warning?: string | null;
}

export interface VersionBody {
  body?: unknown;
  headline?: unknown;
  description?: unknown;
  validation?: unknown;
  warnings?: unknown;
  [key: string]: unknown;
}

export interface PromptCard {
  label: string;
  text: string;
}

export interface ProductVersion {
  /** Advisory only. The user may confirm and select without adding a source. */
  claim_warning?: { message: string; href: string } | null;
  /** Feature Contract L: this version's own failed-check (❌) lines, `null` when none.
   * Advisory like `claim_warning` — selecting it takes one explicit confirm. */
  validation_warning?: { lines: string[] } | null;
  id: string;
  version_index: number;
  generation_round: number;
  selected_at: string | null;
  body: VersionBody | null;
  /** 只有 `image_prompt` 版本有這欄（`image_cards.prompt_cards`，§5.7／§5.11）：這一版的
   * 卡片，選定且是單圖時再加一張 ② 變體卡，圖片 tab 未接港口時原樣顯示。 */
  prompt_cards?: PromptCard[];
  /** F07-I08：look·layout·device·persuasion 標籤，`null` 表示 pre-F07 版本。 */
  fingerprint_text?: string | null;
  /** F07-I08：`["主力"／"探索"]` 加「建議選這張」，`[]` 表示 pre-F07 版本。 */
  badges?: string[];
}

export interface SetProduct {
  state: string;
  selected: number;
  required: number;
  /** Feature Contract L: an ads-dispatched image set already holds `required` selections;
   * the server refuses another (409 `selection_full`) until one is deselected. */
  selection_full?: boolean;
  generation_settings: Record<string, unknown>;
  versions: ProductVersion[];
  /** F07-I08：`image_prompt` 的「複製全部」文字，其餘產物固定 `null`。 */
  copy_all_text?: string | null;
}

export interface SetSibling {
  id: string;
  name: string;
  angle: string | null;
  status: string;
}

export interface GenerationSettingRow {
  label: string;
  text: string;
}

export interface SetDetail {
  generation?: { status: string; error: string | null };
  id: string;
  pack_id: string;
  pack_name: string;
  name: string;
  status: string;
  /** F02-I17: `workbench_pack.source_kind` 原樣傳過來，工作檯不解讀——只用來決定要不要
   * 顯示「到檔期規劃」連結。 */
  source_kind: string;
  /** F03-I07: same origin fields as `PackDetail`, rendered above the set name. */
  origin_label?: string | null;
  origin_href?: string | null;
  /** F02-I17: 任務包核准後鎖住選定，跟 `image_generation.reason` 同一條規則——文字由後端
   * 產生一次，前端只原樣顯示，不重講規則。 */
  lock: { locked: boolean; reason: string | null };
  chips: { platform: string | null; style: string | null; size: string | null };
  siblings: SetSibling[];
  required_parts: ProductPart[];
  products: Partial<Record<ProductPart, SetProduct>>;
  /** §5.13：右欄「生成設定」表，永遠八列，`{label, text}` 逐列照給的順序原樣渲染。 */
  generation_settings: GenerationSettingRow[];
  image_generation: { connected: boolean; reason: string };
}

/** F02-I06 的 `spec` 七個鍵，逐字對照 §5「AI 解析結果」表格列——不多不少
 * （`app/workbench/free_parse.py::_validate_reply`）。 */
export interface FreeParseOutput {
  part: ProductPart;
  count: number;
}

export interface FreeParseSpec {
  topic: string | null;
  outputs: FreeParseOutput[];
  style_hint: string | null;
  platform: string | null;
  size: string | null;
  audience: string | null;
  key_message: string | null;
}

export interface FreeParseResult {
  parsed: boolean;
  note: string | null;
  spec: FreeParseSpec;
}

export interface FreePackSetInput {
  name?: string;
  source_ref?: Record<string, unknown>;
  coordinates?: Record<string, unknown>;
  product_id?: string | null;
  style_key?: string;
  required_outputs: Partial<Record<ProductPart, number>>;
  request?: Record<string, unknown>;
}

export interface NewFreePackRequest {
  name?: string | null;
  free_text?: string | null;
  product_id?: string | null;
  style_key?: string | null;
  sets: FreePackSetInput[];
  summary?: Record<string, unknown>;
  context?: Record<string, unknown>;
}

/** 三個固定長度的「什麼時候用」一句話——設計系統 §8：前端文案，不生成、不落地
 * （契約頁「Module-local」段）。工作檯與排程兩個 feature 資料夾都要顯示這句話，彼此不
 * import，所以放在 `lib/` 這個兩邊都能拿的地方，各自從這裡 import 一份，不是各自寫死一份。
 * `components/schedule/CreativePackList.tsx:6` 是它們僅存的呼叫端——F02 不動那支檔案，
 * 所以這兩個常數留在這裡（F02-I07 Done）。 */
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

export interface VisualSpecWarning {
  text: string;
  href: string;
}

export async function getVisualSpec(
  brandId: string,
): Promise<{ warnings: VisualSpecWarning[] }> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/visual-spec`);
  return parseJsonOrThrow<{ warnings: VisualSpecWarning[] }>(res, "讀取品牌視覺基礎失敗。");
}

export async function listPacks(
  brandId: string,
  opts: { status?: PackListStatus; q?: string; sort?: PackSort } = {},
): Promise<PackCard[]> {
  const params = new URLSearchParams();
  params.set("status", opts.status ?? "all");
  if (opts.q) params.set("q", opts.q);
  params.set("sort", opts.sort ?? "updated");
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/packs?${params.toString()}`,
  );
  const data = await parseJsonOrThrow<{ packs: PackCard[] }>(res, "讀取任務包清單失敗。");
  return data.packs;
}

export async function getPack(brandId: string, packId: string): Promise<PackDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/packs/${encodeURIComponent(packId)}`,
  );
  const data = await parseJsonOrThrow<{ pack: PackDetail }>(res, "讀取任務包失敗。");
  return data.pack;
}

/** `POST /parse`（F02-I06）：使用者按「建立自由工作」時的**一次** AI 解析。`defaults` 用
 * `FreeParseSpec` 同一組七個鍵，失敗／逾時／解析不出來時後端原樣回傳這份 `defaults`
 * （`parsed: false`）——呼叫端永遠拿得到一份可以直接建立的 spec。 */
export async function parseFreeText(
  brandId: string,
  freeText: string,
  defaults: Partial<FreeParseSpec>,
): Promise<FreeParseResult> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/parse`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ free_text: freeText, defaults }),
  });
  const data = await parseJsonOrThrow<{ parse: FreeParseResult }>(res, "AI 解析失敗，請稍後再試。");
  return data.parse;
}

export async function createFreePack(
  brandId: string,
  input: NewFreePackRequest,
): Promise<PackDetail> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/packs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  const data = await parseJsonOrThrow<{ pack: PackDetail }>(res, "建立自由創作失敗。");
  return data.pack;
}

export async function setPackCompletion(
  brandId: string,
  packId: string,
  key: string,
  checked: boolean,
): Promise<PackDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/packs/${encodeURIComponent(packId)}/completion`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ key, checked }),
    },
  );
  const data = await parseJsonOrThrow<{ pack: PackDetail }>(res, "更新完成條件失敗。");
  return data.pack;
}

export async function approvePack(brandId: string, packId: string): Promise<PackDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/packs/${encodeURIComponent(packId)}/approve`,
    { method: "POST" },
  );
  const data = await parseJsonOrThrow<{ pack: PackDetail }>(res, "核准整包失敗。");
  return data.pack;
}

export async function closePack(brandId: string, packId: string): Promise<PackDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/packs/${encodeURIComponent(packId)}/close`,
    { method: "POST" },
  );
  const data = await parseJsonOrThrow<{ pack: PackDetail }>(res, "關閉任務包失敗。");
  return data.pack;
}

export async function getSet(brandId: string, setId: string): Promise<SetDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/sets/${encodeURIComponent(setId)}`,
  );
  const data = await parseJsonOrThrow<{ set: SetDetail }>(res, "讀取素材組失敗。");
  return data.set;
}

export async function runProduct(
  brandId: string,
  setId: string,
  part: ProductPart,
  count?: number,
): Promise<SetDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/sets/${encodeURIComponent(setId)}/products/`
      + `${encodeURIComponent(part)}/run`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(count === undefined ? {} : { count }),
    },
  );
  const data = await parseJsonOrThrow<{ set: SetDetail }>(res, "產出失敗。");
  return data.set;
}

export async function selectVersion(
  brandId: string,
  setId: string,
  versionId: string,
): Promise<SetDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/sets/${encodeURIComponent(setId)}/versions/`
      + `${encodeURIComponent(versionId)}/select`,
    { method: "POST" },
  );
  const data = await parseJsonOrThrow<{ set: SetDetail }>(res, "選定失敗。");
  return data.set;
}

export async function deselectVersion(
  brandId: string,
  setId: string,
  versionId: string,
): Promise<SetDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/sets/${encodeURIComponent(setId)}/versions/`
      + `${encodeURIComponent(versionId)}/select`,
    { method: "DELETE" },
  );
  const data = await parseJsonOrThrow<{ set: SetDetail }>(res, "取消選定失敗。");
  return data.set;
}
