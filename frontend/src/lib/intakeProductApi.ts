/** Product onboarding API (F43-I05): the products page `#/plist`, the five product steps
 * `#/p1`–`#/p5`, the bundle page `#/bundle` and the `#/home` product block of
 * `.harness/scratch/prototype/f41-onboarding/index.html`. Shapes mirror
 * `app/intake/product_onboarding.py` field by field; types + fetchers only (no component logic).
 *
 * Every number and label (break-even, derived list price / cost, offer labels, 食安法 flags) is
 * computed by the server — re-read it after each save, never compute it on the page. PUT bodies
 * carry raw inputs only: an empty list price / cost / cap per sale means "derived / break-even".
 * `source` on a prefilled field: `"saved"` = confirmed, `"ai"` = the product-page read's proposal
 * (with `note`), `"none"` = nothing found. The product-page read (F43-I06) starts on its own when a
 * product is created with a page URL; `startProductScan` re-reads; `prefill_status` of the status
 * reports it. 「自訂」 (`proposeProductCustom`) returns a proposal only: the step's PUT saves it. A 400 / 404 carries a Chinese `error` message, thrown
 * here as an `Error`. Product photos are uploaded with the existing official-asset upload
 * (`uploadAsset` in `libraryApi.ts`, `asset_kind: "product_photo"`, `product_id`). */

import { apiFetch, errorMessageFromResponse } from "./http";
import type { OnboardingSource, PrefillStatus, ProofKind, SourcedText } from "./intakeOnboardingApi";

export type PainKey = "cost" | "effort" | "uncertainty" | "availability" | "experience" | "identity";
/** Which of the 進階 fold's reference values a number is (F05 「不知道 → 參考值」). */
export type AssumptionField = "cost" | "shipping" | "close_rate";

// ---- products page (`GET|POST …/products`) ----

export interface SellWayBrief {
  id: string;
  /** The sell-way part of 「〈商品〉 · 〈賣法〉」, e.g. 「三盒組」. */
  name: string;
  /** F45: base = one product's unit (a bundle may hold it), composed = base sell-ways × qty. Always sent by the
   * server; optional only so fixtures written before F45 still type-check. */
  shape?: "base" | "composed";
  price: number | null;
  /** null = cost unknown. */
  break_even: number | null;
  /** 「組合價 省 198」「滿 NT$999 免運」… in display order; [] = 沒有優惠. */
  offer_labels: string[];
}

export interface ProductCardData {
  id: string;
  name: string;
  thumbnail_url: string | null;
  state: "ready" | "draft";
  /** 1–5 while being built (5 = 賣法 saved, 完成 not pressed); null when ready. */
  step: number | null;
  /** 「2 群顧客・證據 2・說法 3」 or 「建到一半：還沒確認顧客」. */
  summary: string;
  sell_ways: SellWayBrief[];
}

/** A bundle card's component: a base sell-way × qty (F45). `sell_way_id` / `product_name` are always sent by the
 * server; optional only so fixtures written before F45 still type-check. */
export interface ComponentRef {
  sell_way_id?: string;
  /** The base sell-way's knowledge product. */
  product_id: string;
  product_name?: string;
  /** The base sell-way's own name (「單盒」). */
  name: string;
  qty: number;
}

export interface BundleCardData extends SellWayBrief {
  thumbnails: string[];
  /** draft = a component product is still being built. */
  state: "ready" | "draft";
  components: ComponentRef[];
}

export interface ProductSuggestion {
  /** A product the brand scan read that has not been created yet (「AI 讀到了，還沒確認」). */
  name: string;
  url: string | null;
}

export interface ProductsPage {
  products: ProductCardData[];
  bundles: BundleCardData[];
  suggestions: ProductSuggestion[];
}

export interface CreatedProduct {
  product_id: string;
  /** false = a product of that name already existed; its id is returned unchanged. */
  created: boolean;
}

// ---- status (`GET …/onboarding`) ----

export interface ProductOnboardingStatus {
  /** 1 商品是什麼 · 2 誰會買 · 3 證據與說法 · 4 賣法與價格 · 5 完成 (a finished product reads 5). */
  step: number;
  completed: boolean;
  /** The product-page read: none (never started) · running · done · failed. */
  prefill_status: PrefillStatus;
  /** Why it failed (the AI's own error, 「AI 有回覆，但格式讀不成…」, 「讀不到商品頁…」, or the AI
   * cost cap's message when the read was refused at creation); null unless failed. */
  prefill_error: string | null;
}

// ---- 自訂 (F43-I06): a proposal only; the step's PUT saves it ----

export type ProductCustomBlock = "difference" | "group" | "pain" | "product_proof" | "claim";

