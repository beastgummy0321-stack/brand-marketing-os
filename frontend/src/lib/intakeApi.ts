/** 品牌建檔 API：照片上傳、建品牌（第 1 步）、重新建檔、草稿整包、成效目標。七步各自的讀寫在
 * `intakeOnboardingApi.ts`。F42-I14 拆掉了舊階段（初掃印象、AI 問答、交接包、貼回、待處理清單、
 * 花費側欄、賣什麼與數字）的呼叫與型別。 */

import { apiFetch, errorMessageFromResponse } from "./http";

/** Only `shared/LimitCard.tsx` still reads these (the legacy over-cap card; no step renders it any more). */
export type IntakeJobKind = "scan" | "question" | "paste_fix" | "research";

export interface LimitBlock {
  kind: IntakeJobKind;
  amount: number;
  cost_spent: number;
  budget_limit: number;
  suggested_limit: number;
}

export interface IntakePhoto {
  token: string;
  name: string;
  size_mb: number;
}

/** `GET …/draft`: the open draft, else the brand's latest completed one. */
export interface IntakeDraft {
  id: string;
  brand_id: string;
  brand_name: string;
  step: number;
  completed: boolean;

  description: string;
  urls: string[];
  photos: IntakePhoto[];

  scan_done: boolean;
}

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
  /** F42-I04: brand-photo kind per token, same order (logo|store|team|brand_image|other; default other). */
  photo_kinds?: string[];
  /** F42-I04: e.g. "TW"; empty = not set. */
  market_region?: string;
  /** F42-I04: "food_tw" or empty. */
  regulatory_regime?: string;
}

export function submitIntakeStart(fields: IntakeStartFields): Promise<{ brand_id: string; quick: boolean }> {
  const form = new FormData();
  form.append("brand_name", fields.brand_name);
  form.append("client_name", fields.client_name);
  form.append("description", fields.description);
  fields.urls.forEach((u) => form.append("urls", u));
  fields.photo_tokens.forEach((t) => form.append("photo_tokens", t));
  (fields.photo_kinds ?? []).forEach((k) => form.append("photo_kinds", k));
  if (fields.market_region) form.append("market_region", fields.market_region);
  if (fields.regulatory_regime) form.append("regulatory_regime", fields.regulatory_regime);
  return postForm(`/api/intake/brands`, form);
}

/** F42-I04: brand onboarding step 1 (`#/b1`) creates the brand through the same form post. */
export const createBrand = submitIntakeStart;

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

// ---- 成效目標（第 6 步接工具） ----

export function saveConversionGoal(brandId: string, conversionGoal: string): Promise<void> {
  return postJson(`/api/intake/brands/${encodeURIComponent(brandId)}/conversion-goal`, {
    conversion_goal: conversionGoal,
  });
}
