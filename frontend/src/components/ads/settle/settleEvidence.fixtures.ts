import type {SettleRow, SettleView} from "@/lib/adsSettleApi";
import type {NextPeriodPreparation} from "@/lib/adsWizardApi";

export const SETTLE_BRAND = "brd_settle_ui";
export const SETTLE_MONTH = "2026-08";
export function settleEvidence(status: SettleView["status"] = "open"): SettleView {
  const window = {start: "2026-08-01", end: "2026-08-31"};
  const row = (id: string, good: boolean): SettleRow => ({
    campaign_id: id, campaign_name: good ? "日常推廣・已知成本" : "舊平台活動・相對最好仍超標", origin: good ? "internal" : "imported",
    entity_id: `ad_${id}`, name: good ? "通勤喝咖啡" : "相對第一名但每筆500", group_name: "通勤族", thumbnail_url: null,
    spend: good ? 1000 : 5000, results: good ? 20 : 10, cost_per_result: good ? 50 : 500, currency: "TWD",
    result_kind: "purchase", result_label: "購買", result_action: "omni_purchase", result_attribution: "7d_click+1d_view", result_reason: null, result_window: window,
    cap: 100, break_even: null, grade: good ? "on_target" : "over", grade_label: good ? "划算" : "太貴", reason_code: null,
    cap_comparison: {basis: "own", currency: "TWD", source: "user", unit_basis: "manual_ntd_input", reason: null, message: null},
    break_even_unit: {basis: "break_even", currency: null, source: "product_economics", unit_basis: null},
    rank: 1, of: 1, sales: good ? 20 : 10, few: false, verdict: good ? "keep" : "keep_relative", verdict_label: "留下", flags: [],
    fate: good ? "effective" : "ineffective", skip_reason: null, copy_text: "隨時喝一口", angles: {status: "ready", candidates: ["通勤帶著走", "保溫到公司", "隨手一杯"]},
    written_angle: status === "written" ? "通勤帶著走" : null,
  });
  const rows = [row("known", true), row("native", false)];
  return {month: SETTLE_MONTH, ...window, days: 31, status, currency: "TWD", spent: 6000, budget: 7000,
    results: 30, cost_per_result: 200, on_target_results: 20, on_target_spend_share: 1 / 6,
    result_definition: {kind: "purchase", action: "omni_purchase", attribution: "7d_click+1d_view", window}, result_comparison: {reason: null},
    rows, campaigns: rows.map(r => ({campaign_id: r.campaign_id, name: r.campaign_name, origin: r.origin,
      cap: {value: 100, basis: "own"}, break_even: null, data_status: {state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: "2026-09-01T00:00:00Z"}})),
    buckets: [{grade: "on_target", amount: 1000, count: 1, currency: "TWD", ads: []}, {grade: "over", amount: 5000, count: 1, currency: "TWD", ads: []}],
    notebook: {count: status === "written" ? 15 : 12}, written: status === "written" ? {at: "2026-09-02T00:00:00Z", by: "user", count: 3, effective: 1, ineffective: 1, unknown: 1} : null};
}
export function nextPeriodEvidence(): NextPeriodPreparation {
  return {month: SETTLE_MONTH, window: {start: "2026-08-01", end: "2026-08-31"}, revision: "source-revision-1",
    source_campaigns: [{campaign_id: "known", origin: "internal", name: "日常推廣・已知成本", mapping_required: false, result_kind: "purchase", currency: "TWD"},
      {campaign_id: "native", origin: "imported", name: "舊平台活動・相對最好仍超標", mapping_required: true, result_kind: "purchase", currency: "TWD"}],
    eligible_learning_refs: [{owner: "observed_entity", ref: "ad_known", campaign_id: "known"}],
    excluded: [{owner: "observed_entity", ref: "ad_native", reason_code: "above_target"}]};
}
