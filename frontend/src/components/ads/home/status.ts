import type { CampaignStatus } from "@/lib/adsApi";
import type { HomeOverview } from "@/lib/adsHomeApi";
import type {
  QueueItem, QueuePauseProposal, QueueProposal, QueueReviewProposal, SettleQueueRow,
} from "@/lib/adsTriageApi";

/** F19-I02：從 `AdsHomePage.tsx` 抽出，讓 `home/CampaignCards.tsx` 跟 `AdsHomePage.tsx` 都能讀，
 * 不必互相 import 造成循環依賴。`AdsHomePage.tsx` 原樣 re-export，`AllCampaignsPage.tsx`
 * （do_not_touch 外但這次沒有理由改）沿用同一個 import 路徑不受影響。 */
export const STATUS_LABEL: Record<CampaignStatus, string> = {
  draft: "草稿",
  ready: "待發布",
  live: "投放中",
  ended: "已結束",
  closed: "已結案",
};

export const STATUS_TONE: Record<CampaignStatus, "secondary" | "default" | "outline"> = {
  draft: "secondary",
  ready: "outline",
  live: "default",
  ended: "outline",
  closed: "secondary",
};

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
  `/brands/${brandId}/ads/campaigns/${campaignId}/propose/pause/${entityId}`;
// F25-I02: the `scale_budget` row's own entry point when there is no budget proposal yet
// (feature Decisions "Home rows") — `entityId` here is the budget owner's id (an adset, or the
// campaign itself when the campaign holds the budget), never the triage ad's own `entity_id`.
const proposeBudgetPath = (brandId: string, campaignId: string, ownerId: string) =>
  `/brands/${brandId}/ads/campaigns/${campaignId}/propose/budget/${ownerId}`;
const changePath = (
  brandId: string, campaignId: string, setId: string, step: "confirm" | "handoff" | "verify",
) => `/brands/${brandId}/ads/campaigns/${campaignId}/changes/${setId}/${step}`;
// F23-I01: entry for a `worse` row with no review round yet, and the round's own detail/prepare
// steps once one exists (feature Decisions "Queue row state for `worse` rows").
const reviewPath = (brandId: string, campaignId: string, entityId: string) =>
  `/brands/${brandId}/ads/campaigns/${campaignId}/review/${entityId}`;
const reviewRoundPath = (brandId: string, campaignId: string, reviewId: string, step?: "prepare") =>
  `/brands/${brandId}/ads/campaigns/${campaignId}/reviews/${reviewId}${step ? `/${step}` : ""}`;

// `revisit_at` 是「always a timezone-carrying ISO instant」（feature Decisions）——瀏覽器本地
// 時區印「M/D」，不補零、不印年份（跟這頁其餘日期格式一致地簡短）。
function formatRevisitLabel(revisitAt: string): string {
  const d = new Date(revisitAt);
  return `${d.getMonth() + 1}/${d.getDate()} 重看`;
}

/** F23-I01: `proposal.status === "completed"` with a copy change set already exists — the row's
 * button then just follows that change set's own status/verification_state, same labels/steps as
 * a `stop_loss` row's pause change set (feature Decisions "completed with a copy set → that set's
 * step via the F22 labels"). Reuses the pause branch below through a synthetic
 * `QueuePauseProposal` rather than duplicating the switch. The backend only ever sets
 * `change_set_status`/`verification_state` together with `change_set_id` (`_row_review_proposal`)
 * — the `?? "draft"`/`?? "pending"` fallbacks here are defensive, never expected to trigger. */
function reviewChangeSetAction(
  brandId: string, campaignId: string, entityId: string, proposal: QueueReviewProposal,
): ProposalAction {
  const pauseShaped: QueuePauseProposal = {
    kind: "pause",
    change_set_id: proposal.change_set_id as string,
    campaign_id: campaignId,
    status: proposal.change_set_status ?? "draft",
    verification_state: proposal.verification_state ?? "pending",
    reason: proposal.reason,
    revisit_at: proposal.revisit_at,
    multi: proposal.multi,
  };
  return proposalAction(brandId, campaignId, entityId, pauseShaped);
}

