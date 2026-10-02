import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import {
  approveChangeSet,
  createChangeSet,
  decideChangeSet,
  getChangeControl,
  getMonthlyBudget,
  ChangeRequestRejected,
  type ChangeDraft,
  type ChangeSet,
  type MonthlyBudget,
} from "@/lib/adsChangeApi";
import { getQueue, type QueueItem } from "@/lib/adsTriageApi";
import { getAngles, type AnglesResponse } from "@/lib/adsAnglesApi";
import { useApiRead } from "@/lib/useApiRead";
import { currentBudgetMonth } from "../MonthlyBudgetPanel";
import { useOrgClock } from "@/lib/orgClock";
import { reviewRoundPath } from "../review/reviewFlow";
import { ActionBar, CampaignChip, Chip, DecisionSheet, FlowHeader, GradeRules, MoneyRule, ReadFailed, Segmented } from "../patterns";
import { AbEvidence, abApproveLabel, useAbContext } from "./AbEvidence";
import { CleanupEvidence } from "./CleanupEvidence";
import { CleanupProposal, cleanupSteps } from "./CleanupProposal";
import { AdoptLatestButton } from "./CleanupRebuild";
import { createCleanupSet, declinedIdsOf, samePick, useCleanupPick, useCleanupRebuild } from "./cleanupDraft";
import { NewAdEvidence } from "./NewAdEvidence";
import { ANGLE_MAX, BudgetEvidence, CopyEvidence, PauseEvidence, PauseGone, PauseLearnCard } from "./confirmParts";
import { closedNote, monthDay, pauseBack, usePauseView, windowText } from "./usePauseView";
import {
  buildBudgetDraftItem,
  buildPauseDraftItem,
  budgetTitle,
  abSteps,
  campaignChangesPath,
  campaignDetailPath,
  changeStepPath,
  cleanupProposePath,
  isAbSet,
  isCleanupTriageItem,
  isMonthBudgetRejection,
  itemAngle,
  nextOpenQueueItem,
  pauseTitle,
  queueItemEntityId,
  stepFromChangeSet,
  toChangeInput,
} from "./changeFlow";

const STEPS = [{ label: "確認提議" }, { label: "到平台完成" }, { label: "核對結果" }];
const STEP_PURPOSE = "核准後才到平台操作";

type DecisionKind = "rejected" | "deferred";
type QuickPick = "3" | "7" | "custom";

/** 確認提議頁（F22-I02，v7 原型 `confirmPage()`＋拒絕／暫緩 sheet；budget 分支 F25-I03）。兩條
 * 路由共用同一支元件：`entityId`（propose route）還沒有 change set，草稿只在第一次核准／拒絕／
 * 暫緩時才建立（feature Decisions「Agent choice — the draft is created lazily」，never on page
 * load）；`setId`（changes route）已經有 change set，直接讀。`proposeKind` 只在 `entityId` 進來、
 * 還沒有 change set 時分辨這是暫停提議還是加預算提議（`item` 這時還不存在，不能靠
 * `item.kind` 分支）——`setId` 進來時一律讀 `changeSet` 自己的 kind，不受這個參數影響。任何非
 * confirm 的步驟都由這裡導去正確步驟（`changeFlow.ts::stepFromChangeSet`），也同時把 propose
 * 網址收斂成正典的 changes 網址。 */
