/** frontend/src/lib/adsTriageApi.ts — F19-I01: typed entry for the v7 ads-centre home's brand
 * decision queue, per-ad program triage, and campaign target sub-resource. Shapes served by
 * `app/ads/triage.py`/`app/ads/triage_routes.py` and the `target` routes in `app/ads/routes.py`
 * exactly — types are read shapes, not re-worded (labels come from the backend `label` field).
 * Same fetch helper and error style as `frontend/src/lib/adsChangeApi.ts`. */
import { apiFetch } from "./http";
import { BASE } from "./adsApi";
import type { CampaignSyncState, DeliveryView } from "./adsApi";
import type { AlertSeverity } from "./api";
import type { PeriodGradeBucket } from "./adsMonthApi";

/** F27-I06 Contract F: per-campaign capacity, read-only from the ACTIVE ads' own daily-budget
 * owners (`app/ads/triage_capacity.py::capacity_view`, owner lookup shared with
 * `app/ads/triage_scale.py::owner_lookup`) -- `daily_budget`/`currency` are `null` when there are
 * no active ads, any active ad lacks a daily budget owner, or the qualifying owners don't share
 * one currency (never a partial sum across currencies). `can_support` is `null` unless both
 * `daily_budget` and `target` are known and `target > 0`. Shared by `CampaignTriage.data.capacity`
 * here and `CampaignCard.data.capacity` (`adsApi.ts`, imported back as a type only to keep that
 * file under the 800-line gate) -- same shape, never re-defined per caller. */
export interface CampaignCapacity {
  daily_budget: number | null; currency: string | null; target: number | null;
  can_support: number | null; active_ads: number;
}

/** F27-I09 Done #7: `CampaignChip`'s own family, derived read-time from either a system-built
 * campaign's Chinese objective label (`app/ads/repository.py::objective_family`) or an imported
 * campaign's own platform objective string (`app/ads/adapters.objective_family`) -- shared by
 * `TriageItem.campaign_objective` here and `CampaignCard.campaign_objective` (`adsApi.ts`,
 * imported back as a type only to keep that file under the 800-line gate). */
export type CampaignObjectiveFamily = "sales" | "engagement" | "traffic" | "other";

export type TriageClass = "stop_loss" | "worse" | "better" | "flat" | "insufficient" | "no_target";

/** F28-I02, v10 words F29-I01, F48 Contract R: every active ad graded against the campaign's one cap T
 * (`app/ads/triage.py::grade_window`, the one ruler; its thresholds are served by `getAdsRules`) -- `on_target`,
 * `watch`, `over`, `wasted`, `insufficient` (剛開始 when `reason_code` is `too_new`, else 資料不足), `no_target` 未判斷.
 * `grade_label` always comes from the backend. `class` stays the trend note against the previous
 * window and no decision reads it (ads.md §6.33, `components/ads/oneRuler.test.ts`). */
export type TriageGrade = "on_target" | "watch" | "over" | "wasted" | "insufficient" | "no_target";
/** F29-I01 Contract A: the grades a move can run between (both windows graded). */
export type RankedGrade = "on_target" | "watch" | "over" | "wasted";
export interface GradeMove { from: RankedGrade; to: RankedGrade }

/** F19-I06: the shared Chinese vocabulary for `result_kind` (`app/ads/result_kinds.py`) — never
 * re-worded here, `label` always comes from the backend. */
export interface ResultKindOption { kind: string; label: string }

export interface TriageWindow {
  start: string; end: string; days: number;
  previous_start: string; previous_end: string;
  extended_from: number | null;
}
/** F28-I01: the one cost-per-result cap (screen word 上限) -- the user's own, else break-even
 * using product economics; never a trailing actual. */
export type CapBasis = "own" | "break_even";
export interface TriageTargetView {
  value: number | null; basis: CapBasis | null;
  result_kind: string | null;
  // F19-I06: always sent by the backend (`app/ads/result_kinds.py::label()`).
  result_label: string;
  missing: string[];
  // F28-I14: the triage `target` is the full cap view, so these always arrive (ruler 打平 mark,
  // ROAS 參考 = price ÷ cap); optional only because older hand-written test factories omit them.
  break_even?: number | null; price?: number | null;
}
/** F28-I01 cap view (`app/ads/targets.py::resolve`): campaign detail `cap`, triage `target`.
 * `break_even`/`price` are sent even when an own cap wins (打平 mark, ROAS 參考 = price ÷ cap). */
