import { ChevronDown } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** V3 流體卡片殼（GRILL-B4R-performance.md R1-3）：比既有卡片（`--radius-lg`＋
 * `--shadow-card`）更圓、更有深度，hover／展開時陰影加深＋輕微上浮。展開收合用
 * CSS grid-template-rows 技巧做高度動畫（原生 CSS 勝 JS 動畫函式庫，ladder 第四階）,
 * 不必量測實際高度。
 *
 * 不收合時（`collapsible` 未給）就是單純卡片殼，給 R1-3「全站升級」其他頁面直接拿來
 * 包內容用；收合摘要模式給 R1-2 作戰室「目前階段展開、其他收合成摘要卡」用
 * （TaskFlowShell 的 `collapsedMode` 內部就是逐步驟疊這一顆）。 */
export function FluidCard({
  title,
  subtitle,
  children,
  collapsedSummary,
  collapsible = false,
  expanded = true,
  onToggleExpand,
  hoverable = true,
  className,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  collapsedSummary?: ReactNode;
  collapsible?: boolean;
  expanded?: boolean;
  onToggleExpand?: () => void;
  hoverable?: boolean;
  className?: string;
}) {
  const hasHeader = title || subtitle || collapsible;

  return (
    <div
      className={cn(
        "rounded-[var(--radius-xl)] border border-border bg-card p-6 shadow-[var(--shadow-card)]",
        "transition-[box-shadow,transform] duration-300 ease-out motion-reduce:transition-none",
        hoverable && "hover:shadow-[var(--shadow-card-hover)] hover:-translate-y-0.5",
        className,
      )}
    >
      {hasHeader && (
        <button
          type="button"
          disabled={!collapsible}
          onClick={onToggleExpand}
          className={cn(
            "flex w-full items-center justify-between gap-3 text-left",
            collapsible ? "cursor-pointer" : "cursor-default",
            (children || collapsedSummary) && "mb-3",
          )}
        >
          <div>
            {title && <h3 className="font-display text-lg text-foreground">{title}</h3>}
            {subtitle && <p className="text-sm text-muted-foreground">{subtitle}</p>}
          </div>
          {collapsible && (
            <ChevronDown
              className={cn(
                "h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-300 ease-out motion-reduce:transition-none",
                expanded && "rotate-180",
              )}
              aria-hidden="true"
            />
          )}
        </button>
      )}

      {!expanded && collapsedSummary && <div className="text-sm text-muted-foreground">{collapsedSummary}</div>}

      <div
        className={cn(
          "grid transition-[grid-template-rows] duration-300 ease-out motion-reduce:duration-0",
          expanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
        )}
      >
        <div className="overflow-hidden">{children}</div>
      </div>
    </div>
  );
}
