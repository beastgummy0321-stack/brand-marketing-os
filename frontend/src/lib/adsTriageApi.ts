/** frontend/src/lib/adsTriageApi.ts — F19-I01: typed entry for the v7 ads-centre home's brand
 * decision queue, per-ad program triage, and campaign target sub-resource. Mirrors
 * `app/ads/triage.py`/`app/ads/triage_routes.py` and the `target` routes in `app/ads/routes.py`
 * exactly — types are read shapes, not re-worded (labels come from the backend `label` field).
 * Same fetch helper and error style as `frontend/src/lib/adsChangeApi.ts`. */
import { apiFetch } from "./http";
import { BASE } from "./adsApi";
import type { AlertSeverity } from "./api";

export type TriageClass = "stop_loss" | "worse" | "better" | "flat" | "insufficient" | "no_target";

/** F19-I06: the shared Chinese vocabulary for `result_kind` (`app/ads/result_kinds.py`) — never
 * re-worded here, `label` always comes from the backend. */
export interface ResultKindOption { kind: string; label: string }

export interface TriageWindow {
  start: string; end: string; days: number;
  previous_start: string; previous_end: string;
  extended_from: number | null;
}
export interface TriageTargetView {
  value: number | null; basis: "own" | "break_even" | "trailing_30" | null;
  result_kind: string | null;
  // F19-I06: always sent by the backend (`app/ads/result_kinds.py::label()`).
  result_label: string;
  missing: string[];
}
export interface TriageMetricsView {
  spend: number | null; result_count: number | null; cost_per_result: number | null;
  result_kind: string | null;
  result_label: string; // F19-I06: see `TriageTargetView.result_label`.
  derived_zero_days: number; reason: string | null;
}
export interface TriageSampleView {
  gate: boolean; spend_multiple: number | null; days_with_events: number;
}
export interface TriageItem {
  entity_id: string; native_id: string; name: string | null; campaign_id: string;
  // F19-I07: the campaign's own name; always sent (`app/ads/triage.py::classify`).
  campaign_name: string;
  // F20-I01: thumbnail first, else full image, else `null` (`app/ads/triage.py::_thumbnail_url`).
  thumbnail_url: string | null;
  class: TriageClass; label: string; reason_code: string;
  window: TriageWindow; target: TriageTargetView;
  current: TriageMetricsView; previous: TriageMetricsView;
  change_pct: number | null; sample: TriageSampleView;
}
export interface CampaignTriage { window_days: number; items: TriageItem[] }

/** F22-I01: the change set (if any) that currently answers a `stop_loss` row, per
 * `app/ads/triage.py::_row_proposal` (feature Decisions "Queue row state") — `null` when there
 * is none, or the matching set doesn't currently "count" (deferred past `revisit_at`, rejected
 * outside the row's current window, or confirmed while the entity has left `native_status`
 * paused). Always `null` on a `worse` row this batch.
 *
 * F23-I01 backend note: `app/ads/triage.py::_row_review_proposal` now gives `worse` rows their
 * own `{kind:"review", ...}` proposal shape too (see that function's docstring for the exact
 * fields) — NOT yet reflected in this type. Turning `QueueProposal` into a `kind`-discriminated
 * union breaks two do_not_touch files with real evidence (`cd frontend && npm run build`):
 * `home/status.ts:53,60,62` (its existing switch assumes `proposal.status` is exactly
 * `"draft"|"approved"|"rejected"|"deferred"` and calls `changePath(..., proposal.change_set_id,
 * ...)` assuming `string`, not `string | null`; any field named `status` shared with a review
 * variant either breaks that switch's exhaustiveness (`TS2366`) or, if renamed, removes the
 * property from the union so `status.ts` can no longer read it at all (`TS2339`)) and
 * `home/DecisionQueue.test.tsx:45` (its `proposal()` fixture builds a plain object typed as the
 * union via `{...defaults, ...(overrides: Partial<QueueProposal>)}`, which no longer resolves to
 * a single member once `QueueProposal` is a union). Left as the single flat interface pending an
 * orchestrator decision (widen touch to co-edit those two files, or defer the FE type to the
 * issue that builds the review pages). */
