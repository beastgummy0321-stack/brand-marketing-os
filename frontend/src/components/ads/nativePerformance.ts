import { roasOf } from "@/lib/figures";
import type { CampaignPerformance, OutcomeBucket, PerformanceScope } from "@/lib/adsApi";
import type { ExternalView, NativeObservation } from "@/lib/adsExternalApi";

export type PerformanceBucket = Omit<OutcomeBucket, "spend" | "impressions" | "clicks"> & {
  spend: number | null; impressions: number | null; clicks: number | null;
};
export interface PerformanceView {
  totals: PerformanceBucket;
  daily: (PerformanceBucket & { day: string })[];
  groups: (PerformanceBucket & { group_id: string; name: string; spend_share: number | null })[];
  ads: (PerformanceBucket & { ad_id: string; name: string; spend_share: number | null })[];
  coverage: CampaignPerformance["coverage"] | null;
  last_data_at: string | null;
  scope?: PerformanceScope;
  cap_comparison?: CampaignPerformance["cap_comparison"];
}
export interface NativeMetricScope { key: string; label: string; metricScope: string; currency: string | null; attribution: string }
export const nativeScopeKey = (o: NativeObservation) => JSON.stringify([o.metric_scope, o.currency, o.attribution_key]);
export function nativeMetricScopes(view?: ExternalView | null): NativeMetricScope[] {
  const scopes = new Map<string, NativeMetricScope>();
  for (const o of view?.observations ?? []) {
    const key = nativeScopeKey(o);
    scopes.set(key, { key, metricScope: o.metric_scope, currency: o.currency, attribution: o.attribution_key,
      label: `${({ campaign: "活動", adset: "廣告組", ad: "廣告" } as Record<string, string>)[o.metric_scope] ?? o.metric_scope} · ${o.currency ?? "幣別未知"} · ${o.attribution_key || "歸因未知"}` });
  }
  return [...scopes.values()].sort((a, b) => ({ campaign: 0, adset: 1, ad: 2 }[a.metricScope] ?? 3) - ({ campaign: 0, adset: 1, ad: 2 }[b.metricScope] ?? 3) || a.key.localeCompare(b.key));
}
const ratio = (a: number | null, b: number | null) => a !== null && b !== null && b > 0 ? a / b : null;
function aggregate(rows: NativeObservation[]): PerformanceBucket {
  function sum(key: "spend" | "impressions" | "clicks" | "purchases" | "revenue") {
    return !rows.length || rows.some(row => row[key] === null) ? null : rows.reduce((total, row) => total + row[key]!, 0);
  }
  const spend = sum("spend"), impressions = sum("impressions"), clicks = sum("clicks"), purchases = sum("purchases"), revenue = sum("revenue");
  // F51 Contract F: imported rows are summed only when every row is known, so revenue ÷ spend is the all-spend basis.
  return { spend, impressions, clicks, purchases, revenue, cpa: ratio(spend, purchases), ctr: ratio(clicks, impressions), roas_all_spend: roasOf(revenue, spend), roas_tracked_spend: null };
}
/** A selected native scope is the only aggregation boundary: never add parent and child observations. */
export function nativePerformance(view?: (ExternalView & { scope?: PerformanceScope }) | null, scopeKey?: string): PerformanceView {
  const selected = scopeKey ?? nativeMetricScopes(view)[0]?.key;
  const unique = new Map<string, NativeObservation>();
  for (const row of view?.observations ?? []) if (nativeScopeKey(row) === selected) unique.set(JSON.stringify([row.entity_id, row.day]), row);
  const rows = [...unique.values()];
  const totals = aggregate(rows);
  const days = [...new Set(rows.map(row => row.day))].sort();
  const entities = [...new Set(rows.map(row => row.entity_id))].map(id => {
    const entity = view?.entities.find(item => item.id === id);
    const value = aggregate(rows.filter(row => row.entity_id === id));
    return { ...value, id, name: entity?.name ?? entity?.native_label ?? entity?.native_id ?? id, kind: entity?.native_kind, spend_share: ratio(value.spend, totals.spend) };
  });
  return { totals, daily: days.map(day => ({ day, ...aggregate(rows.filter(row => row.day === day)) })),
    groups: entities.filter(row => row.kind === "adset").map(row => ({ ...row, group_id: row.id })),
    ads: entities.filter(row => row.kind === "ad").map(row => ({ ...row, ad_id: row.id })),
    coverage: null, last_data_at: days.at(-1) ?? null, scope: view?.scope };
}
