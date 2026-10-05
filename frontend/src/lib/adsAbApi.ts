// F29-I04 Contract F: automatic A/B pairs of an internal campaign and the "pause the loser"
// proposal. The proposal is only a local change set (`source: "ab"`) that still goes through the
// normal approve -> platform -> verify flow; nothing here writes to an ad platform.
import { apiFetch, readJson } from "./http";
import { BASE } from "./adsApi";
import type { ChangeItem, ChangeSet } from "./adsChangeApi";

export type AbPairState = "collecting" | "no_difference" | "judged" | "unreadable";
// `spend`/`results`/`cost_per_result` are null whenever a day in the window is missing or a
// purchase count is untracked -- never shown as 0.
export interface AbSide {
  ad_id: string; entity_id: string | null; name: string; value_label: string;
  thumbnail_url: string | null; spend: number | null; results: number | null; cost_per_result: number | null;
}
export interface AbRules { min_days: number; min_conversions_each: number; relative_difference: number }
export interface AbDecision {
  change_set_id: string; status: ChangeSet["status"];
  // The pause item's readback state; null until the set is approved.
  verification_state: ChangeItem["verification_state"] | null;
}
export interface AbPair {
  pair_id: string; group_id: string; group_name: string; dimension: string; dimension_label: string;
  a: AbSide; b: AbSide;
  // null until both ads have delivered (the window starts at the later ad's first delivery day).
  window: { start: string; end: string } | null; days: number; rules: AbRules; state: AbPairState;
  // What is still needed to reach the thresholds; a side's count is null when its results are unknown.
  missing: { days: number; a_results: number | null; b_results: number | null };
  winner: "a" | "b" | null; difference_pct: number | null; reason: string | null;
  decision: AbDecision | null;
}
export interface AbPairsView { pairs: AbPair[]; unavailable: string | null }

const pairsPath = (brand: string, campaign: string) =>
  `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}/ab-pairs`;

export async function getAbPairs(brand: string, campaign: string, signal?: AbortSignal): Promise<AbPairsView> {
  return readJson(await apiFetch(pairsPath(brand, campaign), { signal }), "讀取 A/B 比較失敗。");
}
// 409 `ab_not_judged` / `ab_loser_unbound`, 404 `ab_pair_unknown`. An open set for the pair is
// returned instead of a second one; the same `operation_id` replays the same set.
export async function pauseAbLoser(brand: string, campaign: string, pairId: string, operationId: string, signal?: AbortSignal): Promise<ChangeSet> {
  const response = await apiFetch(`${pairsPath(brand, campaign)}/${encodeURIComponent(pairId)}/pause-loser`, {
    method: "POST", signal, headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ operation_id: operationId }),
  });
  return (await readJson<{ change_set: ChangeSet }>(response, "建立暫停清單失敗。")).change_set;
}