export interface CapView extends TriageTargetView {
  own_value: number | null; break_even: number | null; price: number | null;
  product_id: string | null; revision: number;
}
export interface TriageMetricsView {
  spend: number | null; result_count: number | null; cost_per_result: number | null;
  result_kind: string | null;
  result_label: string; // F19-I06: see `TriageTargetView.result_label`.
  derived_zero_days: number; reason: string | null;
}
/** F48 Contract R: the graded window's sample size -- `few` is shown beside the grade (「樣本少」), never a gate.
 * `sales` = known result count (`null` unknown); `few` = 1 to `rules.grade.sample_few - 1` sales; `too_new` = data
 * on fewer than `rules.grade.min_days` days and fewer than `rules.grade.min_results` sales. The three are optional only
 * for older hand-written fixtures; `gate` is no longer served (kept optional for the same fixtures). */
export interface TriageSampleView {
  sales?: number | null; few?: boolean; too_new?: boolean;
  spend_multiple: number | null; days_with_events: number;
  gate?: boolean;
}
/** F27-I01 Contract A: one handling-history entry for an ad or its lineage predecessors, per
 * `app/ads/triage_ladder.py::_entry` — `kind` is never `"budget"` in practice (budget items
 * target owners, not an ad; correction 11), the union just mirrors the contract's own type. */
export interface TriageHistoryEntry {
  change_set_id: string; kind: "copy" | "new_ad" | "budget" | "pause";
  approved_at: string; verified_at: string | null;
  cost_before: number | null; cost_after: number | null;
}
/** F27-I01 Contract A: this ad's own handling ladder, per `app/ads/triage_ladder.py::attach` —
 * `step` 2 once any confirmed `new_ad` replacement exists in its lineage, else 1 once any
 * confirmed `copy` change exists, else 0. `lineage_from` is the ad this ad directly replaced. */
export interface TriageLadder {
  step: 0 | 1 | 2; copy_changes: number; image_changes: number; lineage_from: string | null;
}
export interface TriageItem {
  entity_id: string; native_id: string; name: string | null; campaign_id: string;
  // F49 Contract L: the ad's served delivery (a judged ad is running, or unknown); print `delivery_label`.
  delivery?: DeliveryView; delivery_label?: string;
  // F19-I07: the campaign's own name; always sent (`app/ads/triage.py::classify`).
  campaign_name: string;
  // F20-I01: thumbnail first, else full image, else `null` (`app/ads/triage.py::_thumbnail_url`).
  thumbnail_url: string | null;
  // F48 Contract R: `reason_code` "too_new" = a known zero under the 沒賣出 line (剛開始、數字還不夠, `grade`
  // `insufficient`); "spend_over_target_no_result" = 沒賣出; other codes on `insufficient` = 資料不足. Screens branch on
  // this code, never on `grade_label`.
  class: TriageClass; label: string; reason_code: string;
  grade: TriageGrade; grade_label: string;
  // F29-I01 Contract A: the previous equal-length window graded by the same ruler (null when not
  // synced, below the gate or unknown); `grade_move` only when both are graded and differ. 變貴 =
  // a move from `on_target` to `watch`/`over` -- the only thing that raises a `worse` row.
  previous_grade: RankedGrade | null; grade_move: GradeMove | null;
  window: TriageWindow; target: TriageTargetView;
  current: TriageMetricsView; previous: TriageMetricsView;
  change_pct: number | null; sample: TriageSampleView;
  // F27-I01: optional -- existing hand-written test factories don't set these (real responses
  // always carry them, same `do_not_touch`-vs-`touch` reasoning as `TriageData` below).
  ladder?: TriageLadder; history?: TriageHistoryEntry[];
  // F27-I09 Done #7: optional for the same reason -- real responses always carry it
  // (`app/ads/triage.py::classify`).
  campaign_objective?: CampaignObjectiveFamily;
  // F40-I01: the local ad bound to this platform ad, `null` when the platform ad was not built here
  // (the detail page's 「平台上另有 N 則不是這裡建的」 line). Optional only for older hand-written
  // factories; `undefined` is unknown, never "unmatched".
  bound_ad_id?: string | null;
}
/** F29 Contract D (`app/ads/repository.py::campaign_data_status`): one per-campaign data state for
 * the window the caller judged — triage `data.status` and home rows `data_status` are the same
 * function. A broken sync (`never`／`disconnected`／`auth_expired`／`failed`／`syncing`) wins over a
 * gap; `partial` = a day of the window was never read; `no_rows` = every day read, nothing spent.
 * `label` is one plain sentence to show as is; `missing_days` are the window's unread days. */
