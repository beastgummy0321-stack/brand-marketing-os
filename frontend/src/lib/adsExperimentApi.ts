import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";
export interface ComparisonWindow { start: string | null; end: string | null }
export interface ComparisonSettingsValues {
  min_days: number;
  min_conversions_each: number;
  relative_difference: number;
  window: ComparisonWindow;
}
export type ComparisonOverrides = Partial<ComparisonSettingsValues>;
export interface ComparisonSettings {
  revision: string;
  scope: "campaign";
  defaults: ComparisonSettingsValues;
  effective: ComparisonSettingsValues;
  overrides: ComparisonOverrides;
  customized: (keyof ComparisonSettingsValues)[];
}
export interface ComparisonProposal {
  fingerprint: string; hypothesis: string; variable: string;
  variants: { ad_id: string; name: string; value: string }[];
  shared: { group_id?: string; group: string; audience: string; channel: string; daily_budget: number; objective: string };
  metric?: string; metric_label: string; window: { start: string; end: string };
  rules?: Omit<ComparisonSettingsValues, "window"> | LegacyComparisonRules;
  stop: string; limitation: string;
}
export interface LegacyComparisonRules {
  min_days: number;
  min_purchases_each: number;
  relative_difference: number;
}
export type ConfirmedComparison = Omit<ComparisonProposal, "rules"> & {
  rules?: Omit<ComparisonSettingsValues, "window"> | LegacyComparisonRules;
  confirmed_at: string;
  confirmed_by: string;
  timing: "retrospective" | "before_data";
};
export interface ComparisonState {
  proposal: ComparisonProposal | null; missing: string | null; stale: boolean; closed: boolean; simulation: boolean;
  settings?: ComparisonSettings;
  confirmed: ConfirmedComparison | null;
  result: { verdict: string; reason: string; values: {ad_id: string; name: string; value: number; spend: number; purchases: number}[] };
}
function path(brand: string, campaign: string) { return `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}/comparison`; }
export async function readComparison(brand: string, campaign: string): Promise<ComparisonState> {
  return parseJsonOrThrow(await apiFetch(path(brand,campaign)), "讀取比較提案失敗。");
}
export async function confirmComparison(brand: string, campaign: string, fingerprint: string): Promise<ComparisonState> {
  return parseJsonOrThrow(await apiFetch(path(brand,campaign), {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({fingerprint,controls_checked:true})}), "確認比較計畫失敗。");
}
export async function saveComparisonSettings(
  brand: string,
  campaign: string,
  revision: string,
  overrides: ComparisonOverrides,
): Promise<ComparisonState> {
  return parseJsonOrThrow(await apiFetch(path(brand,campaign), {
    method:"PUT",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({revision,overrides}),
  }), "儲存比較設定失敗。");
}
