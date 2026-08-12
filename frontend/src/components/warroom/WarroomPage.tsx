import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { TaskFlowShell } from "@/components/layout/TaskFlowShell";
import { archiveCampaign, cycleLabel } from "@/lib/campaignsApi";
import { fetchCycleDetail, STAGE_BAR_LABELS, STAGE_ORDER, type CampaignStage, type Cycle } from "@/lib/warroomApi";
import { AiCostMeter } from "./AiCostMeter";
import { CycleDeletePanel } from "./panels/CycleDeletePanel";
import { CreativeStep } from "./steps/CreativeStep";
import { HandoffStep } from "./steps/HandoffStep";
import { IntakeStep } from "./steps/IntakeStep";
import { PerformanceStep } from "./steps/PerformanceStep";
import { PlanStep } from "./steps/PlanStep";
import { ReviewStep } from "./steps/ReviewStep";

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; cycle: Cycle; stage: CampaignStage };

/** S8 檔期作戰室（票 B4-warroom）：開檔到覆盤全程不換頁的任務流，沿用 B3 建檔精靈立起、
 * 本票升格共用的 `TaskFlowShell`（頂部階段條＋中央目前步驟＋右欄插槽）。右欄是跟 B3 同一份
 * 品牌層 AI 花費儀表，不是「廣告花費」（契約「任務流版型」節）。 */
export function WarroomPage({ brandId, cycleId }: { brandId: string; cycleId: string | null }) {
  const navigate = useNavigate();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [viewStep, setViewStep] = useState(1);
  const [deleting, setDeleting] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);

  function refresh() {
    if (!cycleId) return;
    setState({ status: "loading" });
    fetchCycleDetail(brandId, cycleId)
      .then(({ cycle, stage }) => {
        setState({ status: "ready", cycle, stage });
        // STAGE_ORDER 已含「開檔」頭格（index 0），1-based 步數＝陣列位置＋1。
        const currentIndex = STAGE_ORDER.indexOf(stage) + 1;
        setViewStep((prev) => Math.max(prev, currentIndex));
      })
      .catch((err: unknown) => setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" }));
  }

  useEffect(() => {
    if (cycleId) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, cycleId]);

  if (!cycleId) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "檔期", href: `/brands/${brandId}/campaigns` }, { label: "開新檔期" }]} />
        <TaskFlowShell steps={STAGE_BAR_LABELS} current={1} onSelect={() => {}} rightRail={<AiCostMeter brandId={brandId} />}>
          <IntakeStep brandId={brandId} onCreated={(newId) => navigate(`/brands/${brandId}/campaigns/${newId}`)} />
        </TaskFlowShell>
      </div>
    );
  }

  if (state.status === "loading") {
    return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">讀取中…</div>;
  }
  if (state.status === "error") {
    return <EmptyState title="讀取失敗" description={state.message} onAction={refresh} actionLabel="重新載入" />;
  }

  const { cycle } = state;
  const currentIndex = Math.max(viewStep, STAGE_ORDER.indexOf(state.stage) + 1);
  const selectedStep = Math.min(viewStep, currentIndex);
  const activeKey = STAGE_ORDER[selectedStep - 1] ?? STAGE_ORDER[0];

  async function toggleArchive() {
    await archiveCampaign(brandId, cycle.id);
    setBanner(cycle.archived ? "已恢復這期檔期。" : "已封存這期檔期。");
    refresh();
  }

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "檔期", href: `/brands/${brandId}/campaigns` }, { label: cycleLabel(cycle) }]} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="font-display text-2xl text-foreground">{cycleLabel(cycle)}</h1>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => void toggleArchive()} className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary hover:text-primary">
            {cycle.archived ? "恢復" : "封存"}
          </button>
          {cycle.archived && (
            <button type="button" onClick={() => setDeleting(true)} className="rounded-md border border-danger px-3 py-1.5 text-sm font-medium text-danger hover:bg-danger/10">
              永久刪除這期檔期
            </button>
          )}
        </div>
      </div>
      {banner && <p className="rounded-md bg-success/10 px-3 py-2 text-sm text-success">{banner}</p>}

      <TaskFlowShell
        steps={STAGE_BAR_LABELS}
        current={currentIndex}
        onSelect={(step) => step <= currentIndex && setViewStep(step)}
        rightRail={<AiCostMeter brandId={brandId} />}
      >
        {renderStep(activeKey, brandId, cycle, refresh)}
      </TaskFlowShell>

      {deleting && (
        <CycleDeletePanel
          brandId={brandId}
          cycle={cycle}
          onClose={() => setDeleting(false)}
          onDeleted={() => navigate(`/brands/${brandId}/campaigns`)}
        />
      )}
    </div>
  );
}

function renderStep(stage: CampaignStage, brandId: string, cycle: Cycle, refresh: () => void) {
  switch (stage) {
    case "plan":
      return <PlanStep brandId={brandId} cycle={cycle} onApproved={refresh} onRefresh={refresh} />;
    case "creative":
      return <CreativeStep brandId={brandId} cycle={cycle} />;
    case "handoff":
    case "prelaunch":
      return <HandoffStep brandId={brandId} cycle={cycle} />;
    case "performance":
      return <PerformanceStep brandId={brandId} cycle={cycle} />;
    case "review":
      return <ReviewStep brandId={brandId} cycle={cycle} />;
    default:
      return null;
  }
}
