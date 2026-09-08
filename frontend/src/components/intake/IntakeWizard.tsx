import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { EmptyState } from "@/components/layout/EmptyState";
import { TaskFlowShell } from "@/components/layout/TaskFlowShell";
import type { IntakeDraft } from "@/lib/intakeApi";
import { fetchIntakeDraft } from "@/lib/intakeApi";
import { AdvertisingHistoryDialog } from "./AdvertisingHistoryDialog";
import { BudgetPanel } from "./BudgetPanel";
import { CostGauge } from "./CostGauge";
import { IntakeCompletedPage } from "./IntakeCompletedPage";
import { HandoffStep } from "./steps/HandoffStep";
import { PasteStep } from "./steps/PasteStep";
import { QuestionStep } from "./steps/QuestionStep";
import { ScanStep } from "./steps/ScanStep";
import { StartStep } from "./steps/StartStep";

const STEP_LABELS = ["起始輸入", "初步印象", "引導問答", "交接包", "貼回"];

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "notfound" } | { status: "ready"; draft: IntakeDraft };

/** 建檔精靈殼（契約「任務流版型」節）：頂部步驟軌＋中央目前步驟＋右欄花費儀表。
 * `brandId === null` 是全新品牌（`/intake/new`）：還沒有草稿可讀，直接顯示步驟 1。
 * 有 `brandId` 時整包讀草稿一次，之後每個動作完成都靠 `refresh()` 重讀（跟品牌智庫／
 * 產品頁「整包讀」同一個決定，不切成逐步驟各自的 GET）。 */
export function IntakeWizard({ brandId }: { brandId: string | null }) {
  const navigate = useNavigate();
  const { refreshBrands } = useWorkspace();
  const [state, setState] = useState<LoadState>(brandId ? { status: "loading" } : { status: "ready", draft: null as unknown as IntakeDraft });
  const [viewStep, setViewStep] = useState(1);
  const [budgetOpen, setBudgetOpen] = useState(false);
  // 票 past-ads/04（ADR 0067 §1.6）：新品牌送出第一步之後、導頁之前，先問一次投放史分岔。
  const [pendingNewBrand, setPendingNewBrand] = useState<{ brand_id: string; quick: boolean } | null>(null);

  function refresh() {
    if (!brandId) return;
    fetchIntakeDraft(brandId)
      .then((draft) => {
        setState({ status: "ready", draft });
        setViewStep((prev) => Math.max(prev, draft.step));
      })
      .catch((err: unknown) => {
        if (err instanceof Error && err.message.includes("找不到")) setState({ status: "notfound" });
        else setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
  }

  useEffect(() => {
    if (brandId) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId]);

  if (!brandId) {
    return (
      <>
        <TaskFlowShell steps={STEP_LABELS} current={1} onSelect={() => {}} rightRail={<CostGauge draft={null} onAdjust={() => {}} />}>
          <StartStep brandId={null} onSubmitted={(res) => setPendingNewBrand(res)} />
        </TaskFlowShell>
        {pendingNewBrand && (
          <AdvertisingHistoryDialog
            brandId={pendingNewBrand.brand_id}
            onChosen={() => {
              const res = pendingNewBrand;
              refreshBrands();
              navigate(res.quick ? `/brands/${res.brand_id}` : `/brands/${res.brand_id}/intake`);
            }}
          />
        )}
      </>
    );
  }

  if (state.status === "loading") {
    return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">讀取中…</div>;
  }
  if (state.status === "notfound") {
    return (
      <TaskFlowShell steps={STEP_LABELS} current={1} onSelect={() => {}} rightRail={<CostGauge draft={null} onAdjust={() => {}} />}>
        <StartStep brandId={brandId} onSubmitted={refresh} />
      </TaskFlowShell>
    );
  }
  if (state.status === "error") {
    return <EmptyState title="讀取失敗" description={state.message} onAction={refresh} actionLabel="重新載入" />;
  }

  const { draft } = state;

  if (draft.completed) {
    return <IntakeCompletedPage brandId={brandId} onRestart={() => setState({ status: "notfound" })} />;
  }

  return (
    <>
      <TaskFlowShell
        steps={STEP_LABELS}
        current={viewStep}
        reachableThrough={Math.max(viewStep, draft.step)}
        onSelect={(step) => step <= Math.max(viewStep, draft.step) && setViewStep(step)}
        rightRail={<CostGauge draft={draft} onAdjust={() => setBudgetOpen(true)} />}
      >
        {renderStep(viewStep, brandId, draft, refresh, () => setViewStep((s) => Math.min(5, s + 1)))}
      </TaskFlowShell>
      {budgetOpen && <BudgetPanel brandId={brandId} draft={draft} onClose={() => setBudgetOpen(false)} onSaved={refresh} />}
    </>
  );
}

function renderStep(step: number, brandId: string, draft: IntakeDraft, refresh: () => void, next: () => void) {
  switch (step) {
    case 1:
      return <StartStep brandId={brandId} onSubmitted={() => next()} />;
    case 2:
      return <ScanStep brandId={brandId} draft={draft} onRefresh={refresh} onNext={next} />;
    case 3:
      // key={question_index}：每答完一題 index 就 +1，強制重掛 QuestionStep，讓
      // useIntakeJob 的 startedRef 跟著重置，第 2 題起才會真的自動出題（不然同一個
      // 元件實例一路活到步驟結束，startedRef 只會在第 1 題觸發過一次）。
      return <QuestionStep key={draft.question_index} brandId={brandId} draft={draft} onRefresh={refresh} onNext={next} />;
    case 4:
      return <HandoffStep brandId={brandId} draft={draft} onRefresh={refresh} onNext={next} />;
    case 5:
    default:
      return <PasteStep brandId={brandId} draft={draft} onRefresh={refresh} />;
  }
}
