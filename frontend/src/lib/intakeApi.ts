/** 建檔精靈 API 型別與呼叫（票 B3-intake，契約 `.scratch/grill/GRILL-B3-intake.md`）。
 * 型別逐字對照契約「假資料形狀（TypeScript）」節；固定選項清單各自複製一份，不 import
 * `libraryApi.ts`／`productsApi.ts`（模組化規則：跨 feature 只准 import components/layout/
 * 與 lib/，同 `productsApi.ts` 檔頭已有的慣例）。
 *
 * `IntakeDraft.created_product_names` 是契約 TS 區塊沒列出、但「假資料要包含」節要求
 * 「產品偵測清單至少 1 筆已存在（測試「已建立」鎖選狀態）」必須要有的欄位——契約本身要求
 * 的測試資料需要它才能表達，不是額外自創的外部規格。 */

import { apiFetch, errorMessageFromResponse } from "./http";

export type IntakeJobKind = "scan" | "question" | "paste_fix" | "research";
export type IntakeJobStatus = "waiting" | "running" | "done" | "failed";

export interface IntakeJobState {
  status: IntakeJobStatus;
  stage: string;
  started_at: string;
  usual_range_text: string;
  error: string | null;
}

export interface IntakePhoto {
  token: string;
  name: string;
  size_mb: number;
}

export interface ScanImpression {
  looks_like: string;
  title: string;
  content: string;
  basis: string;
}

/** 照片直讀產品卡（T2 契約 1.2）：價格只列在 gaps，不會由照片猜值。 */
export interface ProductCardDraft {
  status: "ready" | "unreadable" | "failed" | "skipped";
  name: string;
  specification: string;
  selling_points: string[];
  source_photo_token: string;
  gaps: string[];
  message: string | null;
}

export interface UrlResult {
  url: string;
  ok: boolean;
}

export interface QuestionChoice {
  label: string;
  desc: string;
}

export interface CurrentQuestion {
  question: string;
  suggested: QuestionChoice;
  branches: QuestionChoice[];
}

export interface QuestionAnswer {
  index: number;
  question: string;
  choice_label: string;
  note: string;
}

export interface CostItem {
  label: string;
  amount: number;
  failed: boolean;
}

export interface PasteError {
  line: number | null;
  msg: string;
  unknown_scope?: string;
}

export type IntakeReviewKind = "品牌事實" | "產品事實" | "限制規則" | "宣稱";

export interface IntakeReviewItem {
  id: string;
  i: number;
  kind: IntakeReviewKind;
  category: string;
  title: string;
  content: string;
  scope: string;
  evidence: string;
  dup_hint: string | null;
  severity: "soft" | "hard" | null;
}

export interface IntakeDraft {
  id: string;
  brand_id: string;
  brand_name: string;
  step: number;
  completed: boolean;
  is_restart: boolean;

  description: string;
  urls: string[];
  photos: IntakePhoto[];

  scan_done: boolean;
  scan_impressions: ScanImpression[];
  scan_products: string[];
  product_card_drafts: ProductCardDraft[];
  created_product_names: string[];
  url_results: UrlResult[];

  qa_done: boolean;
  current_q: CurrentQuestion | null;
  answers: QuestionAnswer[];
  question_index: number;

  handoff_depth: "standard" | "deep" | null;
  handoff_generated: boolean;
  handoff_prompt: string | null;

  paste_raw: string;
  paste_errors: PasteError[];
  paste_fix_used: boolean;

  pending_item_count: number;

  budget_limit: number;
  cost_spent: number;
  cost_items: CostItem[];
}

export interface LimitBlock {
  kind: IntakeJobKind;
  amount: number;
  cost_spent: number;
  budget_limit: number;
  suggested_limit: number;
}

/** 三種 AI 呼叫的預估成本，逐字對照 `app/intake/script.py:33-36`（查證日 2026-08-12）。 */
export const COST_SCAN = 0.3;
export const COST_QUESTION = 0.1;
export const COST_PASTE_FIX = 0.5;
export const DEFAULT_BUDGET = 30.0;
/** 逐字對照 `app/intake/script.py` 的 COST_RESEARCH_STANDARD／COST_RESEARCH_DEEP。 */
export const COST_RESEARCH_STANDARD = 0.6;

export const REVIEW_KIND_OPTIONS: IntakeReviewKind[] = ["品牌事實", "產品事實", "限制規則", "宣稱"];

/** 分類清單逐字對照 `app/intake/script.py` 輸出格式段落與 `app/mock_data.py`（查證日 2026-08-12）。 */
export const CATEGORY_OPTIONS: Record<IntakeReviewKind, string[]> = {
  品牌事實: ["定位", "受眾", "語調", "通路", "法規限制", "視覺基礎"],
  產品事實: ["核心資訊", "作用機制", "差異化", "使用情境", "目標客群", "視覺風格"],
  限制規則: ["語氣", "視覺", "禁用字詞", "素材使用", "平台規格", "政策"],
  宣稱: ["可用", "高風險", "禁用"],
};

