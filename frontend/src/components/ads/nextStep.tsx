/** frontend/src/components/ads/nextStep.tsx — F06-I01: the workspace's *only* next-step
 * producer (ARCHITECTURE.md §6.2 decision 15). 總覽 卡片、狀態時間軸，以及策略／投放結構／
 * 素材／成效每一頁底部的整寬主要按鈕都讀 `nextStep()`；每個 tab 只依 `NextStep.id` 挑自己的
 * 原地動作，不重新檢查 Campaign 欄位。這是導航，不是判斷句：只回「去哪個分頁＋按鈕字」，
 * 不評價 Campaign、不重拼後端規則（§6.1 決議 10）。 */
import type { ComponentProps } from "react";
import { Button } from "@/components/layout/ui/button";
import { cn } from "@/lib/utils";
import type { CampaignDetail } from "@/lib/adsApi";

/** v10 (F30-I07): the perf tab key is `perf`. `performance` stays accepted as a step target only because older
 * tabs still call `onChangeTab("performance")`; the workspace maps it to `perf` (and `?tab=performance` redirects). */
export type WorkspaceTab = "overview" | "strategy" | "structure" | "assets" | "perf" | "changes";
export type StepTarget = WorkspaceTab | "publish" | "performance";
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

/** F49 Contract L: a launched campaign's step reads the served `lifecycle.state`, never the stored status. */
export function nextStep(c: CampaignDetail): NextStep {
  if (c.origin === "imported" || c.capabilities?.unavailable.strategy) {
    return { id: "make_assets", target: "assets", stageIndex: -1, sentence: "查看平台資料，安排自帶素材與手動交接；內部確認不代表平台已上架。", label: "安排自帶素材 →" };
  }
  const life = c.lifecycle?.state;
  if (life === "closed") {
    return { id: "performance", target: "perf", stageIndex: 5, sentence: "已結案，結案紀錄在成效。", label: "查看成效 →" };
  }
  if (life === "live") {
    return { id: "performance", target: "perf", stageIndex: 4, sentence: "投放中，每天的花費與結果在成效。", label: "查看成效 →" };
  }
  if (life === "ended") {
    return { id: "performance", target: "perf", stageIndex: 4, sentence: "投放已結束，到成效看結果或結案。", label: "查看成效 →" };
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

/** F06-I02：工作區唯一的整寬主要按鈕尺寸（48px 高、16px 字，ARCHITECTURE.md §6.2
 * 「快樂路徑大按鈕的尺寸」）。kit `Button` 的 `lg` 只有 40px，這裡不動 kit、不各頁自己加 class。 */
export function StepButton({ className, ...props }: ComponentProps<typeof Button>) {
  return <Button className={cn("h-12 w-full text-base", className)} {...props} />;
}

export function NextStepButton({
  step,
  onChangeTab,
}: {
  step: NextStep;
  onChangeTab: (target: StepTarget) => void;
}) {
  return <StepButton onClick={() => onChangeTab(step.target)}>{step.label}</StepButton>;
}
