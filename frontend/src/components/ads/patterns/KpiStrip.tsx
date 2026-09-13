import type { LucideIcon } from "lucide-react";

export interface KpiCell {
  icon: LucideIcon;
  label: string;
  value: string;
  /** design-system §7「每個數字都要有說明」：必填，不是選填的裝飾。 */
  caption: string;
}

/** 數字條（F04-I07）：3～5 格等寬，格間 1px 直線。cells.length 只接受 3～5——
 * TypeScript 不強制，呼叫端自己保證。 */
export function KpiStrip({ cells }: { cells: KpiCell[] }) {
  return (
    <div className="surface grid grid-cols-1 sm:grid-cols-[repeat(var(--kpi-cols),minmax(0,1fr))]" style={{ ["--kpi-cols" as string]: cells.length }}>
      {cells.map((cell, i) => {
        const Icon = cell.icon;
        return (
          <div
            key={cell.label}
            className={`flex items-center gap-3 p-4 ${i > 0 ? "sm:border-l sm:border-border" : ""}`}
          >
            <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent">
              <Icon className="size-4 text-primary" />
            </div>
            <div className="flex flex-col">
              <span className="text-xs text-muted-foreground">{cell.label}</span>
              <span className="metric-number">{cell.value}</span>
              <span className="text-xs text-muted-foreground">{cell.caption}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