/** F23-I01: the `worse` row branch, per feature Decisions "Queue row state for `worse` rows". */
function reviewProposalAction(
  brandId: string, campaignId: string, entityId: string, proposal: QueueReviewProposal,
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
      return {
        label: "等你決定", href: reviewRoundPath(brandId, campaignId, proposal.review_id), done: false,
      };
    case "completed":
      if (proposal.change_set_id !== null) {
        return reviewChangeSetAction(brandId, campaignId, entityId, proposal);
      }
      return {
        label: "選方向",
        href: reviewRoundPath(brandId, campaignId, proposal.review_id, "prepare"),
        done: false,
      };
    case "deferred":
      return {
        label: proposal.revisit_at ? formatRevisitLabel(proposal.revisit_at) : "已暫緩",
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
): ProposalAction {
  if (proposal === null) {
    if (kind === "review") return { label: "看證據", href: reviewPath(brandId, campaignId, entityId), done: false };
    if (kind === "budget") return { label: "看提議", href: proposeBudgetPath(brandId, campaignId, entityId), done: false };
    return { label: "去處理", href: proposePath(brandId, campaignId, entityId), done: false };
  }
  if (proposal.kind === "review") {
    return reviewProposalAction(brandId, campaignId, entityId, proposal);
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
        label: proposal.revisit_at ? formatRevisitLabel(proposal.revisit_at) : "已暫緩",
        href: stepHref("confirm"),
        done: true,
      };
    case "approved":
      switch (proposal.verification_state) {
        case "pending":
          return { label: "到平台完成", href: stepHref("handoff"), done: false };
        case "reported":
        case "unknown":
          return { label: "核對中", href: stepHref("verify"), done: false };
        case "deviated":
          return { label: "與核准不符", href: stepHref("verify"), done: false };
        case "stale":
          return { label: "需重新檢討", href: stepHref("verify"), done: false };
        case "confirmed":
          return { label: "已核對", href: stepHref("verify"), done: true };
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
  brandId: string, campaignId: string, proposal: QueueProposal | null, actionUrl: string | null,
): ProposalAction | null {
  if (proposal === null) return actionUrl ? { label: "看提議", href: actionUrl, done: false } : null;
  return proposalAction(brandId, campaignId, campaignId, proposal);
}

/** F22-I05/F23-I01/F25-I02/F26-I02/F27-I17: whether a queue row still counts as "open" for the
 * home header count (`AdsHomePage.tsx`). A `stop_loss` or `worse` row is done exactly when
 * `proposalAction(...).done` is true — same rule the row's own button already renders, kept in
 * one place so the header and the button can't disagree. `scale_budget` rows follow the same rule
 * through the `"budget"` branch, keyed to the budget owner's id rather than the triage ad's own
 * `entity_id` (feature Decisions "Home rows"). `cleanup` rows follow `cleanupAction` above — not
 * done while there's no proposal yet, or its change set's `.done` once there is. `refresh_creative`
 * and `insufficient_data` rows never count as done (feature Decisions: "refresh rows never count
 * as done" /「never done」for the insufficient-data row) — neither has a proposal flow, so both
 * fall through to the final `return false` the same way any unhandled kind always has. */
export function isQueueItemDone(item: QueueItem): boolean {
  if (item.brand_id === null) return false;
  // F29-I01（ads.md §6.33 一把尺）：看列的種類 `kind_key`，不看 triage 的趨勢 class——加預算列的
  // 那則廣告趨勢也可能是 worse，卻不是一張「變貴」決定。
  if (item.kind_key === "stop_loss") {
    return proposalAction(item.brand_id, item.triage.campaign_id, item.triage.entity_id, item.proposal).done;
  }
  if (item.kind_key === "worse") {
    return proposalAction(
      item.brand_id, item.triage.campaign_id, item.triage.entity_id, item.proposal, "review",
    ).done;
  }
  if (item.kind_key === "scale_budget" && item.scale) {
    return proposalAction(
      item.brand_id, item.triage.campaign_id, item.scale.owner.id, item.proposal, "budget",
    ).done;
  }
  if (item.kind_key === "cleanup") {
    return cleanupAction(item.brand_id, item.triage.campaign_id, item.proposal, item.action_url)?.done ?? false;
  }
  return false;
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
  const label = `${Number.isFinite(month) ? month : new Date().getMonth() + 1} 月`;
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
