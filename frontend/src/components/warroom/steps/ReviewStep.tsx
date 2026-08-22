import { useEffect, useState } from "react";
import type { EChartsOption } from "echarts";
import { Link } from "react-router-dom";
import { FluidCard } from "@/components/layout/FluidCard";
import { StatBig } from "@/components/layout/StatBig";
import { CHART_COLOR_REVENUE, CHART_COLOR_SPEND } from "@/lib/chartColors";
import { formatCurrency, formatPercent, formatRoas } from "@/lib/format";
import { useEchart } from "@/lib/useEchart";
import { fetchClosingReview, type ClosingReview, type Cycle } from "@/lib/warroomApi";

const VERDICT_LABELS = { supported: "成立", rejected: "不成立", inconclusive: "看不出來" } as const;

/** 覆盤（S8R.23-26 重設計，吸收舊 `S8.59-66`，僅 `cycle.status === 'CLOSED'` 後出現）：固定
 * 四段式，圖像化每一段（雙條圖／環形圖／學習兩張卡／前後對照長條），資料源完全沿用舊條文，
 * 只新增每段的視覺形式，不重新計算任何判讀邏輯。 */
export function ReviewStep({ brandId, cycle }: { brandId: string; cycle: Cycle }) {
  const [state, setState] = useState<{ status: "loading" } | { status: "locked"; message: string } | { status: "ready"; review: ClosingReview }>({ status: "loading" });

  useEffect(() => {
    fetchClosingReview(brandId, cycle.id)
      .then((review) => setState({ status: "ready", review }))
      .catch((err: unknown) => setState({ status: "locked", message: err instanceof Error ? err.message : "這期還沒結案，覆盤要等成效判讀跑完期末結算才會出現。" }));
  }, [brandId, cycle.id]);

  if (state.status === "loading") return <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">讀取中…</div>;
  if (state.status === "locked") {
    return <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">{state.message}</div>;
  }

  const { review } = state;
  return (
    <div className="flex flex-col gap-4">
      <h2 className="font-display text-lg text-foreground">這期覆盤</h2>
      <GoalComparisonCard review={review} />
      <AttributionCard review={review} />
      <LearningCard review={review} />
      <NextCycleCard brandId={brandId} review={review} cycle={cycle} />
      <p className="text-xs text-muted-foreground">本週報告掛載點（B5 範圍，本票只留入口，內部長相延至 B5）。</p>
    </div>
  );
}

/** S8R.23：①目標對照——雙條圖（左＝原訂目標，右＝實際算出的對應 KPI）。 */
function GoalComparisonCard({ review }: { review: ClosingReview }) {
  const { goal_comparison: g } = review;
  const gapPct = g.actual_value === null ? null : Math.round(((g.actual_value - g.target_value) / g.target_value) * 1000) / 10;
  const option: EChartsOption = {
    grid: { left: 56, right: 32, top: 16, bottom: 24 },
    xAxis: { type: "value", name: g.metric_label, axisLabel: { formatter: (v: number) => v.toLocaleString("zh-TW") } },
    yAxis: { type: "category", data: ["目標", "實際"] },
    series: [
      {
        type: "bar",
        barWidth: 22,
        label: { show: true, position: "right", formatter: (p) => (p.value as number).toLocaleString("zh-TW") },
        data: [g.target_value, g.actual_value ?? 0],
      },
    ],
  };
  const ref = useEchart(option);

  return (
    <FluidCard title="①目標對照" subtitle={`${g.objective_label}・${g.target}`}>
      <div ref={ref} className="h-32 w-full" />
      <p className="mt-1 text-sm text-foreground">
        {g.actual_value === null
          ? "還沒有可以算的成效數字，算不出差距。"
          : `實際比目標${gapPct !== null && gapPct >= 0 ? "高" : "低"} ${Math.abs(gapPct ?? 0)}%${g.lower_is_better ? "（這個指標越低越好）" : ""}`}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        CTR {review.goal_comparison.actual_kpis.ctr !== null ? formatPercent(review.goal_comparison.actual_kpis.ctr) : "資料不足"}、CPA {formatCurrency(review.goal_comparison.actual_kpis.cpa)}、ROAS {formatRoas(review.goal_comparison.actual_kpis.roas)}
      </p>
    </FluidCard>
  );
}

