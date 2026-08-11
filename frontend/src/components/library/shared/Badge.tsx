import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** 品牌智庫六分頁共用的小圓角標籤（票 B2-library）：類型、嚴重度、狀態都用同一顆，
 * 十幾處呼叫端共用同一組樣式，不各自重寫 class 字串。 */
export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "danger" | "warning" | "success";
}) {
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
