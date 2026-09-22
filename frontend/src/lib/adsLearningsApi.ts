/** frontend/src/lib/adsLearningsApi.ts — Contract D (F27): the brand's ads-track learning
 * ledger, written when a `pause` change item carrying an `angle` is confirmed. See
 * `app/ads/ads_learnings.py`. */
import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";
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
  const data = await parseJsonOrThrow<{ learnings: AdsLearning[] }>(res, "讀取品牌學習紀錄失敗。");
  return data.learnings;
}
