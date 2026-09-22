/** frontend/src/lib/adsLearningsApi.ts — Contract D (F27): the brand's ads-track learning
 * ledger, written when a `pause` change item carrying an `angle` is confirmed. See
 * `app/ads/ads_learnings.py`. */
import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";

export interface AdsLearning {
  id: string;
  text: string;
  confidence: "observed" | "likely" | "validated";
  count: number;
  campaign_id: string | null;
  campaign_name: string | null;
  learned_at: string;
}

export async function getAdsLearnings(brandId: string, signal?: AbortSignal): Promise<AdsLearning[]> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/learnings`, { signal });
  const data = await parseJsonOrThrow<{ learnings: AdsLearning[] }>(res, "讀取品牌學習紀錄失敗。");
  return data.learnings;
}