export type ProductCustomProposal =
  | { block: "difference"; kind: "value"; value: string }
  | {
      block: "group";
      kind: "option";
      /** Ready to append to `saveProductWho` as a group with `source: "custom"`. */
      option: { who: string; pain_keys: PainKey[]; quote: string; when_used: string };
    }
  | {
      block: "pain";
      kind: "option";
      /** A worry mapped to one of the six keys; `quote` fills 「顧客會怎麼說」. */
      option: { pain_key: PainKey; label: string; quote: string };
    }
  | { block: "product_proof"; kind: "option"; option: { fact_key: ProofKind; label: string; text: string } }
  | {
      block: "claim";
      kind: "option";
      /** A 食安法 hit (`statutory`) forces `verdict: "no"` (not editable). */
      option: { text: string; verdict: ClaimVerdict; statutory: { term: string; sentence: string } | null };
    };

// ---- 1 商品是什麼 ----

export interface ProductPhoto {
  id: string;
  url: string;
}

export interface ProductWhat {
  name: string;
  page_url: string;
  photos: ProductPhoto[];
  intro: SourcedText;
  mechanism: SourcedText;
  difference: SourcedText;
}

export interface ProductWhatInput {
  name: string;
  /** Also the default landing page of its sell-ways; "" = none. */
  page_url: string;
  intro: string;
  mechanism: string;
  difference: string;
  /** Product photos to keep; omit to keep all. */
  photo_ids?: string[];
}

// ---- 2 誰會買 ----

export interface CustomerGroup {
  id: string | null;
  who: string;
  /** 1–2 keys. */
  pain_keys: PainKey[];
  quote: string;
  when_used: string;
  source: OnboardingSource;
  note: string;
}

export interface ProductWho {
  /** ≤3. */
  groups: CustomerGroup[];
  pain_options: { key: PainKey; label: string }[];
}

export interface CustomerGroupInput {
  id?: string | null;
  who: string;
  pain_keys: PainKey[];
  quote?: string;
  when_used?: string;
  /** ai = an accepted proposal, custom = from 自訂, user = typed; saved = keep the row's. */
  source?: "ai" | "custom" | "user" | "saved";
}

// ---- 3 證據與說法 ----

export interface ProductProof {
  id: string | null;
  fact_key: ProofKind;
  text: string;
  source: OnboardingSource;
  note: string;
}

export type ClaimVerdict = "ok" | "no";

export interface ProductClaim {
  id: string | null;
  text: string;
  /** Where the sentence was found (「商品頁」「顧客評論」); "" for a saved one. */
  from_note: string;
  source: OnboardingSource;
  /** null = not chosen yet. Always "no" when `statutory` is set (not editable). */
  verdict: ClaimVerdict | null;
  /** 食安法 hit (brand regime), e.g. `{term: "增強免疫", sentence: "「增強免疫」屬改變生理功能（…）"}`. */
  statutory: { term: string; sentence: string } | null;
}

export interface ProductEvidence {
  proof: ProductProof[];
  proof_kinds: { key: ProofKind; label: string }[];
  claims: ProductClaim[];
}

export interface ProductEvidenceInput {
  /** Full list; an empty text is a blank slot and is dropped. */
  proof: { id?: string | null; fact_key: ProofKind; text: string }[];
  /** Full list; every non-statutory claim needs a verdict (400 「還有 N 句沒選…」). */
  claims: { id?: string | null; text: string; verdict: ClaimVerdict | null }[];
}

// ---- 4 賣法與價格 (and the bundle's money) ----

export interface SellWayMoney {
  price: number | null;
  list_price: number | null;
  /** true = not typed: Σ qty × each part's price (a base derives nothing). */
  list_price_derived: boolean;
  /** 「推算：單盒 180 × 12」; "" when typed. */
  list_price_note: string;
  cost: number | null;
  cost_derived: boolean;
  /** 「推算：單盒 50 × 12」; "" when typed. */
  cost_note: string;
  shipping: number | null;
  /** Only for lead/booking brands (`show_close_rate`). */
  close_rate?: number | null;
  /** (price − cost − shipping) × close rate; null = cost unknown. */
  break_even: number | null;
  /** The sell-way's own cap, else the break-even (`cap_is_default`). */
  cap_per_sale: number | null;
  cap_is_default: boolean;
  /** The sell-way's landing page, else its (first) product page (`landing_is_default`). */
  landing_url: string;
  landing_is_default: boolean;
  offer_labels: string[];
  /** Threshold policies this price does not reach: 「售價未滿 NT$999，不適用滿額免運」. */
  offer_notes: string[];
  /** Fields filled from a reference value (shown as 假設). */
  assumptions: AssumptionField[];
}

/** F45 (`docs/architecture/intake.md` 「base and composed sell-ways」): the money fields of a sell-way that is a
 * base (one product, no quantity) or composed (base sell-way × qty). A composed sell-way's empty price / list price
 * / cost is derived from its bases on the server and flagged `*_derived` (printed as 推算 everywhere). */
