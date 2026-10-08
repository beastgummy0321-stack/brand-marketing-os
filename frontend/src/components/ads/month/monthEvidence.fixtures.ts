import type { AdsRules } from "@/lib/adsTriageApi";
import type { HomeOverview, CommerceEvidence } from "@/lib/adsHomeApi";
import type { MonthSummary, PeriodGradeRow } from "@/lib/adsMonthApi";
import type { SettleView } from "@/lib/adsSettleApi";

export const MONTH = "2026-09";
export const PREVIOUS = "2026-08";
export const MONTH_BRAND = "brd_month_ui";
export function orderEvidence(month = MONTH, amount: number | null = 1200, days = 22): CommerceEvidence {
  return {scope: "brand", start: `${month}-01`, end: `${month}-${days}`, attribution: "unavailable",
    limitations: ["僅列出已匯入且有日期的資料，無法確認是否涵蓋完整期間或全部訂單。", "付款淨額不是金流結算或銀行入帳證明。"],
    order_summary: {count: 12, non_void_count: 11, void_count: 1, unpaid_count: 4,
      unknown_payment_count: 3, refunded_count: 2, unknown_amount_count: 3,
      known_net_count: 8, paid_count: 5, known_paid_net_count: 2,
      order_net_amount: 9999, paid_net_amount: amount, reported_currencies: ["TWD"], latest_import_at: null,
      currency: null, currency_basis: "unknown", coverage: "unknown"},
    channels: [{channel: "website", source: "orders", source_type: "order_mirror", currency: null, amount: 9999, row_count: 12, unknown_amount_count: 3}]};
}
export function monthEvidence(month = MONTH): {summary: MonthSummary; home: HomeOverview; settle: SettleView} {
  const previous = new Date(`${month}-01T12:00:00Z`); previous.setUTCMonth(previous.getUTCMonth()-1);
  const priorMonth = previous.toISOString().slice(0,7);
  const [year, monthNumber] = month.split("-").map(Number);
  const calendarDays = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  const dataDays = month === MONTH ? 22 : calendarDays;
  const currentOrders = orderEvidence(month, 1200, dataDays);
  const previousDays = Math.min(dataDays, new Date(Date.UTC(previous.getUTCFullYear(), previous.getUTCMonth()+1, 0)).getUTCDate());
  const previousOrders = orderEvidence(priorMonth, 800, previousDays);
  previousOrders.order_summary.known_paid_net_count = 1;
  const row: PeriodGradeRow = {campaign_id: "cmp_month", campaign_name: "日常商品推廣", origin: "imported",
    entity_id: "native_ad", name: "仍在投放的原平台廣告", group_name: "原平台受眾", thumbnail_url: null,
    spend: 3500, results: 7, cost_per_result: 500, cap: 100, break_even: null,
    grade: "over", grade_label: "太貴", currency: "TWD", cap_comparison: {basis: "own", currency: "TWD", reason: null, message: null}};
  const summary: MonthSummary = {month, currency: "TWD", total_spend: 3500,
    campaigns: [{campaign_id: row.campaign_id, name: row.campaign_name, objective: "SALES", campaign_objective: "sales", spend: 3500,
      result_count: 7, result_label: "購買", currency: "TWD", cost_per_result: 500, target: 100, verdict: "missed", cap_comparison: row.cap_comparison}],
    orders: {this_net: 1200, this_count: 2, previous_net: 800, previous_count: 1, change_pct: null, amount_basis: "paid_net_amount",
      comparison_missing: ["currency", "coverage", "payment", "amount"], order_book: {this_net: 9999, this_count: 8, previous_net: 8800, previous_count: 7},
      this_evidence: currentOrders, previous_evidence: previousOrders},
    closed_this_month: 0, closed_tracking_since: "2026-06-01T02:00:00Z", suggestions: [],
    days_covered: 0, days_elapsed: month === MONTH ? 23 : calendarDays, data_days: dataDays, window: {start: `${month}-01`, end: `${month}-${dataDays}`},
    grades: {spent: 3500, currency: "TWD", rows: [row], missing: [], buckets: [{grade: "over", amount: 3500, count: 1, currency: "TWD",
      ads: [{entity_id: row.entity_id, name: row.name, thumbnail_url: null, spend: 3500}]}]}, rejected: {worse: [], same_count: 0}};
  const home: HomeOverview = {month, day_of_month: month === MONTH ? 23 : calendarDays, days_in_month: calendarDays, currency: "TWD", spent: 3500,
    commerce: summary.orders!.this_evidence, money: {purchases: 7, cost_per_purchase: 500, cap: {value: 100, basis: "own", break_even: null},
      earn_after_cost_and_ads: null, earn_missing: ["currency"], estimate_basis: {kind: "platform_purchase_margin", assumptions: [], missing: ["currency"]}, excluded: [],
      previous_same_period: {days: 22, purchases: 7, cost_per_purchase: 500, currency: "TWD", cost_comparison: {reason: null}}},
    pace: {budget_amount: 60000, budget_currency: "TWD", budget_comparison: {reason: null}, available: 40000,
      daily: Array.from({length: dataDays}, (_, i) => ({day: `${month}-${String(i+1).padStart(2, "0")}`, cumulative: (i+1)*3500/dataDays})), projected_month_end: 4773},
    quality: null, timeline: null, campaigns: null, sync: null};
  const settle: SettleView = {month, start: `${month}-01`, end: `${month}-${calendarDays}`, days: calendarDays, status: "open", currency: "TWD", spent: 3500,
    budget: 60000, results: 7, cost_per_result: 500, on_target_results: 0, on_target_spend_share: 0,
    buckets: summary.grades.buckets, campaigns: [{campaign_id: row.campaign_id, name: row.campaign_name, origin: "imported", cap: {value: 100, basis: "own"},
      break_even: null, data_status: {state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: "2026-09-23T02:00:00Z"}}],
    rows: [{...row, rank: 1, of: 1, sales: 7, few: false, verdict: "keep_relative", verdict_label: "留下", flags: ["相對最好，仍高於上限"],
      fate: "ineffective", skip_reason: null, copy_text: null, angles: {status: "not_needed", candidates: []}, written_angle: null}], notebook: {count: 0}, written: null};
  return {summary, home, settle};
}

