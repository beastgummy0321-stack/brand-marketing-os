import { campaignFlowPath } from "@/lib/adsRoutes";
import type { HomeOverview } from "@/lib/adsHomeApi";
import { formatInstant } from "@/lib/orgClock";
import type {
  CloseoutQueueRow, QueueItem, QueuePauseProposal, QueuePayload, QueueProposal, QueueReviewProposal, SettleQueueRow,
} from "@/lib/adsTriageApi";

/** F22-I05/F23-I01: what a `stop_loss` or `worse` row／ad leads to, driven entirely by
 * `item.proposal` (feature Decisions "Queue row state"; routes and labels from the issue's rule
 * details). Shared by `home/QueueRow.tsx` and `detail/CampaignDetailPage.tsx` so both surfaces
 * agree — the pages at these routes are built by other issues in this feature, this only routes
 * there. */
export interface ProposalAction {
  label: string;
  href: string;
  /** confirmed／rejected／deferred／deferred(review)／unjudgeable: ghost button, and the row no
   * longer counts as open. */
  done: boolean;
}

const proposePath = (brandId: string, campaignId: string, entityId: string) =>
  campaignFlowPath(brandId, campaignId, ["propose", "pause", entityId]);
// F25-I02: the `scale_budget` row's own entry point when there is no budget proposal yet
// (feature Decisions "Home rows") — `entityId` here is the budget owner's id (an adset, or the
// campaign itself when the campaign holds the budget), never the triage ad's own `entity_id`.
const proposeBudgetPath = (brandId: string, campaignId: string, ownerId: string) =>
  campaignFlowPath(brandId, campaignId, ["propose", "budget", ownerId]);
const changePath = (
  brandId: string, campaignId: string, setId: string, step: "confirm" | "handoff" | "verify",
) => campaignFlowPath(brandId, campaignId, ["changes", setId, step]);
// F23-I01: entry for a `worse` row with no review round yet, and the round's own detail/prepare
// steps once one exists (feature Decisions "Queue row state for `worse` rows").
const reviewPath = (brandId: string, campaignId: string, entityId: string) =>
  campaignFlowPath(brandId, campaignId, ["review", entityId]);
const reviewRoundPath = (brandId: string, campaignId: string, reviewId: string, step?: "prepare") =>
  campaignFlowPath(brandId, campaignId, ["reviews", reviewId, ...(step ? [step] : [])]);

// F47-I07 (drill-10 Q2) 「M/D 再看」, the deferred rows and the confirm page share this one. F50-I12 (Contract K):
// `revisit_at` is the stored instant of 00:00 of the chosen org calendar day, so it prints on the org clock
// (`timezone`), never the viewer's — 「7 天後」 picked on 10/31 in Taipei reads 「11/8 再看」 everywhere.
export function formatRevisitLabel(revisitAt: string, timezone: string): string {
  const day = formatInstant(revisitAt, timezone, "md");
  return day ? `${day} 再看` : "已暫緩";
}

/** A deferred row's label: the revisit day on the org clock when the caller passes the org `timezone`; a caller that
 * never shows a deferred label (only the href／done) may omit it and gets 「已暫緩」, never a browser-zone date. */
function deferredLabel(revisitAt: string | null, timezone: string | undefined): string {
  return revisitAt && timezone ? formatRevisitLabel(revisitAt, timezone) : "已暫緩";
}

/** A ready or completed review with a copy set follows that set's actual workflow — the row's
 * button then just follows that change set's own status/verification_state, same labels/steps as
 * a `stop_loss` row's pause change set (feature Decisions "completed with a copy set → that set's
 * step via the F22 labels"). Reuses the pause branch below through a synthetic
 * `QueuePauseProposal` rather than duplicating the switch. The backend only ever sets
 * `change_set_status`/`verification_state` together with `change_set_id` (`_row_review_proposal`)
 * — the `?? "draft"`/`?? "pending"` fallbacks here are defensive, never expected to trigger. */
