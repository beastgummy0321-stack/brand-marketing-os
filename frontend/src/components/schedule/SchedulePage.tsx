import { useEffect, useState, type ReactNode } from "react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { formatCurrency } from "@/lib/format";
import { fetchProductList, type ProductListItem } from "@/lib/productsApi";
import {
  approveScheduleTree,
  bindScheduleTree,
  createSchedulePlan,
  expandPlanIntoTree,
  fetchSchedule,
  generateCreative,
  PERIOD_STATUS_LABELS,
  rejectSchedulePlans,
  revokeScheduleApproval,
  SCHEDULE_REJECT_CATEGORIES,
  settleSchedulePeriod,
  type RejectEntryInput,
  type RejectSeverity,
  type SchedulePeriod,
  type SchedulePlanItem,
  type ScheduleSource,
  type ScheduleState,
} from "@/lib/scheduleApi";
import { CampaignTree } from "./CampaignTree";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; products: ProductListItem[]; schedule: ScheduleState };

/** 票 10-feedback-entries：一條回饋——畫面上多的 `id` 只是 React key，不進 API。 */
interface FeedbackEntry {
  id: number;
  severity: RejectSeverity;
  ruleType: string;
  content: string;
}

let _feedbackEntryId = 0;
function newFeedbackEntry(): FeedbackEntry {
  _feedbackEntryId += 1;
  return { id: _feedbackEntryId, severity: "soft", ruleType: SCHEDULE_REJECT_CATEGORIES[0][0], content: "" };
}