export type CampaignDataState =
  | "ready" | "partial" | "no_rows" | "syncing" | "never" | "disconnected" | "auth_expired" | "failed";
export interface CampaignDataStatus {
  state: CampaignDataState; label: string; missing_days: string[]; last_success_at: string | null;
}
/** F24-I01: the read-only `data` enrichment of `CampaignTriage` (`app/ads/triage.py::_data_view`)
 * — `sync` is the same `CampaignSyncState` shape `CampaignCard.data.sync` carries (`adsApi.ts`).
 * F49 Contract V: the judged window is the SAME window `classify()` judges every ad with
 * (`window_days` back from the cutoff, ended at the campaign's end date, starting no earlier than
 * its start date). `coverage` is the first and last read day inside it, `null` when none.
 * `missing_days` are its unread days — `[]` when nothing was ever read (that case reads through
 * `sync.state === "never"`, not a wall of missing dates). `days` is every day of the window with
 * its state: `data` (a row), `empty` (read cleanly, no row) or `missing`. */
export type TriageDayState = "data" | "empty" | "missing";
export interface TriageData {
  sync: CampaignSyncState;
  coverage: { start: string; end: string } | null;
  missing_days: string[];
  // Optional: existing hand-written `data` fixtures predate it (F49-I10 paints it on /wait).
  days?: { day: string; state: TriageDayState }[];
  /** F29 Contract D: the one "has data / why not" state of this window (`campaign_data_status`). */
  status: CampaignDataStatus;
  // F27-I06: optional for the same `do_not_touch`-vs-`touch` scope conflict `CampaignData
  // .capacity` (`adsApi.ts`) notes -- existing hand-written `data: {sync, coverage, missing_days}`
  // fixtures (`CampaignCards.test.tsx`/`WaitPage.test.tsx`) can't be reached to add it. Real
  // responses always carry it (`triage.py::_data_view`, capacity=None only on the internal
  // `_campaign_insufficiency` seam, never on a real `classify()`/`GET .../triage` response).
  capacity?: CampaignCapacity;
}
// F24-I01: `data` is optional here for the same `do_not_touch`-vs-`touch` scope conflict noted on
// `adsApi.ts::CampaignCard.data` -- existing hand-written `*.test.tsx` fixtures can't be reached
// to add it. Real responses always carry it (`triage.py::_data_view`).
/** F26-I01: one closed ad's own last-window numbers, per `app/ads/triage.py::_closed_item` --
 * `spend`/`cost_per_result` are `null` when this ad has no rows inside that window (never a
 * second, different-shaped query from `TriageMetricsView`). */
export interface TriageClosedItem {
  entity_id: string; name: string | null; native_status: string | null;
  // F49 Contract L: why it is not judged (not delivering, or off) — print `delivery_label`, never `native_status`.
  delivery?: DeliveryView; delivery_label?: string;
  thumbnail_url: string | null; spend: number | null; cost_per_result: number | null;
  result_label: string;
}
/** F26-I01: `classify()`'s own `closed` block (feature Decisions "I01") -- every ad of this campaign that is not
 * judged (F49 Contract L: its delivery is `not_running` or `off`), kept and reported (`items` never appears in
 * `CampaignTriage.items` above). `items` is capped at 50, in the same (name, id) order the campaign's own ad query
 * returns; `truncated` says whether there's more than that cap. Real responses always carry this
 * (`triage.py::classify`), same reason it's required here unlike `data` above. */
export interface TriageClosedBlock {
  // F49 Contract L: the not-judged ads grouped by their served delivery label, first seen first; counts add up to
  // `total`. Screens print these groups; there is no local status grouping.
  groups: (DeliveryView & { count: number })[];
  total: number;
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
  /** F49 Contract B: the served word of `verification_state` (`change_control_data.VERIFICATION_LABELS`). */
  verification_label?: string | null;
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
  /** F49 Contract B: the served word of `verification_state` (`change_control_data.VERIFICATION_LABELS`). */
  verification_label?: string | null;
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
  /** F49 Contract B: the served word of `verification_state`, `null` with it. */
  verification_label?: string | null;
  multi: boolean;
}

