import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { EmptyState } from "@/components/layout/EmptyState";
import { TaskFlowShell } from "@/components/layout/TaskFlowShell";
import type { IntakeDraft } from "@/lib/intakeApi";
import { fetchIntakeDraft } from "@/lib/intakeApi";
import { BudgetPanel } from "./BudgetPanel";
import { CostGauge } from "./CostGauge";
import { IntakeCompletedPage } from "./IntakeCompletedPage";
import { KnowledgeStep } from "./steps/KnowledgeStep";
import { OfferingsStep } from "./steps/OfferingsStep";
import { ScanStep } from "./steps/ScanStep";
import { StartStep } from "./steps/StartStep";
import { ToolsStep } from "./steps/ToolsStep";

const STEP_LABELS = ["起始輸入", "初步印象", "賣什麼與數字", "接工具", "品牌知識"];

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "notfound" } | { status: "ready"; draft: IntakeDraft };

/** 建檔精靈殼（契約「任務流版型」節）：頂部步驟軌＋中央目前步驟＋右欄花費儀表。
 * `brandId === null` 是全新品牌（`/intake/new`）：還沒有草稿可讀，直接顯示步驟 1。
 * 有 `brandId` 時整包讀草稿一次，之後每個動作完成都靠 `refresh()` 重讀（跟品牌智庫／
 * 產品頁「整包讀」同一個決定，不切成逐步驟各自的 GET）。 */
export function IntakeWizard({ brandId }: { brandId: string | null }) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { refreshBrands } = useWorkspace();
  const [state, setState] = useState<LoadState>(brandId ? { status: "loading" } : { status: "ready", draft: null as unknown as IntakeDraft });
  const [viewStep, setViewStep] = useState(1);
  const [budgetOpen, setBudgetOpen] = useState(false);

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
      <TaskFlowShell steps={STEP_LABELS} current={1} onSelect={() => {}} rightRail={<CostGauge draft={null} onAdjust={() => {}} />}>
        <StartStep
          brandId={null}
          onSubmitted={(res) => {
            refreshBrands();
            navigate(res.quick ? `/brands/${res.brand_id}` : `/brands/${res.brand_id}/intake`);
          }}
        />
      </TaskFlowShell>
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

  const jumpStep = draft.completed ? parseStepParam(searchParams.get("step")) : null;

  if (draft.completed && jumpStep === null) {
    return <IntakeCompletedPage brandId={brandId} onRestart={() => setState({ status: "notfound" })} />;
  }

  const backToCompleted = `/brands/${encodeURIComponent(brandId)}/intake`;
  const current = jumpStep ?? viewStep;
  const reachableThrough = jumpStep !== null ? STEP_LABELS.length : Math.max(viewStep, draft.step);
  const onSelect =
    jumpStep !== null
      ? (step: number) => navigate(`${backToCompleted}?step=${step}`)
      : (step: number) => step <= Math.max(viewStep, draft.step) && setViewStep(step);
  const next =
    jumpStep !== null ? () => navigate(backToCompleted) : () => setViewStep((s) => Math.min(STEP_LABELS.length, s + 1));

  return (
    <>
      <TaskFlowShell
        steps={STEP_LABELS}
        current={current}
        reachableThrough={reachableThrough}
        onSelect={onSelect}
        rightRail={<CostGauge draft={draft} onAdjust={() => setBudgetOpen(true)} />}
      >
        {jumpStep !== null && (
          <Link to={backToCompleted} className="self-start text-sm text-muted-foreground hover:underline">
            回到完成畫面
          </Link>
        )}
        {renderStep(current, brandId, draft, refresh, next)}
      </TaskFlowShell>
      {budgetOpen && <BudgetPanel brandId={brandId} draft={draft} onClose={() => setBudgetOpen(false)} onSaved={refresh} />}
    </>
  );
}

/** 已完成品牌的 `?step=N` 深連結：不是 1..STEP_LABELS.length 之間的整數就當沒給
 * （F05-I14：壞掉的參數不報錯，退回完成畫面）。 */
function parseStepParam(raw: string | null): number | null {
  if (raw === null) return null;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 1 || n > STEP_LABELS.length) return null;
  return n;
}

function renderStep(step: number, brandId: string, draft: IntakeDraft, refresh: () => void, next: () => void) {
  switch (step) {
    case 1:
      return <StartStep brandId={brandId} onSubmitted={() => next()} />;
    case 2:
      return <ScanStep brandId={brandId} draft={draft} onRefresh={refresh} onNext={next} />;
    case 3:
      return <OfferingsStep brandId={brandId} draft={draft} onRefresh={refresh} onNext={next} />;
    case 4:
      return <ToolsStep brandId={brandId} onNext={next} />;
    case 5:
    default:
      return <KnowledgeStep brandId={brandId} draft={draft} onRefresh={refresh} />;
  }
}