export const DEPTH_OPTIONS: { value: "standard" | "deep"; label: string; desc: string }[] = [
  {
    value: "standard",
    label: "標準調研",
    desc: "大約 5 到 10 分鐘跑完，涵蓋定位、受眾、競品與基本法規風險。多數品牌用這個就夠。",
  },
  {
    value: "deep",
    label: "深度調研",
    desc: "對標顧問公司的七章完整調研：市場品類、三軸競品拆解、顧客評論探勘、定價通路、法規備忘與機會點綜整。建議搭配外部 AI 的「深度研究」功能跑，大約 10 到 30 分鐘。新品類或不熟的市場建議選這個。",
  },
];

interface Envelope<T> {
  data: T;
  generated_at: string;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await apiFetch(path);
  if (!res.ok) {
    throw new Error(res.status === 404 ? "找不到這筆資料。" : `讀取失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<T> = await res.json();
  return body.data;
}

async function extractError(res: Response, fallback: string): Promise<string> {
  return errorMessageFromResponse(res, fallback);
}

async function postJson<T = void>(path: string, body?: unknown): Promise<T> {
  const res = await apiFetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw new Error(await extractError(res, `處理失敗（狀態碼 ${res.status}）`));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

async function postForm<T = void>(path: string, form: FormData): Promise<T> {
  const res = await apiFetch(path, { method: "POST", body: form });
  if (!res.ok) throw new Error(await extractError(res, `處理失敗（狀態碼 ${res.status}）`));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---- 起始輸入 ----

export function uploadIntakePhoto(file: File): Promise<IntakePhoto> {
  const form = new FormData();
  form.append("photo", file);
  return postForm(`/api/intake/photos`, form);
}

export interface IntakeStartFields {
  brand_name: string;
  client_name: string;
  description: string;
  urls: string[];
  photo_tokens: string[];
}

export function submitIntakeStart(fields: IntakeStartFields): Promise<{ brand_id: string; quick: boolean }> {
  const form = new FormData();
  form.append("brand_name", fields.brand_name);
  form.append("client_name", fields.client_name);
  form.append("description", fields.description);
  fields.urls.forEach((u) => form.append("urls", u));
  fields.photo_tokens.forEach((t) => form.append("photo_tokens", t));
  return postForm(`/api/intake/brands`, form);
}

export function submitIntakeRestart(
  brandId: string,
  fields: Omit<IntakeStartFields, "brand_name">,
): Promise<{ quick: boolean }> {
  const form = new FormData();
  form.append("description", fields.description);
  fields.urls.forEach((u) => form.append("urls", u));
  fields.photo_tokens.forEach((t) => form.append("photo_tokens", t));
  return postForm(`/api/intake/brands/${encodeURIComponent(brandId)}/restart`, form);
}

export function fetchIntakeDraft(brandId: string): Promise<IntakeDraft> {
  return getJson(`/api/intake/brands/${encodeURIComponent(brandId)}/draft`);
}

// ---- 初掃 ----

export function startScan(brandId: string): Promise<{ limit_block: LimitBlock | null }> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/scan/start`);
}

export function fetchScanStatus(brandId: string): Promise<IntakeJobState> {
  return getJson(`/api/intake/brands/${encodeURIComponent(brandId)}/scan/status`);
}

export function skipScan(brandId: string): Promise<void> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/scan/skip`);
}

export function createScannedProducts(brandId: string, names: string[]): Promise<{ created_count: number }> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/scan/products`, { names });
}

/** 從一張已讀出的照片建產品；回傳包裝在既有 scan/products 的資料裡，這裡只交給畫面要用的欄位。 */
export function createProductFromCard(brandId: string, sourcePhotoToken: string): Promise<{ created_count: number; product_id: string | null }> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/scan/products`, {
    source_photo_token: sourcePhotoToken,
  });
}

export function retryPhotoProduct(brandId: string, sourcePhotoToken: string): Promise<ProductCardDraft> {
  return postJson<{ card: ProductCardDraft }>(`/api/intake/brands/${encodeURIComponent(brandId)}/scan/products/retry`, {
    source_photo_token: sourcePhotoToken,
  }).then((body) => body.card);
}

export function skipPhotoProduct(brandId: string, sourcePhotoToken: string): Promise<void> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/scan/products/skip`, {
    source_photo_token: sourcePhotoToken,
  });
}

// ---- 引導問答 ----

export function startQuestion(brandId: string): Promise<{ limit_block: LimitBlock | null }> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/question/start`);
}

export function fetchQuestionStatus(brandId: string): Promise<IntakeJobState> {
  return getJson(`/api/intake/brands/${encodeURIComponent(brandId)}/question/status`);
}

export function answerQuestion(
  brandId: string,
  fields: { choice: string; note: string },
): Promise<void> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/question/answer`, fields);
}

export function skipQuestionRemaining(brandId: string): Promise<void> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/question/skip-remaining`);
}

// ---- 品牌知識：系統自己跑的調研（F05-I09） ----

export function startResearch(brandId: string): Promise<{ limit_block: LimitBlock | null }> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/research/start`, { depth: "standard" });
}

