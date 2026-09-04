import type { CreativePerformanceValue } from "@/lib/scheduleApi";

/** 票 T6b：把一個維度的座標分成「畫得出來」與兩種「畫不出來」。放在 lib 不放在圖表元件裡，
 * 因為這裡是這張圖唯一做算術的地方（保守 ROAS＝營收 ÷ 全部花費），要單獨測得到。
 *
 * 後端的 `roas` 分母是「有追蹤到轉換的那幾天的花費」，不是全部花費（ADR 0057 §7）。所以
 * 同一個座標有兩個都成立的 ROAS，兩個都要帶出去給圖畫成一段區間；細節見
 * `components/cockpit/CoordinateQuadrantChart.tsx` 檔頭。 */
export interface QuadrantPoint {
  key: string;
  label: string;
  spend: number;
  /** 保守 ROAS：全部花費當分母，沒追蹤到的那幾天當作沒賺。 */
  low: number;
  /** 樂觀 ROAS：後端的 `roas`，只算有追蹤到轉換的花費。 */
  high: number;
  impressions: number;
  clicks: number;
  revenue: number;
  coverage: number;
  adCount: number;
}

export interface QuadrantSplit {
  points: QuadrantPoint[];
  /** 這個月花費是 0 的座標。**一律不畫**——ADR 0057 §8 的讀數陷阱：`DISAPPROVED`／
   * `PENDING_REVIEW` 的廣告花費就是 0，畫在原點跟「這個角度沒人要」長得一模一樣。 */
  noSpend: CreativePerformanceValue[];
  /** 有花費、但一天都沒追蹤到轉換：`revenue`／`roas` 是 null，畫不出縱軸。 */
  noRevenue: CreativePerformanceValue[];
}

export function splitPlottable(values: CreativePerformanceValue[]): QuadrantSplit {
  const points: QuadrantPoint[] = [];
  const noSpend: CreativePerformanceValue[] = [];
  const noRevenue: CreativePerformanceValue[] = [];
  for (const v of values) {
    if (v.spend <= 0) {
      noSpend.push(v);
    } else if (v.revenue === null || v.roas === null) {
      noRevenue.push(v);
    } else {
      points.push({
        key: v.key,
        label: v.label,
        spend: v.spend,
        low: v.revenue / v.spend,
        high: v.roas,
        impressions: v.impressions,
        clicks: v.clicks,
        revenue: v.revenue,
        coverage: v.roas_coverage,
        adCount: v.ad_count,
      });
    }
  }
  return { points, noSpend, noRevenue };
}
