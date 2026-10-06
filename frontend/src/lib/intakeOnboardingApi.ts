/** Brand onboarding API (F42-I04): the seven steps `#/b1`–`#/b7` of
 * `.harness/scratch/prototype/f41-onboarding/index.html`. Shapes mirror
 * `app/intake/onboarding.py` field by field; types + fetchers only (no component logic).
 *
 * `source` on a prefilled field: `"saved"` = a confirmed value, `"ai"` = the website/photo scan's
 * proposal (with `note`, e.g. 「about 頁」), `"none"` = nothing found. PUTs return the step's fresh
 * GET shape; a 400 carries a Chinese `error` message, thrown here as an `Error`. */

import { apiFetch, readJson } from "./http";

export type OnboardingSource = "saved" | "ai" | "none";
export type PrefillStatus = "none" | "running" | "done" | "failed";

export interface OnboardingStatus {
  /** 1 基本 · 2 AI 讀網站 · 3 品牌是誰 · 4 證據與政策 · 5 素材 · 6 接工具 · 7 完成 */
  step: number;
  /** No open draft: re-entry mode (a brand that never had a draft reads as completed too). */
  completed: boolean;
  /** The brand has no URLs and no photos: step 2 is skipped. */
  skipped_scan: boolean;
  prefill_status: PrefillStatus;
  prefill_error: string | null;
}

// ---- 1 基本 ----

export type BrandPhotoKind = "logo" | "store" | "team" | "brand_image" | "other";
export type AdvertisingHistory = "has_history" | "none";

export interface BrandPhoto {
  id: string;
  kind: BrandPhotoKind;
  url: string;
}

export interface OnboardingBasics {
  name: string;
  urls: string[];
  photos: BrandPhoto[];
  market_region: string | null;
  regulatory_regime: "food_tw" | null;
  advertising_history: AdvertisingHistory | null;
  client_name: string;
  description: string;
}

export interface OnboardingBasicsInput {
  name: string;
  urls: string[];
  market_region: string | null;
  regulatory_regime: "food_tw" | null;
  advertising_history?: AdvertisingHistory | null;
  client_name: string;
  description: string;
  /** Existing brand photos to keep; omit to keep all. */
  photo_ids?: string[];
  /** New photos from `uploadIntakePhoto` (intakeApi.ts), with their kinds in the same order. */
  photo_tokens?: string[];
  photo_kinds?: BrandPhotoKind[];
}

// ---- 2 AI 讀網站 (F42-I05) ----

export interface ScanFoundRow {
  /** 品牌是誰 · 品牌證據 · 政策 · 可能的商品 (in this order; a row only when something was found). */
  area: string;
  text: string;
  /** Where it was read (「頁面 1」「about 頁」「品牌照片」…); "" = no note given. */
  note: string;
}

export interface OnboardingScan {
  status: PrefillStatus;
  /** The failure message when `status` is `failed`, else null. */
  error: string | null;
  found: ScanFoundRow[];
  /** Areas the scan looked for and did not find (「媒體報導」「銷售數據」…). */
  not_found: string[];
  /** Fields steps 3/4 will show pre-filled (positioning, tone, visual, each proof, each policy). */
  prefilled: number;
  pages_read: number;
  photos_read: number;
  /** The website list this read was for (F47 Contract F); a saved list that differs makes the read stale
   * (the status then reads `none` and the scan starts again). */
  urls_read: string[];
  /** Pages that could not be read, each with the reason in Chinese (HTTP status, timeout, unknown domain, …). */
  pages_failed: ScanPageFailed[];
}

export interface ScanPageFailed {
  url: string;
  reason: string;
}

// ---- 自訂 (F42-I05): a proposal only; the step's PUT saves it ----

export type CustomBlock = "positioning" | "tone" | "visual" | "brand_proof" | "policy" | "forbidden";

export type CustomProposal =
  | { block: "positioning" | "visual"; kind: "value"; value: string }
  | { block: "tone"; kind: "option"; option: { label: string } }
  | { block: "brand_proof"; kind: "option"; option: { fact_key: ProofKind; label: string; text: string } }
  | {
      block: "policy";
      kind: "option";
      /** Ready to append to `OnboardingEvidenceInput.policies` as `{key, params, sentence}`. */
      option: {
        key: "custom";
        label: string;
        offer_key: OfferKey;
        offer_label: string;
        sentence: string;
        params: { label: string; offer_key: OfferKey };
      };
    }
  | { block: "forbidden"; kind: "option"; option: { text: string } };

// ---- 3 品牌是誰 ----

export interface SourcedText {
  value: string;
  source: OnboardingSource;
  note: string;
}

export interface OnboardingIdentity {
  positioning: SourcedText;
  tone: { values: string[]; options: string[]; source: OnboardingSource; note: string };
  visual: SourcedText & { photo_urls: string[] };
}

export interface OnboardingIdentityInput {
  positioning: string;
  /** 1–2 tones. */
  tone: string[];
  visual: string;
}

// ---- 4 證據與政策 ----

export type ProofKind =
  | "customer_review"
  | "expert_endorsement"
  | "lab_report"
  | "sales_numbers"
  | "media_coverage"
  | "founder_voice";

export type OfferKey =
  | "free_shipping"
  | "discount"
  | "bundle"
  | "trial_sample"
  | "guarantee"
  | "limited_time"
  | "none";

export interface ProofItem {
  id: string | null;
  fact_key: ProofKind;
  text: string;
  source: OnboardingSource;
  note: string;
}

export type PolicyParamValue = string | number;

