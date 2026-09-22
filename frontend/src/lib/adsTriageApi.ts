/** frontend/src/lib/adsTriageApi.ts — F19-I01: typed entry for the v7 ads-centre home's brand
 * decision queue, per-ad program triage, and campaign target sub-resource. Mirrors
 * `app/ads/triage.py`/`app/ads/triage_routes.py` and the `target` routes in `app/ads/routes.py`
 * exactly — types are read shapes, not re-worded (labels come from the backend `label` field).
 * Same fetch helper and error style as `frontend/src/lib/adsChangeApi.ts`. */
import { apiFetch } from "./http";
import { BASE } from "./adsApi";
import type { CampaignSyncState } from "./adsApi";
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
/** F24-I01: the read-only `data` enrichment of `CampaignTriage` (`app/ads/triage.py::_data_view`)
 * — `sync` is the same `CampaignSyncState` shape `CampaignCard.data.sync` carries (`adsApi.ts`).
 * `coverage` is this campaign's own recorded sync coverage, `null` when never synced.
 * `missing_days` are the days of the SAME window `classify()` judges every ad with (`window_days`
 * back from the account cutoff) that fall outside `coverage` — always `[]` when `coverage` is
 * `null` (that case reads through `sync.state === "never"`, not a wall of missing dates). */
export interface TriageData {
  sync: CampaignSyncState;
  coverage: { start: string; end: string } | null;
  missing_days: string[];
}
// F24-I01: `data` is optional here for the same `do_not_touch`-vs-`touch` scope conflict noted on
// `adsApi.ts::CampaignCard.data` -- existing hand-written `*.test.tsx` fixtures can't be reached
// to add it. Real responses always carry it (`triage.py::_data_view`).
/** F26-I01: one closed ad's own last-window numbers, per `app/ads/triage.py::_closed_item` --
 * `spend`/`cost_per_result` are `null` when this ad has no rows inside that window (never a
 * second, different-shaped query from `TriageMetricsView`). */
export interface TriageClosedItem {
  entity_id: string; name: string | null; native_status: string | null;
  thumbnail_url: string | null; spend: number | null; cost_per_result: number | null;
  result_label: string;
}
/** F26-I01: `classify()`'s own `closed` block (feature Decisions "I01") -- every ad of this
 * campaign whose `native_status` reads closed, kept and reported, never judged (`items` never
 * appears in `CampaignTriage.items` above). `paused`/`archived` are the two statuses the frontend
 * groups the strip by; every other closed status (`DELETED`/`ADSET_PAUSED`/`CAMPAIGN_PAUSED`)
 * falls into `other`, so `paused + archived + other === total` always. `items` is capped at 50,
 * in the same (name, id) order the campaign's own ad query returns; `truncated` says whether
 * there's more than that cap. Real responses always carry this (`triage.py::classify`), same
 * reason it's required here unlike `data` above. */
export interface TriageClosedBlock {
  paused: number; archived: number; other: number; total: number;
  items: TriageClosedItem[]; truncated: boolean;
}
export interface CampaignTriage {
  window_days: number; items: TriageItem[]; closed: TriageClosedBlock; data?: TriageData;
}

/** F22-I01: the change set (if any) that currently answers a `stop_loss` row, per
 * `app/ads/triage.py::_row_proposal` (feature Decisions "Queue row state") — `null` when there
 * is none, or the matching set doesn't currently "count" (deferred past `revisit_at`, rejected
 * outside the row's current window, or confirmed while the entity has left `native_status`
 * paused). `kind` is always `"pause"` (`_matching_pause_set` only ever matches a `pause` item). */
export interface QueuePauseProposal {
  kind: "pause";
  change_set_id: string; campaign_id: string;
  status: "draft" | "approved" | "rejected" | "deferred";
  verification_state: "pending" | "reported" | "confirmed" | "deviated" | "unknown" | "stale";
  reason: string | null; revisit_at: string | null; multi: boolean;
}

/** F25-I01: the change set (if any) that currently answers a `scale_budget` row, per
 * `app/ads/triage.py::_row_scale_proposal` — same shape as `QueuePauseProposal`, `kind` always
 * `"budget"` (`_matching_change_item` generalised by kind, feature Decisions "Queue payload"). */
export interface QueueBudgetProposal {
  kind: "budget";
  change_set_id: string; campaign_id: string;
  status: "draft" | "approved" | "rejected" | "deferred";
  verification_state: "pending" | "reported" | "confirmed" | "deviated" | "unknown" | "stale";
  reason: string | null; revisit_at: string | null; multi: boolean;
}

