/** frontend/src/lib/adsWizardApi.ts — F30-I04: the new-campaign wizard's reads and its
 * structured create (Feature F30 Contracts B, C, D). Mirrors `app/ads/wizard_options.py`,
 * `app/ads/objectives.py` and the structured branch of `POST …/campaigns` exactly.
 *
 * Rules the screen can rely on (never re-derive them here):
 * - `products` are the finished sell-ways (F43-I04, `wizard_options.options()`): single sell-ways
 *   grouped by knowledge product (name order), then bundles; a knowledge product itself or a
 *   建到一半 product's sell-way is never listed. `price`/`currency`/`break_even` are null when there
 *   is no current economics row (never a stale price). `has_cost` = the current unit variable
 *   cost is set. `cap_per_sale` is effective (the sell-way's own cap, else its break-even).
 *   `landing_url` is effective (the sell-way's own, else the first product's page).
 * - `default_objective` (F43-I18) = the brand's conversion goal as an objective key; null = no
 *   preselection.
 * - `thumbnail_url` is an authenticated same-origin file route (like the library's `file_url`):
 *   load it with `useAuthedImage`, not a bare `<img src>`. null = no product photo.
 * - `objectives` is one merged cross-platform list in display order. Only `available` ones can
 *   be picked; the others are reserved seats shown as 「尚未開放」. A platform label is null when
 *   that platform has no such objective.
 * - The create's `budget` is this campaign's spending cap (「這個活動最多花」), a number > 0.
 *   `goal_text` is optional (the server composes one from the picks). Without dates the server
 *   starts from the organisation's own today for 30 days. Errors: 400 `objective_unavailable`,
 *   `objective_unknown`, `budget_invalid`, `products_required`, `product_unknown`,
 *   `dates_required`, `end_before_start`. */
import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow, type CampaignDraft } from "./adsApi";
import type { CampaignCreateExtras } from "./adsCampaignTypes";

/** One customer group of a sell-way's knowledge products (`product_customer_group`). */
export interface WizardCustomerGroup {
  id: string;
  who: string;
}

/** One pickable sell-way (the name stays `WizardProduct`: a campaign's `product_ids` hold it). */
export interface WizardProduct {
  id: string;
  /** Full stored name (「〈商品〉 · 〈賣法〉」 for a single sell-way, the bundle's own name) -- the campaign name base. */
  name: string;
  /** The sell-way part of the name (a bundle: its name). */
  display_name: string;
  kind: "single" | "bundle";
  /** The first knowledge product (a bundle has several): the `#/new` section header of a single sell-way. */
  knowledge_product_id: string;
  knowledge_product_name: string;
  price: number | null;
  currency: string | null;
  thumbnail_url: string | null;
  has_cost: boolean;
  break_even: number | null;
  cap_per_sale: number | null;
  /** F45 (ads §6.49 「Picker」): the current economics fields derived from the sell-way's bases (e.g. `selling_price`,
   * `list_price`, `unit_variable_cost`); empty = all its own numbers. */
  derived_fields: string[];
  /** 「組合價」「免運」… each once; empty = no offer. */
  offer_labels: string[];
  customer_groups: WizardCustomerGroup[];
  landing_url: string | null;
}

/** Platform key (a channel key, e.g. `meta`, `google_ads`) -> that platform's own objective
 * name, or null when the platform has no such objective. */
export type ObjectivePlatforms = Record<string, string | null>;

export interface WizardObjective {
  /** The internal objective word stored on the campaign (e.g. 購買). */
  key: string;
  label: string;
  description: string;
  available: boolean;
  platforms: ObjectivePlatforms;
}

export interface WizardOptions {
  products: WizardProduct[];
  objectives: WizardObjective[];
  /** The brand's conversion goal as an objective key (purchase→購買, lead／booking→名單, awareness→知名度); null = unset. */
  default_objective: string | null;
}

/** F43-I04: the 「進階：這期不一樣」 overrides ride along (`CampaignCreateExtras`); a missing one comes from the brand
 * and the picked sell-way (`field_sources` `"sell_way"`), a sent one is the user's. */
export interface CampaignPicks extends CampaignCreateExtras {
  /** Exactly one id, taken from `WizardOptions.products` (anything else is `product_unknown`). */
  product_ids: [string];
  objective: string;
  /** ISO dates; send both or neither. */
  start_date?: string;
  end_date?: string;
  /** This campaign's spending cap, > 0. */
  budget: number;
  goal_text?: string;
  /** Some of the sell-way's `customer_groups` ids; omitted (or `[]`) = every group. */
  customer_group_ids?: string[];
}

const brandPath = (brandId: string) => `${BASE}/brands/${encodeURIComponent(brandId)}`;

export async function getWizardOptions(brandId: string): Promise<WizardOptions> {
  const res = await apiFetch(`${brandPath(brandId)}/new-campaign/options`);
  return parseJsonOrThrow<WizardOptions>(res, "讀取商品與目標失敗。");
}

export async function createCampaignFromPicks(
  brandId: string,
  picks: CampaignPicks,
): Promise<CampaignDraft> {
  const res = await apiFetch(`${brandPath(brandId)}/campaigns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(picks),
  });
  const data = await parseJsonOrThrow<{ campaign: CampaignDraft }>(res, "建立活動失敗。");
  return data.campaign;
}
