/** 產品清單＋詳情 API 型別與呼叫（票 B2-products，契約 `.scratch/grill/GRILL-B2-products.md`）。
 * 型別逐字對照契約「假資料形狀（TypeScript）」節；固定選項清單照抄 `app/mock_data.py:20-93`
 * （查證日 2026-08-11）——這裡不重複定義品牌智庫已有的 RULE_TYPES／CLAIM_TYPES，因為兩份
 * 常數值目前剛好相同，但刻意不 import `libraryApi.ts`：跨 feature 只准 import
 * `components/layout/` 與 `lib/`，import 另一個 feature 的 API 檔會讓兩個本該各自可刪的
 * feature 綁死，兩份各自維護的成本（六行常數）遠低於耦合的成本。
 *
 * 詳情頁採「一次整包讀」（比照 `fetchLibrary()`）：契約「要新增的 API」節列的 facts／
 * economics-view／rules／claims 四支 GET 是後端未來各自的路由邊界，前端原型合併成一支
 * `fetchProductDetail()`，分頁切換不重新打 API——跟 S5 品牌智庫同一個決定，見
 * `GRILL-B2-library.md`「不用新增」節；不是漏做，是重用上一票已經定案的整包讀模式。
 * 其餘寫入端點沿用契約「改回 JSON」的決定，用 JSON body（跟 S5 沿用舊版 FormData 端點不同，
 * 因為 S6 這些端點契約本來就標記為新端點）。 */

export interface ProductListItem {
  id: string;
  name: string;
  status: "active" | "archived";
  fact_count: number;
  pending_fact_count: number;
  economics_status: "confirmed" | "pending" | "none";
}

export interface ProductDetailCard {
  key: "facts" | "economics-view" | "rules" | "claims";
  title: string;
  count: number;
  pending: number;
}

export type ProductFactType =
  | "core_info"
  | "mechanism"
  | "differentiation"
  | "scenario"
  | "audience"
  | "visual_style"
  | string;

export interface ProductFact {
  id: string;
  fact_type: ProductFactType;
  fact_type_label: string;
  label: string;
  value: string;
  status: "confirmed" | "pending";
  confirmed_by: string | null;
  confirmed_at: string | null;
  source_reference: string | null;
}

export interface ProductEconomics {
  selling_price: number;
  fixed_cost: number | null;
  unit_variable_cost: number | null;
  shipping_cost: number | null;
  currency: string;
  cpa_roas_basis: string | null;
  effective_from: string | null;
  status: "confirmed" | "pending";
  confirmed_by: string | null;
}

export interface ProductRule {
  id: string;
  severity: "hard" | "soft";
  rule_type: string;
  rule_type_label: string;
  content: string;
  product_id: string | null;
}

export interface ProductClaim {
  id: string;
  claim_type: "approved" | "high_risk" | "forbidden";
  claim_text: string;
  evidence_source_reference: string | null;
  product_id: string | null;
}

export interface ProductDeleteImpact {
  label: string;
  count: number;
}

export type ResearchJobStatus = "waiting" | "running" | "done" | "failed";

export interface ResearchJobState {
  status: ResearchJobStatus;
  stage: string;
  started_at: string;
  usual_range_text: string;
  error: string | null;
  added_count: number | null;
  price_created: boolean;
}

/** 詳情整包（原型合併版，見檔頭說明）：`ProductDetail` 契約欄位＋四分頁內容一次帶回。 */
export interface ProductDetailBundle {
  id: string;
  brand_id: string;
  name: string;
  status: "active" | "archived";
  knowledge_version: number;
  cards: ProductDetailCard[];
  latest_source_url: string | null;
  economics_pending: boolean;
  facts: ProductFact[];
  economics: ProductEconomics | null;
  rules: ProductRule[];
  claims: ProductClaim[];
}

export const PRODUCT_FACT_TYPES: [string, string][] = [
  ["core_info", "核心資訊"],
  ["mechanism", "作用機制"],
  ["differentiation", "差異化"],
  ["scenario", "使用情境"],
  ["audience", "目標客群"],
  ["visual_style", "視覺風格"],
];

export const RULE_TYPES: [string, string][] = [
  ["tone", "語氣"],
  ["visual", "視覺"],
  ["forbidden_word", "禁用字詞"],
  ["asset_usage", "素材使用"],
  ["platform_spec", "平台規格"],
  ["policy", "政策"],
];

export type ClaimType = "approved" | "high_risk" | "forbidden";
export const CLAIM_TYPES: [ClaimType, string][] = [
  ["approved", "可用"],
  ["high_risk", "高風險"],
  ["forbidden", "禁用"],
];

