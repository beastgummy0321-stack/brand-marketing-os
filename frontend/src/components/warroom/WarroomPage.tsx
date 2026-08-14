import { useEffect, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { TaskFlowShell } from "@/components/layout/TaskFlowShell";
import { archiveCampaign, cycleLabel } from "@/lib/campaignsApi";
import { fetchCycleDetail, BLOCK_OF_STAGE, PACING_STRATEGY_LABELS, STAGE_BAR_LABELS, type CampaignStage, type Cycle } from "@/lib/warroomApi";
import { AiCostMeter } from "./AiCostMeter";
import { CycleDeletePanel } from "./panels/CycleDeletePanel";
import { NewCycleDirectionChoice } from "./NewCycleDirectionChoice";
import { CreativeStep } from "./steps/CreativeStep";
import { HandoffStep } from "./steps/HandoffStep";
import { IntakeStep, IntakeSummary } from "./steps/IntakeStep";
import { PerformanceStep } from "./steps/PerformanceStep";
import { PlanStep } from "./steps/PlanStep";
import { ReviewStep } from "./steps/ReviewStep";

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; cycle: Cycle; stage: CampaignStage };

/** 計畫尚未核准（PLANNING／PLAN_SELECT／REVIEW）時素材還沒開始準備——「企劃」區塊只顯示
 * `PlanStep`，核准之後才疊加 `CreativeStep`（GRILL-B4R-performance.md 199-204 行「企劃」
 * 區塊分組對照表：吸收舊「計畫＋素材」兩格）。 */
const PLAN_NOT_APPROVED = new Set(["PLANNING", "PLAN_SELECT", "REVIEW"]);

/** S8 檔期作戰室（GRILL-B4R-performance.md R1-2 重設計，票 B4R-warroom）：頂部 5 格階段條
 * （開檔／企劃／交接／成效／覆盤）＋中央單頁卡片分區，目前所在區塊自動展開、其餘收合成
 * 摘要卡，點階段條任一格可自由跳過去展開（不擋，跳段不算違規操作——`TaskFlowShell` 新增
 * `freeNavigation`／`expandedStep` 兩個選用 prop，建檔精靈零像素改變）。右欄跟 B3 同一份
 * 品牌層 AI 花費儀表，不是「廣告花費」。 */
export function WarroomPage({ brandId, cycleId }: { brandId: string; cycleId: string | null }) {
  const navigate = useNavigate();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [viewBlock, setViewBlock] = useState(1);
  const [deleting, setDeleting] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);

  function refresh() {
    if (!cycleId) return;
    setState({ status: "loading" });
    fetchCycleDetail(brandId, cycleId)
      .then(({ cycle, stage }) => {
        setState({ status: "ready", cycle, stage });
        // 第一次讀到資料時，展開的區塊跳到真正進度所在的區塊；之後使用者自己點過哪格
        // 就維持使用者的選擇（跳段不算違規操作，R1-2），不會每次 refresh 被拉回去。
        setViewBlock((prev) => (prev === 1 ? BLOCK_OF_STAGE[stage] : prev));
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
        <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "歷史檔期", href: `/brands/${brandId}/campaigns` }, { label: "開新檔期" }]} />
        <TaskFlowShell steps={STAGE_BAR_LABELS} current={1} onSelect={() => {}} rightRail={<AiCostMeter brandId={brandId} />}>
          <NewCycleDirectionChoice brandId={brandId}>
            {(initialBackground) => <IntakeStep brandId={brandId} initialBackground={initialBackground} onCreated={(newId) => navigate(`/brands/${brandId}/campaigns/${newId}`)} />}
          </NewCycleDirectionChoice>
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

  const { cycle, stage } = state;
  const currentBlock = BLOCK_OF_STAGE[stage];
  const planApproved = !PLAN_NOT_APPROVED.has(cycle.status);

  async function toggleArchive() {
    await archiveCampaign(brandId, cycle.id);
    setBanner(cycle.archived ? "已恢復這期檔期。" : "已封存這期檔期。");
    refresh();
  }

  const blockContent: Record<number, ReactNode> = {
    1: <IntakeSummary cycle={cycle} />,
    2: (
      <div className="flex flex-col gap-4">
        <PlanStep brandId={brandId} cycle={cycle} onApproved={refresh} onRefresh={refresh} />
        {planApproved && <CreativeStep brandId={brandId} cycle={cycle} />}
      </div>
    ),
    3: <HandoffStep brandId={brandId} cycle={cycle} />,
    4: <PerformanceStep brandId={brandId} cycle={cycle} />,
    5: <ReviewStep brandId={brandId} cycle={cycle} />,
  };

  const stepSummaries = [
    `${cycleLabel(cycle)}`,
    planApproved ? "計畫已核准，素材準備中" : "待確認方案",
    PACING_STRATEGY_LABELS[cycle.pacing_strategy].title,
    cycle.status === "LIVE" || cycle.status === "EVALUATING" ? "投放中" : "尚未開始投放",
    cycle.status === "CLOSED" ? "已結案，可查看覆盤" : "尚未結案",
  ];

  return (
    <div className="flex flex-col gap-4">
      <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "歷史檔期", href: `/brands/${brandId}/campaigns` }, { label: cycleLabel(cycle) }]} />
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
        current={currentBlock}
        expandedStep={viewBlock}
        onSelect={setViewBlock}
        rightRail={<AiCostMeter brandId={brandId} />}
        collapsedMode
        freeNavigation
        stepSummaries={stepSummaries}
      >
        {blockContent[viewBlock] ?? blockContent[currentBlock]}
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
