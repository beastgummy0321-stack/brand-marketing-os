import { cn } from "@/lib/utils";

/** 骨架佔位塊（票 B1-inbox／B1-settings）：進行中態要「灰色佔位卡片」，不是純文字
 * 「讀取中…」——契約 S2.19／S2.20／S15 進行中態明講要看得到卡片形狀。原生 CSS
 * `animate-pulse`（Tailwind 內建）即可，不必為此裝動畫函式庫。`motion-reduce` 退化成
 * 靜態灰塊，不閃爍。 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "animate-pulse rounded-md bg-muted motion-reduce:animate-none",
        className,
      )}
    />
  );
}
