import { describe, expect, it } from "vitest";
import type { ExternalView, NativeObservation } from "@/lib/adsExternalApi";
import { nativeMetricScopes, nativePerformance } from "./nativePerformance";
const row = (o: Partial<NativeObservation> = {}): NativeObservation => ({ id: "o", entity_id: "c", day: "2026-09-01", metric_scope: "campaign", attribution_key: "7d", currency: "USD", spend: 10, impressions: 100, clicks: 5, purchases: 2, revenue: 30, availability: {}, ...o });
const view = (observations: NativeObservation[]): ExternalView => ({ observations, entities: [], next_entity_cursor: null, next_observation_cursor: null, window: { start: "2026-09-01", end: "2026-09-30" }, connections: [], sync: {}, coverage: {} });
describe("native performance", () => {
  it("separates levels currencies attribution and duplicates", () => {
    const v = view([row(), row(), row({ entity_id: "ad", metric_scope: "ad", spend: 999 }), row({ currency: "TWD", spend: 200 }), row({ attribution_key: "1d", spend: 333 })]);
    expect(nativeMetricScopes(v)).toHaveLength(4);
    const p = nativePerformance(v, JSON.stringify(["campaign", "USD", "7d"]));
    expect(p.totals.spend).toBe(10); expect(p.totals.roas_all_spend).toBe(3); expect(p.totals.roas_tracked_spend).toBeNull(); expect(p.coverage).toBeNull(); expect(p.ads).toEqual([]);
  });
  it("preserves incomplete and zero values", () => {
    const p = nativePerformance(view([row(), row({ day: "2026-09-02", spend: null, revenue: null, purchases: 0 })]));
    expect(p.totals.spend).toBeNull(); expect(p.totals.roas_all_spend).toBeNull(); expect(p.daily[1].purchases).toBe(0); expect(nativePerformance(view([])).totals.spend).toBeNull();
  });
  it("resolves native entity names for selected level shares", () => {
    const v = view([row({ entity_id: "ad1", metric_scope: "ad" }), row({ entity_id: "ad2", metric_scope: "ad", spend: 30 })]);
    v.entities = [{ id: "ad1", name: "原生廣告名稱", native_kind: "ad" }, { id: "ad2", name: "第二則", native_kind: "ad" }] as ExternalView["entities"];
    const p = nativePerformance(v); expect(p.ads[0].name).toBe("原生廣告名稱"); expect(p.ads[0].spend_share).toBe(0.25); expect(p.groups).toEqual([]);
  });
});
