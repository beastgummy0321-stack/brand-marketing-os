import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

/** 步驟指示（F04-I07，圖 4）：`current` 是 0-based。不是 OverviewTab 的狀態時間軸——
 * 那個沿著 backend state 走，這個只描三步固定流程。 */
export function StepIndicator({ steps, current }: { steps: string[]; current: number }) {
  return (
    <div className="flex items-center">
      {steps.map((step, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <div key={step} className="flex flex-1 items-center last:flex-none">
            <div className="flex flex-col items-center gap-1.5">
              <div
                className={cn(
                  "flex size-6 items-center justify-center rounded-full text-xs font-medium text-primary-foreground",
                  done ? "bg-success" : active ? "bg-primary" : "bg-border text-muted-foreground",
                )}
              >
                {done ? <Check size={13} /> : i + 1}
              </div>
              <span className={cn("text-xs", active ? "font-semibold" : "text-muted-foreground")}>{step}</span>
            </div>
            {i < steps.length - 1 && (
              <div className={cn("mx-2 h-px flex-1", done ? "bg-success" : "bg-border")} />
            )}
          </div>
        );
      })}
    </div>
  );
}
