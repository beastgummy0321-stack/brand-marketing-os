import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** v10 `.lg` (F30): a wrapping row of legend entries, each an 8px swatch then its words. `swatch` is the
 * swatch's own classes (fill, border or ring), so a legend always names the same classes as the piece it
 * explains — e.g. `DAY_SWATCH` from `DayGrid`. `line` draws the cap-line entry (2px wide). `data-slot="legend"`. */

export interface LegendItem { label: ReactNode; swatch: string; line?: boolean }

export function Legend({ items, className }: { items: LegendItem[]; className?: string }) {
  return (
    <div data-slot="legend" className={cn("flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground", className)}>
      {items.map((it, i) => (
        <span key={i}>
          <i aria-hidden="true" className={cn("mr-[5px] inline-block h-2 rounded-[2px]", it.line ? "w-0.5" : "w-2", it.swatch)} />
          {it.label}
        </span>
      ))}
    </div>
  );
}
