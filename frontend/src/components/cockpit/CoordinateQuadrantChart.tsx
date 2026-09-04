import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import { CHART_COLOR_LOSS_ZONE, CHART_COLOR_SPEND } from "@/lib/chartColors";
import { formatCurrency } from "@/lib/format";
import { splitPlottable, type QuadrantPoint } from "@/lib/quadrant";
import { useEchart } from "@/lib/useEchart";
import type { CreativePerformanceUntagged, CreativePerformanceValue } from "@/lib/scheduleApi";

/** 票 T6b（ADR 0057 §5–§8）：一個維度的座標賺賠圖。零行後端改動——`spend`／`revenue`／
 * `roas` 三個數字 T5 就已經回了，這裡只是把它們擺到位置上。
 *
 * **為什麼一個座標是一段線不是一個點**（2026-09-04 探針量到的，看板原本沒有這一條）：
 * 後端的 `roas` 分母是「有追蹤到轉換的那幾天的花費」，不是全部花費（ADR 0057 §7 刻意
 * 如此——不套 `spend_summary` 的 `bool_and`，免得一天沒追蹤就把整個月吃掉）。所以同一個
 * 座標有兩個都成立的 ROAS：
 *   保守 = `revenue / spend`      沒追蹤到的那幾天當作沒賺
 *   樂觀 = `roas`（後端給的）      沒追蹤到的那幾天當作跟有追蹤的一樣好
 * 實測：花 3,570、追蹤到營收 2,737.8、覆蓋率 75% → 保守 0.767（賠）、樂觀 1.029（賺）。
 * **只畫其中一個就是在挑一個謊。** 所以畫成一段從保守拉到樂觀的線，橫跨打平線的那幾段
 * 就是「資料還不夠，不知道賺賠」。覆蓋率 100% 時兩端重合，自然變回一個點。
 *
 * 顏色只有一個（`CHART_COLOR_SPEND`）：賺或賠由它在打平線的上下決定，座標靠直接標籤認人，
 * 兩者都不靠顏色分辨——所以不需要七個分類色（理由與 dataviz 驗證結果見 `chartColors.ts`）。
 *
 * 沒有直的那條分界線（2026-09-04 使用者裁決）：今天圖上只有個位數的座標，任何一條
 * 「花很多錢」的門檻都是編的。位置留著，之後加一條垂直線就是四象限。 */

/** 泡泡大小照曝光數開根號縮放（面積正比於曝光，不是直徑）。下限 8px 是可點擊的最小記號。 */
function symbolSize(impressions: number): number {
  return Math.max(8, Math.min(44, Math.sqrt(impressions) / 11));
}

function buildOption(points: QuadrantPoint[]): EChartsOption {
  // 上緣進位到 0.5 的倍數：直接用 `max(...)*1.15` 會讓刻度印出 2.415 這種算出來的數字。
  const maxY = Math.ceil(Math.max(1.4, ...points.map((p) => p.high * 1.15)) * 2) / 2;
  return {
    grid: { left: 56, right: 72, top: 24, bottom: 44 },
    xAxis: {
      type: "value",
      name: "本月花費",
      nameLocation: "middle",
      nameGap: 26,
      min: 0,
      axisLabel: { formatter: (v: number) => `${Math.round(v).toLocaleString("zh-TW")}` },
      splitLine: { lineStyle: { opacity: 0.35 } },
    },
    yAxis: {
      type: "value",
      name: "ROAS",
      min: 0,
      max: maxY,
      splitLine: { lineStyle: { opacity: 0.35 } },
    },
    tooltip: {
      trigger: "item",
      formatter: (params: unknown) => {
        const p = (params as { data: { point: QuadrantPoint } }).data.point;
        return [
          `<b>${p.label}</b>`,
          `花費 ${formatCurrency(p.spend)}　營收 ${formatCurrency(p.revenue)}`,
          `ROAS ${p.low.toFixed(2)}x（保守）～ ${p.high.toFixed(2)}x（樂觀）`,
          `資料覆蓋率 ${(p.coverage * 100).toFixed(0)}%　廣告 ${p.adCount} 則`,
          `曝光 ${p.impressions.toLocaleString("zh-TW")}　點擊 ${p.clicks.toLocaleString("zh-TW")}`,
        ].join("<br/>");
      },
    },
    series: points.map((p, index) => ({
      type: "line" as const,
      name: p.label,
      data: [
        { value: [p.spend, p.low], point: p, symbolSize: symbolSize(p.impressions) },
        {
          value: [p.spend, p.high],
          point: p,
          symbolSize: symbolSize(p.impressions),
          label: {
            show: true,
            position: "top" as const,
            formatter: p.label,
            color: "#334155",
            fontSize: 12,
          },
        },
      ],
      symbol: "circle",
      lineStyle: { width: 2, color: CHART_COLOR_SPEND, opacity: 0.55 },
      itemStyle: { color: CHART_COLOR_SPEND, opacity: 0.75, borderColor: "#f8fafc", borderWidth: 2 },
      // 打平線與賠錢區塊只掛在第一個系列上——每個系列各掛一份會疊出七層一樣的色塊。
      ...(index === 0
        ? {
            markArea: {
              silent: true,
              itemStyle: { color: CHART_COLOR_LOSS_ZONE, opacity: 0.07 },
              label: {
                show: true,
                position: "insideBottomLeft" as const,
                formatter: "打平線以下＝賠錢",
                color: "#64748b",
                fontSize: 12,
              },
              data: [[{ yAxis: 0 }, { yAxis: 1 }]],
            },
            markLine: {
              silent: true,
              symbol: "none" as const,
              lineStyle: { color: CHART_COLOR_LOSS_ZONE, type: "dashed" as const, width: 1.5 },
              label: { formatter: "打平 1.0x", color: "#64748b", position: "end" as const },
              data: [{ yAxis: 1 }],
            },
          }
        : {}),
    })) as EChartsOption["series"],
  };
}

export function CoordinateQuadrantChart({
  values, untagged,
}: {
  values: CreativePerformanceValue[];
  untagged: CreativePerformanceUntagged;
}) {
  const { points, noSpend, noRevenue } = useMemo(() => splitPlottable(values), [values]);
  const option = useMemo(() => buildOption(points), [points]);
  const ref = useEchart(option);

  if (points.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        這個維度還沒有可以畫的座標——要上圖得同時有花費、又追蹤到營收。底下那張表是完整的數字。
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div ref={ref} className="h-72 w-full" />
      <ul className="flex flex-col gap-0.5 text-xs text-muted-foreground">
        <li>泡泡愈大＝曝光愈多。一段線＝這個座標的 ROAS 可能落在哪，線愈長代表追蹤到的天數愈少。</li>
        {untagged.ad_count > 0 && (
          <li>
            另有未標座標 {formatCurrency(untagged.spend)}（{untagged.ad_count} 則廣告）沒有畫在圖上——
            那是手動建的廣告，沒有座標可以對。
          </li>
        )}
        {noSpend.length > 0 && (
          <li>
            這個月還沒花到錢，所以沒上圖：{noSpend.map((v) => v.label).join("、")}
            （廣告可能還在審核或被退，不代表這個角度沒人要）。
          </li>
        )}
        {noRevenue.length > 0 && (
          <li>
            有花費但一天都沒追蹤到轉換，畫不出 ROAS：{noRevenue.map((v) => v.label).join("、")}。
          </li>
        )}
      </ul>
    </div>
  );
}
