import type { EChartsOption } from "echarts";
import type { CockpitKpi } from "@/lib/api";
import { CHART_COLOR_REVENUE } from "@/lib/chartColors";
import { formatMomPct } from "@/lib/format";
import { useEchart } from "@/lib/useEchart";

/** KPI 卡（票 03-cockpit-kpi-chart）：數字＋環比＋迷你趨勢線。趨勢線不畫座標軸／
 * 提示框——首屏只給「形狀」，細節看主圖（規格圖表鐵則「首屏只做一眼判斷好壞」）。
 * 完全沒資料時顯示文字，不畫一顆空白/壞掉的圖（規格驗收條件）。 */
export function KpiCard({
  label,
  kpi,
  format,
}: {
  label: string;
  kpi: CockpitKpi;
  format: (value: number | null) => string;
}) {
  const hasTrend = kpi.trend.some((v) => v !== null);
  const option: EChartsOption = {
    grid: { top: 4, right: 4, bottom: 4, left: 4 },
    xAxis: { type: "category", show: false, data: kpi.trend.map((_, i) => i) },
    yAxis: { type: "value", show: false, scale: true },
    tooltip: { show: false },
    series: [
      {
        type: "line",
        data: kpi.trend,
        showSymbol: false,
        connectNulls: true,
        lineStyle: { width: 2, color: CHART_COLOR_REVENUE },
        areaStyle: { color: CHART_COLOR_REVENUE, opacity: 0.08 },
      },
    ],
  };
  const ref = useEchart(option);

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="text-2xl font-semibold text-foreground">{format(kpi.value)}</p>
      <p className="h-4 text-xs text-muted-foreground">{formatMomPct(kpi.mom_pct)}</p>
      {hasTrend ? (
        <div ref={ref} className="h-10 w-full" />
      ) : (
        <p className="flex h-10 items-center text-xs text-muted-foreground">
          還沒有足夠資料畫趨勢線
        </p>
      )}
    </div>
  );
}
