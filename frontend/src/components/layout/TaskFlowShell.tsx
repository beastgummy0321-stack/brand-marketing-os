import { Check } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** 任務流殼（B3 品牌建檔精靈立起、B4 檔期作戰室升格為共用件）：頂部步驟軌＋中央目前
 * 步驟＋右欄插槽。原本只有 `components/intake/WizardSteps.tsx` 一份呼叫端，B4 出現第二個
 * 真呼叫端（S8 作戰室）就是「出現第 2 個真實呼叫端才抽」的時機（code-rules.md 第三節）
 * ——原樣搬過來，畫面一像素不改，只把 `STEP_LABELS` 常數換成呼叫端傳入的 `steps`。 */
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
function TaskFlowSteps({ steps, current, onSelect }: { steps: string[]; current: number; onSelect: (step: number) => void }) {
  return (
    <ol className="flex items-center gap-2 overflow-x-auto rounded-lg border border-border bg-card p-3 shadow-[var(--shadow-card)]">
      {steps.map((label, idx) => {
        const step = idx + 1;
        const done = step < current;
        const active = step === current;
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
                active && "bg-primary text-primary-foreground",
                !active && done && "bg-success/10 text-success hover:bg-success/20",
                !active && !done && "bg-muted text-muted-foreground",
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
