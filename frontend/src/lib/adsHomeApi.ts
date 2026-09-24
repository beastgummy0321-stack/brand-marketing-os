/** frontend/src/lib/adsHomeApi.ts — F28-I06 "Home overview": the month-level numbers of the
 * ads-centre home (board D). Mirrors `app/ads/home_overview.py` exactly; the GET response is flat.
 *
 * Rules the screen can rely on (never re-derive them here):
 * - `spent` is the one spend figure for the whole screen; `quality.buckets` add up to it exactly
 *   (spend on a closed ad, or on any ad triage did not grade, is in `ungraded`).
 * - `null` means unknown — never read it as 0. `spent` is null when nothing is synced yet, a day's
 *   spend is unknown, or the rows mix currencies. A block that failed to read is `null` as a whole.
 * - `money` covers purchase campaigns only; the rest are listed in `money.excluded`. `earn` is null
 *   whenever an input is missing, and `earn_missing` says which (`product`, `product_cost`,
 *   `spend`, `purchases`, `no_purchase_campaign`).
 * - The month's data stops at yesterday (org timezone): `pace.daily` ends yesterday, and
 *   `previous_same_period.days` is that many days at the start of the previous month. */
import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow, type CampaignStatus, type CampaignSyncState } from "./adsApi";
import type { CapBasis, TriageGrade } from "./adsTriageApi";

export interface HomeCap { value: number; basis: CapBasis | null }

export type HomeEarnMissing =
  | "product" | "product_cost" | "spend" | "purchases" | "no_purchase_campaign";

export interface HomeExcludedCampaign {
  campaign_id: string; name: string; reason: "not_purchase" | "result_kind_unknown";
}

export interface HomePreviousSamePeriod {
  days: number; purchases: number | null; cost_per_purchase: number | null;
}

export interface HomeMoney {
  purchases: number | null;
  cost_per_purchase: number | null;
  /** The one cap every included purchase campaign shares; null when they differ or none has one. */
  cap: HomeCap | null;
  earn: number | null;
  earn_missing: HomeEarnMissing[];
  excluded: HomeExcludedCampaign[];
  previous_same_period: HomePreviousSamePeriod | null;
}

export interface HomePace {
  budget_amount: number | null;
  available: number | null;
  daily: { day: string; cumulative: number | null }[];
  projected_month_end: number | null;
}

export type HomeBucketGrade = TriageGrade | "ungraded";

export interface HomeBucketAd {
  entity_id: string; name: string | null; thumbnail_url: string | null; spend: number;
}

export interface HomeBucket {
  grade: HomeBucketGrade;
  amount: number;
  /** Every ad with spend in this bucket; `ads` lists at most 12, highest spend first. */
  count: number;
  ads: HomeBucketAd[];
}

export interface HomeQuality { buckets: HomeBucket[] }

export type HomeTimelineKind = "today" | "month_review" | "campaign_start" | "campaign_end";

export interface HomeTimelineItem {
  date: string; kind: HomeTimelineKind;
  campaign_id: string | null; name: string | null;
  /** Only on `campaign_start`. */
  ready: boolean | null;
}

export interface HomeDraft {
  start_date: string | null; cap_missing: boolean; ads_total: number; ads_ready: number;
  approved: boolean;
}

export interface HomeCampaign {
  campaign_id: string; name: string; origin: "internal" | "imported"; status: CampaignStatus;
  month_spend: number | null;
  purchases: number | null;
  cost_per_purchase: number | null;
  cap: HomeCap | null;
  active_ads: number;
  daily_budget: number | null;
  missing_days: string[];
  sync_state: CampaignSyncState["state"];
  draft: HomeDraft | null;
}

export interface HomeSync { last_success_at: string | null; next_at: string | null }

export interface HomeOverview {
  month: string;
  day_of_month: number;
  days_in_month: number;
  currency: string | null;
  spent: number | null;
  money: HomeMoney | null;
  pace: HomePace | null;
  quality: HomeQuality | null;
  timeline: HomeTimelineItem[] | null;
  campaigns: HomeCampaign[] | null;
  sync: HomeSync | null;
}

/** `month` (YYYY-MM) is optional: the backend defaults to the org timezone's current month. */
export async function getHomeOverview(
  brand: string, month?: string, signal?: AbortSignal,
): Promise<HomeOverview> {
  const query = month ? `?month=${encodeURIComponent(month)}` : "";
  try {
    const response = await apiFetch(
      `${BASE}/brands/${encodeURIComponent(brand)}/home${query}`, { signal },
    );
    return await parseJsonOrThrow<HomeOverview>(response, "讀取投放中心首頁失敗。");
  } catch (error) {
    if (error instanceof TypeError) throw new Error("未收到伺服器回應，請重試。");
    throw error;
  }
}
