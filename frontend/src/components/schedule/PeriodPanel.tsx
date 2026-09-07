import { formatCurrency } from "@/lib/format";
import { PERIOD_STATUS_LABELS, type SchedulePeriod } from "@/lib/scheduleApi";
export function PeriodPanel({
  period,
  settling,
  settleError,
  onSettle,
}: {
  period: SchedulePeriod;
  settling: boolean;
  settleError: string | null;
  onSettle: (periodId: string) => void;
}) {
  const badgeClass =
    period.status === "awaiting_data"
      ? "bg-danger/10 text-danger"
      : period.status === "running"
        ? "bg-success/10 text-success"
        : "bg-muted text-muted-foreground";
  const settled = period.settled;
  const hasLateMoney = settled !== null
    && (settled.late_spend_since !== 0 || settled.late_revenue_since !== 0);

  return (
    <div className="surface px-5 py-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-base text-foreground">{period.name}</h2>
        <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium ${badgeClass}`}>
          {PERIOD_STATUS_LABELS[period.status]}
        </span>
      </div>
      <p className="mb-2 text-xs text-muted-foreground">{period.start_date} ～ {period.end_date}{period.daily_budget !== null && `・每日預算 ${formatCurrency(period.daily_budget)}`}</p>

      {period.status === "awaiting_data" && (
        <div className="flex flex-col items-start gap-2">
          <p className="text-sm text-foreground">
            這期已結束。Meta 的成交回報最長 7 天才補齊，建議 {period.settle_advice_date} 之後再結算。
          </p>
          {settleError && <p className="text-sm text-danger">{settleError}</p>}
          <button
            type="button"
            onClick={() => onSettle(period.id)}
            disabled={settling}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {settling ? "結算中…" : "結算這期"}
          </button>
        </div>
      )}

      {settled && (
        <div className="flex flex-col items-start gap-1">
          <p className="text-sm text-foreground">花費：{formatCurrency(settled.spend)}</p>
          <p className="text-sm text-foreground">這期間全通路營收：{formatCurrency(settled.revenue)}</p>
          <p className="text-sm text-muted-foreground">
            結算時間：{new Date(settled.settled_at).toLocaleString("zh-TW")}
          </p>
          {settled.late_spend_since !== 0 && (
            <p className="text-sm text-foreground">
              結算後花費又進來 {formatCurrency(settled.late_spend_since)}
            </p>
          )}
          {settled.late_revenue_since !== 0 && (
            <p className="text-sm text-foreground">
              結算後營收又進來 {formatCurrency(settled.late_revenue_since)}
            </p>
          )}
          {hasLateMoney && (
            <>
              {settleError && <p className="text-sm text-danger">{settleError}</p>}
              <button
                type="button"
                onClick={() => onSettle(period.id)}
                disabled={settling}
                className="mt-1 rounded-md border border-primary px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {settling ? "結算中…" : "重新結算"}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}


