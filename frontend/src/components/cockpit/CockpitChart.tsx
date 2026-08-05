import type { EChartsOption } from "echarts";
import type { CockpitData } from "@/lib/api";
import { CHART_COLOR_REVENUE, CHART_COLOR_SPEND } from "@/lib/chartColors";
import { useEchart } from "@/lib/useEchart";

/** 主圖（票 03-cockpit-kpi-chart）：營收 vs 廣告花費疊線，單一金額軸（兩條線同單位，
 * 不做雙軸——dataviz 技能包「兩把量尺 → 兩張圖或同基準指數化，絕不雙軸」）。
 * 顏色只分類（哪條線是營收／花費），不表數值大小（規格圖表鐵則：無圓餅/儀表盤/3D）。 */
export function CockpitChart({ chart }: { chart: CockpitData["chart"] }) {
  const hasData = chart.revenue.some((v) => v !== null) || chart.spend.some((v) => v !== null);

  const option: EChartsOption = {
    color: [CHART_COLOR_REVENUE, CHART_COLOR_SPEND],
    grid: { top: 48, right: 24, bottom: 32, left: 72 },
    legend: { data: ["營收", "廣告花費"], top: 0 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: chart.months },
    yAxis: {
      type: "value",
      axisLabel: { formatter: (v: number) => `NT$${Math.round(v / 1000)}k` },
    },
    series: [
      {
        name: "營收",
        type: "line",
        data: chart.revenue,
        connectNulls: true,
        symbolSize: 6,
        lineStyle: { width: 2 },
      },
      {
        name: "廣告花費",
        type: "line",
        data: chart.spend,
        connectNulls: true,
        symbolSize: 6,
        lineStyle: { width: 2 },
      },
    ],
  };
  const ref = useEchart(option);

  if (!hasData) {
    return (
      <div className="flex h-72 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-card text-center shadow-[var(--shadow-card)]">
        <p className="text-sm font-medium text-foreground">還沒有營收或廣告花費資料</p>
        <p className="text-xs text-muted-foreground">
          累積訂單與成效資料後，這裡會畫出營收與花費的疊線走勢。
        </p>
      </div>
    );
  }

  return (
    <div
      ref={ref}
      className="h-72 w-full rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]"
    />
  );
}
