/** Library API types and calls (ticket B2-library, contract `.scratch/grill/GRILL-B2-library.md`).
 * Types are copied verbatim from the contract's "mock data shape (TypeScript)" section — that
 * shape was distilled from the existing backend functions' return fields, not invented here.
 * Envelope format follows the existing convention {data, generated_at}, see lib/api.ts
 * `Envelope<T>`. All write actions now call the `/api/library/...` JSON endpoints in
 * `app/brand_web/routes_library_write.py` (and `routes_library.py` for delete-brand /
 * assets / customer-voice) — same style as B1 resolveAlert(): fetch JSON, check res.ok,
 * caller re-fetches fetchLibrary to refresh the whole payload afterwards.
 *
 * Fixed option lists are copied from `app/mock_data.py:20-156` (verified 2026-08-11), not an
 * invented external shape — same pattern as `workbenchApi.ts` REJECT_REASONS: the backend
 * constant table has no enumeration endpoint, so the frontend side-panel dropdown options are
 * copied here next to the matching API calls as "values that never change" (code-rules §2). */

import { apiFetch, errorMessageFrom } from "./http";

export interface LibraryBrandFact {
  id: string;
  fact_type: string;
  fact_type_label: string;
  /** F38-I01: which evidence kind a 「證據」 fact is; F42-I01: a 「全店政策」 fact's registry key
   * (its Chinese name is `label`); null for every other type. */
  fact_key: string | null;
  fact_key_label: string | null;
  label: string;
  value: string;
  status: "confirmed" | "pending";
  confirmed_by: string | null;
  confirmed_at: string | null;
  stale_label: string | null;
  source_reference: string | null;
}

export type RuleSeverity = "hard" | "soft";

export interface LibraryRule {
  id: string;
  rule_type: string;
  rule_type_label: string;
  content: string;
  severity: RuleSeverity;
  product_id: string | null;
  scope_label: string;
  source_reference: string | null;
}

export type ClaimType = "approved" | "high_risk" | "forbidden";

export interface LibraryClaim {
  id: string;
  claim_text: string;
  claim_type: ClaimType;
  product_id: string | null;
  scope_label: string;
  evidence_source_reference: string | null;
}

export interface LibraryAsset {
  id: string;
  asset_kind: "logo" | "product_photo" | "packaging" | "store" | "team" | "brand_image" | "other";
  asset_kind_label: string;
  title: string | null;
  product_id: string | null;
  product_name: string | null;
  file_url: string;
}

export interface LibraryChannel {
  id: string;
  channel_type: "website" | "fb_page" | "ig_account";
  channel_type_label: string;
  name: string;
  identifier: string;
  status: "active" | "inactive";
}

export type CustomerVoiceTaskLayer = "functional" | "emotional" | "social";
export type CustomerVoiceSignal = "unprompted" | "prompted";

export interface CustomerVoiceExtractionItem {
  task_layer: CustomerVoiceTaskLayer;
  quote: string;
  insight: string;
  signal: CustomerVoiceSignal;
}

export interface LibraryCustomerVoice {
  id: string;
  source_channel: string;
  source_channel_label: string;
  source_detail: string | null;
  raw_text: string;
  status: "active" | "archived";
  extraction: CustomerVoiceExtractionItem[];
}

export type CustomerVoiceJobStatus =
  | { status: "running" }
  | { status: "done"; result: LibraryCustomerVoice }
  | { status: "failed"; message: string };

export interface LibraryBrandProfile {
  id: string;
  name: string;
  client_name: string | null;
  status: "active" | "archived";
  market_region: string | null;
  conversion_goal: string | null;
  advertising_history: "has_history" | "none" | null;
  regulatory_regime: "food_tw" | null;
  delete_impact: { label: string; count: number }[];
}

export interface LibraryProductOption {
  id: string;
  name: string;
}

export interface LibraryData {
  brand: LibraryBrandProfile;
  products: LibraryProductOption[];
  facts: LibraryBrandFact[];
  rules: LibraryRule[];
  claims: LibraryClaim[];
  assets: LibraryAsset[];
  channels: LibraryChannel[];
  customer_voices: LibraryCustomerVoice[];
}

export const BRAND_FACT_TYPES: [string, string][] = [
  ["positioning", "定位"],
  ["audience", "受眾"],
  ["tone", "語調"],
  ["channel", "通路"],
  ["regulatory", "法規限制"],
  ["visual_base", "視覺基礎"],
  ["proof", "證據"],
  // F42-I01: shown in the list only -- policies are written by brand onboarding, not this form.
  ["policy", "全店政策"],
];

