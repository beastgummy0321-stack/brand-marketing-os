import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CalendarRange, GitCompareArrows, Network, LoaderCircle, Layers3 } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { PageTabs } from "@/components/layout/PageTabs";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { fetchProductList, type ProductListItem } from "@/lib/productsApi";
import { saveRuleCard } from "@/lib/settingsApi";
import {
  approveScheduleTree, bindScheduleTree, createSchedulePlan, expandPlanIntoTree, fetchSchedule,
  rejectSchedulePlans, revokeScheduleApproval, SCHEDULE_REJECT_CATEGORIES,
  settleSchedulePeriod, type RejectEntryInput, type ScheduleState,
} from "@/lib/scheduleApi";
import { CampaignTree } from "./CampaignTree";
import { CreativePackList } from "./CreativePackList";
import { PeriodPanel } from "./PeriodPanel";
import { PlanComparison, type FeedbackEntry } from "./PlanComparison";
import { ScheduleSetup, type ScheduleDraft } from "./ScheduleSetup";

type LoadState = { status: "loading" } | { status: "error"; message: string }
  | { status: "ready"; products: ProductListItem[]; schedule: ScheduleState };
const stageTabs = [
  { value: "setup", label: "設定檔期", icon: <CalendarRange className="size-4" aria-hidden="true" /> },
  { value: "plans", label: "方案比較", icon: <GitCompareArrows className="size-4" aria-hidden="true" /> },
  { value: "tree", label: "投放結構", icon: <Network className="size-4" aria-hidden="true" /> },
  { value: "assets", label: "素材準備", icon: <Layers3 className="size-4" aria-hidden="true" /> },
] as const;
type ScheduleTab = (typeof stageTabs)[number]["value"];

let feedbackEntryId = 0;
function newFeedbackEntry(): FeedbackEntry {
  feedbackEntryId += 1;
  return { id: feedbackEntryId, severity: "soft", ruleType: SCHEDULE_REJECT_CATEGORIES[0][0], content: "" };
}

