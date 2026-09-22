/** frontend/src/lib/adsMonthApi.ts — F27-I07 Contract G: the monthly review summary and
 * suggestion dismissal. Mirrors `app/ads/month_summary.py`/`app/ads/month_summary_routes.py`
 * exactly — the GET response is flat (no outer wrapper key), same shape as
 * `adsChangeApi.ts::getChangeControl`. Same fetch helper/error style as the other `ads*Api.ts`
 * files (each keeps its own small copy, existing convention — see `adsChangeApi.ts`). */
import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";
import type { CampaignObjectiveFamily } from "./adsTriageApi";

export type MonthVerdict = "met" | "missed" | "unjudged";

// `campaign_objective` (F27-I27): the SAME family `app/ads/repository.py::campaign_objective_family`
// already serves campaign cards/triage items with (F27-I09, `CampaignObjectiveFamily` from
// `adsTriageApi.ts`, same reuse precedent as `adsApi.ts::CampaignCard`) — reused here so
// `CampaignChip` never has to be driven by a second, frontend-side guess off the raw `objective`
// string. Optional/nullable only for defensiveness against an older cached response shape; the
// backend always sets it.
export interface MonthCampaignRow {
  campaign_id: string; name: string; objective: string;
  campaign_objective?: CampaignObjectiveFamily | null;
  spend: number | null; result_count: number | null; result_label: string;
  cost_per_result: number | null; target: number | null; verdict: MonthVerdict;
}
export interface MonthOrders {
  this_net: number | null; this_count: number; previous_net: number | null;
  previous_count: number; change_pct: number | null;
}
export type SuggestionKind = "refresh" | "cleanup" | "no_target";
export interface MonthSuggestion {
  key: string; kind: SuggestionKind; campaign_id: string; campaign_name: string;
  objective: string; campaign_objective?: CampaignObjectiveFamily | null;
  title: string; why: string; action_url: string | null;
}
export interface MonthSummary {
  month: string; currency: string | null; total_spend: number | null;
  campaigns: MonthCampaignRow[];
  orders: MonthOrders | null;
  closed_this_month: number | null; closed_tracking_since: string;
  suggestions: MonthSuggestion[];
  days_covered: number; days_elapsed: number;
}

const brandPath = (brand: string) => `${BASE}/brands/${encodeURIComponent(brand)}`;

export class MonthRequestRejected extends Error {}

async function json<T>(path: string, method: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  try {
    const response = await apiFetch(path, { method, signal, ...(body === undefined ? {} : {
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }) });
    try {
      return await parseJsonOrThrow(response, "目前無法完成，請稍後重試。");
    } catch (error) {
      if (response.status >= 400 && response.status < 500) {
        throw new MonthRequestRejected(error instanceof Error ? error.message : "請修正後再試。");
      }
      throw error;
    }
  } catch (error) {
    if (error instanceof TypeError) throw new Error("未收到伺服器回應，請重試。");
    throw error;
  }
}

export function getMonthSummary(brand: string, month: string, signal?: AbortSignal) {
  return json<MonthSummary>(
    `${brandPath(brand)}/month-summary?month=${encodeURIComponent(month)}`, "GET", undefined, signal,
  );
}

export function dismissSuggestion(brand: string, month: string, key: string, signal?: AbortSignal) {
  return json<{ ok: boolean }>(
    `${brandPath(brand)}/month-summary/suggestions/${encodeURIComponent(key)}/dismiss`
      + `?month=${encodeURIComponent(month)}`,
    "POST", {}, signal,
  );
}
