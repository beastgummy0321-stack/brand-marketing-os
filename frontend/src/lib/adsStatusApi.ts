/** frontend/src/lib/adsStatusApi.ts — F27-I09 Contract I: the brand-wide sync/queue status
 * summary. Mirrors `app/ads/status_summary.py::get_status_summary` exactly — a read shape, not
 * re-worded. Same `BASE`/`parseJsonOrThrow` helpers `adsApi.ts` already exports, same import
 * style `adsTriageApi.ts` already uses for them.
 *
 * F27-I10 Contract K: `getRecovery` mirrors `app/ads/recovery.py::get_recovery` the same way. */
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

/** One of the five recovery steps (always present, in order): `state` is `"done"` (past),
 * `"active"` (the one the brand is waiting on right now — the first not-done step), or `"todo"`
 * (not reached yet). `label` for the third step (`key === "resync"`) already carries its own
 * `N` (「補 N 小時的資料」); every label is server-rendered text, never built client-side. */
export interface AdsRecoveryStep {
  key: string;
  label: string;
  state: "done" | "active" | "todo";
}

/** `recovering`: true only while a gap (two of this brand's own consecutive `beat` events more
 * than 120 minutes apart) ended within the last 24 hours AND at least one step is not done.
 * `gap`/`steps` are `null`/`[]` whenever `recovering` is false (no banner to show). */
export interface AdsRecovery {
  recovering: boolean;
  gap: { start: string; end: string; minutes: number } | null;
  steps: AdsRecoveryStep[];
}

export async function getRecovery(brandId: string, signal?: AbortSignal): Promise<AdsRecovery> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/recovery`, { signal },
  );
  return parseJsonOrThrow<AdsRecovery>(res, "讀取系統恢復狀態失敗。");
}