/** F23-I01: the review round (if any) that currently answers a `worse` row, per
 * `app/ads/triage.py::_row_review_proposal` (feature Decisions "Queue row state") — `null` when
 * there is no round whose `window_end` falls inside the row's current triage window. `status` is
 * the round's own workflow status; the matching copy change set's own status is the separate
 * `change_set_status` field (never `status` — a `worse` row's round and its optional copy change
 * set carry two different, independently-evolving statuses). `change_set_id`,
 * `change_set_status`, and `verification_state` are all `null` together when no copy change set
 * matches this round yet. */
export interface QueueReviewProposal {
  kind: "review";
  review_id: string;
  status: "waiting" | "queued" | "running" | "ready" | "completed" | "deferred" | "unjudgeable"
    | "failed" | "unknown";
  decision: "completed" | "deferred" | "unjudgeable" | null;
  reason: string | null; revisit_at: string | null;
  recommendation_id: string | null;
  change_set_id: string | null;
  change_set_status: "draft" | "approved" | "rejected" | "deferred" | null;
  verification_state: "pending" | "reported" | "confirmed" | "deviated" | "unknown" | "stale" | null;
  multi: boolean;
}

export type QueueProposal = QueuePauseProposal | QueueReviewProposal | QueueBudgetProposal;

// F26-I02: `QueueKind`/`QueueItem.kind_key` now carry the real backend's fifth kind
// (`app/ads/triage.py`'s `insufficient_data`) -- F26-I01 left this at four values on purpose
// (see the removed comment here) since its own touch didn't cover `home/QueueRow.tsx`'s
// exhaustive `Record<QueueKind, ...>` switches; this issue's touch does, so both widen together.
export type QueueKind = "stop_loss" | "worse" | "scale_budget" | "refresh_creative" | "insufficient_data";

/** F25-I01: the budget owner a `scale_budget` row proposes to raise -- an adset, or the campaign
 * when the campaign holds the budget (`app/ads/triage_scale.py::scale_candidates`). `ads_count`
 * is the owner's whole ad group, paused ads included (a budget change affects every ad sitting
 * under this owner). */
export interface QueueScaleOwner {
  id: string; name: string | null; native_kind: string; native_id: string;
  ads_count: number; currency: string | null;
}
/** F25-I01: the `scale_budget` row's own payload (feature Decisions "Queue payload") --
 * `cost_per_result`/`previous_cost_per_result`/`window_days` are the row's own `triage` (best)
 * ad's numbers, never pooled across the owner's other ads. */
export interface QueueScale {
  owner: QueueScaleOwner; from: number; to: number;
  cost_per_result: number | null; previous_cost_per_result: number | null;
  target: TriageTargetView; window_days: number;
  month: { available: number | null; extra_needed: number };
}
/** F25-I01: the `refresh_creative` row's own payload -- `thumbnails` is at most 4 entries (never
 * padded to 4; the frontend adds hollow tiles for the remainder), each `null` when that ad has
 * none (`app/ads/triage_scale.py::refresh_candidates`). */
export interface QueueRefresh {
  campaign_id: string; campaign_name: string;
  readable_count: number; classified_count: number;
  thumbnails: (string | null)[];
}
/** F26-I01: the `insufficient_data` row's own payload -- `missing_days`/`coverage` are the SAME
 * window `classify()` judges every ad of this campaign with (`app/ads/triage.py::_data_view`),
 * `sync_state` the campaign's own `data.sync.state` (`app/ads/repository.py::campaign_sync_state`
 * — never re-derived, always one of the values that field can read). */
export interface QueueInsufficient {
  campaign_id: string; campaign_name: string; missing_days: string[];
  sync_state: CampaignSyncState["state"];
  coverage: { start: string; end: string } | null;
}

/** One open row of the brand decision queue (`interrupt` table columns actually returned) plus
 * `triage`: the current triage item that produced it, matched by the same dedupe key the
 * enqueue used. A row whose kind has since stopped qualifying (e.g. an ad moved off
 * `stop_loss`/`worse`, or an owner's ads are no longer all stable) is filtered out of the payload
 * rather than listed without a match, so `triage` is always present here. `scale`/`refresh`/
 * `insufficient` are present only on their own `kind_key` (F25-I01/F26-I01, feature Decisions
 * "Queue payload"). */
export interface QueueItem {
  id: string; org_id: string; brand_id: string | null; campaign_period_id: string | null;
  dedupe_key: string; category: string; kind: string | null; severity: AlertSeverity;
  message: string; action_url: string | null; visible_from: string | null;
  status: string; created_at: string; resolved_at: string | null;
  kind_key: QueueKind;
  triage: TriageItem; proposal: QueueProposal | null;
  scale?: QueueScale; refresh?: QueueRefresh; insufficient?: QueueInsufficient;
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