export interface PolicyItem {
  /** Registry key of `policy_types`, or `custom` (params `{label, offer_key}` + its own sentence). */
  key: string;
  label: string;
  group: string;
  params: Record<string, PolicyParamValue>;
  offer_key: OfferKey | null;
  offer_label: string;
  /** The ad-ready sentence the program composed (「滿 NT$999 免運」); "" when a param is missing. */
  sentence: string;
  source: OnboardingSource;
  note: string;
}

export interface PolicyParamSpec {
  name: string;
  label: string;
  kind: "money" | "text" | "number" | "percent";
  optional?: boolean;
}

export interface PolicyType {
  key: string;
  group: string;
  label: string;
  params: PolicyParamSpec[];
  offer_key: OfferKey;
  offer_label: string;
  /** Shown by default; the rest sit behind 「更多政策」. */
  common: boolean;
  threshold: string | null;
  template: string;
  template_bare?: string;
}

export interface OnboardingEvidence {
  proof: ProofItem[];
  proof_kinds: { key: ProofKind; label: string }[];
  policies: PolicyItem[];
  policy_types: PolicyType[];
  /** 7 天猶豫期 (消保法 §19): applies unless the brand sells a statutory exception. */
  cooling_off: { applies: boolean; disclosure: string; conditions?: string; source_note?: string };
  /** Policy-owner text limits; absent on older servers. */
  cooling_off_limits?: { conditions: number; source_note: number };
  forbidden: { id: string | null; text: string }[];
  /** e.g. 「台灣食品（食安法）」; "" when the brand has no regime. */
  regime_label: string;
}

export interface OnboardingEvidenceInput {
  proof: { id?: string | null; fact_key: ProofKind; text: string }[];
  policies: { key: string; params: Record<string, PolicyParamValue>; sentence?: string }[];
  /** Omitted merchant fields preserve saved text; empty strings clear individual fields. */
  cooling_off: { applies: boolean; disclosure?: string; conditions?: string; source_note?: string };
  forbidden: string[];
}

// ---- 5 素材 ----

export type MediaCapability = "photo" | "photo_video";

export interface OnboardingMedia {
  /** null = never asked. */
  media: MediaCapability | null;
}

// ---- 6 接工具 ----

export type ConnectorState = "connected" | "available" | "seat";

export interface Connector {
  key: string;
  group: string;
  label: string;
  icon: string;
  /** 「接上後系統能讀：…」 */
  reads: string;
  state: ConnectorState;
  /** 「已接上：〈帳戶名〉」 when connected, 「即將開放」 for a seat. */
  note: string;
  /** In-app path for a live connector with its own page (csv → the orders import). */
  link: string | null;
}

export interface OnboardingTools {
  connectors: Connector[];
  conversion_goal: string | null;
  conversion_goal_options: { key: string; label: string }[];
}

// ---- transport ----

interface Envelope<T> {
  data: T;
  generated_at: string;
}

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  const body = await readJson<Envelope<T>>(res, `處理失敗（狀態碼 ${res.status}）`);
  return body.data;
}

function json(method: "PUT" | "POST", body: unknown): RequestInit {
  return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

const base = (brandId: string) => `/api/intake/brands/${encodeURIComponent(brandId)}/onboarding`;

export const fetchOnboardingStatus = (brandId: string): Promise<OnboardingStatus> =>
  send(base(brandId));

export const completeOnboarding = (brandId: string): Promise<OnboardingStatus> =>
  send(`${base(brandId)}/complete`, json("POST", {}));

export const fetchOnboardingScan = (brandId: string): Promise<OnboardingScan> =>
  send(`${base(brandId)}/scan`);

/** Starts the scan once (no-op while running or after a read); returns the status. 409 = the
 * AI cost cap refused, 400 = nothing to read / onboarding already completed. */
export const startOnboardingScan = (brandId: string): Promise<OnboardingScan> =>
  send(`${base(brandId)}/scan`, json("POST", {}));

/** 「自訂」: one sentence (≤200 chars) → one proposal; nothing is saved. 422 carries
 * 「AI 整理不出來，換個說法再試一次」. */
export const proposeCustom = (brandId: string, block: CustomBlock, text: string): Promise<CustomProposal> =>
  send(`${base(brandId)}/custom`, json("POST", { block, text }));

export const fetchOnboardingBasics =(brandId: string): Promise<OnboardingBasics> =>
  send(`${base(brandId)}/basics`);

export const saveOnboardingBasics = (brandId: string, input: OnboardingBasicsInput): Promise<OnboardingBasics> =>
  send(`${base(brandId)}/basics`, json("PUT", input));

export const fetchOnboardingIdentity = (brandId: string): Promise<OnboardingIdentity> =>
  send(`${base(brandId)}/identity`);

export const saveOnboardingIdentity = (brandId: string, input: OnboardingIdentityInput): Promise<OnboardingIdentity> =>
  send(`${base(brandId)}/identity`, json("PUT", input));

export const fetchOnboardingEvidence = (brandId: string): Promise<OnboardingEvidence> =>
  send(`${base(brandId)}/evidence`);

export const saveOnboardingEvidence = (brandId: string, input: OnboardingEvidenceInput): Promise<OnboardingEvidence> =>
  send(`${base(brandId)}/evidence`, json("PUT", input));

export const fetchOnboardingMedia = (brandId: string): Promise<OnboardingMedia> =>
  send(`${base(brandId)}/media`);

export const saveOnboardingMedia = (brandId: string, media: MediaCapability): Promise<OnboardingMedia> =>
  send(`${base(brandId)}/media`, json("PUT", { media }));

export const fetchOnboardingTools = (brandId: string): Promise<OnboardingTools> =>
  send(`${base(brandId)}/tools`);