export interface SellWayNumbers extends SellWayMoney {
  /** true = a composed sell-way's empty price, Σ qty × each base's price. */
  price_derived: boolean;
  /** 「推算：單盒 180 × 5 ＋ 體驗包 100 × 2」; "" when typed. */
  price_note: string;
  /** Σ qty × each base's cost when every base cost is known (shown as 「照內容推算是 X」 beside a typed cost). */
  cost_estimate: number | null;
  /** Bases without a cost: the composed cost cannot be derived. */
  cost_missing: { sell_way_id: string; name: string }[];
  /** 「這個賣法免運」. */
  free_shipping: boolean;
  /** The break-even uses a derived price or cost (推算). */
  break_even_derived: boolean;
  /** This sell-way's own offer sentences: 「優惠價 NT$1,980（原價 NT$2,160）」, 「免運」 / 「這組免運」. */
  offer_sentences: string[];
}

/** One base inside a composed step-4 row, with that base's own effective numbers. */
export interface SellWayComponent {
  /** null on an unsaved proposal from the product page (it names its base). */
  sell_way_id: string | null;
  name: string;
  qty: number;
  price: number | null;
  cost: number | null;
}

export interface SellWayRow extends SellWayNumbers {
  /** null = an unsaved proposal from the product page. */
  id: string | null;
  name: string;
  /** base = the unit itself (no components); composed = base sell-ways × qty. */
  shape: "base" | "composed";
  /** [] for a base. */
  components: SellWayComponent[];
  /** A base: the names of the active composed sell-ways that use it (it cannot be deleted while used). */
  used_by: string[];
  source: OnboardingSource;
  note: string;
}

export interface BenchmarkValue {
  value: number;
  /** 「毛利率假設 45% · 美國 2025 基準，起點用 · 來源：…」 */
  source_text: string;
}

export interface Benchmarks {
  gross_margin: BenchmarkValue;
  shipping_cost: BenchmarkValue;
  /** Only for lead/booking brands. */
  close_rate?: BenchmarkValue;
}

export interface ProductSellWays {
  sell_ways: SellWayRow[];
  show_close_rate: boolean;
  /** Reference values of the 「不知道？用同業參考值」 fold. */
  assumptions: Benchmarks;
}

/** Raw inputs of one sell-way / bundle; omit or null = derived (list price, cost) / break-even
 * (cap) / product page (landing). */
export interface MoneyInput {
  price: number;
  list_price?: number | null;
  cost?: number | null;
  shipping?: number | null;
  close_rate?: number | null;
  cap_per_sale?: number | null;
  landing_url?: string | null;
  assumptions?: AssumptionField[];
}

/** One step-4 PUT row. No `components` = a base (price required); with `components` = composed (its empty price /
 * list price / cost are derived). Components name a base row of the same body; a `qty` key on the row is refused. */
export interface SellWayInput extends Omit<MoneyInput, "price"> {
  /** Omit for a new sell-way. A sell-way left out of the list is archived (refused while a kept composed one uses it). */
  id?: string | null;
  name: string;
  /** null only on a composed row (= derived). */
  price: number | null;
  components?: { base: string; qty: number }[];
  free_shipping?: boolean;
}

// ---- bundles (`#/bundle`) ----

/** One base sell-way × qty of a bundle, with that base's own effective numbers (「售價 180・成本 50」). */
export interface BundleComponent extends ComponentRef {
  sell_way_id: string;
  product_name: string;
  thumbnail_url: string | null;
  /** null when unknown. */
  unit_price: number | null;
  unit_cost: number | null;
}

/** A cross-product bundle: a composed sell-way whose bases belong to at least two products. Money fields as step 4
 * (`SellWayNumbers`: an empty price / list price / cost is derived from the bases, 推算). */
export interface Bundle extends SellWayNumbers {
  id: string;
  name: string;
  status: "active" | "archived";
  components: BundleComponent[];
  show_close_rate: boolean;
  benchmarks: Benchmarks;
  /** 「廣告會用到的」: reused from the component products, not copied. */
  reused: {
    groups: { product_id: string; product_name: string; who: string; pain_labels: string[] }[];
    proof: { product_id: string; product_name: string; fact_key: ProofKind; label: string; text: string }[];
  };
}

/** `POST …/bundles/preview`: a bundle not created yet, as `GET …/bundles/{id}` would show it. */
export type BundlePreview = Omit<Bundle, "id"> & { id: null };

export interface BundleInput extends Omit<MoneyInput, "price"> {
  name: string;
  /** Base sell-ways of finished products, from ≥2 different products (the server refuses fewer, 400). */
  components: { sell_way_id: string; qty: number }[];
  /** null = derived from the bases. */
  price: number | null;
  free_shipping: boolean;
}