/** 檔期規劃（票 07：最薄路徑；票 08：表單加平台／目標／促銷重點／方案數，一次拿回 N 張
 * 方案卡）。選產品、填表、確認，畫面下方長出方案卡——同一頁，不換路由、不開 modal
 * （票 07 settled 段「Frontend」）。 */
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
  const [generatingCreative, setGeneratingCreative] = useState(false);
  const [creativeError, setCreativeError] = useState<string | null>(null);
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
      const schedule = await rejectSchedulePlans(brandId, entries);
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
      setFeedbackByPlan({});
    } catch (err) {
      setRejectError(err instanceof Error ? err.message : "送出失敗，請稍後再試。");
    } finally {
      setRejecting(false);
    }
  }

  function load() {
    setState({ status: "loading" });
    Promise.all([fetchProductList(brandId), fetchSchedule(brandId)])
      .then(([products, schedule]) => {
        setState({ status: "ready", products, schedule });
        // 票 05-1：出方案／展開／產內容三支 POST 現在排進佇列、幾百毫秒就回來——按下去那一刻
        // 設的這三個旗標不能在 POST 的 finally 就清掉，那會在 worker 真的插進 llm_task 那一列
        // 之前把 runningNow 提早關掉，2 秒輪詢永遠不會啟動。改在這裡（每次 load() 成功都會
        // 經過，輪詢也是靠它跑）清：worker 真的還在跑，schedule.*.running 會是 true 撐住
        // runningNow，這裡清掉 submitting 不影響畫面顯示「還在跑」；worker 已經死了，這裡清
        // 掉之後 runningNow 一起變 false，畫面自己退回 idle。不設逾時常數，自己會收斂。
        setSubmitting(false);
        setExpandingIndex(null);
        setGeneratingCreative(false);
        // 上次送出的平台／目標要一起還原——目標是掛在平台底下的，只還原一個會讓選單顯示
        // 不在自己選項裡的值；選項來自資料檔、會變，對不上就退回第一個選項。
        const last = schedule.plan;
        if (
          last &&
          schedule.platforms.some((p) => p.id === last.platform && p.enabled) &&
          schedule.objectives.some((o) => o.platform === last.platform && o.value === last.objective)
        ) {
          setPlatform(last.platform);
          setObjective(last.objective);
        } else {
          const firstEnabled = schedule.platforms.find((p) => p.enabled);
          setPlatform(firstEnabled?.id ?? "");
          const firstObjective = schedule.objectives.find((o) => o.platform === firstEnabled?.id);
          setObjective(firstObjective?.value ?? "");
        }
        setPromotionNote("");
        setPlanCount(Math.min(Math.max(3, schedule.plan_count_min), schedule.plan_count_max));
        // 票 T2b：草稿（planning）還原上次填的日期；已經核准過的檔期不還原——再按一次
        // 出方案是開新草稿，不是延續那個已經在投的檔期，日期不該被悄悄帶過去。
        if (schedule.period && schedule.period.status === "planning") {
          setStartDate(schedule.period.start_date);
          setEndDate(schedule.period.end_date);
        } else {
          setStartDate("");
          setEndDate("");
        }
      })
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, [brandId]);

  // 決策 12（等待就是前端輪詢）：出方案與展開都是幾分鐘的呼叫，離開頁面、重新整理、或
  // 伺服器重啟都會讓那個阻塞的 POST 斷掉。輪詢讓畫面自己接回進行中的那一次，不必再按一次
  // ——再按一次只會多開一個工作，那正是 2026-08-29 那個「展開失敗→重按→又失敗」迴圈的成因。
  // `submitting`／`expandingIndex` 也算在內：剛按下去的那一刻，畫面上的資料還是上一次載入
  // 的（running 是 false），只靠伺服器狀態會等到第一次輪詢才啟動。把「我剛送出」一起算成
  // 進行中，按下去就開始輪詢，那個阻塞的 POST 中途斷掉也接得回來。
  const runningNow =
    state.status === "ready" &&
    Boolean(submitting || expandingIndex !== null || generatingCreative
            || state.schedule.plan?.running || state.schedule.tree?.running
            || state.schedule.creative?.running);
  useEffect(() => {
    if (!runningNow) return;
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [runningNow, brandId]);

  function toggleProduct(id: string) {
    setSelectedIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
  }

  async function handleStart() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const schedule = await createSchedulePlan(brandId, {
        productIds: selectedIds, platform, objective, promotionNote, planCount,
        startDate, endDate,
      });
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
      setConfirming(false);
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
      const schedule = await expandPlanIntoTree(brandId, planIndex);
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
    } catch (err) {
      setExpandError(err instanceof Error ? err.message : "展開失敗，請稍後再試。");
      setExpandingIndex(null); // 票 05-1：理由同 handleStart 的 catch
    }
  }

  async function handleBind() {
    setBinding(true);
    setBindError(null);
    try {
      const schedule = await bindScheduleTree(brandId);
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
      const schedule = await approveScheduleTree(brandId);
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
      const schedule = await revokeScheduleApproval(brandId);
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
    } catch (err) {
      setRevokeError(err instanceof Error ? err.message : "撤回失敗，請稍後再試。");
    } finally {
      setRevoking(false);
    }
  }

  async function handleGenerateCreative() {
    setGeneratingCreative(true);
    setCreativeError(null);
    try {
      const schedule = await generateCreative(brandId);
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
    } catch (err) {
      setCreativeError(err instanceof Error ? err.message : "產出失敗，請稍後再試。");
      setGeneratingCreative(false); // 票 05-1：理由同 handleStart 的 catch
    }
  }

  async function handleSettle(periodId: string) {
    setSettling(true);
    setSettleError(null);
    try {
      const schedule = await settleSchedulePeriod(brandId, periodId);
      setState((prev) => (prev.status === "ready" ? { ...prev, schedule } : prev));
    } catch (err) {
      setSettleError(err instanceof Error ? err.message : "結算失敗，請稍後再試。");
    } finally {
      setSettling(false);
    }
  }

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  } else {
    const { schedule } = state;
    const activeProducts = state.products.filter((p) => p.status === "active");
    const selectedNames = activeProducts
      .filter((p) => selectedIds.includes(p.id))
      .map((p) => p.name);
    const objectivesForPlatform = schedule.objectives.filter((o) => o.platform === platform);
    const objectiveLabel = objectivesForPlatform.find((o) => o.value === objective)?.label ?? "";
    const platformLabel = schedule.platforms.find((p) => p.id === platform)?.label ?? "";
    const planCountOptions = Array.from(
      { length: Math.max(schedule.plan_count_max - schedule.plan_count_min + 1, 0) },
      (_, i) => schedule.plan_count_min + i,
    );
    // 票 05-1 驗收回饋：出方案已經排進佇列在跑的時候，不准再按一次——後端本來就會回 409
    // （同一個品牌同一種工作一次一份），畫面先擋掉才不會讓人按了才吃到錯誤訊息。
    const planRunning = Boolean(schedule.plan?.running);
    const canConfirm =
      selectedIds.length > 0 && platform !== "" && objective !== "" && !planRunning
      && startDate !== "" && endDate !== "" && endDate >= startDate;

    content = (
      <div className="flex flex-col gap-4">
        {schedule.period && (
          <PeriodPanel
            period={schedule.period}
            settling={settling}
            settleError={settleError}
            onSettle={handleSettle}
          />
        )}
        <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
          <h2 className="mb-1 font-display text-lg text-foreground">這期要投放哪些產品</h2>
          <p className="mb-3 text-sm text-muted-foreground">
            本期每日預算：{formatCurrency(schedule.daily_budget)}
            {schedule.daily_budget <= 0 && "（尚未設定，請先到設定頁填「檔期日預算」）"}
          </p>
          {activeProducts.length === 0 ? (
            <p className="text-sm text-muted-foreground">這個品牌底下還沒有產品，請先去產品頁新增。</p>
          ) : (
            <div className="flex flex-col gap-2">
              {activeProducts.map((product) => (
                <label key={product.id} className="flex items-center gap-2 text-sm text-foreground">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(product.id)}
                    onChange={() => toggleProduct(product.id)}
                  />
                  {product.name}
                </label>
              ))}
            </div>
          )}

          <div className="mt-4 flex flex-col gap-3 border-t border-border pt-4">
            <div>
              <p className="mb-1 text-sm font-medium text-foreground">平台</p>
              <div className="flex flex-wrap gap-3">
                {schedule.platforms.map((p) => (
                  <label
                    key={p.id}
                    className={`flex items-center gap-1 text-sm ${p.enabled ? "text-foreground" : "text-muted-foreground"}`}
                  >
                    <input
                      type="radio"
                      name="platform"
                      checked={platform === p.id}
                      disabled={!p.enabled}
                      onChange={() => {
                        setPlatform(p.id);
                        const first = schedule.objectives.find((o) => o.platform === p.id);
                        setObjective(first?.value ?? "");
                      }}
                    />
                    {p.label}
                    {!p.enabled && "（尚未啟用）"}
                  </label>
                ))}
              </div>
            </div>

            <label className="flex flex-col gap-1 text-sm text-foreground">
              行銷目標
              <select
                value={objective}
                onChange={(e) => setObjective(e.target.value)}
                className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
              >
                {objectivesForPlatform.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1 text-sm text-foreground">
              促銷或重點（選填）
              <textarea
                value={promotionNote}
                onChange={(e) => setPromotionNote(e.target.value)}
                rows={2}
                className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                placeholder="例如：這期主打新品上市"
              />
            </label>

            <label className="flex flex-col gap-1 text-sm text-foreground">
              要幾個方案
              <select
                value={planCount}
                onChange={(e) => setPlanCount(Number(e.target.value))}
                className="w-24 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
              >
                {planCountOptions.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>

            <div className="flex flex-wrap gap-3">
              <label className="flex flex-col gap-1 text-sm text-foreground">
                開始日
                <input
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm text-foreground">
                結束日
                <input
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                />
              </label>
            </div>
            {startDate !== "" && endDate !== "" && endDate < startDate && (
              <p className="text-sm text-danger">結束日不能早於開始日。</p>
            )}
          </div>

          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={!canConfirm}
            className="mt-3 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            確認
          </button>
        </div>

        {confirming && (
          <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
            <h2 className="mb-1 font-display text-lg text-foreground">確認這期要排程的內容</h2>
            <p className="mb-1 text-sm text-foreground">產品：{selectedNames.join("、")}</p>
            <p className="mb-1 text-sm text-foreground">平台：{platformLabel}</p>
            <p className="mb-1 text-sm text-foreground">行銷目標：{objectiveLabel}</p>
            {promotionNote && <p className="mb-1 text-sm text-foreground">促銷或重點：{promotionNote}</p>}
            <p className="mb-1 text-sm text-foreground">方案數：{planCount}</p>
            <p className="mb-3 text-sm text-foreground">檔期：{startDate} ～ {endDate}</p>
            {submitError && <p className="mb-3 text-sm text-danger">{submitError}</p>}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={submitting}
                className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
              >
                修改
              </button>
              <button
                type="button"
                onClick={handleStart}
                disabled={submitting || planRunning}
                className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {submitting ? "排程中…" : "開始排程"}
              </button>
            </div>
          </div>
        )}

        {/* 票 05-1 驗收回饋：`submitting` 也要算——按下去到第一次輪詢之間（約 2 秒）伺服器
            還沒有那一列 running，只靠 planRunning 會有一段畫面看起來什麼都沒發生，而確認框
            在送出成功那一刻就收起來了。量到的時間來自 llm_task 實測（平均 106 秒、最久 171
            秒），不是估的。 */}
        {(planRunning || submitting) && (
          <p className="rounded-md border border-dashed border-border bg-muted/40 p-3 text-sm text-muted-foreground">
            出方案中…這一步通常要 1 到 3 分鐘，可以先離開這一頁，回來會自己接上。
          </p>
        )}
        {schedule.plan && (
          <PlanResult
            plan={schedule.plan}
            expandingIndex={expandingIndex}
            expandError={expandError}
            onExpand={handleExpand}
            feedbackByPlan={feedbackByPlan}
            onAddFeedback={addFeedbackEntry}
            onUpdateFeedback={updateFeedbackEntry}
            onRemoveFeedback={removeFeedbackEntry}
            onReject={handleReject}
            rejecting={rejecting}
            rejectError={rejectError}
          />
        )}
        {schedule.tree?.running && (
          <p className="rounded-md border border-dashed border-border bg-muted/40 p-3 text-sm text-muted-foreground">
            展開中…這一步通常要 3 到 5 分鐘，可以先離開這一頁，回來會自己接上。
          </p>
        )}
        {schedule.tree && !schedule.tree.running && (
          <CampaignTree
            tree={schedule.tree}
            binding={binding}
            bindError={bindError}
            onBind={handleBind}
            approving={approving}
            approveError={approveError}
            onApprove={handleApprove}
            revoking={revoking}
            revokeError={revokeError}
            onRevoke={handleRevoke}
            creative={schedule.creative}
            generatingCreative={generatingCreative}
            creativeError={creativeError}
            onGenerateCreative={handleGenerateCreative}
          />
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "檔期" }]} />
      <h1 className="font-display text-2xl text-foreground">檔期</h1>
      {content}
    </div>
  );
}

