import { Check } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { FluidCard } from "./FluidCard";

/** 任務流殼（B3 品牌建檔精靈立起、B4 檔期作戰室升格為共用件）：頂部步驟軌＋中央目前
 * 步驟＋右欄插槽。原本只有 `components/intake/WizardSteps.tsx` 一份呼叫端，B4 出現第二個
 * 真呼叫端（S8 作戰室）就是「出現第 2 個真實呼叫端才抽」的時機（code-rules.md 第三節）
 * ——原樣搬過來，畫面一像素不改，只把 `STEP_LABELS` 常數換成呼叫端傳入的 `steps`。
 *
 * `collapsedMode`（GRILL-B4R-performance.md R1-2「可跳段＋收合摘要」，票 v3-fluid-cards）：
 * 預設 `false`＝原本行為（只渲染目前步驟的 `children`，零像素改變，建檔精靈走這條）。
 * 開啟後改成逐步驟疊 `FluidCard`：目前步驟展開顯示 `children`，其他步驟收合顯示
 * `stepSummaries[idx]`（未提供就顯示「已完成」/「尚未開始」等效字樣），點收合卡片
 * 摘要等同點步驟軌那顆 chip，預設受 `reachable`（`step <= current`）限制。
 *
 * `freeNavigation`（GRILL-B4R-performance.md R1-2「點階段條任一格可跳過去展開（不擋，
 * 跳段不算違規操作）」）：預設 `false`＝維持原本 `reachable` 限制（建檔精靈走這條，
 * 零像素改變）。作戰室 5 區塊自適應單頁改用 `true`，任一格皆可點開，不受目前進度限制。
 *
 * `expandedStep`：預設沿用 `current`（零改動）。作戰室需要「目前展開哪一格」與「真正進度
 * 到哪一格」是兩件事——`freeNavigation` 讓使用者點開還沒走到的區塊查看時，不能讓步驟軌
 * 的「已完成」勾勾／顏色跟著誤植成使用者點到哪，`current` 只管進度顯示，`expandedStep`
 * 才管哪一格展開 `children`。 */
export function TaskFlowShell({
  steps,
  current,
  onSelect,
  rightRail,
  children,
  collapsedMode = false,
  stepSummaries,
  freeNavigation = false,
  expandedStep,
}: {
  steps: string[];
  current: number;
  onSelect: (step: number) => void;
  rightRail: ReactNode;
  children: ReactNode;
  collapsedMode?: boolean;
  stepSummaries?: (ReactNode | undefined)[];
  freeNavigation?: boolean;
  expandedStep?: number;
}) {
  const active = expandedStep ?? current;
  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <div className="flex flex-1 flex-col gap-4">
        <TaskFlowSteps steps={steps} current={current} active={active} onSelect={onSelect} freeNavigation={freeNavigation} />
        {collapsedMode ? (
          <TaskFlowSegments steps={steps} current={current} active={active} onSelect={onSelect} stepSummaries={stepSummaries} freeNavigation={freeNavigation}>
            {children}
          </TaskFlowSegments>
        ) : (
          children
        )}
      </div>
      <div className="lg:w-72 lg:shrink-0">{rightRail}</div>
    </div>
  );
}

/** 收合摘要模式：`active` 那格用 `FluidCard` 展開顯示 `children`，其餘步驟收合成摘要卡；
 * 「已完成」摘要文字看 `current`（真正進度），不是 `active`（使用者目前點開哪格）。 */
function TaskFlowSegments({
  steps,
  current,
  active,
  onSelect,
  stepSummaries,
  freeNavigation,
  children,
}: {
  steps: string[];
  current: number;
  active: number;
  onSelect: (step: number) => void;
  stepSummaries?: (ReactNode | undefined)[];
  freeNavigation: boolean;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3">
      {steps.map((label, idx) => {
        const step = idx + 1;
        const expanded = step === active;
        const reachable = freeNavigation || step <= current;
        const summary = stepSummaries?.[idx] ?? (step < current ? "已完成" : "尚未開始");
        return (
          <FluidCard
            key={label}
            title={label}
            collapsible
            expanded={expanded}
            onToggleExpand={() => reachable && onSelect(step)}
            collapsedSummary={summary}
            hoverable={reachable}
          >
            {expanded ? children : null}
          </FluidCard>
        );
      })}
    </div>
  );
}

/** 頂部步驟軌：只能點回已經走過的步驟，不能跳過還沒到的步驟（`freeNavigation` 時例外）。
 * 「已完成」勾勾／顏色看 `current`（真正進度），高亮那顆看 `active`（目前展開哪格）。 */
function TaskFlowSteps({
  steps,
  current,
  active,
  onSelect,
  freeNavigation = false,
}: {
  steps: string[];
  current: number;
  active: number;
  onSelect: (step: number) => void;
  freeNavigation?: boolean;
}) {
  return (
    <ol className="flex items-center gap-2 overflow-x-auto rounded-lg border border-border bg-card p-3 shadow-[var(--shadow-card)]">
      {steps.map((label, idx) => {
        const step = idx + 1;
        const done = step < current;
        const isActive = step === active;
        const reachable = freeNavigation || step <= current;
        return (
          <li key={label} className="flex items-center gap-2">
            {idx > 0 && <span className="h-px w-6 shrink-0 bg-border" aria-hidden="true" />}
            <button
              type="button"
              disabled={!reachable}
              onClick={() => onSelect(step)}
              className={cn(
                "flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium",
                isActive && "bg-primary text-primary-foreground",
                !isActive && done && "bg-success/10 text-success hover:bg-success/20",
                !isActive && !done && "bg-muted text-muted-foreground",
                !reachable && "cursor-not-allowed opacity-60",
              )}
            >
              {done ? <Check className="h-3 w-3" aria-hidden="true" /> : <span>{step}</span>}
              {label}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