/** S8R.24：②落差歸因——環形圖（訂單歸因四分類佔比）＋下方判讀結論既有理由清單原樣引用。 */
function AttributionCard({ review }: { review: ClosingReview }) {
  const { attribution: a, reasons, channel_note, ga4_leak_note } = review.gap_attribution;
  const total = a.gross.count + a.net.count + a.excluded.count + a.natural.count;
  const option: EChartsOption = {
    tooltip: { trigger: "item" },
    legend: { bottom: 0 },
    series: [
      {
        type: "pie",
        radius: ["40%", "68%"],
        avoidLabelOverlap: true,
        label: { formatter: "{b}\n{d}%" },
        data: [
          { name: "毛單", value: a.gross.count },
          { name: "淨單", value: a.net.count },
          { name: "排除", value: a.excluded.count },
          { name: "自然單", value: a.natural.count },
        ],
      },
    ],
  };
  const ref = useEchart(option);

  return (
    <FluidCard title="②落差歸因">
      {total === 0 ? (
        <p className="text-sm text-muted-foreground">這期還沒有收到訂單歸因資料。</p>
      ) : (
        <>
          <div ref={ref} className="h-56 w-full" />
          <dl className="mt-2 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            {([
              ["毛單", a.gross],
              ["淨單", a.net],
              ["排除", a.excluded],
              ["自然單", a.natural],
            ] as const).map(([label, cat]) => (
              <div key={label}>
                <dt className="text-xs text-muted-foreground">{label}</dt>
                <dd className="text-foreground">{cat.count} 筆・{formatCurrency(cat.net_revenue)}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
      <ul className="mt-3 list-disc pl-4 text-sm text-foreground">
        {reasons.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
      {channel_note && <p className="mt-1 text-xs text-muted-foreground">{channel_note}</p>}
      {ga4_leak_note && <p className="mt-1 text-xs text-warning">{ga4_leak_note}</p>}
    </FluidCard>
  );
}

/** S8R.25：③學習兩層——本期層（策略假設結案）／跨期層（累積智慧）兩張卡。 */
function LearningCard({ review }: { review: ClosingReview }) {
  const { learning } = review;
  return (
    <FluidCard title="③學到的事">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-md border border-border p-3">
          <p className="text-xs font-medium text-muted-foreground">這期驗證了什麼</p>
          <ul className="mt-1 list-disc pl-4 text-sm text-foreground">
            {learning.hypotheses.map((h, i) => (
              <li key={i}>
                {h.statement}：{VERDICT_LABELS[h.verdict]}
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-md border border-border p-3">
          <p className="text-xs font-medium text-muted-foreground">累積下來學到什麼</p>
          {learning.ledger_entries.length === 0 ? (
            <p className="mt-1 text-sm text-muted-foreground">這期沒有新入帳的累積智慧。</p>
          ) : (
            <ul className="mt-1 list-disc pl-4 text-sm text-foreground">
              {learning.ledger_entries.map((e, i) => (
                <li key={i}>{e.text}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </FluidCard>
  );
}

/** S8R.26：④下期建議——前後對照長條（本期預算→下期建議預算）＋一鍵帶設定按鈕。 */
function NextCycleCard({ brandId, review, cycle }: { brandId: string; review: ClosingReview; cycle: Cycle }) {
  const { recommendation: r } = review;
  const option: EChartsOption = {
    color: [CHART_COLOR_SPEND, CHART_COLOR_REVENUE],
    grid: { left: 56, right: 32, top: 16, bottom: 24 },
    xAxis: { type: "value", axisLabel: { formatter: (v: number) => `NT$${Math.round(v / 1000)}k` } },
    yAxis: { type: "category", data: ["本期預算", "下期建議"] },
    series: [
      {
        type: "bar",
        barWidth: 22,
        label: { show: true, position: "right", formatter: (p) => formatCurrency(p.value as number) },
        data: [
          { value: cycle.budget, itemStyle: { color: CHART_COLOR_SPEND } },
          { value: r.proposed_budget, itemStyle: { color: CHART_COLOR_REVENUE } },
        ],
      },
    ],
  };
  const ref = useEchart(option);

  return (
    <FluidCard title="④下期建議">
      <div ref={ref} className="h-24 w-full" />
      <StatBig value={formatCurrency(r.proposed_budget)} label="下期建議預算" className="mt-2" />
      <p className="mt-1 text-sm text-foreground">{r.budget_advice}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        新增規則卡 {r.rule_cards_created} 張
        {r.echo_chamber && "・已提示避免回音室"}
      </p>
      <Link to={`/brands/${brandId}/campaigns/new`} className="mt-3 inline-block self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">
        開下一期就這樣開
      </Link>
    </FluidCard>
  );
}