export function SchedulePage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [platform, setPlatform] = useState("");
  const [objective, setObjective] = useState("");
  const [promotionNote, setPromotionNote] = useState("");
  const [planCount, setPlanCount] = useState(3);
  // 票 T2b（ADR 0053）：檔期的開始日／結束日——沒有預設值，使用者自己填。
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [settling, setSettling] = useState(false);
  const [settleError, setSettleError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [expandingIndex, setExpandingIndex] = useState<number | null>(null);
  const [expandError, setExpandError] = useState<string | null>(null);
  const [binding, setBinding] = useState(false);
  const [bindError, setBindError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);
  const [adoptingBudget, setAdoptingBudget] = useState(false);
  const [adoptBudgetError, setAdoptBudgetError] = useState<string | null>(null);
  const [feedbackByPlan, setFeedbackByPlan] = useState<Record<number, FeedbackEntry[]>>({});
  const [rejecting, setRejecting] = useState(false);
  const [rejectError, setRejectError] = useState<string | null>(null);

  function addFeedbackEntry(planIndex: number) {
    setFeedbackByPlan((prev) => ({
      ...prev,
      [planIndex]: [...(prev[planIndex] ?? []), newFeedbackEntry()],
    }));
  }

  function updateFeedbackEntry(planIndex: number, id: number, patch: Partial<FeedbackEntry>) {
    setFeedbackByPlan((prev) => ({
      ...prev,
      [planIndex]: (prev[planIndex] ?? []).map((e) => (e.id === id ? { ...e, ...patch } : e)),
    }));
  }

  function removeFeedbackEntry(planIndex: number, id: number) {
    setFeedbackByPlan((prev) => ({
      ...prev,
      [planIndex]: (prev[planIndex] ?? []).filter((e) => e.id !== id),
    }));
  }

  async function handleReject() {
    const entries: RejectEntryInput[] = Object.values(feedbackByPlan)
      .flat()
      .map((e) => ({ severity: e.severity, ruleType: e.ruleType, content: e.content }));
    setRejecting(true);
    setRejectError(null);
    try {
      const schedule = await trackAction(() => rejectSchedulePlans(brandId, entries));
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
      setFeedbackByPlan({});
    } catch (err) {
      setRejectError(err instanceof Error ? err.message : "送出失敗，請稍後再試。");
    } finally {
      setRejecting(false);
    }
  }

  const initializedBrand = useRef<string | null>(null);
  const requestId = useRef(0);
  const pageActive = useRef(true);
  const loadingRequest = useRef(false);
  const pendingActions = useRef(0);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [params, setParams] = useSearchParams();
  const defaultTab = state.status === "ready" && state.schedule.tree ? "tree" : state.status === "ready" && state.schedule.plan ? "plans" : "setup";
  const tab = stageTabs.find((item) => item.value === params.get("tab"))?.value ?? defaultTab;

  function changeTab(value: ScheduleTab) {
    if (!pageActive.current) return;
    setParams((previous) => { const next = new URLSearchParams(previous); next.set("tab", value); return next; });
  }

  // 只在首次進入品牌時還原表單。後續輪詢只更新伺服器狀態，草稿由父層持續保留。
  const load = useCallback(async () => {
    const initial = initializedBrand.current !== brandId;
    if ((loadingRequest.current && !initial) || pendingActions.current > 0) return;
    loadingRequest.current = true;
    const id = ++requestId.current;
    if (initial) setState({ status: "loading" });
    try {
      const [products, schedule] = await Promise.all([
        initial ? fetchProductList(brandId) : Promise.resolve(null),
        fetchSchedule(brandId),
      ]);
      if (requestId.current !== id) return;
      if (initial) {
        initializedBrand.current = brandId;
        const last = schedule.plan;
        const validLast = last && schedule.platforms.some((item) => item.id === last.platform && item.enabled)
          && schedule.objectives.some((item) => item.platform === last.platform && item.value === last.objective);
        const initialPlatform = validLast ? last.platform : schedule.platforms.find((item) => item.enabled)?.id ?? "";
        setPlatform(initialPlatform);
        setObjective(validLast ? last.objective : schedule.objectives.find((item) => item.platform === initialPlatform)?.value ?? "");
        setPlanCount(Math.min(Math.max(3, schedule.plan_count_min), schedule.plan_count_max));
        const planning = schedule.period?.status === "planning";
        // 票 smart-loop 05：沒有草稿檔期時，第一次讀到「建議下一期」就先帶入日期
        // （只有這裡跑一次，之後使用者輸入的內容不會被蓋掉）。
        const suggestion = schedule.next_period_suggestion;
        setStartDate(planning ? schedule.period!.start_date : suggestion?.start_date ?? "");
        setEndDate(planning ? schedule.period!.end_date : suggestion?.end_date ?? "");
        setSelectedIds(planning ? (last?.product_ids ?? []).filter((selectedId) => products?.some((product) => product.id === selectedId && product.status === "active")) : []);
        setPromotionNote(planning ? last?.promotion_note ?? "" : "");
      }
      setState((previous) => ({ status: "ready", products: products ?? (previous.status === "ready" ? previous.products : []), schedule }));
      setRefreshError(null);
      setSubmitting(false);
      setExpandingIndex(null);
    } catch (err) {
      if (requestId.current !== id) return;
      const message = err instanceof Error ? err.message : "讀取失敗，請稍後再試。";
      if (initial) setState({ status: "error", message });
      else setRefreshError(message);
    } finally {
      loadingRequest.current = false;
    }
  }, [brandId]);

  useEffect(() => {
    pageActive.current = true;
    void load();
    return () => { pageActive.current = false; requestId.current += 1; };
  }, [load]);

  // 不讓 GET 舊快照覆蓋剛完成的操作，也不在 POST 尚未回覆時把送出旗標清掉。
  async function trackAction<T>(action: () => Promise<T>): Promise<T> {
    requestId.current += 1;
    pendingActions.current += 1;
    try { return await action(); }
    finally { pendingActions.current -= 1; requestId.current += 1; }
  }

  // 票 05：素材工作檯工單沒有自己的 running 輪詢旗標——一份 brief 還在 queued／running
  // 就代表這一期還有背景工作在跑，跟 plan／tree 的 running 欄同一條規則（既有 2 秒輪詢
  // 順便把它覆蓋掉，不必另開一條）。
  const briefsRunning = state.status === "ready" && state.schedule.briefs.some(
    (b) => b.status === "queued" || b.status === "running",
  );
  const runningNow = state.status === "ready" && Boolean(
    submitting || expandingIndex !== null || rejecting || briefsRunning
    || state.schedule.plan?.running || state.schedule.tree?.running,
  );
  useEffect(() => {
    if (!runningNow) return;
    const timer = setInterval(() => { void load(); }, 2000);
    return () => clearInterval(timer);
  }, [runningNow, load]);


  async function handleStart() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const schedule = await trackAction(() => createSchedulePlan(brandId, {
        productIds: selectedIds, platform, objective, promotionNote, planCount,
        startDate, endDate,
      }));
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
      setConfirming(false);
      changeTab("plans");
      setFeedbackByPlan({}); // 新的一批方案，舊方案卡上寫的回饋不再對得上號
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "排程失敗，請稍後再試。");
      setSubmitting(false); // 票 05-1：成功時不在這裡清，見 load() 註解；失敗（含 409）沒有
      // 後續的輪詢會清，這裡不清就永遠鎖住按鈕。
    }
  }

  async function handleExpand(planIndex: number) {
    setExpandingIndex(planIndex);
    setExpandError(null);
    try {
      const schedule = await trackAction(() => expandPlanIntoTree(brandId, planIndex));
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
      changeTab("tree");
    } catch (err) {
      setExpandError(err instanceof Error ? err.message : "展開失敗，請稍後再試。");
      setExpandingIndex(null); // 票 05-1：理由同 handleStart 的 catch
    }
  }

  async function handleBind() {
    setBinding(true);
    setBindError(null);
    try {
      const schedule = await trackAction(() => bindScheduleTree(brandId));
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
    } catch (err) {
      setBindError(err instanceof Error ? err.message : "配對失敗，請稍後再試。");
    } finally {
      setBinding(false);
    }
  }

  async function handleApprove() {
    setApproving(true);
    setApproveError(null);
    try {
      const schedule = await trackAction(() => approveScheduleTree(brandId));
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
    } catch (err) {
      setApproveError(err instanceof Error ? err.message : "核准失敗，請稍後再試。");
    } finally {
      setApproving(false);
    }
  }

  async function handleRevoke() {
    setRevoking(true);
    setRevokeError(null);
    try {
      const schedule = await trackAction(() => revokeScheduleApproval(brandId));
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
    } catch (err) {
      setRevokeError(err instanceof Error ? err.message : "撤回失敗，請稍後再試。");
    } finally {
      setRevoking(false);
    }
  }

  async function handleAdoptBudget() {
    const suggestion = state.status === "ready" ? state.schedule.next_period_suggestion : null;
    if (!suggestion) return;
    setAdoptingBudget(true);
    setAdoptBudgetError(null);
    try {
      await trackAction(() => saveRuleCard(brandId, "schedule_budget", {
        daily_budget: suggestion.daily_budget, step_rate: suggestion.step_rate,
      }));
      await load();
    } catch (err) {
      setAdoptBudgetError(err instanceof Error ? err.message : "採用失敗，請稍後再試。");
    } finally {
      setAdoptingBudget(false);
    }
  }

  async function handleSettle(periodId: string) {
    setSettling(true);
    setSettleError(null);
    try {
      const schedule = await trackAction(() => settleSchedulePeriod(brandId, periodId));
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
    } catch (err) {
      setSettleError(err instanceof Error ? err.message : "結算失敗，請稍後再試。");
    } finally {
      setSettling(false);
    }
  }

  function updateDraft(patch: Partial<ScheduleDraft>) {
    if (patch.selectedIds !== undefined) setSelectedIds(patch.selectedIds);
    if (patch.platform !== undefined) setPlatform(patch.platform);
    if (patch.objective !== undefined) setObjective(patch.objective);
    if (patch.promotionNote !== undefined) setPromotionNote(patch.promotionNote);
    if (patch.planCount !== undefined) setPlanCount(patch.planCount);
    if (patch.startDate !== undefined) setStartDate(patch.startDate);
    if (patch.endDate !== undefined) setEndDate(patch.endDate);
  }
  const schedule = state.status === "ready" ? state.schedule : null;
  const planRunning = Boolean(submitting || schedule?.plan?.running || rejecting);
  const treeRunning = Boolean(expandingIndex !== null || schedule?.tree?.running);

  return <div className="flex flex-col gap-5">
    <PageHeader title="檔期規劃" description="設定產品與目標、比較方案，再整理本期的投放結構與素材。" />
    <PageTabs items={[...stageTabs]} value={tab} onChange={changeTab} label="檔期規劃階段" />
    {state.status === "loading" && <div aria-label="檔期載入中" className="grid grid-cols-[minmax(0,1fr)_280px] gap-5"><Skeleton className="h-[440px]" /><Skeleton className="h-80" /></div>}
    {state.status === "error" && <div className="surface"><EmptyState title="讀取失敗" description={state.message} onAction={() => { void load(); }} actionLabel="重新載入" /></div>}
    {schedule && state.status === "ready" && <>
      {refreshError && <div role="alert" className="flex items-center justify-between gap-4 rounded-lg border border-danger/25 bg-danger/5 p-4"><p className="text-sm">背景更新失敗：{refreshError} 目前保留上次讀取的內容。</p><Button type="button" variant="outline" onClick={() => { void load(); }}>重新載入</Button></div>}
      {schedule.period && <PeriodPanel period={schedule.period} settling={settling} settleError={settleError} onSettle={handleSettle} />}
      {(planRunning || treeRunning || briefsRunning) && <div role="status" className="flex items-start gap-3 rounded-lg border border-primary/15 bg-accent/60 px-4 py-3">
        <LoaderCircle className="mt-0.5 size-4 animate-spin text-primary" aria-hidden="true" /><div><p className="text-sm font-medium">{planRunning ? "出方案中…" : treeRunning ? "展開中…" : "素材產出中…"}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">這一步可能需要幾分鐘；可以先離開，回來後會接續顯示。背景更新會保留目前的表單與意見。</p></div>
      </div>}
      <div hidden={tab !== "setup"}><ScheduleSetup brandId={brandId} schedule={schedule} products={state.products} draft={{ selectedIds, platform, objective, promotionNote, planCount, startDate, endDate }} onChange={updateDraft} confirming={confirming} onConfirm={setConfirming} submitting={submitting} submitError={submitError} onStart={handleStart} busy={planRunning || treeRunning || briefsRunning} onAdoptBudget={handleAdoptBudget} adoptingBudget={adoptingBudget} adoptBudgetError={adoptBudgetError} /></div>
      <div hidden={tab !== "plans"}>
        {schedule.plan ? <PlanComparison key={schedule.plan.task_id} plan={schedule.plan} expandingIndex={expandingIndex} expandError={expandError} onExpand={handleExpand} feedbackByPlan={feedbackByPlan} onAddFeedback={addFeedbackEntry} onUpdateFeedback={updateFeedbackEntry} onRemoveFeedback={removeFeedbackEntry} onReject={handleReject} rejecting={rejecting} rejectError={rejectError} busy={planRunning || treeRunning || briefsRunning} /> : <div className="surface"><EmptyState title="先建立本期方案" description="選擇產品、目標與檔期後，開始排程即可在這裡比較方案。" actionLabel="前往設定檔期" onAction={() => changeTab("setup")} /></div>}
      </div>
      <div hidden={tab !== "tree"}>
        {schedule.tree && !schedule.tree.running ? <CampaignTree key={schedule.tree.task_id} tree={schedule.tree} binding={binding} bindError={bindError} onBind={handleBind} approving={approving} approveError={approveError} onApprove={handleApprove} revoking={revoking} revokeError={revokeError} onRevoke={handleRevoke} briefs={schedule.briefs} creativePack={schedule.creative_pack} brandId={brandId} onGoToAssets={() => changeTab("assets")} /> : <div className="surface"><EmptyState title={treeRunning ? "正在整理投放結構" : "尚未展開投放結構"} description={treeRunning ? "完成後會顯示節點、預算與內容，可以先到其他階段工作。" : "先在方案比較中選擇一個方案，再展開成投放結構。"} actionLabel={treeRunning ? undefined : "前往方案比較"} onAction={treeRunning ? undefined : () => changeTab("plans")} /></div>}
      </div>
      <div hidden={tab !== "assets"}>
        {schedule.tree && !schedule.tree.running
          ? <CreativePackList brandId={brandId} briefs={schedule.briefs} creativePack={schedule.creative_pack} />
          : <div className="surface"><EmptyState title="先展開投放結構" description="投放結構展開成功後，這裡會自動出現每個廣告節點的素材工單。" actionLabel="前往投放結構" onAction={() => changeTab("tree")} /></div>}
      </div>
    </>}
  </div>;
}