/** 票 T2b（ADR 0053）：檔期狀態面板——四個狀態的徽章、已結束時的結算建議與按鈕、
 * 已結算時的兩個凍結數字與（有晚到的錢才顯示的）重新結算按鈕。ADR 0051：既有頁面上的
 * 一塊面板，不是新的長頁。 */
function PeriodPanel({
  period,
  settling,
  settleError,
  onSettle,
}: {
  period: SchedulePeriod;
  settling: boolean;
  settleError: string | null;
  onSettle: (periodId: string) => void;
}) {
  const badgeClass =
    period.status === "awaiting_data"
      ? "bg-danger/10 text-danger"
      : period.status === "running"
        ? "bg-success/10 text-success"
        : "bg-muted text-muted-foreground";
  const settled = period.settled;
  const hasLateMoney = settled !== null
    && (settled.late_spend_since !== 0 || settled.late_revenue_since !== 0);

  return (
    <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="font-display text-lg text-foreground">{period.name}</h2>
        <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium ${badgeClass}`}>
          {PERIOD_STATUS_LABELS[period.status]}
        </span>
      </div>

      {period.status === "awaiting_data" && (
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-foreground">
            這期已結束。Meta 的成交回報最長 7 天才補齊，建議 {period.settle_advice_date} 之後再結算。
          </p>
          {settleError && <p className="text-sm text-danger">{settleError}</p>}
          <button
            type="button"
            onClick={() => onSettle(period.id)}
            disabled={settling}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {settling ? "結算中…" : "結算這期"}
          </button>
        </div>
      )}

      {settled && (
        <div className="flex flex-col items-start gap-1">
          <p className="text-sm text-foreground">花費：{formatCurrency(settled.spend)}</p>
          <p className="text-sm text-foreground">這期間全通路營收：{formatCurrency(settled.revenue)}</p>
          <p className="text-sm text-muted-foreground">
            結算時間：{new Date(settled.settled_at).toLocaleString("zh-TW")}
          </p>
          {settled.late_spend_since !== 0 && (
            <p className="text-sm text-foreground">
              結算後花費又進來 {formatCurrency(settled.late_spend_since)}
            </p>
          )}
          {settled.late_revenue_since !== 0 && (
            <p className="text-sm text-foreground">
              結算後營收又進來 {formatCurrency(settled.late_revenue_since)}
            </p>
          )}
          {hasLateMoney && (
            <>
              {settleError && <p className="text-sm text-danger">{settleError}</p>}
              <button
                type="button"
                onClick={() => onSettle(period.id)}
                disabled={settling}
                className="mt-1 rounded-md border border-primary px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {settling ? "結算中…" : "重新結算"}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function PlanResult({
  plan,
  expandingIndex,
  expandError,
  onExpand,
  feedbackByPlan,
  onAddFeedback,
  onUpdateFeedback,
  onRemoveFeedback,
  onReject,
  rejecting,
  rejectError,
}: {
  plan: NonNullable<ScheduleState["plan"]>;
  expandingIndex: number | null;
  expandError: string | null;
  onExpand: (planIndex: number) => void;
  feedbackByPlan: Record<number, FeedbackEntry[]>;
  onAddFeedback: (planIndex: number) => void;
  onUpdateFeedback: (planIndex: number, id: number, patch: Partial<FeedbackEntry>) => void;
  onRemoveFeedback: (planIndex: number, id: number) => void;
  onReject: () => void;
  rejecting: boolean;
  rejectError: string | null;
}) {
  if (plan.failure) {
    return (
      <div className="rounded-md border border-danger/40 bg-card p-4 shadow-[var(--shadow-card)]">
        <h2 className="mb-1 font-display text-lg text-foreground">方案</h2>
        <p className="text-sm text-danger">{plan.failure}</p>
      </div>
    );
  }

  const totalFeedbackCount = Object.values(feedbackByPlan).reduce((n, list) => n + list.length, 0);

  return (
    <div className="flex flex-col gap-3">
      {plan.sources.length > 0 && <SourceList sources={plan.sources} />}
      {expandError && <p className="text-sm text-danger">{expandError}</p>}
      {plan.plans.map((item, i) => (
        <PlanCard
          key={i}
          index={i}
          plan={item}
          expanding={expandingIndex === i}
          onExpand={() => onExpand(i)}
          entries={feedbackByPlan[i] ?? []}
          onAddEntry={() => onAddFeedback(i)}
          onUpdateEntry={(id, patch) => onUpdateFeedback(i, id, patch)}
          onRemoveEntry={(id) => onRemoveFeedback(i, id)}
        />
      ))}

      <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        {rejectError && <p className="mb-2 text-sm text-danger">{rejectError}</p>}
        <button
          type="button"
          onClick={onReject}
          disabled={totalFeedbackCount === 0 || rejecting}
          className="rounded-md border border-danger px-3 py-1.5 text-sm font-medium text-danger hover:bg-danger/10 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {rejecting ? "送出中…" : "這批都不要，重新出方案"}
        </button>
      </div>
    </div>
  );
}

function SourceList({ sources }: { sources: ScheduleSource[] }) {
  return (
    <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <h2 className="mb-2 font-display text-sm text-foreground">排程前查到的資料</h2>
      <ul className="flex flex-col gap-1 text-sm text-foreground">
        {sources.map((s, i) => (
          <li key={i}>
            <a href={s.url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
              {s.title || s.url}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PlanCard({
  index,
  plan,
  expanding,
  onExpand,
  entries,
  onAddEntry,
  onUpdateEntry,
  onRemoveEntry,
}: {
  index: number;
  plan: SchedulePlanItem;
  expanding: boolean;
  onExpand: () => void;
  entries: FeedbackEntry[];
  onAddEntry: () => void;
  onUpdateEntry: (id: number, patch: Partial<FeedbackEntry>) => void;
  onRemoveEntry: (id: number) => void;
}) {
  return (
    <div className="rounded-md border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h2 className="font-display text-lg text-foreground">方案 {index + 1}</h2>
        <button
          type="button"
          onClick={onExpand}
          disabled={expanding}
          className="rounded-md border border-primary px-2.5 py-1 text-sm font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {expanding ? "展開中…" : "用這個方案展開"}
        </button>
      </div>
      <p className="mb-2 whitespace-pre-wrap text-sm text-foreground">{plan.summary}</p>
      <p className="mb-3 whitespace-pre-wrap text-sm text-muted-foreground">{plan.reasoning}</p>
      {plan.splits.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">方向</th>
                <th className="px-3 py-2 font-medium">比例</th>
                <th className="px-3 py-2 font-medium">每日金額</th>
                <th className="px-3 py-2 font-medium">理由</th>
              </tr>
            </thead>
            <tbody>
              {plan.splits.map((split, i) => (
                <tr key={i} className="border-t border-border">
                  <td className="px-3 py-2 text-foreground">{split.label}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-foreground">
                    {(split.share * 100).toFixed(0)}%
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-foreground">
                    {formatCurrency(split.daily_amount)}
                  </td>
                  <td className="px-3 py-2 text-foreground">{split.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <FeedbackControl entries={entries} onAdd={onAddEntry} onUpdate={onUpdateEntry} onRemove={onRemoveEntry} />
    </div>
  );
}

/** 票 10-feedback-entries（ADR 0037）：每張方案卡自己的回饋清單，一次加一條（+）。
 * 送出時（`PlanResult` 的「這批都不要，重新出方案」）跨卡片彙整成一批——這裡只管輸入。 */
function FeedbackControl({
  entries,
  onAdd,
  onUpdate,
  onRemove,
}: {
  entries: FeedbackEntry[];
  onAdd: () => void;
  onUpdate: (id: number, patch: Partial<FeedbackEntry>) => void;
  onRemove: (id: number) => void;
}) {
  return (
    <div className="mt-3 flex flex-col gap-2 border-t border-border pt-3">
      {entries.map((entry) => (
        <div key={entry.id} className="flex flex-col gap-1 rounded-md border border-border p-2">
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={entry.severity}
              onChange={(e) => onUpdate(entry.id, { severity: e.target.value as RejectSeverity })}
              className="rounded-md border border-border bg-background px-2 py-1 text-sm"
            >
              <option value="soft">偏好</option>
              <option value="hard">紅線</option>
            </select>
            {entry.severity === "soft" && (
              <select
                value={entry.ruleType}
                onChange={(e) => onUpdate(entry.id, { ruleType: e.target.value })}
                className="rounded-md border border-border bg-background px-2 py-1 text-sm"
              >
                {SCHEDULE_REJECT_CATEGORIES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            )}
            <button
              type="button"
              onClick={() => onRemove(entry.id)}
              className="ml-auto text-sm text-muted-foreground hover:text-danger"
            >
              移除
            </button>
          </div>
          <input
            type="text"
            value={entry.content}
            onChange={(e) => onUpdate(entry.id, { content: e.target.value })}
            maxLength={100}
            placeholder="一句話說明哪裡不對"
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
          <p className="text-xs text-muted-foreground">
            一句話就好——系統只記得 20 條規則，寫太長會擠掉別的。
          </p>
        </div>
      ))}
      <button
        type="button"
        onClick={onAdd}
        className="self-start rounded-md border border-border px-2.5 py-1 text-sm font-medium text-foreground hover:bg-muted"
      >
        ＋ 加一條意見
      </button>
    </div>
  );
}
