import { cn } from "@/lib/utils";

/** 健康燈號四態，字面沿用 GRILL-B4R-performance.md 假資料型別 `HealthLightStatus`
 * （契約條文第 429 行），不得自創詞彙代替規格已定義的狀態值（reuse-first 第四節）。 */
export type StatusLightValue = "green" | "yellow" | "red" | "insufficient";

const DOT_CLASS: Record<StatusLightValue, string> = {
  green: "bg-success",
  yellow: "bg-warning",
  red: "bg-danger",
  insufficient: "bg-muted-foreground",
};

/** 中文狀態字給螢幕閱讀器與純文字說明用——不得只靠顏色傳達狀態（無障礙鐵則）。
 * 呼叫端可用 `statusText` 覆寫成更貼切的白話說明。 */
const DEFAULT_TEXT: Record<StatusLightValue, string> = {
  green: "正常",
  yellow: "注意",
  red: "異常",
  insufficient: "資料不足",
};

/** V3 流體卡片語彙：健康燈號（GRILL-B4R-performance.md R3-3「一排大燈號」）。
 * 純展示元件——是否要在非綠燈時展開數字明細，由呼叫端（駕駛艙／作戰室頁面）決定，
 * 這裡只負責畫一顆燈＋標籤。 */
export function StatusLight({
  status,
  label,
  statusText,
  size = "lg",
  className,
}: {
  status: StatusLightValue;
  label: string;
  statusText?: string;
  size?: "sm" | "lg";
  className?: string;
}) {
  const dotSize = size === "lg" ? "h-4 w-4" : "h-2.5 w-2.5";
  const text = statusText ?? DEFAULT_TEXT[status];

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span className={cn("shrink-0 rounded-full", dotSize, DOT_CLASS[status])} aria-hidden="true" />
      <div className="flex flex-col leading-tight">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <span className="text-xs text-muted-foreground">{text}</span>
      </div>
    </div>
  );
}
