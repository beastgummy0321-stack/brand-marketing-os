import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** V3 流體卡片語彙：環形進度（GRILL-B4R-performance.md R1-3／R3-4，交接總分環、
 * 訂單歸因環等共用這一顆）。純展示元件，不含資料邏輯——`value` 是呼叫端算好的
 * 0-100 百分比，中央文字由呼叫端用 `children` 傳（例如「N/M 通過」）。
 *
 * `indeterminate` 給資料仍在讀取的等效「進行中」態：轉圈動畫，`motion-reduce`
 * 退化成靜態半圈（不閃爍，無障礙鐵則）。 */
export function ProgressRing({
  value,
  size = 96,
  strokeWidth = 10,
  colorClassName = "stroke-primary",
  trackClassName = "stroke-muted",
  indeterminate = false,
  children,
  className,
}: {
  value: number;
  size?: number;
  strokeWidth?: number;
  colorClassName?: string;
  trackClassName?: string;
  indeterminate?: boolean;
  children?: ReactNode;
  className?: string;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.min(100, Math.max(0, value));
  const offset = indeterminate ? circumference * 0.75 : circumference * (1 - clamped / 100);

  return (
    <div className={cn("relative inline-flex items-center justify-center", className)} style={{ width: size, height: size }}>
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className={cn(indeterminate && "animate-spin motion-reduce:animate-none")}
        role="img"
        aria-label={indeterminate ? "讀取中" : `進度 ${Math.round(clamped)}%`}
      >
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={strokeWidth} className={trackClassName} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          className={cn(colorClassName, "transition-[stroke-dashoffset] duration-700 ease-out motion-reduce:transition-none")}
        />
      </svg>
      {children && <div className="absolute inset-0 flex flex-col items-center justify-center">{children}</div>}
    </div>
  );
}