export interface QueueProposal {
  change_set_id: string; campaign_id: string; kind: string;
  status: "draft" | "approved" | "rejected" | "deferred";
  verification_state: "pending" | "reported" | "confirmed" | "deviated" | "unknown" | "stale";
  reason: string | null; revisit_at: string | null; multi: boolean;
}

/** One open row of the brand decision queue (`interrupt` table columns actually returned) plus
 * `triage`: the current triage item that produced it, matched by the same dedupe key the
 * enqueue used. A row whose ad has moved off `stop_loss`/`worse` since it was raised is filtered
 * out of the payload rather than listed without a match, so `triage` is always present here. */
export interface QueueItem {
  id: string; org_id: string; brand_id: string | null; campaign_period_id: string | null;
  dedupe_key: string; category: string; kind: string | null; severity: AlertSeverity;
  message: string; action_url: string | null; visible_from: string | null;
  status: string; created_at: string; resolved_at: string | null;
  triage: TriageItem; proposal: QueueProposal | null;
}
export interface QueuePayload {
  items: QueueItem[]; counts: Record<TriageClass, number>; total_ads: number;
  kinds_available: string[]; kinds_pending: string[];
}

export interface CampaignTarget {
  campaign_id: string; product_ids: string[]; own_value: number | null; revision: number;
  value: number | null; basis: "own" | "break_even" | "trailing_30" | null;
  result_kind: string | null; result_label: string; result_kinds: ResultKindOption[];
  missing: string[];
}
export interface TargetRequest {
  result_kind?: string | null; basis?: "own" | "break_even" | "trailing_30" | null;
  value?: number | null; product_id?: string | null; price?: number | null;
  variable_cost?: number | null; expected_revision: number;
}

const brandPath = (brand: string) => `${BASE}/brands/${encodeURIComponent(brand)}`;
const campaignPath = (brand: string, campaign: string) =>
  `${brandPath(brand)}/campaigns/${encodeURIComponent(campaign)}`;

/** F19-I06: carries the error envelope's `code` (`app/shared/web.py::ApiError`, e.g.
 * `"target_conflict"`) so callers can branch on it instead of matching the Chinese message —
 * `code` is `null` when the response wasn't the standard `{"error":{...}}` shape at all. */
export class TriageRequestRejected extends Error {
  code: string | null;
  constructor(message: string, code: string | null = null) {
    super(message);
    this.code = code;
  }
}

async function json<T>(path: string, method: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await apiFetch(path, { method, signal, ...(body === undefined ? {} : {
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }) });
  } catch (error) {
    if (error instanceof TypeError) throw new Error("未收到伺服器回應，結果尚未確認。請重試。");
    throw error;
  }
  if (!response.ok) {
    let code: string | null = null;
    let message = "目前無法完成，請稍後重試。";
    try {
      const data = (await response.json()) as { error?: { code?: string; message?: string } };
      if (data.error?.code) code = data.error.code;
      if (data.error?.message) message = data.error.message;
    } catch {
      // 回應不是 JSON，用預設訊息，`code` 維持 `null`。
    }
    if (response.status >= 400 && response.status < 500) throw new TriageRequestRejected(message, code);
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export async function getQueue(brand: string, signal?: AbortSignal) {
  return (await json<{ queue: QueuePayload }>(`${brandPath(brand)}/queue`, "GET", undefined, signal)).queue;
}
export async function refreshQueue(brand: string, signal?: AbortSignal) {
  return (await json<{ queue: QueuePayload }>(`${brandPath(brand)}/queue/refresh`, "POST", {}, signal)).queue;
}
export async function getTriage(brand: string, campaign: string, signal?: AbortSignal) {
  return (await json<{ triage: CampaignTriage }>(`${campaignPath(brand, campaign)}/triage`, "GET", undefined, signal)).triage;
}
export async function getTarget(brand: string, campaign: string, signal?: AbortSignal) {
  return (await json<{ target: CampaignTarget }>(`${campaignPath(brand, campaign)}/target`, "GET", undefined, signal)).target;
}
export async function putTarget(brand: string, campaign: string, body: TargetRequest, signal?: AbortSignal) {
  return (await json<{ target: CampaignTarget }>(`${campaignPath(brand, campaign)}/target`, "PUT", body, signal)).target;
}
