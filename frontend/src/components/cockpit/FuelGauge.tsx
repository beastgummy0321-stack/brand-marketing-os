import type { FuelGauge as FuelGaugeData } from "@/lib/api";

/** AI 油錢錶（票 05-alerts-fuel-pipeline）：本月已花／全站共用花費上限。幣別沿用
 * `app/core/settings.py` budget_exceeded_message() 的美元口徑（US$），不跟 KPI 卡
 * 的 NT$ 混用。 */
export function FuelGauge({ gauge }: { gauge: FuelGaugeData }) {
  const pct = gauge.limit > 0 ? Math.min(100, (gauge.spent_this_month / gauge.limit) * 100) : 0;
  const over = gauge.spent_this_month > gauge.limit;

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]">
      <p className="text-sm text-muted-foreground">AI 油錢錶（本月）</p>
      <p className="text-lg font-semibold text-foreground">
        US$ {gauge.spent_this_month.toFixed(2)}
        <span className="ml-1 text-sm font-normal text-muted-foreground">
          ／ US$ {gauge.limit.toFixed(2)} 上限
        </span>
      </p>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full ${over ? "bg-danger" : "bg-primary"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
