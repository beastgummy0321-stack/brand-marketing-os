/** F22-I02: shared, presentation-free logic for the v7 three-step "light" repair flow
 * (`docs/design/ads/prototype-v7-ads-center.html` `confirmPage()`/`handoff()`/`verify()`).
 * Kept separate from `ConfirmPage.tsx` so I03 (到平台完成) and I04 (核對結果) reuse the same
 * step rule and paths instead of re-deriving them. */
import type { ChangeInput, ChangeItem, ChangeKind, ChangeSet } from "@/lib/adsChangeApi";
import type { QueueCleanupAd, QueueItem, QueuePayload } from "@/lib/adsTriageApi";
// F25-I03: 「下一件」跨 kind 共用同一顆判斷——home 列表跟這裡的 handoff/verify 頁不能各算各的
// （feature Decisions「下一件」）。只 import，不改 `home/status.ts`（F25-I02 同時在改那支檔）。
import { decisionPosition, isQueueItemDone, proposalAction, type ProposalAction } from "../home/status";

export type FlowStepName = "confirm" | "handoff" | "verify";

export interface FlowStep {
  step: FlowStepName;
  /** True on the confirm page when the set is terminal and not actionable (rejected / deferred /
   * superseded) — feature Decisions "Step from a change set". */
  closed: boolean;
}

/** Which of the three v7 screens a change set currently belongs on, mirroring the prototype's
 * `state(q)` for the `light` flow (the six-step `review` flow is a different feature). Approved
 * sets split on `verification_state`/`reported_at` per feature Decisions — F27-I15 generalises
 * this from "the single item" to "every item" so a multi-item cleanup set (Contract F) routes the
 * same way a single-item set always has: still on "handoff" while ANY item hasn't even been
 * reported yet, "verify" once every item has (a `new_ad` item's own `reported_at` never gets set
 * by this flow at all — its handoff goes through `ads_handoff_item`/`ManualHandoffPanel` instead,
 * see `NewAdHandoffPanel.tsx` — so it only ever leaves "pending" once its readback aggregate
 * lands, which is exactly when `verification_state` itself stops being `"pending"`). For a
 * single-item set this is byte-for-byte the same rule the code had before. */
export function stepFromChangeSet(set: ChangeSet): FlowStep {
  if (set.status === "draft") return { step: "confirm", closed: false };
  if (set.status === "rejected" || set.status === "deferred" || set.status === "superseded") {
    return { step: "confirm", closed: true };
  }
  if (set.items.length === 0) return { step: "verify", closed: false };
  const stillHandoff = set.items.some((i) => i.verification_state === "pending" && i.reported_at === null);
  return { step: stillHandoff ? "handoff" : "verify", closed: false };
}

const STEP_ORDER: Record<FlowStepName, number> = { confirm: 0, handoff: 1, verify: 2 };

/** F47-I07 (drill-10 C3-E): what a step page does with the set it opened. The set's own step renders as usual; an
 * earlier step of an approved set (the user followed 「回到確認」／「回到在平台完成」) renders read-only with `ahead`
 * = where the set really is now, instead of bouncing back; a step the set has not reached yet, or any step but
 * confirm for a draft／closed set, redirects to the set's own step. */
export function stepRoute(set: ChangeSet, page: FlowStepName): { redirect: FlowStepName | null; ahead: FlowStepName | null } {
  const { step } = stepFromChangeSet(set);
  if (step === page) return { redirect: null, ahead: null };
  if (set.status === "approved" && STEP_ORDER[page] < STEP_ORDER[step]) return { redirect: null, ahead: step };
  return { redirect: step, ahead: null };
}

/** The forward link on a read-only earlier step (`stepRoute(...).ahead`). */
export const AHEAD_LABEL: Record<FlowStepName, string> = { confirm: "回到確認", handoff: "接著到平台完成", verify: "看核對結果" };

/** F27-I15 Contract F: `QueueKind`/`QueueItem.kind_key`'s own TypeScript type in `adsTriageApi.ts`
 * (out of this issue's touch) is deliberately one value narrower than what real responses carry —
 * that file's own comment says widening it to include `"cleanup"` is "deferred to the frontend
 * issue that builds that row's UI", which is this one. Comparing `kind_key` straight to the
 * literal `"cleanup"` would fail to compile (TS2367, the two types have no overlap) until that
 * type widens; routing the value through a `string`-typed parameter first type-checks without a
 * cast at every call site, and without editing `adsTriageApi.ts`. */
function isCleanupKind(kindKey: string): boolean {
  return kindKey === "cleanup";
}