// Scripted rules from the existing served fixture, without Vitest-only module initialization.
export const MONTH_RULES: AdsRules = {
  grade: {
    watch_band: 1.2, unsold_spend_multiple: 3, min_results: 10, min_days: 7,
    sample_few: 5, near_best: 1.3, break_even_band: 0.02,
  },
  ab: { min_days: 7, min_conversions_each: 10, relative_difference: 0.1 },
  labels: {
    grade: {
      on_target: "划算", watch: "偏貴", over: "太貴", wasted: "沒賣出",
      too_new: "剛開始、數字還不夠", no_data: "資料不足", no_target: "未判斷",
    },
    verdict: { keep: "留下", keep_relative: "留下", replace: "換掉" },
    flags: { few: "樣本少", relative: "相對最好，仍高於上限", relative_no_cap: "相對最好" },
  },
  glossary: {
    cap: "你願意為一筆訂單付的廣告費，每個活動自己設",
    on_target: "每筆廣告費沒超過這個活動的上限",
    watch: "每筆廣告費超過上限，但超過不到 2 成",
    over: "每筆廣告費超過上限 2 成以上，賣越多虧越多",
    wasted: "花到上限 3 倍的錢，還一筆都沒賣出",
    thin: "賣出的廣告都有分數；還沒賣出且花不到上限 3 倍的先標「剛開始」；成交少於 5 筆標「樣本少」",
    money: "拿每筆廣告費跟打平線比：比它低是有賺，比它高是在虧，差不到 2% 算剛好打平",
    notebook: "系統記住哪些主打有效；下次開新活動，AI 會先讀這些，避開沒效的主打",
    break_even: "賣一筆扣掉商品成本和運費後剩下的錢；每筆廣告費超過它，就是在虧",
  },
  // F50 Contract I: `triage.limits()` as served today.
  limits: {
    review_days: { min: 1, max: 31 },
    review_cadence_default: 7,
    campaign_default_days: 30,
    copy_items_max: 5,
    upload_max_mb: 50,
  },
  // F49 Contract Q: `triage.reasons()` as served today.
  reasons: {
    too_new: { title: "剛開始、數字還不夠", text: "這則廣告還沒賣出，也還沒花到上限 3 倍；再跑幾天數字才夠判斷", fix: "wait" },
    result_unknown_days: {
      title: "有幾天的成果沒讀到",
      text: "平台沒回報這幾天的花費或成果數，系統不把沒讀到當成 0；重新讀取平台資料後再判斷",
      fix: "resync",
    },
    needs_resync: {
      title: "有幾天的資料要重新讀",
      text: "這段期間有幾天沒讀到，或是在系統開始記成果數之前讀的；重新讀取一次就會補上",
      fix: "resync",
    },
    mixed_currency: { title: "混了兩種幣別", text: "這段期間的花費有兩種幣別，系統不會自己換算加總，所以先不判斷", fix: null },
    mixed_result_definition: {
      title: "成果的算法不一致",
      text: "這段期間平台用了不只一種方式算成果（例如歸因設定改過），數字不能直接相加，所以先不判斷",
      fix: null,
    },
    no_previous_window: {
      title: "沒有上一段可以比",
      text: "這則廣告照常判斷划不划算；只是前一段同樣天數的資料不完整，看不出變好還是變差",
      fix: "wait",
    },
    result_kind_unknown: {
      title: "還不知道要算哪種成果",
      text: "這個活動還沒設定要看哪種成果（例如購買），平台資料也沒說；設定後才能判斷",
      fix: "cap",
    },
    target_unresolved: {
      title: "還沒設定上限",
      text: "這個活動還沒設定一筆訂單願意付多少廣告費，沒有尺可以量；設定上限後就會判斷",
      fix: "cap",
    },
    spend_over_target_no_result: { title: "沒賣出", text: "花到上限 3 倍的錢，還一筆都沒賣出", fix: null },
    cost_per_result_up: { title: "比上一段貴", text: "跟前一段同樣天數比，每筆廣告費多了超過 2 成", fix: null },
    cost_per_result_down: { title: "比上一段便宜", text: "跟前一段同樣天數比，每筆廣告費少了超過 2 成", fix: null },
    cost_per_result_flat: { title: "跟上一段差不多", text: "跟前一段同樣天數比，每筆廣告費差不到 2 成", fix: null },
  },
};