/** F38-I01: the six evidence kinds of a 「證據」 fact (= `app/core/vocab.py` PROOF_KINDS). */
export const PROOF_KINDS: [string, string][] = [
  ["customer_review", "顧客評論原話"],
  ["expert_endorsement", "專家背書"],
  ["lab_report", "檢驗報告／認證"],
  ["sales_numbers", "銷售數據"],
  ["media_coverage", "媒體報導"],
  ["founder_voice", "創辦人第一手"],
];

export const RULE_TYPES: [string, string][] = [
  ["tone", "語氣"],
  ["visual", "視覺"],
  ["forbidden_word", "禁用字詞"],
  ["asset_usage", "素材使用"],
  ["platform_spec", "平台規格"],
  ["policy", "政策"],
];

export const CLAIM_TYPES: [ClaimType, string][] = [
  ["approved", "可用"],
  ["high_risk", "高風險"],
  ["forbidden", "禁用"],
];

export const CHANNEL_TYPES: [string, string][] = [
  ["website", "官方網站"],
  ["fb_page", "粉絲專頁"],
  ["ig_account", "Instagram 帳號"],
];

export const ASSET_KINDS: [string, string][] = [
  ["logo", "Logo"],
  ["product_photo", "商品參考照"],
  ["packaging", "包裝"],
  // F42-I01: brand photos (brand onboarding step 素材).
  ["store", "門市／工作室"],
  ["team", "團隊／創辦人"],
  ["brand_image", "品牌形象"],
  ["other", "其他"],
];

export const CUSTOMER_VOICE_CHANNELS: [string, string][] = [
  ["shopee", "蝦皮商品評論"],
  ["momo", "momo 商品評論"],
  ["dcard", "Dcard"],
  ["ptt", "PTT"],
  ["fb_group", "FB 社團／粉專留言"],
  ["customer_service", "客服對話紀錄"],
  ["other", "其他"],
];

export const TASK_LAYER_LABELS: Record<CustomerVoiceTaskLayer, string> = {
  functional: "功能任務",
  emotional: "情感任務",
  social: "社會任務",
};

export const SIGNAL_LABELS: Record<CustomerVoiceSignal, string> = {
  unprompted: "主動提及",
  prompted: "被提示才講",
};

export const PERSONA_TYPES: [string, string][] = [
  ["kol", "KOL／創作者"],
  ["brand", "品牌／商家"],
  ["solo_seller", "個人賣家"],
  ["service_booking", "服務／預約制"],
  ["other", "其他"],
];

export const MARKET_REGIONS: [string, string][] = [["TW", "台灣"]];

export const CONVERSION_GOALS: [string, string][] = [
  ["purchase", "購買"],
  ["lead", "留資料"],
  ["booking", "預約"],
  ["awareness", "認識品牌"],
];

export function optionLabel(pairs: [string, string][], value: string): string {
  return pairs.find(([v]) => v === value)?.[1] ?? value;
}

interface Envelope<T> {
  data: T;
  generated_at: string;
}

export async function fetchLibrary(brandId: string): Promise<LibraryData> {
  const res = await apiFetch(`/api/library/brands/${encodeURIComponent(brandId)}`);
  if (!res.ok) {
    throw new Error(
      res.status === 404 ? "找不到這個品牌。" : `品牌智庫讀取失敗（狀態碼 ${res.status}）`,
    );
  }
  const body: Envelope<LibraryData> = await res.json();
  return body.data;
}

/** Shared JSON write helper for every write endpoint in this file. Error message is pulled
 * from whichever shape the backend used: `{error}` (single message, e.g. brand_delete_api),
 * `{errors}` (per-field validation dict, e.g. routes_library_write.py), or `{detail}`
 * (StarletteHTTPException / NotFoundKind's 404 JSON shape) — same convention as
 * `campaignsApi.ts` postJson(). `body` defaults to `{}` for delete/confirm-style calls that
 * carry no fields. `method` defaults to POST (every existing caller); ticket past-ads/03's
 * advertising-history endpoint is this file's first PUT. */
