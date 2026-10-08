/** Browser-only served shapes for F54 home evidence. These do not establish live execution or revenue. */
import type { CommerceEvidence, HomeOverview } from "@/lib/adsHomeApi";
import type { QueueItem, QueuePayload, TriageItem } from "@/lib/adsTriageApi";
import type { ActiveJobsSnapshot } from "@/lib/jobsApi";

export const HOME_BRAND = "brd_f54_home";
export const HOME_PATH = `/app/brands/${HOME_BRAND}/ads`;
export const LONG_HOME_NAME = "中秋限定活動・送禮受眾 2026｜Advantage+ 購物活動 - 複本・平台活動與付款資料仍須核對";
export type HomeScene = "healthy" | "stopped" | "unknown" | "over-cap-zero-queue" | "order-unknown" | "pace-mismatch" | "pace-unknown";
const AT = "2026-09-23T00:40:00Z";
const projection = (state: "alive" | "stopped" | "unknown") => ({ state, checked_at: AT,
  last_heartbeat_at: state === "unknown" ? null : AT,
  reason_code: state === "alive" ? "heartbeat_fresh" as const : state === "stopped" ? "heartbeat_stale" as const : "health_unavailable" as const });

export function homeOrders(amount: number | null = 12500): CommerceEvidence {
  return { scope: "brand", start: "2026-09-01", end: "2026-09-22", attribution: "unavailable",
    limitations: ["僅列出已匯入且有日期的資料，無法確認是否涵蓋完整期間或全部訂單。",
      "訂單幣別缺乏來源證據；既有匯入預設幣別不代表原始交易幣別。",
      "付款淨額只計入明確已付款或已退款狀態的未作廢訂單，不是金流結算或銀行入帳證明；未付款與狀態不明的訂單另外計數。"],
    order_summary: { count: 12, non_void_count: 11, void_count: 1, unpaid_count: 2, unknown_payment_count: 1,
      refunded_count: 1, unknown_amount_count: 1, known_net_count: 10, paid_count: 8, known_paid_net_count: 7,
      order_net_amount: 14500, paid_net_amount: amount, reported_currencies: ["TWD"], latest_import_at: AT,
      currency: null, currency_basis: "unknown", coverage: "unknown" },
    channels: [{ channel: "official", source: "orders", source_type: "order_mirror", currency: null,
      amount: 14500, row_count: 11, unknown_amount_count: 1 }] };
}

const costTriage: TriageItem = {
  entity_id: "ad_current", native_id: "native_current", name: LONG_HOME_NAME, campaign_id: "cmp_home", campaign_name: LONG_HOME_NAME,
  thumbnail_url: null, class: "worse", label: "成本持續超過上限", reason_code: "persistently_over_cap",
  grade: "over", grade_label: "太貴", previous_grade: "over", grade_move: null,
  window: { start: "2026-09-16", end: "2026-09-22", days: 7, previous_start: "2026-09-09", previous_end: "2026-09-15", extended_from: null },
  target: { value: 100, basis: "own", result_kind: "purchase", result_label: "購買", missing: [], break_even: null,
    cap_unit: { basis: "own", currency: "TWD" }, break_even_unit: { basis: "break_even", currency: null } },
  cap_comparison: { basis: "own", currency: "TWD", reason: null, message: null },
  current: { spend: 3500, result_count: 7, cost_per_result: 500, result_kind: "purchase", result_label: "購買", currency: "TWD", derived_zero_days: 0, reason: null },
  previous: { spend: 3500, result_count: 7, cost_per_result: 500, result_kind: "purchase", result_label: "購買", currency: "TWD", derived_zero_days: 0, reason: null },
  change_pct: 0, sample: { gate: true, spend_multiple: 35, days_with_events: 7 },
};

export function homeDecision(): QueueItem {
  return { id: "itr_cost", org_id: "org_home", brand_id: HOME_BRAND, campaign_period_id: null, dedupe_key: "episode_cost",
    category: "ads_triage_worse", kind: null, severity: "rule_warning", message: "成本持續超過上限", action_url: null,
    visible_from: null, status: "open", created_at: AT, resolved_at: null, kind_key: "worse", trigger_reason: "persistently_over_cap",
    triage: structuredClone(costTriage), proposal: null, done: false, decision: true, position: 0 };
}

