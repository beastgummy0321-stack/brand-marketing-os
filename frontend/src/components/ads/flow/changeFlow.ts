/** F22-I02: shared, presentation-free logic for the v7 three-step "light" repair flow
 * (`docs/design/ads/prototype-v7-ads-center.html` `confirmPage()`/`handoff()`/`verify()`).
 * Kept separate from `ConfirmPage.tsx` so I03 (到平台完成) and I04 (核對結果) reuse the same
 * step rule and paths instead of re-deriving them. */
import type { ChangeInput, ChangeItem, ChangeKind, ChangeSet } from "@/lib/adsChangeApi";
import type { QueueItem, QueuePayload } from "@/lib/adsTriageApi";
// F25-I03: 「下一件」跨 kind 共用同一顆判斷——home 列表跟這裡的 handoff/verify 頁不能各算各的
// （feature Decisions「下一件」）。只 import，不改 `home/status.ts`（F25-I02 同時在改那支檔）。
import { isQueueItemDone, proposalAction, type ProposalAction } from "../home/status";

export type FlowStepName = "confirm" | "handoff" | "verify";

export interface FlowStep {
  step: FlowStepName;
  /** True on the confirm page when the set is terminal and not actionable (rejected / deferred /
   * superseded) — feature Decisions "Step from a change set". */
  closed: boolean;
}

/** Which of the three v7 screens a change set currently belongs on, mirroring the prototype's
 * `state(q)` for the `light` flow (the six-step `review` flow is a different feature). Approved
 * sets split on the single item's `verification_state`/`reported_at` per feature Decisions —
 * multi-item sets are handled by the caller (they link out instead of rendering). */
export function stepFromChangeSet(set: ChangeSet): FlowStep {
  if (set.status === "draft") return { step: "confirm", closed: false };
  if (set.status === "rejected" || set.status === "deferred" || set.status === "superseded") {
    return { step: "confirm", closed: true };
  }
  const item = set.items[0];
  if (item && item.verification_state === "pending" && item.reported_at === null) {
    return { step: "handoff", closed: false };
  }
  return { step: "verify", closed: false };
}

const brandPath = (brandId: string) => `/brands/${encodeURIComponent(brandId)}`;
const campaignPath = (brandId: string, campaignId: string) =>
  `${brandPath(brandId)}/ads/campaigns/${encodeURIComponent(campaignId)}`;

/** `changes/:setId/confirm|handoff|verify` — the canonical route once a change set exists
 * (feature Decisions "Agent choice — routes"). */
export function changeStepPath(brandId: string, campaignId: string, setId: string, step: FlowStepName): string {
  return `${campaignPath(brandId, campaignId)}/changes/${encodeURIComponent(setId)}/${step}`;
}

/** `propose/pause/:entityId` — the confirm page for a proposal that has no change set yet. */
export function proposePausePath(brandId: string, campaignId: string, entityId: string): string {
  return `${campaignPath(brandId, campaignId)}/propose/pause/${encodeURIComponent(entityId)}`;
}

/** `propose/budget/:entityId` — same idea as `proposePausePath`, `entityId` here is the scale row's
 * `scale.owner.id` (an adset or a campaign), never an ad (F25-I03, feature Decisions "Confirm page
 * budget propose mode"). */
export function proposeBudgetPath(brandId: string, campaignId: string, ownerId: string): string {
  return `${campaignPath(brandId, campaignId)}/propose/budget/${encodeURIComponent(ownerId)}`;
}

/** F25-I01 Home rows Decisions: a `refresh_creative` row's button always goes here — there is no
 * change-set flow for it, so it never routes through `changeStepPath`/`proposeBudgetPath`. */
export function materialWorkbenchPath(brandId: string, campaignId: string): string {
  return `${campaignPath(brandId, campaignId)}?tab=assets&material_new=1`;
}

/** Multi-item sets, and any change-item kind this flow doesn't render, fall back to the existing
 * workspace change list instead of being re-interpreted (feature Decisions "Multi-item sets"). */
export function campaignChangesPath(brandId: string, campaignId: string): string {
  return `${campaignPath(brandId, campaignId)}?tab=changes`;
}

/** Feature Decisions "Agent choice — the draft is created lazily": the one fixed reason this
 * batch's single kind (`pause`) proposes. */
export const PAUSE_REASON = "花費超過停損線（目標 × 3）仍未達成目標";

export function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

/** `title = 暫停「<ad name, cut to 60 chars; null → 未命名廣告>」`. */
export function pauseTitle(adName: string | null): string {
  return `暫停「${truncate(adName ?? "未命名廣告", 60)}」`;
}

export function buildPauseDraftItem(entityId: string): ChangeInput {
  return { kind: "pause", target_id: entityId, after: { status: "PAUSED" }, reason: PAUSE_REASON };
}

/** F25-I03: the one fixed reason a `scale_budget` row proposes (feature Decisions "Confirm page
 * budget propose mode" — "Lazy create on first write"). */
export const BUDGET_REASON = "近兩期成本都在目標內，加碼 20% 擴量";

/** `title = 加碼「<owner name, cut to 60 chars; null → 未命名投放組>」`，同 `pauseTitle` 的做法。 */
export function budgetTitle(ownerName: string | null): string {
  return `加碼「${truncate(ownerName ?? "未命名投放組", 60)}」`;
}

export function buildBudgetDraftItem(ownerId: string, to: number): ChangeInput {
  return { kind: "budget", target_id: ownerId, after: { daily_amount: to }, reason: BUDGET_REASON };
}

