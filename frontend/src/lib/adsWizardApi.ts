/** frontend/src/lib/adsWizardApi.ts — F30-I04: the new-campaign wizard's reads and its
 * structured create (Feature F30 Contracts B, C, D). Mirrors `app/ads/wizard_options.py`,
 * `app/ads/objectives.py` and the structured branch of `POST …/campaigns` exactly.
 *
 * Rules the screen can rely on (never re-derive them here):
 * - `products` are the sellable items, active only, in name order. A product with sell ways is
 *   listed as its sell ways; `price`/`currency` are null when there is no current economics row
 *   (never a stale price). `has_cost` = the current unit variable cost is set.
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
import { BASE, parseJsonOrThrow, type CampaignDetail, type CampaignDraft } from "./adsApi";

export interface WizardProduct {
  id: string;
  name: string;
  price: number | null;
  currency: string | null;
  thumbnail_url: string | null;
  has_cost: boolean;
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
}

export interface CampaignPicks {
  /** Exactly one id, taken from `WizardOptions.products` (anything else is `product_unknown`). */
  product_ids: [string];
  objective: string;
  /** ISO dates; send both or neither. */
  start_date?: string;
  end_date?: string;
  /** This campaign's spending cap, > 0. */
  budget: number;
  goal_text?: string;
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

/** The wizard's 受眾方向 correction (`PATCH` `audience_hint`); an empty string clears it. */
export async function patchAudienceHint(
  brandId: string,
  campaignId: string,
  audienceHint: string | null,
): Promise<CampaignDetail> {
  const res = await apiFetch(`${brandPath(brandId)}/campaigns/${encodeURIComponent(campaignId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audience_hint: audienceHint }),
  });
  const data = await parseJsonOrThrow<{ campaign: CampaignDetail }>(res, "更新受眾方向失敗。");
  return data.campaign;
}
