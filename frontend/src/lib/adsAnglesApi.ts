/** frontend/src/lib/adsAnglesApi.ts — Contract C (F27): per-ad AI angle candidates.
 * `GET .../entities/{entity_id}/angles` enqueues on the first call and returns the cached
 * result (keyed by entity + this ad's own copy hash) on later calls. See `app/ads/angles.py`. */
import { apiFetch, readJson } from "./http";
import { BASE } from "./adsApi";

export type AnglesStatus = "pending" | "ready" | "failed";

export interface AnglesResponse {
  status: AnglesStatus;
  candidates: string[];
  error: string | null;
}

export async function getAngles(
  brandId: string,
  campaignId: string,
  entityId: string,
): Promise<AnglesResponse> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}` +
      `/entities/${encodeURIComponent(entityId)}/angles`,
  );
  return readJson<AnglesResponse>(res, "讀取這則廣告的主打候選失敗。");
}