async function postJson<T>(path: string, body: unknown = {}, method: string = "POST"): Promise<T> {
  const res = await apiFetch(path, {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let message = `處理失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: string; errors?: Record<string, string>; detail?: string };
      // 欄位錯誤表是這支獨有的形狀；其餘兩種外殼交給共用的 errorMessageFrom
      if (data.errors) message = Object.values(data.errors).join("；");
      else message = errorMessageFrom(data, message);
    } catch {
      // Response body isn't JSON, use the default message.
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

// ---- 品牌事實 ----

export async function createFact(
  brandId: string,
  fields: {
    fact_type: string;
    fact_key?: string | null;
    label: string;
    value: string;
    status: string;
    source_reference: string;
  },
): Promise<void> {
  await postJson(`/api/library/brands/${encodeURIComponent(brandId)}/facts`, fields);
}

export async function updateFact(
  brandId: string,
  factId: string,
  fields: { fact_type: string; fact_key?: string | null; label: string; value: string; source_reference: string },
): Promise<void> {
  await postJson(
    `/api/library/brands/${encodeURIComponent(brandId)}/facts/${encodeURIComponent(factId)}/edit`,
    fields,
  );
}

export async function confirmFact(brandId: string, factId: string, confirmedBy: string): Promise<void> {
  await postJson(
    `/api/library/brands/${encodeURIComponent(brandId)}/facts/${encodeURIComponent(factId)}/confirm`,
    { confirmed_by: confirmedBy },
  );
}

export async function deleteFact(brandId: string, factId: string): Promise<void> {
  await postJson(`/api/library/brands/${encodeURIComponent(brandId)}/facts/${encodeURIComponent(factId)}/delete`);
}

// ---- 限制規則 ----

export async function createRule(
  brandId: string,
  fields: { rule_type: string; content: string; severity: string; product_id: string; source_reference: string },
): Promise<void> {
  await postJson(`/api/library/brands/${encodeURIComponent(brandId)}/rules`, fields);
}

export async function updateRule(
  brandId: string,
  ruleId: string,
  fields: { rule_type: string; content: string; severity: string; product_id: string; source_reference: string },
): Promise<void> {
  await postJson(
    `/api/library/brands/${encodeURIComponent(brandId)}/rules/${encodeURIComponent(ruleId)}/edit`,
    fields,
  );
}

export async function deleteRule(brandId: string, ruleId: string): Promise<void> {
  await postJson(`/api/library/brands/${encodeURIComponent(brandId)}/rules/${encodeURIComponent(ruleId)}/delete`);
}

// ---- 宣稱 ----

export async function createClaim(
  brandId: string,
  fields: { claim_text: string; claim_type: string; product_id: string; evidence_source_reference: string },
): Promise<LibraryClaim> {
  const body = await postJson<Envelope<LibraryClaim>>(`/api/library/brands/${encodeURIComponent(brandId)}/claims`, fields);
  return body.data;
}

export async function updateClaim(
  brandId: string,
  claimId: string,
  fields: { claim_text: string; claim_type: string; product_id: string; evidence_source_reference: string },
): Promise<LibraryClaim> {
  const body = await postJson<Envelope<LibraryClaim>>(
    `/api/library/brands/${encodeURIComponent(brandId)}/claims/${encodeURIComponent(claimId)}/edit`,
    fields,
  );
  return body.data;
}

export async function deleteClaim(brandId: string, claimId: string): Promise<void> {
  await postJson(`/api/library/brands/${encodeURIComponent(brandId)}/claims/${encodeURIComponent(claimId)}/delete`);
}

// ---- 官方素材 ----

export async function uploadAsset(
  brandId: string,
  fields: { asset_kind: string; product_id: string; title: string; file: File },
): Promise<void> {
  const body = new FormData();
  body.append("asset_kind", fields.asset_kind);
  body.append("product_id", fields.product_id);
  body.append("title", fields.title);
  body.append("file", fields.file);
  const res = await apiFetch(`/api/brands/${encodeURIComponent(brandId)}/assets`, { method: "POST", body });
  if (!res.ok) {
    throw new Error(`上傳失敗（狀態碼 ${res.status}）`);
  }
}

export async function deleteAsset(brandId: string, assetId: string): Promise<void> {
  await postJson(`/api/library/brands/${encodeURIComponent(brandId)}/assets/${encodeURIComponent(assetId)}/delete`);
}

// ---- 自有渠道 ----
// update/delete 兩支端點是本票新增（見契約 S5.31「拿不準的點」，本票先假設要補；
// 若之後確認渠道是故意只增不改，這兩支連同 ChannelPanel 的編輯入口整批刪掉即可，
// 前端只有這一個檔案跟一個側板元件牽涉到，改動面很小）。

export async function createChannel(
  brandId: string,
  fields: { channel_type: string; name: string; identifier: string; status: string },
): Promise<void> {
  await postJson(`/api/library/brands/${encodeURIComponent(brandId)}/channels`, fields);
}

export async function updateChannel(
  brandId: string,
  channelId: string,
  fields: { channel_type: string; name: string; identifier: string; status: string },
): Promise<void> {
  await postJson(
    `/api/library/brands/${encodeURIComponent(brandId)}/channels/${encodeURIComponent(channelId)}/edit`,
    fields,
  );
}

export async function deleteChannel(brandId: string, channelId: string): Promise<void> {
  await postJson(
    `/api/library/brands/${encodeURIComponent(brandId)}/channels/${encodeURIComponent(channelId)}/delete`,
  );
}

// ---- 顧客原話 ----

/** 貼入＋AI 抽取：背景執行，立即回 job_key，不等 AI 跑完（契約 S5.40、五鐵則③）。 */
export async function submitCustomerVoice(
  brandId: string,
  fields: { source_channel: string; source_detail: string; raw_text: string },
): Promise<{ job_key: string }> {
  const res = await apiFetch(`/api/library/brands/${encodeURIComponent(brandId)}/customer-voice`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(fields),
  });
  if (!res.ok) {
    throw new Error(`送出失敗（狀態碼 ${res.status}）`);
  }
  return res.json();
}

/** 佔位卡輪詢：後端補接口階段會定案真實輪詢間隔／端點，本票先定「不能同步擋住 request」
 * 這條（契約「要新增的 API」節）。 */
export async function fetchCustomerVoiceJob(
  brandId: string,
  jobKey: string,
): Promise<CustomerVoiceJobStatus> {
  const res = await apiFetch(
    `/api/library/brands/${encodeURIComponent(brandId)}/customer-voice/jobs/${encodeURIComponent(jobKey)}`,
  );
  if (!res.ok) {
    throw new Error(`查詢失敗（狀態碼 ${res.status}）`);
  }
  return res.json();
}

export async function archiveCustomerVoice(brandId: string, cvId: string): Promise<void> {
  await postJson(
    `/api/library/brands/${encodeURIComponent(brandId)}/customer-voice/${encodeURIComponent(cvId)}/archive`,
  );
}

export async function deleteCustomerVoice(brandId: string, cvId: string): Promise<void> {
  await postJson(
    `/api/library/brands/${encodeURIComponent(brandId)}/customer-voice/${encodeURIComponent(cvId)}/delete`,
  );
}

// ---- 品牌資料側板 ----

export async function saveBrandProfile(
  brandId: string,
  fields: {
    name: string;
    client_name: string;
    status: string;
    persona: string;
    market_region: string;
    conversion_goal: string;
  },
): Promise<void> {
  await postJson(`/api/library/brands/${encodeURIComponent(brandId)}/edit`, fields);
}

/** 票 past-ads/03（ADR 0067 rule 6）：投放過／沒投過的一次性選擇（兩顆按鈕的
 * `ui/dialog`，也能從品牌頁改）。PUT，跟本檔其餘寫入端點的 POST 慣例不同——後端路由本身
 * 就是 PUT（票面明講）。 */
export async function setAdvertisingHistory(
  brandId: string,
  value: "has_history" | "none",
): Promise<"has_history" | "none"> {
  const result = await postJson<{ data: { advertising_history: "has_history" | "none" } }>(
    `/api/library/brands/${encodeURIComponent(brandId)}/advertising-history`,
    { value },
    "PUT",
  );
  return result.data.advertising_history;
}

/** F34-I01（Contract R）：品牌適用哪一套廣告法規；`null` 清除（= 不適用）。PUT，同上。 */
export async function setRegulatoryRegime(
  brandId: string,
  value: "food_tw" | null,
): Promise<"food_tw" | null> {
  const result = await postJson<{ data: { regulatory_regime: "food_tw" | null } }>(
    `/api/library/brands/${encodeURIComponent(brandId)}/regulatory-regime`,
    { value },
    "PUT",
  );
  return result.data.regulatory_regime;
}

/** 回傳訊息含備份位置與素材資料夾刪除的 warn，呼叫端刪完導頁前先讓使用者看一眼。 */
export function deleteBrand(brandId: string, confirmName: string): Promise<string> {
  return postJson<{ message: string }>(
    `/api/library/brands/${encodeURIComponent(brandId)}/delete`,
    { confirm_name: confirmName },
  ).then((body) => body.message);
}