function reviewChangeSetAction(
  brandId: string, campaignId: string, entityId: string, proposal: QueueReviewProposal, timezone?: string,
): ProposalAction {
  const pauseShaped: QueuePauseProposal = {
    kind: "pause",
    change_set_id: proposal.change_set_id as string,
    campaign_id: campaignId,
    status: proposal.change_set_status ?? "draft",
    verification_state: proposal.verification_state ?? "pending",
    verification_label: proposal.verification_label,
    reason: proposal.reason,
    revisit_at: proposal.revisit_at,
    multi: proposal.multi,
  };
  return proposalAction(brandId, campaignId, entityId, pauseShaped, "pause", timezone);
}

/** F23-I01: the `worse` row branch, per feature Decisions "Queue row state for `worse` rows". */
function reviewProposalAction(
  brandId: string, campaignId: string, entityId: string, proposal: QueueReviewProposal, timezone?: string,
): ProposalAction {
  switch (proposal.status) {
    case "queued":
    case "running":
      return {
        label: "整理證據中", href: reviewRoundPath(brandId, campaignId, proposal.review_id), done: false,
      };
    case "waiting":
      return {
        label: "資料不足", href: reviewRoundPath(brandId, campaignId, proposal.review_id), done: false,
      };
    case "failed":
    case "unknown":
      return {
        label: "證據沒整理成", href: reviewRoundPath(brandId, campaignId, proposal.review_id), done: false,
      };
    case "ready":
      if (proposal.change_set_id !== null) {
        return reviewChangeSetAction(brandId, campaignId, entityId, proposal, timezone);
      }
      return {
        label: "等你決定", href: reviewRoundPath(brandId, campaignId, proposal.review_id), done: false,
      };
    case "completed":
      if (proposal.change_set_id !== null) {
        return reviewChangeSetAction(brandId, campaignId, entityId, proposal, timezone);
      }
      return {
        label: "選方向",
        href: reviewRoundPath(brandId, campaignId, proposal.review_id, "prepare"),
        done: false,
      };
    case "deferred":
      return {
        label: deferredLabel(proposal.revisit_at, timezone),
        href: reviewRoundPath(brandId, campaignId, proposal.review_id),
        done: true,
      };
    case "unjudgeable":
      return {
        label: "無法判定", href: reviewRoundPath(brandId, campaignId, proposal.review_id), done: true,
      };
  }
}

export function proposalAction(
  brandId: string,
  campaignId: string,
  entityId: string,
  proposal: QueueProposal | null,
  // F23-I01: only the null-proposal case needs telling apart — once `proposal` itself carries a
  // `kind`, that alone decides the branch below. Optional and defaulted so every existing 4-arg
  // call site (`stop_loss`-only today) keeps its exact original "去處理" behaviour unchanged.
  // F25-I02: `"budget"` is the `scale_budget` row's own null-proposal entry point (feature
  // Decisions "Home rows") — once a `QueueBudgetProposal` exists it falls through to the same
  // generic switch below as `"pause"` does (`change_set_id`/`status`/`verification_state` are the
  // same shape, "budget branch = the pause branch on a budget set"), so only this branch differs.
  kind: "pause" | "review" | "budget" = "pause",
  // F50-I12: the org timezone a deferred row's 「M/D 再看」 prints in (see `deferredLabel`).
  timezone?: string,
): ProposalAction {
  if (proposal === null) {
    if (kind === "review") return { label: "看證據", href: reviewPath(brandId, campaignId, entityId), done: false };
    if (kind === "budget") return { label: "看提議", href: proposeBudgetPath(brandId, campaignId, entityId), done: false };
    return { label: "去處理", href: proposePath(brandId, campaignId, entityId), done: false };
  }
  if (proposal.kind === "review") {
    return reviewProposalAction(brandId, campaignId, entityId, proposal, timezone);
  }
  // F28: every change set, a multi-item cleanup set included, opens its own step page. The flow
  // pages (confirm / handoff / verify) render cleanup sets since F28-I11/I14; the old fallback to
  // the campaign workspace sent 「等你核准」 to an overview with no decision on it.
  const stepHref = (step: "confirm" | "handoff" | "verify") =>
    changePath(brandId, campaignId, proposal.change_set_id, step);

  switch (proposal.status) {
    case "draft":
      return { label: "等你核准", href: stepHref("confirm"), done: false };
    case "rejected":
      return { label: "已拒絕", href: stepHref("confirm"), done: true };
    case "deferred":
      return {
        label: deferredLabel(proposal.revisit_at, timezone),
        href: stepHref("confirm"),
        done: true,
      };
    case "approved": {
      // F49 Contract B: the state's word is served (`verification_label`); this only picks the step. A set nothing has
      // been reported on yet waits on the platform side, every other state is read on the verify step. Without the
      // served word (older hand-written fixtures only) the step's own name stands in.
      const pending = proposal.verification_state === "pending";
      return {
        label: proposal.verification_label ?? (pending ? "到平台完成" : "核對中"),
        href: stepHref(pending ? "handoff" : "verify"),
        done: proposal.verification_state === "confirmed",
      };
    }
  }
}