/** F27-I15 Contract F: a multi-item cleanup set is only ever recognised through the queue's own
 * `cleanup` row (matched the same way `findFlowTriageItem` already matches any kind) — never by
 * guessing from the set's own item shape. A generic multi-`pause` set (different ads, no cleanup
 * row behind it) must keep falling through to the existing "多項變更" workspace link, so this is
 * a lookup, not a `items.every(kind==="pause")` heuristic. */
export function isCleanupTriageItem(item: QueueItem | null): boolean {
  return !!item && isCleanupKind(item.kind_key);
}

const brandPath = (brandId: string) => `/brands/${encodeURIComponent(brandId)}`;
const campaignPath = (brandId: string, campaignId: string) =>
  `${brandPath(brandId)}/ads/campaigns/${encodeURIComponent(campaignId)}`;

/** `changes/:setId/confirm|handoff|verify` — the canonical route once a change set exists
 * (feature Decisions "Agent choice — routes"). */
export function changeStepPath(brandId: string, campaignId: string, setId: string, step: FlowStepName): string {
  return `${campaignPath(brandId, campaignId)}/changes/${encodeURIComponent(setId)}/${step}`;
}

/** F45-I06 (ads.md §6.49): where a pause entry came from, for the pause page's back link — the 成效 tab, a
 * review round (`ref` = review id) or a set's 核對結果 step (`ref` = set id). No `from` = the home queue. */
export type PauseFrom = "perf" | "review" | "verify";

/** `propose/pause/:entityId` — the confirm page for a proposal that has no change set yet. F45-I06: an entry
 * other than the home queue adds `?from=…&ref=…` so the page's back link returns there. */
export function proposePausePath(brandId: string, campaignId: string, entityId: string, from?: PauseFrom, ref?: string): string {
  const path = `${campaignPath(brandId, campaignId)}/propose/pause/${encodeURIComponent(entityId)}`;
  if (!from) return path;
  const query = new URLSearchParams({ from, ...(ref ? { ref } : {}) });
  return `${path}?${query.toString()}`;
}

/** `propose/budget/:entityId` — same idea as `proposePausePath`, `entityId` here is the scale row's
 * `scale.owner.id` (an adset or a campaign), never an ad (F25-I03, feature Decisions "Confirm page
 * budget propose mode"). */
export function proposeBudgetPath(brandId: string, campaignId: string, ownerId: string): string {
  return `${campaignPath(brandId, campaignId)}/propose/budget/${encodeURIComponent(ownerId)}`;
}

/** `propose/cleanup/:campaignId` — F27-I15 Contract F. The backend's own queue row already sends
 * the campaign id twice (`app/ads/triage.py::_cleanup_candidates` — `.../campaigns/{c}/propose/
 * cleanup/{c}`, pre-dispatch correction); the route carries a second, unused param only so that
 * exact link works, this builder mirrors the same shape rather than only emitting the first
 * segment. */
export function cleanupProposePath(brandId: string, campaignId: string): string {
  return `${campaignPath(brandId, campaignId)}/propose/cleanup/${encodeURIComponent(campaignId)}`;
}

/** F25-I01 Home rows Decisions: a `refresh_creative` row's button always goes here — there is no
 * change-set flow for it, so it never routes through `changeStepPath`/`proposeBudgetPath`. */
export function materialWorkbenchPath(brandId: string, campaignId: string): string {
  return `${campaignPath(brandId, campaignId)}?tab=assets&material_new=1`;
}

/** F29-I14: the campaign detail page (`…/campaigns/:c/detail`, v10 `#/camp/<c>/perf`) — where an A/B pair's
 * 「關掉輸家」 proposal starts, so an `ab` set's confirm step goes back there (prototype `back: ["成效", …]`). */
export function campaignDetailPath(brandId: string, campaignId: string): string {
  return `${campaignPath(brandId, campaignId)}/detail`;
}

/** F29-I14 Contract F: an A/B "pause the loser" set names itself (`source: "ab"`); its flow is 確認 → 到平台完成 →
 * 核對結果 (prototype v10 `stepsOf()` for kind `ab` — the performance card is the proposal). */
export function isAbSet(set: ChangeSet | null | undefined): boolean {
  return set?.source === "ab" && Boolean(set.ab);
}
export function abSteps(confirmHref?: string, handoffHref?: string): { label: string; to?: string }[] {
  return [{ label: "確認", to: confirmHref }, { label: "到平台完成", to: handoffHref }, { label: "核對結果" }];
}