/** F27-I06 Contract F: the change set (if any) that currently answers a `cleanup` row, per
 * `app/ads/triage.py::_row_cleanup_proposal` -- same shape as `QueuePauseProposal`, `kind` always
 * `"cleanup"`, `multi` always `true` (a cleanup set is inherently the multi-item kind, never
 * computed from item count). `verification_state` is `"confirmed"` only once every one of the
 * set's several `pause` items reads back that way. */
export interface QueueCleanupProposal {
  kind: "cleanup";
  change_set_id: string; campaign_id: string;
  status: "draft" | "approved" | "rejected" | "deferred";
  verification_state: "pending" | "reported" | "confirmed" | "deviated" | "unknown" | "stale";
  /** F49 Contract B: the served word of `verification_state` (`change_control_data.VERIFICATION_LABELS`). */
  verification_label?: string | null;
  reason: string | null; revisit_at: string | null; multi: boolean;
}

export type QueueProposal =
  | QueuePauseProposal | QueueReviewProposal | QueueBudgetProposal | QueueCleanupProposal;

// F26-I02: `QueueKind`/`QueueItem.kind_key` now carry the real backend's fifth kind
// (`app/ads/triage.py`'s `insufficient_data`) -- F26-I01 left this at four values on purpose
// (see the removed comment here) since its own touch didn't cover `home/QueueRow.tsx`'s
// exhaustive `Record<QueueKind, ...>` switches; this issue's touch does, so both widen together.
// F27-I17 Done 0: widened again with the real backend's sixth kind (`app/ads/triage.py`'s
// `"cleanup"`, Contract F) -- `home/QueueRow.tsx`'s exhaustive switches and `home/status.ts`'s
// `proposalAction`/`isQueueItemDone` widen together with it (this issue's touch covers both).
// F29-I03: the backend's brand-level `"settle"` row is NOT a `QueueKind` -- `splitQueue` takes it
// out of `items` into `QueuePayload.settle`, so every ad-row consumer keeps a non-null `triage`.
// F49 Contract Q: widened with `"closeout"` (an ended campaign's row). Like `"settle"`, a closeout row carries no ad
// (`triage: null`), so `splitQueue` takes it out of `items` into `QueuePayload.closeouts`; the kind is in the union for
// `decisions.kinds`. Which kinds are decisions, and their board order, is served (`decisions.kinds`), never listed here.
export type QueueKind =
  | "stop_loss" | "worse" | "scale_budget" | "refresh_creative" | "insufficient_data" | "cleanup" | "closeout";

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
  /** F48 Contract R "reason texts" (`triage_scale.scale_reason_text`): why this raise, built from the owner's cheapest
   * 划算 ad's own numbers. The budget draft's reason is this sentence as served. Always served; optional only for older
   * hand-written fixtures. */
  reason_text?: string | null;
}
/** F48 Contract R (a money action states its reason): a budget owner whose raise is held back on sample size
 * (`triage_scale.scale_candidates` `holds`) — `reason_text` is the served 「樣本少，先不加碼」. */