/** F27-I17 Contract F / Done 0: the `cleanup` row's own action — no proposal yet uses the row's
 * own `action_url` (backend's `/propose/cleanup/:campaignId`, `app/ads/triage.py
 * ::_cleanup_candidates`, never reconstructed here — same trust `home/QueueRow.tsx` already gives
 * the `refresh_creative`/`insufficient_data` rows' own `action_url`); once a cleanup change set
 * exists it's the same multi-item change-set step every other kind uses through `proposalAction`'s
 * own generic switch (`kind` only matters for the null-proposal branch, irrelevant once `proposal`
 * itself carries one — a cleanup set's `multi` is always `true`, Contract F). */
export function cleanupAction(
  brandId: string, campaignId: string, proposal: QueueProposal | null, actionUrl: string | null, timezone?: string,
): ProposalAction | null {
  if (proposal === null) return actionUrl ? { label: "看提議", href: actionUrl, done: false } : null;
  return proposalAction(brandId, campaignId, campaignId, proposal, "pause", timezone);
}

/** F47-I07 (Contract D): whether a queue row still waits on the user is the backend's own
 * `item.done` (`app/ads/queue_done.py`, stamped on every row of the queue read) — the top bar, the
 * home list and 「下一件」 all read that one field; there is no second copy of the rule here. */
export function isQueueItemDone(item: QueueItem): boolean {
  return item.done;
}

/** F49 Contract Q: whether a row is a decision the user is asked to make is the row's served `decision` (`false` on a
 * notice: `scale_budget` on the money card, `insufficient_data` on the campaign row). A row without the flag (older
 * hand-written fixtures only; every real row carries it) counts. */
function isDecision(row: { decision?: boolean }): boolean {
  return row.decision !== false;
}

/** One entry of the home board: an ad-level queue row, the brand's period-settle row, or an ended campaign's
 * closeout row. */
export type HomeDecision =
  | { kind: "item"; item: QueueItem }
  | { kind: "settle"; row: SettleQueueRow }
  | { kind: "closeout"; row: CloseoutQueueRow };

const positionOf = (d: HomeDecision): number | null | undefined => (d.kind === "item" ? d.item.position : d.row.position);

/** F49 Contract Q: the home 「需要你決定」 board — every decision row of the queue (ad rows, the settle row, the
 * closeout rows), open ones in their served `position` (board order is the backend's `DECISION_KINDS`), then the
 * handled ones as served. Done-ness is each row's own served `done`. The count is `decisionCount`. */
export function decisionBoard(brandId: string, queue: QueuePayload): { open: HomeDecision[]; done: HomeDecision[] } {
  const settle = queue.settle ?? null;
  const entries: HomeDecision[] = [
    ...queue.items.filter(isDecision).map((item): HomeDecision => ({ kind: "item", item })),
    ...(settle && isDecision(settle) ? [{ kind: "settle", row: settle } as HomeDecision] : []),
    ...(queue.closeouts ?? []).filter(isDecision).map((row): HomeDecision => ({ kind: "closeout", row })),
  ];
  const isDone = (d: HomeDecision) =>
    d.kind === "item" ? isQueueItemDone(d.item) : d.kind === "settle" ? (d.row.done ?? settleAction(brandId, d.row).done) : d.row.done;
  const open = entries
    .filter((d) => !isDone(d))
    .map((d, i) => ({ d, i }))
    .sort((a, b) => (positionOf(a.d) ?? Infinity) - (positionOf(b.d) ?? Infinity) || a.i - b.i)
    .map(({ d }) => d);
  return { open, done: entries.filter(isDone) };
}

/** 「共 M 件」: the served `decisions.open` (the top bar's `open_items` and the inbox's ads rows are the same number);
 * the board's own open rows only when a payload predates it (older hand-written fixtures). */