export function fetchResearchStatus(brandId: string): Promise<IntakeJobState> {
  return getJson(`/api/intake/brands/${encodeURIComponent(brandId)}/research/status`);
}

// ---- 交接包 ----

export function generateHandoff(brandId: string, depth: "standard" | "deep"): Promise<{ prompt_text: string }> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/handoff`, { depth });
}

export function fetchOperatorCard(
  brandId: string,
  provider: "claude" | "chatgpt",
): Promise<{ title: string; steps: string[] }> {
  return getJson(`/api/intake/brands/${encodeURIComponent(brandId)}/handoff/${provider}`);
}

// ---- 貼回 ----

/** 上傳檔案的情況（S4.47「有檔案以檔案內容為準」）由呼叫端在送出前用 `File.text()` 把檔案
 * 內容併入 `raw_text`，這裡只送純文字——不用為了模擬層再多一份「後端讀檔案」的邏輯。 */
export function validatePaste(
  brandId: string,
  rawText: string,
): Promise<{ errors: PasteError[]; data_line_count: number }> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/paste/validate`, { raw_text: rawText });
}

export function resolvePasteScope(
  brandId: string,
  fields: { scope_name: string; action: "create_product" | "assign_brand" },
): Promise<void> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/paste/resolve-scope`, fields);
}

export function startPasteFix(brandId: string): Promise<{ limit_block: LimitBlock | null }> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/paste/fix/start`);
}

export function fetchPasteFixStatus(brandId: string): Promise<IntakeJobState> {
  return getJson(`/api/intake/brands/${encodeURIComponent(brandId)}/paste/fix/status`);
}

// ---- 待處理清單 ----

export function fetchReviewList(brandId: string): Promise<IntakeReviewItem[]> {
  return getJson(`/api/intake/brands/${encodeURIComponent(brandId)}/review`);
}

export function reviewPendingAll(brandId: string): Promise<void> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/review/pending-all`);
}

export function fetchReviewItem(brandId: string, i: number): Promise<IntakeReviewItem> {
  return getJson(`/api/intake/brands/${encodeURIComponent(brandId)}/review/${i}`);
}

export interface ReviewItemEdit {
  outcome: "confirm" | "pending" | "discard";
  kind: IntakeReviewKind;
  category: string;
  title: string;
  content: string;
  scope: string;
  severity: "soft" | "hard" | null;
}

export function resolveReviewItem(brandId: string, i: number, fields: ReviewItemEdit): Promise<void> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/review/${i}`, fields);
}

// ---- 花費上限 ----

export function saveBudget(brandId: string, limit: number): Promise<void> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/budget`, { limit });
}

export function raiseBudgetAndRetry(
  brandId: string,
  kind: IntakeJobKind,
): Promise<{ job: IntakeJobState }> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/budget/raise`, { kind });
}

export function skipRemainingAi(brandId: string): Promise<void> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/skip-remaining-ai`);
}

// ---- 賣什麼與數字 ----

export type OfferingAssumptionField = "cost" | "shipping" | "close_rate";

export interface Offering {
  product_id: string;
  name: string;
  parent_id: string | null;
  selling_price: number | null;
  unit_variable_cost: number | null;
  shipping_cost: number | null;
  close_rate: number | null;
  assumptions: OfferingAssumptionField[];
}

export interface OfferingBenchmark {
  value: number;
  source_text: string;
}

export interface OfferingsData {
  offerings: Offering[];
  benchmarks: Record<"gross_margin" | "shipping_cost" | "close_rate", OfferingBenchmark>;
}

export function fetchOfferings(brandId: string): Promise<OfferingsData> {
  return getJson(`/api/intake/brands/${encodeURIComponent(brandId)}/offerings`);
}

export interface OfferingVariantInput {
  product_id?: string;
  label: string;
  selling_price: number | null;
  unit_variable_cost: number | null;
  shipping_cost: number | null;
  close_rate?: number | null;
  assumptions?: OfferingAssumptionField[];
}

export interface OfferingInput {
  parent: { product_id?: string; name: string };
  variants: OfferingVariantInput[];
}

export function saveOfferings(brandId: string, offerings: OfferingInput[]): Promise<void> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/offerings`, { offerings });
}

// ---- 精靈第 4 步：接工具（F05-I08） ----

export interface ConversionGoalOption {
  key: string;
  label: string;
}

export interface IntakeToolsData {
  conversion_goal: string | null;
  conversion_goal_options: ConversionGoalOption[];
  bound_account_ids: string[];
}

export function fetchIntakeTools(brandId: string): Promise<IntakeToolsData> {
  return getJson(`/api/intake/brands/${encodeURIComponent(brandId)}/tools`);
}

export function saveConversionGoal(brandId: string, conversionGoal: string): Promise<void> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/conversion-goal`, {
    conversion_goal: conversionGoal,
  });
}
