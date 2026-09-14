/** frontend/src/components/ads/nextStep.tsx — F06-I01: the workspace's *only* next-step
 * producer (ARCHITECTURE.md §6.2 decision 15). 總覽 卡片、狀態時間軸，以及策略／投放結構／
 * 素材／成效每一頁底部的整寬主要按鈕都讀 `nextStep()`；每個 tab 只依 `NextStep.id` 挑自己的
 * 原地動作，不重新檢查 Campaign 欄位。這是導航，不是判斷句：只回「去哪個分頁＋按鈕字」，
 * 不評價 Campaign、不重拼後端規則（§6.1 決議 10）。 */
import { Button } from "@/components/layout/ui/button";
import type { CampaignDetail } from "@/lib/adsApi";

export type WorkspaceTab = "overview" | "strategy" | "structure" | "assets" | "performance";
export type StepTarget = WorkspaceTab | "publish";
export type StepId =
  | "strategy_generate"
  | "strategy_adopt"
  | "add_ad"
  | "dispatch"
  | "make_assets"
  | "publish"
  | "performance";

export interface NextStep {
  id: StepId;
  target: StepTarget;
  stageIndex: number;
  sentence: string;
  label: string;
}

export function nextStep(c: CampaignDetail): NextStep {
  if (c.status === "closed") {
    return { id: "performance", target: "performance", stageIndex: 5, sentence: "已結案，結案紀錄在成效。", label: "查看成效 →" };
  }
  if (c.status === "live") {
    return { id: "performance", target: "performance", stageIndex: 4, sentence: "投放中，每天的花費與結果在成效。", label: "查看成效 →" };
  }
  if (c.status === "ended") {
    return { id: "performance", target: "performance", stageIndex: 4, sentence: "投放已結束，到成效看結果或結案。", label: "查看成效 →" };
  }
  if (!c.budget_basis_json.strategy) {
    return { id: "strategy_generate", target: "strategy", stageIndex: 0, sentence: "還沒有策略，先產生策略建議。", label: "前往策略 →" };
  }
  if (c.groups.length === 0) {
    return { id: "strategy_adopt", target: "strategy", stageIndex: 1, sentence: "策略已產生，確認後系統會建立投放結構。", label: "前往策略 →" };
  }
  const adCount = c.groups.reduce((sum, g) => sum + g.ads.length, 0);
  if (adCount === 0) {
    return { id: "add_ad", target: "structure", stageIndex: 2, sentence: "投放結構裡還沒有廣告，先新增一則廣告。", label: "前往投放結構 →" };
  }
  if (c.asset_readiness.total > 0 && c.asset_readiness.ready_count >= c.asset_readiness.total) {
    return { id: "publish", target: "publish", stageIndex: 3, sentence: "素材都就位了，可以發布。", label: "發布 →" };
  }
  if (!c.asset_readiness.pack_id) {
    return { id: "dispatch", target: "structure", stageIndex: 2, sentence: "投放結構已建立，下一步開始做素材。", label: "前往投放結構 →" };
  }
  return { id: "make_assets", target: "assets", stageIndex: 3, sentence: "素材製作中，全部就位後就能發布。", label: "前往素材 →" };
}

export function NextStepButton({
  step,
  onChangeTab,
}: {
  step: NextStep;
  onChangeTab: (target: StepTarget) => void;
}) {
  return (
    <Button className="w-full" onClick={() => onChangeTab(step.target)}>
      {step.label}
    </Button>
  );
}
