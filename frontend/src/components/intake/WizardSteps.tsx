import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

const STEP_LABELS = ["起始輸入", "初步印象", "引導問答", "交接包", "貼回"];

/** 頂部步驟軌（契約「任務流版型」節）：只能點回已經走過的步驟，不能跳過還沒到的步驟。 */
export function WizardSteps({ current, onSelect }: { current: number; onSelect: (step: number) => void }) {
  return (
    <ol className="flex items-center gap-2 overflow-x-auto rounded-lg border border-border bg-card p-3 shadow-[var(--shadow-card)]">
      {STEP_LABELS.map((label, idx) => {
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
