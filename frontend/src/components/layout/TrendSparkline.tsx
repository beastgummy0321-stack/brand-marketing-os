import { cn } from "@/lib/utils";

/** V3 流體卡片語彙：趨勢縮圖（GRILL-B4R-performance.md R4-3 歷史歸檔頁「每列關鍵數字
 * ＋趨勢縮圖欄」）。純展示元件，`data` 是呼叫端算好的數列，這裡只負責畫線——不做
 * 統計、不猜缺值，資料形狀由呼叫端保證。 */
export function TrendSparkline({
  data,
  width = 80,
  height = 24,
  colorClassName = "stroke-primary",
  className,
}: {
  data: number[];
  width?: number;
  height?: number;
  colorClassName?: string;
  className?: string;
}) {
  if (data.length === 0) {
    return (
      <div style={{ width, height }} className={cn("flex items-center text-xs text-muted-foreground", className)}>
        尚無資料
      </div>
    );
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1; // 全部同值時避免除以 0，畫一條水平線
  const step = data.length > 1 ? width / (data.length - 1) : 0;
  const points = data
    .map((v, i) => {
      const x = i * step;
      const y = height - ((v - min) / range) * height;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className={className} role="img" aria-label="趨勢縮圖">
      <polyline
        points={points}
        fill="none"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        className={colorClassName}
      />
    </svg>
  );
}
