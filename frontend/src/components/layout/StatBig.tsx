import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

const TREND_ICON = { up: TrendingUp, down: TrendingDown, flat: Minus } as const;
const TREND_CLASS = { up: "text-success", down: "text-danger", flat: "text-muted-foreground" } as const;

/** V3 流體卡片語彙：大數字（GRILL-B4R-performance.md R4-3 歷史歸檔頁「每列關鍵數字」、
 * S3P 系列各視圖摘要數字）。純展示元件，`value` 傳呼叫端已格式化好的字串（幣別／百分比
 * 由呼叫端決定，這裡不猜格式）。`value` 為 `null` 時顯示「—」等效空態。 */
export function StatBig({
  value,
  label,
  trend,
  className,
}: {
  value: string | number | null;
  label?: string;
  trend?: { direction: "up" | "down" | "flat"; text: string };
  className?: string;
}) {
  const TrendIcon = trend ? TREND_ICON[trend.direction] : null;

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="font-display text-3xl tabular-nums text-foreground">{value ?? "—"}</span>
      {label && <span className="text-sm text-muted-foreground">{label}</span>}
      {trend && TrendIcon && (
        <span className={cn("flex items-center gap-1 text-xs font-medium", TREND_CLASS[trend.direction])}>
          <TrendIcon className="h-3 w-3" aria-hidden="true" />
          {trend.text}
        </span>
      )}
    </div>
  );
}