// F25-I03: `app/ads/change_control.py::approve` maps every `ValueError` it raises to the same
// `409 change_control_unavailable` — there is no `code` telling "premise changed" (which should
// rebuild once) apart from "the month budget can't take this" (which should not, feature
// Decisions "a 409 from approve about the month budget shows the backend message and does NOT
// rebuild"). These three are the only messages `app/ads/month_budget.py::preflight` ever raises —
// matched verbatim rather than guessed at, same duplication style as `QueueRow.tsx`'s
// `STOP_LOSS_SPEND_MULTIPLE` comment.
const MONTH_BUDGET_REJECTION_MESSAGES = new Set([
  "新增花費請在執行月份重新確認月預算與最新資料。",
  "餘額尚不確定，暫不能核准新增花費；可補資料、檢視或核准降低風險的操作。",
  "這份變更超過本月總額；尚未讀回完成的降額不能先釋放額度。",
]);
export function isMonthBudgetRejection(message: string): boolean {
  return MONTH_BUDGET_REJECTION_MESSAGES.has(message);
}

/** Rebuilding a draft after approve answers a conflict (feature Decisions: "the page rebuilds the
 * draft once with a NEW operation_id and supersedes_id = the old set") resends the same items. */
export function toChangeInput(item: ChangeItem): ChangeInput {
  return { kind: item.kind as ChangeKind, target_id: item.target_id, after: item.after, reason: item.reason };
}

/** Money formatting for the pause card's meter caption — same honest-null convention as
 * `home/QueueRow.tsx` (spend/counts are measured values missing "累積中"; target/stop-loss lines
 * are configuration values missing "尚未設定"). Not imported from there: `QueueRow.tsx` keeps its
 * own copy as its own module-private helper (feature Decisions). */
export function formatAmount(value: number | null): string {
  if (value === null) return "累積中";
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}
export function formatTargetAmount(value: number | null): string {
  if (value === null) return "尚未設定";
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

/** Which queue row a change set's single item belongs to (matched the same way `ConfirmPage`
 * does it): reused by I03/I04 so the "第 N 件／共 M 件" context chip doesn't get re-derived per
 * page (feature Decisions "Gaps, shown honestly, not faked"). `null` when the set has no items,
 * or its target has left the queue. */
export function findFlowTriageItem(queue: QueuePayload | null, changeSet: ChangeSet | null): QueueItem | null {
  if (!queue || !changeSet) return null;
  const targetId = changeSet.items[0]?.target_id;
  return queue.items.find((i) => i.proposal?.change_set_id === changeSet.id || i.triage.entity_id === targetId) ?? null;
}

export function flowPosition(queue: QueuePayload | null, item: QueueItem | null): { pos: number; total: number } | null {
  if (!queue || !item) return null;
  return { pos: queue.items.indexOf(item) + 1, total: queue.items.length };
}

/** F25-I03: the id that identifies "which thing" a queue row is about, for the four `kind_key`s —
 * an ad for `stop_loss`/`worse`, the budget owner (adset/campaign) for `scale_budget`, the campaign
 * for `refresh_creative`. `ConfirmPage`'s `entityId` route param and `nextOpenQueueItem` both use
 * this so "is this the same row as the one I'm on" agrees everywhere. */
export function queueItemEntityId(item: QueueItem): string {
  if (item.kind_key === "scale_budget" && item.scale) return item.scale.owner.id;
  if (item.kind_key === "refresh_creative" && item.refresh) return item.refresh.campaign_id;
  return item.triage.entity_id;
}

/** 「下一件」（F25-I03，feature Decisions）：佇列順序中第一個還沒完成
 * (`home/status.ts::isQueueItemDone`) 且識別碼跟目前這件不同的項目，同原型 `nextOf` 的做法
 * （`open().find(q=>q.id!==id)`——從頭找第一個「開著、不是自己」的，不是「陣列位置上的下一個」）。
 * `stop_loss`／`worse`／已有提議的 `scale_budget` 都直接交給 `proposalAction`（跟首頁同一份規則，
 * feature Decisions「budget 分支＝pause 分支」）；`scale_budget` 還沒建草稿時的正確連結是
 * `propose/budget/:ownerId`（`proposalAction` 的 null-proposal 分支目前寫死 `propose/pause`，
 * 那個分支的既有行為是給 `stop_loss` 用的，不在這裡動 `home/status.ts` 去改它），`refresh_creative`
 * 從來沒有 change-set 流程可走，兩種都在這裡直接組——不硬套一個 `proposalAction` 目前接不住的
 * kind 字串。 */
export function nextOpenQueueItem(queue: QueuePayload | null, currentEntityId: string | undefined): ProposalAction | null {
  if (!queue) return null;
  const next = queue.items.find((item) => !isQueueItemDone(item) && queueItemEntityId(item) !== currentEntityId);
  if (!next || next.brand_id === null) return null;
  if (next.kind_key === "refresh_creative") {
    return { label: "準備新素材", href: materialWorkbenchPath(next.brand_id, next.triage.campaign_id), done: false };
  }
  if (next.kind_key === "scale_budget" && next.proposal === null) {
    return { label: "看提議", href: proposeBudgetPath(next.brand_id, next.triage.campaign_id, queueItemEntityId(next)), done: false };
  }
  const kind = next.kind_key === "worse" ? "review" : "pause";
  return proposalAction(next.brand_id, next.triage.campaign_id, queueItemEntityId(next), next.proposal, kind);
}