/** Multi-item sets, and any change-item kind this flow doesn't render, fall back to the existing
 * workspace change list instead of being re-interpreted (feature Decisions "Multi-item sets"). */
export function campaignChangesPath(brandId: string, campaignId: string): string {
  return `${campaignPath(brandId, campaignId)}?tab=changes`;
}

/** F48 Contract R "reason texts": a draft's reason is the sentence the backend built from that ad's (or owner's) own
 * grade and numbers — `pause_view.reason_text`, a cleanup entry's `reason_text`, `scale.reason_text`. The frontend
 * never writes a reason of its own (drill 11 c3-09: a 太貴 ad was paused 「花到上限 3 倍…還一筆都沒賣出」). A missing
 * sentence (an older backend) refuses the write instead of inventing one. */
export function servedReason(text: string | null | undefined): string {
  const trimmed = text?.trim();
  if (!trimmed) throw new Error("這件提議的理由還沒讀到，請重新整理後再試。");
  return trimmed;
}

export function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

/** `title = 暫停「<ad name, cut to 60 chars; null → 未命名廣告>」`. */
export function pauseTitle(adName: string | null): string {
  return `暫停「${truncate(adName ?? "未命名廣告", 60)}」`;
}

/** Contract C: `angle` lives beside `kind`/`target_id`/`after`/`reason` on a pause item itself
 * (`app/ads/change_control_data.py::build_item`'s key whitelist, correction 7) -- part of
 * `content_hash`/`premise_hash` like every other item field, but never inside `after`
 * (`SettingValues`). `adsChangeApi.ts`'s `ChangeInput`/`ChangeItem` (out of this issue's touch)
 * don't carry it in their TS shape yet; read/write it through a local widening at the call site,
 * same technique `ConfirmPage.tsx`'s `source: "cleanup"` widening already uses (F27-I15) rather
 * than editing that file. */
export type ChangeItemAngle = ChangeItem & { angle?: string | null };
export function itemAngle(item: ChangeItem | undefined | null): string | null {
  if (!item) return null;
  return (item as ChangeItemAngle).angle ?? null;
}

export function buildPauseDraftItem(entityId: string, reason: string, angle?: string | null): ChangeInput {
  const trimmed = angle?.trim();
  return {
    kind: "pause", target_id: entityId, after: { status: "PAUSED" }, reason,
    ...(trimmed ? { angle: trimmed } : {}),
  } as ChangeInput;
}

/** `title = 清理「<campaign name, cut to 60 chars; null → 未命名活動>」`，同 `pauseTitle`／
 * `budgetTitle` 的做法。 */
export function cleanupTitle(campaignName: string | null): string {
  return `清理「${truncate(campaignName ?? "未命名活動", 60)}」`;
}

/** F27-I15 Contract F: the lazily-created cleanup set's own items — one `pause` item per proposed
 * ad, in the order the queue row's own `cleanup.ads` already carries (F28-I02, ads.md §6.32:
 * every 沒賣出 ad first, then the over-cap ads 太貴 before 偏貴, most expensive per result first;
 * 划算 and ungraded ads are never in the list). F48 Contract R: each item's reason is that ad's own served
 * `reason_text` (「第 r／n 名，每筆 X 對上限 Y（太貴）」／「花了 X，一筆都沒賣出」). */
export function buildCleanupDraftItems(ads: QueueCleanupAd[]): ChangeInput[] {
  return ads.map((ad) => buildPauseDraftItem(ad.entity_id, servedReason(ad.reason_text)));
}

/** `title = 加碼「<owner name, cut to 60 chars; null → 未命名投放組>」`，同 `pauseTitle` 的做法。 */
export function budgetTitle(ownerName: string | null): string {
  return `加碼「${truncate(ownerName ?? "未命名投放組", 60)}」`;
}

/** F48 Contract R: the reason is the scale row's served `scale.reason_text`. */
export function buildBudgetDraftItem(ownerId: string, to: number, reason: string): ChangeInput {
  return { kind: "budget", target_id: ownerId, after: { daily_amount: to }, reason };
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
  const angle = itemAngle(item);
  return {
    kind: item.kind as ChangeKind, target_id: item.target_id, after: item.after, reason: item.reason,
    ...(angle ? { angle } : {}),
  } as ChangeInput;
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
  // F47-I07 (drill-10 Q1): a row is matched by its own identity (`queueItemEntityId`), never by the `triage` ad it
  // carries for display — a cleanup or 資料不足 row carries the campaign's first ad there.
  return queue.items.find((i) => i.proposal?.change_set_id === changeSet.id || queueItemEntityId(i) === targetId) ?? null;
}

