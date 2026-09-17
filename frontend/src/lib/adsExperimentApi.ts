import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";
export interface ComparisonProposal {
  fingerprint: string; hypothesis: string; variable: string;
  variants: { ad_id: string; name: string; value: string }[];
  shared: { group: string; audience: string; channel: string; daily_budget: number; objective: string };
  metric_label: string; window: { start: string; end: string }; stop: string; limitation: string;
}
export interface ComparisonState {
  proposal: ComparisonProposal | null; missing: string | null; stale: boolean; closed: boolean; simulation: boolean;
  confirmed: (ComparisonProposal & { confirmed_at: string; confirmed_by: string; timing: "retrospective" | "before_data" }) | null;
  result: { verdict: string; reason: string; values: {ad_id: string; name: string; value: number; spend: number; purchases: number}[] };
}
function path(brand: string, campaign: string) { return `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}/comparison`; }
export async function readComparison(brand: string, campaign: string): Promise<ComparisonState> {
  return parseJsonOrThrow(await apiFetch(path(brand,campaign)), "讀取比較提案失敗。");
}
export async function confirmComparison(brand: string, campaign: string, fingerprint: string): Promise<ComparisonState> {
  return parseJsonOrThrow(await apiFetch(path(brand,campaign), {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({fingerprint,controls_checked:true})}), "確認比較計畫失敗。");
}
