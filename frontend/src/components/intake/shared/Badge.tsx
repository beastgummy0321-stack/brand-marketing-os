import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** 建檔精靈共用的小圓角標籤（票 B3-intake）。跟其他 feature 的 `shared/Badge.tsx` 樣式相同
 * 但獨立一份（模組化規則：跨 feature 只准 import components/layout/ 與 lib/）。 */
export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "danger" | "warning" | "success" }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium",
        tone === "neutral" && "bg-muted text-muted-foreground",
        tone === "danger" && "bg-danger/10 text-danger",
        tone === "warning" && "bg-warning/10 text-warning",
        tone === "success" && "bg-success/10 text-success",
      )}
    >
      {children}
    </span>
  );
}
