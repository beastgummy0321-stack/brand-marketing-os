/** 票 T6b：座標賺賠圖上唯一做算術的地方——保守 ROAS 與三向分流。
 * 數字取自 2026-09-04 的探針（真實形狀，不是編的）：四天花 3,570、追蹤到營收 2,737.8、
 * 覆蓋率 75%。後端回的 `roas` 是 1.029（只除有追蹤的 2,660），保守值是 0.767（除全部
 * 花費）——**一個在打平線上、一個在打平線下**，這就是這張圖要畫成一段區間的理由。
 * 只畫 `roas` 那一顆，一則實際在賠的廣告會被畫在賺錢那一側。 */
import { describe, expect, it } from "vitest";
import { splitPlottable } from "@/lib/quadrant";
import type { CreativePerformanceValue } from "@/lib/scheduleApi";

function value(over: Partial<CreativePerformanceValue>): CreativePerformanceValue {
  return {
    key: "product_explainer", label: "產品講解",
    spend: 3570, impressions: 28900, clicks: 769,
    revenue: 2737.8, roas: 1.029248120300752, roas_coverage: 0.75, ad_count: 1,
    ...over,
  };
}

describe("splitPlottable", () => {
  it("保守 ROAS 用全部花費當分母，跟後端的樂觀值一起帶出去", () => {
    const { points } = splitPlottable([value({})]);
    expect(points).toHaveLength(1);
    expect(points[0].low).toBeCloseTo(0.767, 3);
    expect(points[0].high).toBeCloseTo(1.029, 3);
    // 這一段真的橫跨打平線——沒橫跨的話這張圖就不必畫成區間。
    expect(points[0].low).toBeLessThan(1);
    expect(points[0].high).toBeGreaterThan(1);
  });

  it("覆蓋率 100% 時兩端重合，區間自然變回一個點", () => {
    const { points } = splitPlottable([value({ revenue: 4998, roas: 1.4, roas_coverage: 1 })]);
    expect(points[0].low).toBeCloseTo(points[0].high, 6);
  });

  it("零花費的座標不上圖（ADR 0057 §8：被退件的廣告花費是 0，畫在原點會被讀成沒人要）", () => {
    const { points, noSpend } = splitPlottable([
      value({ key: "ugc_disguise", spend: 0, revenue: null, roas: null, roas_coverage: 0 }),
    ]);
    expect(points).toHaveLength(0);
    expect(noSpend.map((v) => v.key)).toEqual(["ugc_disguise"]);
  });

  it("有花費但一天都沒追蹤到轉換，畫不出縱軸，另外歸一類", () => {
    const { points, noRevenue } = splitPlottable([
      value({ key: "moment_anchoring", revenue: null, roas: null, roas_coverage: 0 }),
    ]);
    expect(points).toHaveLength(0);
    expect(noRevenue.map((v) => v.key)).toEqual(["moment_anchoring"]);
  });
});