export const CURRENCIES: [string, string][] = [
  ["TWD", "新台幣（TWD）"],
  ["USD", "美元（USD）"],
  ["CNY", "人民幣（CNY）"],
];

export const CURRENCY_SYMBOLS: Record<string, string> = { TWD: "NT$", USD: "$", CNY: "¥" };

export function optionLabel(pairs: [string, string][], value: string): string {
  return pairs.find(([v]) => v === value)?.[1] ?? value;
}

/** AI 調研成本常數，逐字對照 `app/brand_intelligence/product_ai.py:36,124`（查證日 2026-08-11）。 */
export const COST_PRODUCT_SCAN = 0.3;
export const COST_PRODUCT_HANDOFF_FIX = 0.5;

interface Envelope<T> {
  data: T;
  generated_at: string;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(res.status === 404 ? "找不到這筆資料。" : `讀取失敗（狀態碼 ${res.status}）`);
  }
  const body: Envelope<T> = await res.json();
  return body.data;
}

async function postJson<T = void>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    let message = `處理失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: string };
      if (data.error) message = data.error;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---- 產品清單 ----

export function fetchProductList(brandId: string): Promise<ProductListItem[]> {
  return getJson(`/api/products/brands/${encodeURIComponent(brandId)}`);
}

export function createProduct(
  brandId: string,
  fields: { name: string; source_url: string },
): Promise<{ id: string }> {
  return postJson(`/api/products/brands/${encodeURIComponent(brandId)}`, fields);
}

export function startProductResearch(
  brandId: string,
  fields: { name: string; source_url: string },
): Promise<{ product_id: string }> {
  return postJson(`/api/products/brands/${encodeURIComponent(brandId)}/research`, fields);
}

// ---- 產品詳情（整包） ----

export function fetchProductDetail(brandId: string, productId: string): Promise<ProductDetailBundle> {
  return getJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}`,
  );
}

export function archiveProduct(brandId: string, productId: string): Promise<void> {
  return postJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/archive`,
  );
}

// ---- AI 調研（新建與再次調研共用背景工作，key = product_id）----

export function startRescan(brandId: string, productId: string, sourceUrl: string): Promise<void> {
  return postJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/rescan`,
    { source_url: sourceUrl },
  );
}

export function fetchResearchStatus(brandId: string, productId: string): Promise<ResearchJobState> {
  return getJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/research-status`,
  );
}

// ---- 產品事實 ----

export function createProductFact(
  brandId: string,
  productId: string,
  fields: { fact_type: string; label: string; value: string; status: string; source_reference: string },
): Promise<void> {
  return postJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/facts`,
    fields,
  );
}

export function updateProductFact(
  brandId: string,
  productId: string,
  factId: string,
  fields: { fact_type: string; label: string; value: string; source_reference: string },
): Promise<void> {
  return postJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/facts/${encodeURIComponent(factId)}`,
    fields,
  );
}

export function confirmProductFact(
  brandId: string,
  productId: string,
  factId: string,
): Promise<void> {
  return postJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/facts/${encodeURIComponent(factId)}/confirm`,
    {},
  );
}

export function deleteProductFact(brandId: string, productId: string, factId: string): Promise<void> {
  return postJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/facts/${encodeURIComponent(factId)}/delete`,
  );
}

// ---- 產品經濟數字 ----

export function saveProductEconomics(
  brandId: string,
  productId: string,
  fields: {
    selling_price: number;
    fixed_cost: number;
    unit_variable_cost: number;
    shipping_cost: number;
    currency: string;
    cpa_roas_basis: string;
    effective_from: string;
    confirmed_by: string;
  },
): Promise<void> {
  return postJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/economics`,
    fields,
  );
}

export function confirmProductEconomics(brandId: string, productId: string): Promise<void> {
  return postJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/economics/confirm`,
  );
}

// ---- 調研交接包 ----

export function fetchProductHandoffPrompt(brandId: string, productId: string): Promise<{ prompt_text: string }> {
  return getJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/handoff`,
  );
}

export function submitProductHandoff(
  brandId: string,
  productId: string,
  replyText: string,
): Promise<{ added_count: number }> {
  return postJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/handoff`,
    { reply_text: replyText },
  );
}

// ---- 永久刪除 ----

export function fetchDeleteImpact(brandId: string, productId: string): Promise<ProductDeleteImpact[]> {
  return getJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/delete`,
  );
}

export function deleteProduct(brandId: string, productId: string, confirmName: string): Promise<void> {
  return postJson(
    `/api/products/brands/${encodeURIComponent(brandId)}/products/${encodeURIComponent(productId)}/delete`,
    { confirm_name: confirmName },
  );
}
