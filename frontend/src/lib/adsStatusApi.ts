/** frontend/src/lib/adsStatusApi.ts — F27-I09 Contract I: the brand-wide sync/queue status
 * summary. Mirrors `app/ads/status_summary.py::get_status_summary` exactly — a read shape, not
 * re-worded. Same `BASE`/`parseJsonOrThrow` helpers `adsApi.ts` already exports, same import
 * style `adsTriageApi.ts` already uses for them. */
import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";

/** `last_success_at`: the newest moment among this brand's own non-closed campaigns that are
 * currently syncing cleanly (`state === "ok"`), `null` when none are. `failing_campaigns`: how
 * many of those campaigns are NOT in that clean state right now (never/disconnected/auth_expired/
 * failed/syncing all count). `open_items`: how many open `ads_triage_*` queue rows (the six kinds
 * `app/ads/triage.py::QUEUE_CATEGORY` registers) are waiting on a decision. */
export interface AdsStatusSummary {
  last_success_at: string | null;
  failing_campaigns: number;
  open_items: number;
}

export async function getStatusSummary(brandId: string, signal?: AbortSignal): Promise<AdsStatusSummary> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/status-summary`, { signal },
  );
  return parseJsonOrThrow<AdsStatusSummary>(res, "讀取同步狀態摘要失敗。");
}
