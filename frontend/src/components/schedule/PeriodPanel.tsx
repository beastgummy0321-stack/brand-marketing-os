import { formatCurrency, formatMetaRoas } from "@/lib/format";
import {
  NODE_RESULT_DEPTH_LABELS,
  NODE_RESULT_VERDICT_LABELS,
  PERIOD_STATUS_LABELS,
  type SchedulePeriod,
} from "@/lib/scheduleApi";
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

      {period.node_results.length > 0 && <NodeResultTable results={period.node_results} />}
    </div>
  );
}

/** 票 smart-loop 01（ADR 0066）：結算之後，每個綁定節點對打平線的判決。全部零花費是
 * 「這期綁定的物件還沒有花費紀錄」，不是判讀壞了——句子講在表格之前（ticket §5）。
 * 票 smart-loop 03：加一句提醒花費的口徑差——結算上面的花費是品牌層（含這期沒綁定、
 * 未登記的廣告），這張表只算綁定到節點的那一份，兩個數字本來就不會相等（ADR 0055 §11；
 * 票 01 走查的實機驗收看到 1,068 對零花費的表格，當場問了）。 */
function NodeResultTable({ results }: { results: SchedulePeriod["node_results"] }) {
  const allZeroSpend = results.every((row) => row.actual_spend === 0);
  const breakeven = results[0];
  return (
    <div className="mt-3 flex flex-col gap-2">
      <p className="text-sm text-muted-foreground">
        花費是品牌層的數字（含未登記的廣告）；下表只算這期綁定的節點。
      </p>
      {allZeroSpend && (
        <p className="text-sm text-muted-foreground">
          這期綁定的 Meta 物件沒有花費紀錄，判決全部是「看不出」。
        </p>
      )}
      <div className="table-surface">
        <table className="w-full text-left text-sm">
          <thead className="bg-muted text-muted-foreground">
            <tr>
              <th>節點</th>
              <th>層</th>
              <th>核准比例</th>
              <th>實花</th>
              <th>保守 ROAS</th>
              <th>樂觀 ROAS</th>
              <th>判決</th>
            </tr>
          </thead>
          <tbody>
            {results.map((row) => (
              <tr key={row.node_key} className="border-t border-border">
                <td>{row.node_name}</td>
                <td>{NODE_RESULT_DEPTH_LABELS[row.depth]}</td>
                <td className="numeric">
                  {row.approved_share === null ? "—" : `${(row.approved_share * 100).toFixed(0)}%`}
                </td>
                <td className="numeric">{formatCurrency(row.actual_spend)}</td>
                <td className="numeric">{formatMetaRoas(row.roas_conservative)}</td>
                <td className="numeric">{formatMetaRoas(row.roas_optimistic)}</td>
                <td>{NODE_RESULT_VERDICT_LABELS[row.verdict]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-sm text-muted-foreground">
        {breakeven.breakeven_roas === null
          ? `算不出打平線：${breakeven.breakeven_source}`
          : `打平線 ${breakeven.breakeven_roas.toFixed(2)}x，來自${breakeven.breakeven_source}`}
      </p>
    </div>
  );
}