/** 「第 N 件／共 M 件」: F47-I07 — counted by the home board's owner (`home/status.ts::decisionPosition`, open home
 * decisions by the row's own `done`), the same number the home and the top bar show; never every queue row. */
export function flowPosition(queue: QueuePayload | null, item: QueueItem | null): { pos: number; total: number } | null {
  return decisionPosition(queue, item);
}

/** F25-I03: the id that identifies "which thing" a queue row is about, for the four `kind_key`s —
 * an ad for `stop_loss`/`worse`, the budget owner (adset/campaign) for `scale_budget`, the campaign
 * for `refresh_creative`. `ConfirmPage`'s `entityId` route param and `nextOpenQueueItem` both use
 * this so "is this the same row as the one I'm on" agrees everywhere. */
export function queueItemEntityId(item: QueueItem): string {
  if (item.kind_key === "scale_budget" && item.scale) return item.scale.owner.id;
  if (item.kind_key === "refresh_creative" && item.refresh) return item.refresh.campaign_id;
  // F27-I15 Contract F: a `cleanup` row's own identity is the campaign, not any one ad
  // (`app/ads/triage.py::_cleanup_candidates`'s `identity_id`) — same reasoning as the two kinds
  // above.
  if (isCleanupKind(item.kind_key) && item.cleanup) return item.cleanup.campaign_id;
  // F47-I07 (drill-10 Q1): a 資料不足 row is about the campaign too; its `triage` is only the campaign's first ad.
  if (item.kind_key === "insufficient_data" && item.insufficient) return item.insufficient.campaign_id;
  return item.triage.entity_id;
}

/** 「下一件」（F25-I03，feature Decisions）：佇列順序中第一個還沒完成
 * （列自己的 `done`，F47 Contract D，`home/status.ts::isQueueItemDone`）且識別碼跟目前這件不同的項目，同原型 `nextOf` 的做法
 * （`open().find(q=>q.id!==id)`——從頭找第一個「開著、不是自己」的，不是「陣列位置上的下一個」）。
 * `stop_loss`／`worse`／已有提議的 `scale_budget` 都直接交給 `proposalAction`（跟首頁同一份規則，
 * feature Decisions「budget 分支＝pause 分支」）；`scale_budget` 還沒建草稿時的正確連結是
 * `propose/budget/:ownerId`（`proposalAction` 的 null-proposal 分支目前寫死 `propose/pause`，
 * 那個分支的既有行為是給 `stop_loss` 用的，不在這裡動 `home/status.ts` 去改它），`refresh_creative`
 * 從來沒有 change-set 流程可走，兩種都在這裡直接組——不硬套一個 `proposalAction` 目前接不住的
 * kind 字串。F47-I07（drill-10 Q1）：`資料不足` 列一樣沒有提議流程，走它自己的 `action_url`（等資料頁），
 * 不再被當成暫停提議組出 `propose/pause/<活動第一則廣告>`。 */
export function nextOpenQueueItem(queue: QueuePayload | null, currentEntityId: string | undefined): ProposalAction | null {
  if (!queue) return null;
  const next = queue.items.find((item) => !isQueueItemDone(item) && queueItemEntityId(item) !== currentEntityId);
  if (!next || next.brand_id === null) return null;
  if (next.kind_key === "refresh_creative") {
    return { label: "準備新素材", href: materialWorkbenchPath(next.brand_id, next.triage.campaign_id), done: false };
  }
  if (next.kind_key === "insufficient_data") {
    return next.action_url ? { label: "去處理", href: next.action_url, done: false } : null;
  }
  if (next.kind_key === "scale_budget" && next.proposal === null) {
    return { label: "看提議", href: proposeBudgetPath(next.brand_id, next.triage.campaign_id, queueItemEntityId(next)), done: false };
  }
  // F27-I15 Contract F: same "null-proposal owns its own link" shape as `scale_budget` above —
  // `proposalAction`'s null-proposal branch is hard-coded to `propose/pause` (that branch's
  // existing behaviour belongs to `stop_loss`, not touched here). Once a cleanup set exists, fall
  // through to that generic call for its label/step, same as every other kind.
  if (isCleanupKind(next.kind_key) && next.proposal === null) {
    return { label: "看提議", href: cleanupProposePath(next.brand_id, next.triage.campaign_id), done: false };
  }
  const kind = next.kind_key === "worse" ? "review" : "pause";
  return proposalAction(next.brand_id, next.triage.campaign_id, queueItemEntityId(next), next.proposal, kind);
}