// ---- transport ----

interface Envelope<T> {
  data: T;
  generated_at: string;
}

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) {
    const fallback = res.status === 404 ? "找不到這筆資料。" : `處理失敗（狀態碼 ${res.status}）`;
    throw new Error(await errorMessageFromResponse(res, fallback));
  }
  const body: Envelope<T> = await res.json();
  return body.data;
}

function json(method: "PUT" | "POST", body: unknown): RequestInit {
  return { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

const brandBase = (brandId: string) => `/api/intake/brands/${encodeURIComponent(brandId)}`;
const stepBase = (brandId: string, productId: string) =>
  `${brandBase(brandId)}/products/${encodeURIComponent(productId)}/onboarding`;

export const fetchProductsPage = (brandId: string): Promise<ProductsPage> =>
  send(`${brandBase(brandId)}/products`);

/** A new product at step 1 (with `page_url`, the product-page read can start). */
export const createProduct = (brandId: string, input: { name: string; page_url?: string }): Promise<CreatedProduct> =>
  send(`${brandBase(brandId)}/products`, json("POST", input));

export const fetchProductOnboarding = (brandId: string, productId: string): Promise<ProductOnboardingStatus> =>
  send(stepBase(brandId, productId));

/** Re-read the product page (no-op while a read runs) -> the status. 400: the product is finished
 * or has neither a page URL nor a photo; 409: the AI cost cap refused before any call. */
export const startProductScan = (brandId: string, productId: string): Promise<ProductOnboardingStatus> =>
  send(`${stepBase(brandId, productId)}/scan`, json("POST", {}));

/** 「自訂」: one sentence -> one proposal (nothing saved). 409 = AI cost cap, 422 = 「AI 整理不出來，
 * 換個說法再試一次」, 502 = the AI call failed. */
export const proposeProductCustom = (
  brandId: string,
  productId: string,
  block: ProductCustomBlock,
  text: string,
): Promise<ProductCustomProposal> => send(`${stepBase(brandId, productId)}/custom`, json("POST", { block, text }));

/** 400 while a step is not saved yet or the product has no sell-way; idempotent once done. */
export const completeProductOnboarding = (brandId: string, productId: string): Promise<ProductOnboardingStatus> =>
  send(`${stepBase(brandId, productId)}/complete`, json("POST", {}));

export const fetchProductWhat = (brandId: string, productId: string): Promise<ProductWhat> =>
  send(`${stepBase(brandId, productId)}/what`);

export const saveProductWhat = (brandId: string, productId: string, input: ProductWhatInput): Promise<ProductWhat> =>
  send(`${stepBase(brandId, productId)}/what`, json("PUT", input));

export const fetchProductWho = (brandId: string, productId: string): Promise<ProductWho> =>
  send(`${stepBase(brandId, productId)}/who`);

export const saveProductWho = (
  brandId: string,
  productId: string,
  groups: CustomerGroupInput[],
): Promise<ProductWho> => send(`${stepBase(brandId, productId)}/who`, json("PUT", { groups }));

export const fetchProductEvidence = (brandId: string, productId: string): Promise<ProductEvidence> =>
  send(`${stepBase(brandId, productId)}/evidence`);

export const saveProductEvidence = (
  brandId: string,
  productId: string,
  input: ProductEvidenceInput,
): Promise<ProductEvidence> => send(`${stepBase(brandId, productId)}/evidence`, json("PUT", input));

export const fetchProductSellWays = (brandId: string, productId: string): Promise<ProductSellWays> =>
  send(`${stepBase(brandId, productId)}/sell-ways`);

export const saveProductSellWays = (
  brandId: string,
  productId: string,
  sellWays: SellWayInput[],
): Promise<ProductSellWays> =>
  send(`${stepBase(brandId, productId)}/sell-ways`, json("PUT", { sell_ways: sellWays }));

export const createBundle = (brandId: string, input: BundleInput): Promise<Bundle> =>
  send(`${brandBase(brandId)}/bundles`, json("POST", input));

/** 新增組合's numbers before 「建立組合」: `createBundle`'s body, nothing written; 400 on the same refusals. */
export const previewBundle = (brandId: string, input: BundleInput): Promise<BundlePreview> =>
  send(`${brandBase(brandId)}/bundles/preview`, json("POST", input));

export const fetchBundle = (brandId: string, bundleId: string): Promise<Bundle> =>
  send(`${brandBase(brandId)}/bundles/${encodeURIComponent(bundleId)}`);

export const saveBundle = (brandId: string, bundleId: string, input: BundleInput): Promise<Bundle> =>
  send(`${brandBase(brandId)}/bundles/${encodeURIComponent(bundleId)}`, json("PUT", input));