export function homeEvidence(scene: HomeScene = "healthy") {
  const state = scene === "stopped" ? "stopped" : scene === "unknown" ? "unknown" : "alive";
  const health: ActiveJobsSnapshot = { data: [], total: 0, other_count: 0, done_today: 0, failed_today: 0,
    generated_at: AT, worker_health: projection(state), worker_alive: state === "alive" };
  const over = scene === "over-cap-zero-queue";
  const home: HomeOverview = { closed_this_month: 0, month: "2026-09", day_of_month: 23, days_in_month: 30,
    currency: "TWD", spent: 3500, commerce: scene === "order-unknown" ? null : homeOrders(),
    money: { purchases: 7, cost_per_purchase: 500, cap: { value: 100, basis: "own", break_even: null },
      configured_cap: { value: 100, basis: "own" }, cap_comparison: { basis: "own", currency: "TWD", reason: null, message: null },
      earn_after_cost_and_ads: null, earn_missing: ["currency"], estimate_basis: { kind: "platform_purchase_margin",
        assumptions: ["假設平台購買数就是付款訂單；尚未與訂單來源核對。"], missing: ["currency"] }, excluded: [], previous_same_period: null },
    pace: { budget_currency: "TWD", budget_comparison: { reason: null }, budget_amount: 60000, available: 40000, daily: [{ day: "2026-09-22", cumulative: 3500 }], projected_month_end: 4500 },
    quality: { buckets: [{ grade: "on_target", amount: 0, count: 0, ads: [] },
      { grade: "over", amount: 3500, count: 1, ads: [{ entity_id: "ad_current", name: LONG_HOME_NAME, thumbnail_url: null, spend: 3500 }] }] },
    timeline: [{ date: "2026-09-23", kind: "today", campaign_id: null, name: null, ready: null },
      { date: "2026-09-30", kind: "month_review", campaign_id: null, name: null, ready: null }],
    campaigns: [{ campaign_id: "cmp_home", name: LONG_HOME_NAME, origin: "internal", status: "live", currency: "TWD",
      month_spend: 3500, purchases: 7, cost_per_purchase: 500, cap: { value: 100, basis: "own", break_even: null },
      configured_cap: { value: 100, basis: "own" }, cap_comparison: { basis: "own", currency: "TWD", reason: null, message: null },
      active_ads: 1, daily_budget: 500, missing_days: [], sync_state: state === "alive" ? "ok" : "syncing",
      data_status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: AT }, handoff: null, draft: null,
      running: { count: 1, unknown: 0, read_at: AT, stale: false, state: "running", freshness: "read" } }],
    // Deliberately stale alive projection: the fresh independent health must win.
    sync: { last_success_at: AT, next_at: "2026-09-23T04:40:00Z", eligible_at: "2026-09-23T04:40:00Z", worker_health: projection("alive") },
  };
  if (scene === "pace-mismatch" || scene === "pace-unknown") {
    home.pace!.budget_currency = scene === "pace-mismatch" ? "USD" : null;
    home.pace!.budget_comparison = { reason: scene === "pace-mismatch" ? "currency_mismatch" : "currency_unknown" };
    home.pace!.available = -200;
    home.money!.previous_same_period = { days: 22, purchases: 3, cost_per_purchase: 100, currency: "USD",
      cost_comparison: { reason: "currency_mismatch" } };
  }
  const items = over ? [] : [homeDecision()];
  const queue: QueuePayload = { items, counts: { stop_loss: 0, worse: items.length, better: 0, flat: 0, insufficient: 0, no_target: 0 },
    total_ads: 1, kinds_available: ["worse"], kinds_pending: [], decisions: { kinds: ["worse"], open: items.length }, settle: null, closeouts: [] };
  return { home, queue, health };
}

export function homeMocks(scene: HomeScene = "healthy") {
  const fixture = homeEvidence(scene);
  const org = { id: "org_home", name: "首頁測試工作區", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-09-23" };
  return {
    "**/api/**": { data: [], total: 0, generated_at: AT },
    "**/api/identity/me": { user: { id: "u_home", email: "home@example.com" }, org, orgs: [org] },
    "**/api/dashboard/overview": { data: [{ brand_id: HOME_BRAND, brand_name: "首頁反例品牌", health: "yellow", revenue_this_month: null, revenue_mom_pct: null, next_step: null }], generated_at: AT },
    "**/api/interrupts*": { data: [], total: 0, generated_at: AT },
    "**/api/ads/brands/*/rules": {
      grade: { watch_band: 1.2, unsold_spend_multiple: 3, min_results: 10, min_days: 7, sample_few: 5, near_best: 1.3, break_even_band: 0.02 },
      ab: { min_days: 7, min_conversions_each: 10, relative_difference: 0.1 },
      labels: { grade: { on_target: "划算", watch: "偏貴", over: "太貴", wasted: "沒賣出", too_new: "剛開始、數字還不夠", no_data: "資料不足", no_target: "未判斷" },
        verdict: { keep: "留下", keep_relative: "留下", replace: "換掉" }, flags: { few: "樣本少", relative: "相對最好，仍高於上限", relative_no_cap: "相對最好" } },
      glossary: { cap: "每筆成果的廣告成本上限", on_target: "每筆成本未超過上限", watch: "超過上限不到兩成", over: "超過上限兩成以上",
        wasted: "已花到上限三倍但無成果", thin: "樣本尚少", money: "假設成本比較", notebook: "保存可參考的觀察", break_even: "假設售價扣除成本與运費" },
      reasons: {}, limits: { review_days: { min: 1, max: 31 }, review_cadence_default: 7, campaign_default_days: 30, copy_items_max: 5, upload_max_mb: 50 },
    },
    "**/api/ads/brands/*/status-summary": { last_success_at: AT, attention: { count: 0, note: null }, open_items: fixture.queue.items.length },
    "**/api/ads/brands/*/home*": fixture.home,
    "**/api/ads/brands/*/queue*": { queue: fixture.queue },
    "**/api/ads/brands/*/queue/refresh": { queue: fixture.queue },
    "**/api/ads/brands/*/recovery*": { recovering: false, gap: null, steps: [] },
    "**/api/jobs/active*": fixture.health,
  };
}