export function ConfirmPage({ brandId, campaignId, entityId, setId, proposeKind = "pause" }: {
  brandId: string; campaignId: string; entityId?: string; setId?: string; proposeKind?: "pause" | "budget" | "cleanup";
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { timezone } = useOrgClock();
  const homeHref = `/brands/${brandId}/ads`;

  // Contract K: the queue is its own read. On the propose routes it is the page's content; on a set's route it is
  // context (position, live numbers) — either way a failure is shown, never read as "no proposal".
  const [reloadKey, setReloadKey] = useState(0);
  const queueRead = useApiRead((signal) => getQueue(brandId, signal), [brandId, campaignId, setId, reloadKey]);
  const queue = queueRead.data;
  const [changeSet, setChangeSet] = useState<ChangeSet | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // F27-I15 Contract F: `propose/cleanup/:campaignId` never carries an `entityId` (the campaign
  // id is already a prop) — a third branch alongside the existing budget/pause ones.
  const [operationId] = useState(() => {
    if (entityId && proposeKind === "budget") return `triage-budget:${entityId}:${crypto.randomUUID()}`;
    if (proposeKind === "cleanup") return `triage-cleanup:${campaignId}:${crypto.randomUUID()}`;
    return `triage-pause:${entityId ?? ""}:${crypto.randomUUID()}`;
  });
  const [busy, setBusy] = useState(false);
  // The page is keyed by its URL, so an approve error must ride the canonical redirect in router
  // state — otherwise a rebuild-then-fail lands on a fresh instance with the message gone.
  const [actionError, setActionError] = useState<string | null>(() => (location.state as { actionError?: string } | null)?.actionError ?? null);

  const [sheetOpen, setSheetOpen] = useState(false);
  const [decisionKind, setDecisionKind] = useState<DecisionKind>("deferred");
  const [reason, setReason] = useState("想再觀察幾天");
  const [quickPick, setQuickPick] = useState<QuickPick>("7");
  const [customDate, setCustomDate] = useState("");
  const [sheetError, setSheetError] = useState<string | null>(null);

  useEffect(() => {
    if (!setId) { setLoading(false); return; }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    getChangeControl(brandId, campaignId)
      .then((data) => { if (!cancelled) setChangeSet(data.change_sets.find((s) => s.id === setId) ?? null); })
      .catch((err) => { if (!cancelled) setLoadError(err instanceof Error ? err.message : "讀取這份變更清單失敗，請稍後再試。"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [brandId, campaignId, setId, reloadKey]);
  const queueFailed = queueRead.status === "error";
  // F45-I06 (ads.md §6.49): the pause propose route reads the ad itself (Contract P); the queue only adds the
  // position, and its failure drops the position, never the page. Budget／cleanup proposals still read the queue.
  const pauseMode = Boolean(entityId) && !setId && proposeKind === "pause";
  const pauseRead = usePauseView(brandId, campaignId, pauseMode ? entityId ?? null : null);
  const pauseView = pauseMode ? pauseRead.data : null;
  const back = pauseBack(brandId, campaignId, searchParams.get("from"), searchParams.get("ref"));

  const triageItem: QueueItem | null = useMemo(() => {
    if (!queue) return null;
    if (entityId) {
      // F25-I03：加預算的 propose 網址帶的是 `scale.owner.id`（投放組／活動），不是廣告的
      // `triage.entity_id`——兩種 id 空間不同，不能沿用暫停提議那顆比對式（feature Decisions
      // 「Confirm page budget propose mode」：route 讀 `scale.owner.id === entityId`）。
      if (proposeKind === "budget") {
        return queue.items.find((i) => i.kind_key === "scale_budget" && i.scale?.owner.id === entityId) ?? null;
      }
      return queue.items.find((i) => i.triage.entity_id === entityId) ?? null;
    }
    // F27-I15 Contract F: the cleanup propose route has no `entityId` — its own identity is the
    // campaign, matched through the queue's `cleanup` row directly (`item.cleanup.campaign_id`,
    // same field `changeFlow.ts::queueItemEntityId` reads for this `kind_key`).
    if (!setId && proposeKind === "cleanup") {
      return queue.items.find((i) => isCleanupTriageItem(i) && i.cleanup?.campaign_id === campaignId) ?? null;
    }
    const targetId = changeSet?.items[0]?.target_id;
    return queue.items.find((i) =>
      (changeSet && i.proposal?.change_set_id === changeSet.id) || i.triage.entity_id === targetId || i.scale?.owner.id === targetId,
    ) ?? null;
  }, [queue, entityId, proposeKind, changeSet, setId, campaignId]);
  const position = queue && triageItem ? { pos: queue.items.indexOf(triageItem) + 1, total: queue.items.length } : null;
  // F27-I15 Contract F: a cleanup set names itself (`source: "cleanup"`, F29-I04), so a failed queue read cannot turn
  // it into a "multi-item" set; the queue's own `cleanup` row still recognises a propose-route cleanup.
  const cleanupSet = changeSet?.source === "cleanup" || isCleanupTriageItem(triageItem);
  const isCleanupPropose = !entityId && !setId && proposeKind === "cleanup";
  // F29-I14: the user's ticks on the cleanup proposal (URL `?keep=`), and an A/B set's context reads.
  const pick = useCleanupPick(isCleanupPropose ? triageItem?.cleanup : null);
  const abSet = !cleanupSet && isAbSet(changeSet);
  const abContext = useAbContext(brandId, campaignId, abSet ? changeSet?.ab : null);

  // F27-I16: `closed`／`item`／`kind`／`blocked` used to be computed after the loading／error
  // guards below (they only ever needed `changeSet`, never the guards' own state) — moved up here
  // so the angle-fetching hooks right after them can read `kind`／`closed` too, without a hook
  // ending up after a conditional `return` (React's hook-order rule; `useEffect` can't move below
  // the guards instead).
  const { closed } = changeSet ? stepFromChangeSet(changeSet) : { closed: false };
  const item = changeSet && changeSet.items.length === 1 ? changeSet.items[0] : undefined;
  // `item` 在 propose 模式、change set 還沒建立前是 `undefined`（草稿延遲建立），這時 kind 由
  // 路由本身的 `proposeKind` 決定，不能沿用舊的「沒有 item 就當 pause」（F25-I03 之前唯一的
  // propose kind 只有 pause，這裡是新加的分支）。F27-I15：cleanup 是多項清單，沒有單一 `item`
  // 可讀，`cleanupSet`（佇列比對，不是內容猜測）優先於這整套 `item`／`proposeKind` 判斷。
  const kind = cleanupSet ? "cleanup" : abSet ? "ab" : item ? item.kind : entityId ? proposeKind : "pause";
  const blocked = changeSet !== null && !cleanupSet
    && (changeSet.items.length !== 1 || !["pause", "copy", "budget", "new_ad", "ab"].includes(kind));

  // Contract C / correction 9: 「一則廣告一次 copy hash 一顆 LLM call，暫停提議頁一開就打」——
  // `entityId`（propose 網址）或既有草稿的 `item.target_id` 都是同一則廣告的 id；`!closed` 只是
  // 不在已經拒絕／暫緩、不會再送出的清單上浪費呼叫（核准之後這頁本來就會被 `stepFromChangeSet`
  // 導去 handoff／verify，不會停留在這裡）。
  const pauseEntityId = kind !== "pause" || (pauseMode && pauseView?.state !== "active") ? null
    : (entityId ?? item?.target_id ?? triageItem?.triage.entity_id ?? null);
  const [angleChoice, setAngleChoice] = useState("");
  const [angleCustomOpen, setAngleCustomOpen] = useState(false);
  // `item` narrowed to `item?.id`：整個 `item` 物件每次 `getChangeControl` 重新讀取都是新的參照，只有身分（id）
  // 真的換了才需要重置選取狀態或重打一次 `getAngles`。A failed request stays a failed read (Contract K), shown
  // with 重試 — it is not the backend's own `failed` judgement.
  const angleRead = useApiRead<AnglesResponse | null>(
    () => (kind === "pause" && !closed && pauseEntityId ? getAngles(brandId, campaignId, pauseEntityId) : Promise.resolve(null)),
    [kind, closed, pauseEntityId, brandId, campaignId, item?.id],
  );
  const angleData = angleRead.data;
  useEffect(() => {
    setAngleChoice(itemAngle(item) ?? "");
    setAngleCustomOpen(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- same identity list as the angle read above.
  }, [kind, closed, pauseEntityId, brandId, campaignId, item?.id]);

  // F40-I08: the month budget is read here (not inside `BudgetEvidence`) because it also decides whether 核准 can be
  // pressed — state (ii) of the 本月預算放得下 card (no month budget yet) greys the button with its reason beside it.
  // Only a budget set reads it; every other kind resolves `null` (same shape as the angle read above).
  const budgetMonth = currentBudgetMonth(timezone);
  const budgetRead = useApiRead<MonthlyBudget | null>(
    (signal) => (kind === "budget" ? getMonthlyBudget(brandId, budgetMonth, signal) : Promise.resolve(null)),
    [kind, brandId, budgetMonth],
  );
  // State (iii): the set whose approve answered 「premise changed」 (a 409 that is not a month-budget message). It
  // waits here until 重新檢查 rebuilds it — the rebuild is the existing one-shot supersede, now the user's own step
  // on the budget page instead of a silent retry (issue Done 3). Other kinds keep the silent rebuild below.
  const [premiseSet, setPremiseSet] = useState<ChangeSet | null>(null);
  // 「Rebuild once, then show the error」 survives the remount: the rebuilt set's canonical URL is a new page, so the
  // marker rides router state like `actionError` — a second 「premise changed」 on that page is shown, not re-offered.
  const [rechecked, setRechecked] = useState<boolean>(() => (location.state as { rechecked?: boolean } | null)?.rechecked ?? false);

  // feature Decisions「Step from a change set」：非 confirm 步驟的清單，或還沒對到正典
  // changes/:setId 網址的 propose 頁，都在這裡收斂——I03/I04 加了 handoff/verify 頁之後這裡
  // 才會真的把人送到那兩頁；這批只加了 propose 與 confirm 兩條路由。
  useEffect(() => {
    if (!changeSet || busy) return;
    const { step } = stepFromChangeSet(changeSet);
    const canonical = changeStepPath(brandId, campaignId, changeSet.id, step);
    if (canonical !== location.pathname) {
      navigate(canonical, { replace: true, state: actionError || rechecked ? { actionError, rechecked } : undefined });
    }
  }, [changeSet, busy, actionError, rechecked, brandId, campaignId, location.pathname, navigate]);

  // F28-I15: an outdated cleanup draft offers only 「改用最新提議」 (see `cleanupDraft.ts::useCleanupRebuild`).
  const { drift, draftProposalId, adopt } = useCleanupRebuild({
    brandId, campaignId, setId, isCleanup: kind === "cleanup",
    // A pick of the user's own (some proposed ads unticked) is approved as picked, never swapped for an older draft.
    proposeConfirmStep: isCleanupPropose && searchParams.get("step") === "confirm" && !pick.changed,
    changeSet, triageItem, busy, setBusy, setChangeSet, setActionError,
  });

  function errorMessage(err: unknown): string {
    return err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。";
  }

  /** 拿到可以動作的 change set：`changeSet` 已經有就直接用；propose 模式第一次寫入時，
   * 先看佇列列有沒有既有提議（`proposal.change_set_id`），有就重用，沒有才建立新草稿
   * （feature Decisions「first reuse proposal.change_set_id when the queue row has one」）。
   * 草稿內容依 `proposeKind` 分支：budget 一定要有 `triageItem.scale`（propose 網址只會比對到
   * `kind_key==="scale_budget"` 的列，見上面 `triageItem` 的 `useMemo`），沒有就是資料還沒讀到。
   * F29-I14: a cleanup is approved as the user ticked it (unticked ads → `declined_ids`); 拒絕／暫緩 answer the whole
   * proposal, so they carry every proposed ad. An existing draft with another pick is superseded, not reused. */
  async function ensureWorkingSet(intent: "approve" | "decide" = "approve"): Promise<ChangeSet> {
    if (changeSet) return changeSet;
    const cleanupPick = proposeKind === "cleanup" && intent === "approve" ? pick.declined : [];
    const existingId = pauseMode ? pauseView?.change_set_id : triageItem?.proposal?.change_set_id;
    if (existingId) {
      const data = await getChangeControl(brandId, campaignId);
      const found = data.change_sets.find((s) => s.id === existingId);
      const cleanup = triageItem?.cleanup;
      if (found && proposeKind === "cleanup" && cleanup && found.status === "draft" && intent === "approve" && !samePick(found, pick.ticked)) {
        return createCleanupSet(brandId, campaignId, cleanup, operationId, timezone, found.id, cleanupPick);
      }
      if (found) return found;
    }
    if (proposeKind === "budget") {
      const scale = triageItem?.scale;
      if (!scale) throw new Error("這個投放組的資料還沒讀到，請重新整理後再試。");
      return createChangeSet(brandId, campaignId, {
        operation_id: operationId,
        title: budgetTitle(scale.owner.name),
        month: currentBudgetMonth(timezone),
        items: [buildBudgetDraftItem(scale.owner.id, scale.to)],
      });
    }
    if (proposeKind === "cleanup") {
      const cleanup = triageItem?.cleanup;
      if (!cleanup) throw new Error("這個活動的清理資料還沒讀到，請重新整理後再試。");
      return createCleanupSet(brandId, campaignId, cleanup, operationId, timezone, undefined, cleanupPick);
    }
    // F45-I06: the draft is built from Contract P (the ad's own name and id), never from a queue row.
    if (!pauseView) throw new Error("這則廣告的資料還沒讀到，請重新整理後再試。");
    // Contract C: whatever the user picked (a candidate tag or the custom input) at the moment of
    // this first write — `undefined` reason keeps `buildPauseDraftItem`'s own default.
    return createChangeSet(brandId, campaignId, {
      operation_id: operationId,
      title: pauseTitle(pauseView.name ?? pauseView.triage?.name ?? null),
      month: currentBudgetMonth(timezone),
      items: [buildPauseDraftItem(pauseView.entity_id, undefined, angleChoice)],
    });
  }

  /** The one-shot rebuild after 「premise changed」: the same items under a NEW operation_id with
   * `supersedes_id` = the refused set (feature Decisions「When approve answers 409 because the premise changed」). */
  async function rebuildDraft(target: ChangeSet): Promise<ChangeSet> {
    // F27-I15: a cleanup set's rebuild must carry `source: "cleanup"` again — otherwise the
    // rebuilt draft would silently stop being the campaign's cleanup proposal (Contract F's
    // own `_matching_cleanup_set` only matches on `plan_json.source`).
    // F29-I14: the user's unticked ads ride along (Contract B), or the rebuild would forget them.
    const declined = cleanupSet ? declinedIdsOf(target) : [];
    return createChangeSet(brandId, campaignId, {
      operation_id: crypto.randomUUID(),
      title: target.title,
      month: target.month,
      items: target.items.map(toChangeInput),
      supersedes_id: target.id,
      ...(cleanupSet ? { source: "cleanup" as const } : {}),
      ...(declined.length ? { declined_ids: declined } : {}),
    } as ChangeDraft & { source?: "cleanup" });
  }

  /** `null` = the approve was refused because the premise changed and the page now waits for 重新檢查 (budget only). */
  async function approveWithRebuild(target: ChangeSet, rebuilt: boolean): Promise<ChangeSet | null> {
    try {
      return await approveChangeSet(brandId, campaignId, target);
    } catch (err) {
      // feature Decisions「When approve answers 409 because the premise changed」：只重建一次，
      // 用新的 operation_id 帶 supersedes_id 再核准一次；再失敗就照一般錯誤處理，不無限重試。
      // 月預算放不下的 409（`isMonthBudgetRejection`）不是「前提變了」，是「這個月的餘額真的不夠」
      // ——重建一份一樣內容的草稿再核准一次只會得到同一個錯誤，還多留一份沒用的草稿；這種 409
      // 直接把後端訊息顯示出來，不重建（feature Decisions「a 409 from approve about the month
      // budget shows the backend message and does NOT rebuild」）。
      if (err instanceof ChangeRequestRejected && !rebuilt && !isMonthBudgetRejection(err.message)) {
        // F40-I08 (issue Done 3): on the budget page the premise change is the 本月預算放得下 card's
        // third state — the user rebuilds with 重新檢查, 核准 stays grey with the reason beside it.
        if (kind === "budget" && !rechecked) { setPremiseSet(target); return null; }
        if (kind === "budget") throw err;
        const rebuiltSet = await rebuildDraft(target);
        setChangeSet(rebuiltSet);
        return approveWithRebuild(rebuiltSet, true);
      }
      throw err;
    }
  }

  async function handleApprove() {
    if (busy) return;
    setBusy(true);
    setActionError(null);
    try {
      const target = await ensureWorkingSet();
      const updated = await approveWithRebuild(target, false);
      if (updated) setChangeSet(updated);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  /** State (iii) 「重新檢查」: rebuild the refused set; the rebuilt draft then takes over the page (its canonical
   * confirm URL, 核准 enabled again) — nothing is approved here, that is the user's next press. */
  async function handleRecheck() {
    if (busy || !premiseSet) return;
    setBusy(true);
    setActionError(null);
    try {
      const rebuiltSet = await rebuildDraft(premiseSet);
      setPremiseSet(null);
      setRechecked(true);
      setChangeSet(rebuiltSet);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function openSheet() {
    setDecisionKind("deferred");
    setReason("想再觀察幾天");
    setQuickPick("7");
    setCustomDate("");
    setSheetError(null);
    setSheetOpen(true);
  }

  function revisitAt(): Date | null {
    if (decisionKind !== "deferred") return null;
    if (quickPick === "custom") {
      if (!customDate) return null;
      const d = new Date(customDate);
      return Number.isNaN(d.getTime()) ? null : d;
    }
    const d = new Date();
    d.setDate(d.getDate() + (quickPick === "3" ? 3 : 7));
    return d;
  }
  const revisit = revisitAt();
  const revisitValid = decisionKind !== "deferred" || (revisit !== null && revisit.getTime() > Date.now());

  async function handleSaveDecision() {
    if (busy) return;
    const trimmedReason = reason.trim();
    if (!trimmedReason) { setSheetError("請填寫原因。"); return; }
    if (!revisitValid) { setSheetError("請選一個之後的時間。"); return; }
    setBusy(true);
    setSheetError(null);
    setActionError(null);
    try {
      const target = await ensureWorkingSet("decide");
      const updated = await decideChangeSet(brandId, campaignId, target.id, {
        decision: decisionKind,
        reason: trimmedReason,
        ...(decisionKind === "deferred" ? { revisit_at: revisit!.toISOString() } : {}),
      });
      setChangeSet(updated);
      setSheetOpen(false);
    } catch (err) {
      setSheetError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const proposeRoute = Boolean(entityId || isCleanupPropose) && !pauseMode;
  const pauseTriage = pauseView?.triage ?? null;
  const crumb = pauseMode
    ? [{ label: "投放中心", href: homeHref },
      ...(pauseTriage ? [{ label: pauseTriage.campaign_name, href: `/brands/${brandId}/ads/campaigns/${campaignId}?tab=perf` }] : []),
      { label: "暫停" }]
    : [{ label: "投放中心", href: homeHref }, { label: "確認" }];
  const readLoading = pauseMode ? pauseRead.status === "loading" : queueRead.status === "loading" && !queue;
  if (loading || draftProposalId || readLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={crumb} />
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-28 w-full max-w-[560px]" />
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={crumb} />
        <EmptyState title="讀取失敗" description={loadError} onAction={() => setReloadKey((k) => k + 1)} actionLabel="重新讀取" />
      </div>
    );
  }
  if (pauseMode && pauseRead.status === "error") {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={crumb} />
        <ReadFailed what={`這則廣告的資料讀不到（${pauseRead.error}）；還沒有任何變更被寫入`} onRetry={pauseRead.reload} />
      </div>
    );
  }
  if (pauseView?.state === "gone") {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={crumb} />
        <PauseGone name={pauseView.name} lastRead={monthDay(pauseView.last_read_at, timezone)} homeHref={homeHref} />
      </div>
    );
  }
  if (proposeRoute && queueFailed) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={crumb} />
        <ReadFailed what={`這件提議的資料讀不到（${queueRead.error}）；還沒有任何變更被寫入`} onRetry={queueRead.reload} />
      </div>
    );
  }
  if (proposeRoute && !triageItem) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={crumb} />
        <EmptyState
          title={proposeKind === "budget" ? "找不到這個投放組的加預算提議" : isCleanupPropose ? "找不到這個活動的清理提議" : "找不到這則廣告的停損提議"}
          description="可能已經處理過，或資料剛好還沒同步到投放中心。"
          actionHref={homeHref}
          actionLabel="回投放中心"
          actionInternal
        />
      </div>
    );
  }
  if (setId && !changeSet) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={crumb} />
        <EmptyState
          title="找不到這份變更清單"
          description="網址可能過期，或這份清單已經被另一份取代。"
          actionHref={homeHref}
          actionLabel="回投放中心"
          actionInternal
        />
      </div>
    );
  }

  if (blocked && changeSet) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={crumb} />
        <EmptyState
          title="這份清單有多項變更"
          description="請到活動的「變更與核對」查看完整內容並逐項處理。"
          actionHref={campaignChangesPath(brandId, campaignId)}
          actionLabel="前往變更與核對"
          actionInternal
        />
      </div>
    );
  }

  // F28-I11: the cleanup light flow opens on its proposal step (提議 → 確認 → …); `?step=confirm` is the confirm step
  // of the same propose URL, so the browser's back returns to the proposal. Nothing is written before 核准.
  if (isCleanupPropose && triageItem?.cleanup && searchParams.get("step") !== "confirm") {
    return (
      <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "清理" }]} />
        <CleanupProposal brandId={brandId} campaignId={campaignId} item={{ ...triageItem, cleanup: triageItem.cleanup }} position={position} homeHref={homeHref} pick={pick} />
      </div>
    );
  }
  // The proposal step keeps the user's ticks when the confirm step goes back to it (F29-I14).
  const cleanupBackHref = kind === "cleanup" && !closed
    ? `${cleanupProposePath(brandId, campaignId)}${isCleanupPropose ? pick.href() : ""}`
    : null;
  // F29-I14 Contract F: an A/B set starts on the performance card of the campaign detail page — back goes there.
  const abBackHref = kind === "ab" && !closed ? campaignDetailPath(brandId, campaignId) : null;
  const ab = abSet ? changeSet?.ab ?? null : null;
  // Before the cleanup set exists the close list is the user's pick; none ticked leaves nothing to approve.
  const cleanupCloseCount = kind === "cleanup" ? (changeSet ? changeSet.items.length : pick.ticked.length) : 0;
  const nothingPicked = kind === "cleanup" && !changeSet && cleanupCloseCount === 0;
  // F40-I08: why 核准 is grey on a budget set, printed beside the button (prototype `#/approve` `.reason`):
  // (iii) the premise changed → 重新檢查 first; (ii) the month has no budget yet → set it first. Same inputs as
  // the 本月預算放得下 card, so the card's state and the button's reason can never disagree.
  const budgetMonthNumber = Number((budgetRead.data?.month ?? budgetMonth).split("-")[1]) || 0;
  const approveBlock = kind !== "budget" ? null
    : premiseSet ? "內容變了，先按「重新檢查」"
    : budgetRead.data?.amount === null ? `要先設 ${budgetMonthNumber} 月月預算`
    : null;

  // F45-I06: Contract P says the ad is already closed on the platform — nothing to approve, one way back.
  const adClosed = pauseView?.state === "closed" && !changeSet;
  const headTriage = pauseMode ? pauseTriage : triageItem?.triage ?? null;
  const title = adClosed ? "這則已經停了"
    : kind === "copy" ? "確認變更"
    : kind === "budget" ? "提議：加預算"
    : kind === "new_ad" ? "確認新廣告提議"
    : kind === "cleanup" ? "確認清理"
    : kind === "ab" ? "確認關掉輸家"
    : "提議：暫停這則廣告";
  const approveLabel = kind === "copy" ? "核准，接著到平台操作"
    : kind === "budget" ? "核准加碼，接著到平台操作"
    : kind === "new_ad" ? "核准新廣告，接著到平台操作"
    : kind === "cleanup" ? `核准清理（關 ${cleanupCloseCount} 則）`
    : kind === "ab" && ab ? abApproveLabel(ab, abContext.pair)
    : "核准暫停，接著到平台操作";
  const closedLabel = changeSet
    ? (changeSet.status === "superseded" ? "已由新清單取代" : `${changeSet.status === "rejected" ? "已拒絕" : "已暫緩"}・${changeSet.reason ?? ""}`)
    : "";
  // 「下一件」（F25-I03）：跟 VerifyPage 共用同一顆判斷，不各自算各自的（feature Decisions
  // 「下一件」）。目前這件的識別碼：propose 網址就是 `entityId` 本身；`setId` 網址（含已關閉的
  // 清單）從比對到的 `triageItem` 反推。
  const currentEntityId = entityId ?? (triageItem ? queueItemEntityId(triageItem) : undefined);
  const nextAction = closed ? nextOpenQueueItem(queue, currentEntityId) : null;
  // 改文案清單、還沒關閉（草稿）、承接自某一輪檢討：返回鍵改成「修改內容」回那一輪的改文案頁
  // （v7 原型 `confirmPage()` 的 `back:i.kind==="copy"?["修改內容",...]`）；已關閉或核准之後的清單
  // （`stepFromChangeSet` 這裡不會再回傳 confirm 步驟）都留原本的「投放中心」（issue Done 3）。
  const editCopyHref = !closed && kind === "copy" && changeSet?.review_id
    ? reviewRoundPath(brandId, campaignId, changeSet.review_id, "copy")
    : null;

  return (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
      <Breadcrumb items={crumb} />
      <div className={kind === "cleanup" || kind === "ab" ? "flex max-w-[1260px] flex-col gap-4" : "flex flex-col gap-4"}>
        <FlowHeader
          steps={kind === "cleanup" ? cleanupSteps(cleanupBackHref ?? undefined) : kind === "ab" ? abSteps() : STEPS}
          current={kind === "cleanup" ? 1 : 0}
          title={title}
          purpose={adClosed ? "平台上這則廣告已經是關閉狀態，不用再暫停" : STEP_PURPOSE}
          aside={closed ? <Chip tone="neutral">{closedLabel}</Chip> : undefined}
          context={kind === "ab" ? (
            abContext.campaign && <CampaignChip objective={abContext.campaign.objective} name={abContext.campaign.name} />
          ) : headTriage ? (
            <>
              {kind === "cleanup" ? (
                <CampaignChip objective={headTriage.campaign_objective ?? "other"} name={headTriage.campaign_name} />
              ) : <Badge variant="outline" className="max-w-[14rem] shrink" title={headTriage.campaign_name}>
                <span className="block w-full min-w-0 truncate">{headTriage.campaign_name}</span>
              </Badge>}
              {position && <span>第 {position.pos} 件／共 {position.total} 件</span>}
            </>
          ) : undefined}
        />

        {queueFailed && !pauseMode && (
          <ReadFailed what="待決定清單讀不到：這件的即時數字與「第幾件」暫時看不到；下面的變更內容照舊" onRetry={queueRead.reload} />
        )}

        {kind === "pause" && (
          <PauseEvidence
            triage={headTriage}
            fallbackName={item?.target.name ?? "（未命名廣告）"}
            fallbackReason={item?.reason ?? ""}
            closed={adClosed && pauseView ? closedNote(pauseView, timezone) : null}
            windowLine={headTriage ? windowText(headTriage.window) : null}
          />
        )}
        {kind === "copy" && item && <CopyEvidence item={item} />}
        {kind === "budget" && (
          <BudgetEvidence
            item={item}
            scale={triageItem?.scale ?? null}
            bestAdThumbnailUrl={triageItem?.triage.thumbnail_url ?? null}
            fit={{ read: budgetRead, month: budgetMonth, premiseChanged: premiseSet !== null, busy, onRecheck: () => void handleRecheck(), budgetHref: homeHref }}
          />
        )}
        {kind === "new_ad" && item && <NewAdEvidence item={item} />}
        {kind === "cleanup" && (
          <div>
            <CleanupEvidence
              cleanup={triageItem?.cleanup ?? null} items={changeSet?.items ?? []} drift={drift}
              picked={isCleanupPropose ? pick.ticked : undefined} breakEven={triageItem?.triage.target.break_even ?? null}
            />
            <GradeRules breakEven={triageItem?.triage.target.break_even ?? null} />
          </div>
        )}
        {kind === "ab" && ab && (
          <div>
            {abContext.failed && (
              <div className="mb-4">
                <ReadFailed what="這組比較的縮圖、A／B 標記或打平線讀不到；下面核准的內容照舊" onRetry={abContext.reload} />
              </div>
            )}
            <AbEvidence ab={ab} context={abContext} />
            <MoneyRule breakEven={abContext.breakEven} />
          </div>
        )}

        {/* Contract C/D: only while there's still a decision to make — once closed (rejected／
            暫緩), the angle chosen (or not) is already fixed and nothing more will be recorded. */}
        {kind === "pause" && !closed && !adClosed && (
          <PauseLearnCard
            status={angleData?.status ?? (angleRead.status === "error" ? "failed" : "pending")}
            candidates={angleData?.candidates ?? []}
            onRetry={angleRead.status === "error" ? angleRead.reload : undefined}
            angle={angleChoice}
            customOpen={angleCustomOpen}
            disabled={busy}
            onSelect={(c) => { setAngleChoice(c); setAngleCustomOpen(false); }}
            onOpenCustom={() => { setAngleCustomOpen(true); setAngleChoice(""); }}
            onCustomChange={(v) => setAngleChoice(v.slice(0, ANGLE_MAX))}
          />
        )}

        {actionError && <p role="alert" className="text-sm text-destructive">{actionError}</p>}
      </div>

      <div className="flex-1" />
      {adClosed ? (
        <ActionBar><Button asChild><Link to={back.to}>← 回上一頁（{back.label}）</Link></Button></ActionBar>
      ) : <ActionBar
        back={pauseMode && !closed ? back : {
          label: editCopyHref ? "修改內容" : cleanupBackHref ? "提議" : abBackHref ? "成效" : "投放中心",
          to: editCopyHref ?? cleanupBackHref ?? abBackHref ?? homeHref,
        }}
        exit={closed ? undefined : { label: "先不要，回投放中心", to: homeHref }}
        hint={closed || drift ? undefined : nothingPicked ? "一則都沒勾，沒有可核准的" : "核准不會改動平台"}
      >
        {!closed && (
          <Button variant="outline" disabled={busy} onClick={openSheet}>拒絕／暫緩</Button>
        )}
        {drift ? (
          <AdoptLatestButton busy={busy} onClick={() => void adopt()} />
        ) : !closed ? (
          <>
            {approveBlock && <span role="status" className="inline-flex items-center gap-1.5 text-xs font-medium text-warning">⚠ {approveBlock}</span>}
            <Button disabled={busy || nothingPicked || approveBlock !== null} onClick={() => void handleApprove()}>{busy ? "處理中…" : `${approveLabel} →`}</Button>
          </>
        ) : nextAction ? (
          <Button asChild><Link to={nextAction.href}>下一件 →</Link></Button>
        ) : null}
      </ActionBar>}

      {sheetOpen && (
        <DecisionSheet
          actions={<>
            <Button variant="outline" disabled={busy} onClick={() => setSheetOpen(false)}>取消</Button>
            <Button disabled={busy} onClick={() => void handleSaveDecision()}>{busy ? "保存中…" : "保存"}</Button>
          </>}
        >
          <Segmented
            label="決定"
            options={[{ value: "deferred", label: "暫緩" }, { value: "rejected", label: "拒絕" }]}
            value={decisionKind}
            onChange={setDecisionKind}
          />
          <label className="flex min-w-[200px] flex-1 flex-col gap-1 text-sm">
            原因
            <Input value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy} />
          </label>
          {decisionKind === "deferred" && (
            <label className="flex flex-col gap-1 text-sm">
              何時重看
              <div className="flex items-center gap-2">
                <Segmented
                  label="何時重看"
                  options={[{ value: "3", label: "3 天後" }, { value: "7", label: "7 天後" }, { value: "custom", label: "自訂" }]}
                  value={quickPick}
                  onChange={setQuickPick}
                />
                {quickPick === "custom" && (
                  <Input type="date" aria-label="重看日期" value={customDate} onChange={(e) => setCustomDate(e.target.value)} disabled={busy} />
                )}
              </div>
            </label>
          )}
          {sheetError && <p role="alert" className="w-full text-xs text-destructive">{sheetError}</p>}
        </DecisionSheet>
      )}
    </div>
  );
}
