import { Check } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** 任務流殼：頂部步驟軌＋中央目前步驟＋右欄插槽。唯一呼叫端是
 * `components/intake/IntakeWizard.tsx`（建檔精靈）。
 *
 * 原本還支援「作戰室」用的收合摘要模式（`collapsedMode`／`freeNavigation`／
 * `expandedStep`，逐步驟疊 `FluidCard` 讓使用者跳段查看）——作戰室那份呼叫端已刪除
 * （dead-code-sweep），三個 prop 從此沒有呼叫端傳 true／非預設值，隨呼叫端一起刪除
 * （ticket dead-code-sweep 05）。 */
export function TaskFlowShell({
  steps,
  current,
  onSelect,
  rightRail,
  children,
}: {
  steps: string[];
  current: number;
  onSelect: (step: number) => void;
  rightRail: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <div className="flex flex-1 flex-col gap-4">
        <TaskFlowSteps steps={steps} current={current} onSelect={onSelect} />
        {children}
      </div>
      <div className="lg:w-72 lg:shrink-0">{rightRail}</div>
    </div>
  );
}

/** 頂部步驟軌：只能點回已經走過的步驟，不能跳過還沒到的步驟。 */
function TaskFlowSteps({
  steps,
  current,
  onSelect,
}: {
  steps: string[];
  current: number;
  onSelect: (step: number) => void;
}) {
  return (
    <ol className="flex items-center gap-2 overflow-x-auto rounded-lg border border-border bg-card p-3 shadow-[var(--shadow-card)]">
      {steps.map((label, idx) => {
        const step = idx + 1;
        const done = step < current;
        const isActive = step === current;
        const reachable = step <= current;
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
