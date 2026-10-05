/** frontend/src/lib/adsLearningsApi.ts — Contract D (F27): the brand's ads-track learning
 * ledger, written when a `pause` change item carrying an `angle` is confirmed. See
 * `app/ads/ads_learnings.py`.
 *
 * F46 Contract L: `getCoordinateLearnings` reads what the closed campaigns taught — every ad of a
 * closed internal campaign ranked by cost per sale with its 留下／換掉 verdict, written at closeout.
 * See `app/ads/learning_view.py`; numbers are the stored ones, never recomputed here. */
import { apiFetch, readJson } from "./http";
import { BASE } from "./adsApi";
import type { CampaignObjectiveFamily } from "./adsTriageApi";

export interface AdsLearning {
  id: string;
  text: string;
  confidence: "observed" | "likely" | "validated";
  count: number;
  campaign_id: string | null;
  campaign_name: string | null;
  // F27-I27: same family `app/ads/repository.py::campaign_objective_family` already serves
  // campaign cards/triage items/month-summary rows with — `null` only when the campaign itself
  // is unknown/deleted, never a frontend-side guess off a raw objective string. Optional for the
  // same reason `TriageItem.campaign_objective` is (`adsTriageApi.ts`): real responses always
  // carry it, existing hand-written test factories may not.
  campaign_objective?: CampaignObjectiveFamily | null;
  learned_at: string;
}

export async function getAdsLearnings(brandId: string, signal?: AbortSignal): Promise<AdsLearning[]> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/learnings`, { signal });
  const data = await readJson<{ learnings: AdsLearning[] }>(res, "讀取品牌學習紀錄失敗。");
  return data.learnings;
}

/** One coordinate of a ranked ad; dimensions the ad did not set are omitted by the server. */
export interface LearningCoordinate {
  dimension: string;
  dimension_label: string;
  key: string;
  label: string;
}

/** `keep` = cost per sale within the cap; `keep_relative` = none was within the cap, this one is the best or within
 * 30% of it; `replace` = everything else, 沒賣出 included. `verdict_label` is the word to print. */
export type LearningVerdict = "keep" | "keep_relative" | "replace";

export interface LearningRow {
  /** As served: sold rows by cost per sale, 沒賣出 last. Print it, never re-sort. */
  rank: number;
  of: number;
  ad_id: string;
  ad_name: string;
  /** `null` = the ad bound no customer group; a deleted group arrives with who 「已刪除的顧客群」. */
  customer_group: { id: string; who: string } | null;
  coordinates: LearningCoordinate[];
  spend: number | null;
  sales: number;
  /** `null` = 沒賣出 (no sale). */
  cost_per_sale: number | null;
  verdict: LearningVerdict;
  verdict_label: string;
  /** e.g. 「樣本少」, 「相對最好，仍高於上限」. */
  flags: string[];
  learning_id: string;
}

export interface LearningCampaign {
  campaign_id: string;
  campaign_name: string;
  sell_way_id: string | null;
  /** ISO dates (`YYYY-MM-DD`); `closed_on` is the org-local closing date. */
  start_date: string | null;
  end_date: string | null;
  closed_on: string | null;
  /** `null` = no cap was stored: print no cap line or chip. */
  cap: number | null;
  currency: string | null;
  /** Totals of the stored rows; `null` when the campaign has no rows. */
  spend: number | null;
  sales: number | null;
  cost_per_sale: number | null;
  counts: { keep: number; replace: number };
  rule_text: string;
  /** Set exactly when `rows` is empty: the sentence to print instead of a table. */
  empty_reason: string | null;
  rows: LearningRow[];
}

/** One customer group over the listed rows; `cap` = the newest listed campaign's with that group. */
export interface LearningGroup {
  customer_group_id: string;
  who: string;
  ads: number;
  spend: number;
  sales: number;
  cap: number | null;
  cost_per_sale: number | null;
}

export interface CoordinateLearnings {
  /** Closed internal campaigns, newest closed first. */
  campaigns: LearningCampaign[];
  /** Sorted by cost per sale, 沒賣出 last. */
  groups: LearningGroup[];
  /** `new_campaign_href` is an app path (`/brands/{b}/ads/new?sell_way=…`); `null` when nothing is closed. */
  next: { sell_way_id: string; new_campaign_href: string } | null;
}

export async function getCoordinateLearnings(
  brandId: string,
  filter: { campaignId?: string; sellWayId?: string } = {},
  signal?: AbortSignal,
): Promise<CoordinateLearnings> {
  const query = new URLSearchParams();
  if (filter.campaignId) query.set("campaign_id", filter.campaignId);
  if (filter.sellWayId) query.set("sell_way_id", filter.sellWayId);
  const qs = query.toString();
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/coordinate-learnings${qs ? `?${qs}` : ""}`,
    { signal },
  );
  return readJson<CoordinateLearnings>(res, "讀取投放學到的失敗。");
}