export function decisionCount(queue: QueuePayload, board: { open: HomeDecision[] }): number {
  return queue.decisions?.open ?? board.open.length;
}

/** F49 Contract Q: 「第 N 件／共 M 件」 — the served `position` of an open decision row among `decisions.open`. `null`
 * when the row is not an open decision (handled, or a notice): no position is invented for it. */
function boardPosition(
  brandId: string, queue: QueuePayload, which: (d: HomeDecision) => boolean,
): { pos: number; total: number } | null {
  const board = decisionBoard(brandId, queue);
  const at = board.open.findIndex(which);
  if (at < 0) return null;
  return { pos: positionOf(board.open[at]) ?? at + 1, total: decisionCount(queue, board) };
}

/** A flow page's 「第 N 件／共 M 件」 for an ad-level row. */
export function decisionPosition(queue: QueuePayload | null, item: QueueItem | null): { pos: number; total: number } | null {
  if (!queue || !item || item.brand_id === null) return null;
  return boardPosition(item.brand_id, queue, (d) => d.kind === "item" && d.item.id === item.id);
}

/** The settle page's 「第 N 件（共 M 件）」 for the brand's open settle row. */
export function settlePosition(brandId: string, queue: QueuePayload | null): { pos: number; total: number } | null {
  if (!queue?.settle) return null;
  return boardPosition(brandId, queue, (d) => d.kind === "settle");
}

/** F29-I11 (Contract E): the brand-level period-settle row's own action. Its link is the row's own
 * `action_url` (the settle page, `/brands/:b/ads/settle/:month/result`), falling back to the same
 * route built from the payload's month. The queue lists open rows only; a row whose status is no
 * longer `open` reads as written (「✓ 已寫進筆記本」, prototype `qState` settle branch). */
export function settleAction(brandId: string, row: SettleQueueRow): ProposalAction {
  const href = row.action_url ?? `/brands/${brandId}/ads/settle/${row.settle.month}/result`;
  return row.status === "open"
    ? { label: "開始結算", href, done: false }
    : { label: "✓ 已寫進筆記本", href, done: true };
}

/** F40-I07 (drill-7 #8): what the home quality band shows when there is nothing to grade — decided from the payload
 * alone (`home/QualityBand.tsx` only renders it), in this order:
 * (i) `quality` and `spent` both unknown and some campaign has unread days → the month's spend is incomplete: name
 *     the days and offer 重新讀取平台 (the first such campaign's 成效 tab, where the sync lives);
 * (ii) `spent` known but `quality` null → the guarded quality block failed, not "no data": 分級讀取失敗 + 重試;
 * (iii) nothing spent (no bucket has an amount, or `spent` is 0／null with every day read) → 還沒有花費資料;
 * otherwise the normal band. `null` is never read as 0 (adsHomeApi rules). */
export type BandState =
  | { kind: "band" }
  | { kind: "missing_days"; sentence: string; campaign_id: string }
  | { kind: "read_failed"; sentence: string }
  | { kind: "no_spend"; sentence: string };

/** `YYYY-MM-DD` → 「MM/DD」 (prototype 「10/03 沒讀到」). */
const monthDay = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(8, 10)}`;

export function bandState(home: HomeOverview): BandState {
  const month = Number(home.month.split("-")[1]);
  const label = Number.isFinite(month) ? `${month} 月` : "本月";
  const gapped = (home.campaigns ?? []).filter((c) => c.missing_days.length > 0);
  if (home.quality === null && home.spent === null && gapped.length > 0) {
    const days = [...new Set(gapped.flatMap((c) => c.missing_days))].sort();
    const when = days.length <= 3 ? `${days.map(monthDay).join("、")} 沒讀到` : `${days.length} 天沒讀到`;
    return { kind: "missing_days", sentence: `${label}已花還不完整（${when}），先不分級`, campaign_id: gapped[0].campaign_id };
  }
  if (home.quality === null && home.spent !== null) {
    return { kind: "read_failed", sentence: "分級讀取失敗" };
  }
  const graded = home.quality !== null && home.quality.buckets.some((b) => b.amount > 0);
  if (!graded) return { kind: "no_spend", sentence: `${label}還沒有花費資料，先不分級` };
  return { kind: "band" };
}