export interface QueueScaleHold {
  owner_id: string; owner_name: string | null; campaign_id: string; sales: number; reason_text: string;
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
/** F29-I01 Contract B: the user's earlier "no" to closing this ad -- set only on a proposed ad
 * that re-entered the cut because its grade got worse since (`grade` is the grade it had then). */
export interface RejectedBefore {
  grade: RankedGrade; grade_label: string; at: string; reason: string | null;
  change_set_id: string;
}
/** F27-I06 Contract F, re-cut by F28-I02 (`app/ads/triage_capacity.py::cleanup_candidates`):
 * `ads` is the proposed cut -- every 沒賣出 ad first, then, while active ads exceed `can_support`,
 * 太貴 before 偏貴, highest cost per result first; 划算 and ungraded ads never. `keep` is every
 * other active ad (same shape). `can_support` is `null` when capacity is unknown (a 沒賣出 ad
 * alone still raises the row). `short` counts ads still over capacity after the cut;
 * `scale_owner_id` is the campaign's qualifying `scale_budget` owner while `short > 0`.
 * `spend_7d`/`daily_spend`/`daily_saving` are `null` when the last 7 days aren't fully known;
 * `cost_per_result`/`spend`/`result_count` are the ad's graded window (`TriageItem.current`). */
export interface QueueCleanupAd {
  entity_id: string; name: string | null; thumbnail_url: string | null;
  spend_7d: number | null;
  grade: TriageGrade; cost_per_result: number | null; spend: number | null;
  result_count: number | null; daily_spend: number | null;
  // F29-I01 Contract B: null unless this ad was rejected before and its grade got worse since
  // (always null on `keep` entries).
  rejected_before: RejectedBefore | null;
  // F48-I02 (Contract R "ordering／verdict"): the ad's place in the campaign's `learning_rank` ranking -- `rank` of
  // `of` (`rank` null for an ungraded ad), `sales`, `few` (「樣本少」), `verdict`／`verdict_label` 留下／換掉, `flags`
  // the served flag words, and `reason_text` the program's sentence built from this ad's own grade and numbers.
  // `ads` and `keep` arrive in rank order: print them in that order, never re-sort. Always served; optional only for
  // older hand-written fixtures.
  rank?: number | null; of?: number | null; sales?: number | null; few?: boolean;
  verdict?: "keep" | "keep_relative" | "replace" | null; verdict_label?: string | null; flags?: string[];
  reason_text?: string | null;
}
export interface QueueCleanup {
  campaign_id: string; campaign_name: string; can_support: number | null; active_ads: number;
  ads: QueueCleanupAd[]; keep: QueueCleanupAd[]; short: number;
  daily_saving: number | null; scale_owner_id: string | null;
}
/** F29-I03 Contract E: the `settle` row's own payload -- the latest ended calendar month (org
 * timezone), raised from the 2nd day after it ends while nothing is written. `learnable_count`
 * counts the ads that will be written (划算／太貴／沒賣出); `buckets` is the month's spend by grade
 * (`app/ads/period_grades.py::summarize`, same as the month review). The page reads
 * `adsSettleApi.ts::getSettle(brand, month)`. Exposed as `QueuePayload.settle`, never in `items`. */
/** F49 Contract Q: the `closeout` row's own payload -- one per internal campaign whose lifecycle is `ended`
 * (`app/ads/triage.py::_closeout_candidates`). `running` = the campaign's ads still running at the platform read
 * (`lifecycle.running_view`; `read_at` that read, `null` when never read). Never done: it leaves when the campaign
 * closes. Exposed as `QueuePayload.closeouts`, never in `items`. */
export interface QueueCloseout {
  campaign_id: string; campaign_name: string; end_date: string | null;
  running: { count: number; read_at: string | null };
}
export interface QueueSettle {
  month: string; start: string; end: string;
  campaign_count: number; imported_count: number; learnable_count: number;
  buckets: PeriodGradeBucket[];
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
  /** F47 Contract D (`app/ads/queue_done.py`): the row no longer waits on the user (decided,
   * deferred, or its change confirmed). The only done rule — read it, never recompute it. */
  done: boolean;
  /** F49 Contract Q (`queue_done.stamp`): the row is a decision the user is asked to make (counted); `false` on a
   * notice (`scale_budget` on the money card, `insufficient_data` on the campaign row), which is never in the inbox.
   * Always served; optional only for older hand-written fixtures. */
  decision?: boolean;
  /** F49 Contract Q: 1-based place among the open decision rows in board order (settle and closeout rows
   * included) — 「第 N 件」; `null` on a done row or a notice. */
  position?: number | null;
  /** F49 Contract Q: the campaign the row belongs to (`null` on the brand's settle row). */
  campaign_id?: string | null;
  scale?: QueueScale; refresh?: QueueRefresh; insufficient?: QueueInsufficient;
  cleanup?: QueueCleanup;
}
/** F29-I03 Contract E: the brand's open period-settle row (`kind_key: "settle"` on the wire, whose
 * `triage` is `null` -- it is about the whole brand's month, not one ad). */
export interface SettleQueueRow {
  id: string; dedupe_key: string; category: string; severity: AlertSeverity;
  message: string; action_url: string | null; visible_from: string | null;
  status: string; created_at: string;
  settle: QueueSettle;
  /** F49 Contract Q: see `QueueItem.decision`／`position`／`done`. Optional for older fixtures. */
  decision?: boolean; position?: number | null; done?: boolean;
}
/** F49 Contract Q: an ended campaign's open closeout row (`kind_key: "closeout"` on the wire, `triage: null`). */
export interface CloseoutQueueRow {
  id: string; dedupe_key: string; category: string; severity: AlertSeverity;
  message: string; action_url: string | null; visible_from: string | null;
  status: string; created_at: string;
  campaign_id: string; decision: boolean; position: number | null; done: boolean;
  closeout: QueueCloseout;
}
/** F49 Contract Q: the queue's decision count (`queue_done.stamp`) — `kinds` are the decision kinds in board order,
 * `open` the open decision rows: 「共 M 件」, the top bar's `open_items` and the inbox's ads rows are this number. */
// `settle` is a decision kind (the brand's period-settle row) but not a `QueueKind` (`splitQueue` takes it out of
// `items`), so the served list is widened by it here.
export interface QueueDecisions { kinds: (QueueKind | "settle")[]; open: number }
export interface QueuePayload {
  /** Ad-level rows only (every one carries its `triage` item). */
  items: QueueItem[]; counts: Record<TriageClass, number>; total_ads: number;
  kinds_available: string[]; kinds_pending: string[];
  /** F29-I03: the open settle row, `null` when none. Always set by `getQueue`/`refreshQueue`
   * (`splitQueue`); optional only so existing hand-written payload fixtures stay valid. */
  settle?: SettleQueueRow | null;
  /** F48-I02: the owners whose raise is held back on sample size. Always served; optional for older fixtures. */
  scale_hold?: QueueScaleHold[];
  /** F49 Contract Q: the open closeout rows (ended campaigns), split out of `items` by `splitQueue`. Always set by
   * `getQueue`/`refreshQueue`; optional only so existing hand-written payload fixtures stay valid. */
  closeouts?: CloseoutQueueRow[];
  /** F49 Contract Q: the served decision count. Always served; optional for older fixtures. */
  decisions?: QueueDecisions;
}
/** The backend's queue as it arrives: ad rows plus, at most, one brand-level settle row, and the ended campaigns'
 * closeout rows. */
type WireSettleRow = SettleQueueRow & { kind_key: "settle"; triage: null };
type WireCloseoutRow = CloseoutQueueRow & { kind_key: "closeout"; triage: null };
type WireRow = QueueItem | WireSettleRow | WireCloseoutRow;
export type WireQueuePayload = Omit<QueuePayload, "items" | "settle" | "closeouts"> & {
  items: WireRow[];
};

const isWireSettle = (row: WireRow): row is WireSettleRow =>
  (row as { kind_key: string }).kind_key === "settle";
const isWireCloseout = (row: WireRow): row is WireCloseoutRow =>
  (row as { kind_key: string }).kind_key === "closeout";

/** F29-I03, F49 Contract Q: the one type boundary for the rows without an ad (the brand-level settle row, the ended
 * campaigns' closeout rows) -- split once here, so no screen that scans `items` ever meets a row without an ad. */
export function splitQueue(wire: WireQueuePayload): QueuePayload {
  const items: QueueItem[] = [];
  const closeouts: CloseoutQueueRow[] = [];
  let settle: SettleQueueRow | null = null;
  for (const row of wire.items) {
    if (isWireSettle(row)) {
      settle ??= {
        id: row.id, dedupe_key: row.dedupe_key, category: row.category, severity: row.severity,
        message: row.message, action_url: row.action_url, visible_from: row.visible_from,
        status: row.status, created_at: row.created_at, settle: row.settle,
        decision: row.decision, position: row.position, done: row.done,
      };
    } else if (isWireCloseout(row)) {
      closeouts.push({
        id: row.id, dedupe_key: row.dedupe_key, category: row.category, severity: row.severity,
        message: row.message, action_url: row.action_url, visible_from: row.visible_from,
        status: row.status, created_at: row.created_at, campaign_id: row.campaign_id,
        decision: row.decision, position: row.position, done: row.done, closeout: row.closeout,
      });
    } else {
      items.push(row);
    }
  }
  return { ...wire, items, settle, closeouts };
}

/** F45-I05 Contract P (ads.md §6.49, `app/ads/triage_pause.py::pause_view`): the pause page's own read
 * of one ad -- never the home queue. `active` = a platform ad of this campaign not read as closed
 * (unknown status counts as active); `closed` = closed but not deleted; `gone` = no such ad in this
 * campaign, or deleted (`triage` is then `null`). `triage` is the `GET …/triage` item computed for
 * this one ad (closed ads too). `closed_at` = when its status last changed, `last_read_at` = its
 * last successful read (ISO instants, either may be `null`). `change_set_id` = the open plain pause
 * set on this ad (draft, or approved and not yet confirmed), else `null`. F48 Contract R "reason texts":
 * `reason_text` is the pause's reason built from this ad's own grade and numbers (`triage_capacity.reason_text`),
 * `null` when `triage` is; always served, optional only for older hand-written fixtures. */
export type PauseViewState = "active" | "closed" | "gone";
export interface PauseView {
  state: PauseViewState; entity_id: string; name: string | null; triage: TriageItem | null;
  reason_text?: string | null;
  closed_at: string | null; last_read_at: string | null; change_set_id: string | null;
}

/** F48 Contract R-API (`GET …/brands/{b}/rules`, `app/ads/triage.py::rules`): every threshold, label and glossary
 * sentence the ads screens print, read from the backend's two ruler modules. The frontend keeps no copy; it reads
 * these through `components/ads/patterns/rules.ts::useAdsRules()`. `glossary.break_even` has no value -- the screen
 * appends 「（這裡是 X）」. */
export interface AdsRules {
  grade: {
    watch_band: number; unsold_spend_multiple: number; min_results: number; min_days: number;
    sample_few: number; near_best: number; break_even_band: number;
  };
  ab: { min_days: number; min_conversions_each: number; relative_difference: number };
  labels: {
    grade: Record<"on_target" | "watch" | "over" | "wasted" | "too_new" | "no_data" | "no_target", string>;
    verdict: Record<"keep" | "keep_relative" | "replace", string>;
    flags: Record<"few" | "relative" | "relative_no_cap", string>;
  };
  glossary: Record<"cap" | "on_target" | "watch" | "over" | "wasted" | "thin" | "money" | "notebook" | "break_even", string>;
  /** F49 Contract Q (`triage.reasons()`): every `reason_code` an ad can carry, with its title, sentence and what fixes
   * it (`resync` read the platform again, `connections` fix the data connection, `cap` set the cap／result, `wait`
   * give it time, `null` nothing to do here). Screens look a code up here; they keep no table of codes. */
  reasons: Record<string, AdsReason>;
}
export interface AdsReason { title: string; text: string; fix: "resync" | "connections" | "cap" | "wait" | null }

export interface CampaignTarget extends CapView {
  campaign_id: string; product_ids: string[]; result_kinds: ResultKindOption[];
  /** F29 Contract D: 成本含運 (unit cost incl. shipping) from the same product economics row as
   * `break_even`, so price − cost = break-even; null unless the result is a purchase and it is known. */
  cost: number | null;
}
export interface TargetRequest {
  result_kind?: string | null; basis?: CapBasis | null;
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

/** F48 Contract R-API: served unwrapped (`{grade, ab, labels, glossary}`). */
export async function getAdsRules(brand: string, signal?: AbortSignal) {
  return json<AdsRules>(`${brandPath(brand)}/rules`, "GET", undefined, signal);
}
export async function getQueue(brand: string, signal?: AbortSignal) {
  return splitQueue((await json<{ queue: WireQueuePayload }>(`${brandPath(brand)}/queue`, "GET", undefined, signal)).queue);
}
export async function refreshQueue(brand: string, signal?: AbortSignal) {
  return splitQueue((await json<{ queue: WireQueuePayload }>(`${brandPath(brand)}/queue/refresh`, "POST", {}, signal)).queue);
}
export async function getTriage(brand: string, campaign: string, signal?: AbortSignal) {
  return (await json<{ triage: CampaignTriage }>(`${campaignPath(brand, campaign)}/triage`, "GET", undefined, signal)).triage;
}
/** F45-I05 Contract P: 404 only for an unknown campaign; an unknown ad is `state: "gone"`. */
export async function getPauseView(brand: string, campaign: string, entityId: string, signal?: AbortSignal) {
  return (await json<{ pause: PauseView }>(
    `${campaignPath(brand, campaign)}/triage/${encodeURIComponent(entityId)}/pause`, "GET", undefined, signal,
  )).pause;
}
export async function getTarget(brand: string, campaign: string, signal?: AbortSignal) {
  return (await json<{ target: CampaignTarget }>(`${campaignPath(brand, campaign)}/target`, "GET", undefined, signal)).target;
}
export async function putTarget(brand: string, campaign: string, body: TargetRequest, signal?: AbortSignal) {
  return (await json<{ target: CampaignTarget }>(`${campaignPath(brand, campaign)}/target`, "PUT", body, signal)).target;
}
