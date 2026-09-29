import { describe, expect, it } from "vitest";
import type { QueueCleanupProposal, QueueItem, QueueReviewProposal, SettleQueueRow, TriageItem } from "@/lib/adsTriageApi";
import type { HomeCampaign, HomeOverview } from "@/lib/adsHomeApi";
import { bandState, cleanupAction, isQueueItemDone, settleAction } from "./status";

// F29-I11 (Contract E): the brand-level settle row opens the settle page through its own action_url.
const settleRow = (overrides: Partial<SettleQueueRow> = {}): SettleQueueRow => ({
  id: "itr_s", dedupe_key: "settle", category: "ads_triage_settle", severity: "rule_warning", message: "",
  action_url: "/brands/brd_1/ads/settle/2026-08/result", visible_from: null, status: "open", created_at: "2026-09-02T00:00:00Z",
  settle: { month: "2026-08", start: "2026-08-01", end: "2026-08-31", campaign_count: 2, imported_count: 1, learnable_count: 5, buckets: [] },
  ...overrides,
});

describe("settleAction", () => {
  it("an open row starts the settle at its own link; without one, the same route from the month", () => {
    expect(settleAction("brd_1", settleRow())).toEqual({ label: "開始結算", href: "/brands/brd_1/ads/settle/2026-08/result", done: false });
    expect(settleAction("brd_1", settleRow({ action_url: null }))).toMatchObject({ href: "/brands/brd_1/ads/settle/2026-08/result" });
  });

  it("a row no longer open reads as written", () => {
    expect(settleAction("brd_1", settleRow({ status: "resolved" }))).toMatchObject({ label: "✓ 已寫進筆記本", done: true });
  });
});

const cleanupSet = (
  status: QueueCleanupProposal["status"], verification_state: QueueCleanupProposal["verification_state"],
): QueueCleanupProposal => ({
  kind: "cleanup", change_set_id: "cs_1", campaign_id: "cmp_1", status, verification_state,
  reason: null, revisit_at: null, multi: true,
});

describe("cleanupAction", () => {
  it("opens a multi-item cleanup set's own step page, never the campaign overview", () => {
    const base = "/brands/brd_1/ads/campaigns/cmp_1/changes/cs_1";
    expect(cleanupAction("brd_1", "cmp_1", cleanupSet("draft", "pending"), null)).toMatchObject({ label: "等你核准", href: `${base}/confirm` });
    expect(cleanupAction("brd_1", "cmp_1", cleanupSet("approved", "pending"), null)).toMatchObject({ label: "到平台完成", href: `${base}/handoff` });
    expect(cleanupAction("brd_1", "cmp_1", cleanupSet("approved", "reported"), null)).toMatchObject({ href: `${base}/verify` });
  });

  it("uses the row's own proposal link before any change set exists", () => {
    expect(cleanupAction("brd_1", "cmp_1", null, "/brands/brd_1/ads/campaigns/cmp_1/propose/cleanup/cmp_1"))
      .toMatchObject({ label: "看提議", href: "/brands/brd_1/ads/campaigns/cmp_1/propose/cleanup/cmp_1" });
  });
});

// F29-I01（ads.md §6.33 一把尺）：列是不是做完，看列的種類 `kind_key`，不看 triage 的趨勢 class。
const triageItem = (overrides: Partial<TriageItem> = {}): TriageItem => ({
  entity_id: "ad_1", native_id: "n_1", name: "再行銷・兩入組", campaign_id: "cmp_1", campaign_name: "日常商品推廣",
  thumbnail_url: null, class: "flat", label: "持平", reason_code: "cost_per_result_flat",
  grade: "watch", grade_label: "偏貴", previous_grade: "on_target", grade_move: { from: "on_target", to: "watch" },
  window: { start: "2026-09-16", end: "2026-09-22", days: 7, previous_start: "2026-09-09", previous_end: "2026-09-15", extended_from: null },
  target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
  current: { spend: 3120, result_count: 6, cost_per_result: 520, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
  previous: { spend: 3080, result_count: 7, cost_per_result: 440, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
  change_pct: 0.18, sample: { gate: true, spend_multiple: 6.9, days_with_events: 7 },
  ...overrides,
});
const deferredReview: QueueReviewProposal = {
  kind: "review", review_id: "arv_1", status: "deferred", decision: "deferred", reason: "下週再看",
  revisit_at: null, recommendation_id: null, change_set_id: null, change_set_status: null,
  verification_state: null, multi: false,
};
const queueItem = (overrides: Partial<QueueItem>): QueueItem => ({
  id: "itr_1", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: "k", category: "ads_triage_worse",
  kind: null, severity: "rule_warning", message: "", action_url: null, visible_from: null, status: "open",
  created_at: "2026-09-23T00:00:00Z", resolved_at: null, kind_key: "worse", triage: triageItem(), proposal: null,
  ...overrides,
});

describe("isQueueItemDone", () => {
  it("a 變貴 row reads its review proposal even when the trend note says flat", () => {
    expect(isQueueItemDone(queueItem({ proposal: deferredReview }))).toBe(true);
    expect(isQueueItemDone(queueItem({ proposal: null }))).toBe(false);
  });

  it("a trend class of worse never turns another row kind into a review row", () => {
    const refresh = queueItem({ kind_key: "refresh_creative", triage: triageItem({ class: "worse" }), proposal: deferredReview });
    expect(isQueueItemDone(refresh)).toBe(false);
  });
});

// F40-I07（drill-7 #8）：首頁分級帶的三種空狀態只看 payload，順序＝缺天 → 分級讀取失敗 → 沒花費 → 正常帶。
const homeCampaign = (overrides: Partial<HomeCampaign> = {}): HomeCampaign => ({
  campaign_id: "cmp_1", name: "日常商品推廣", origin: "internal", status: "live", month_spend: null, purchases: null,
  cost_per_purchase: null, cap: null, active_ads: 2, daily_budget: null, missing_days: [], sync_state: "ok",
  data_status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: null }, handoff: null, draft: null,
  ...overrides,
});
const homeOverview = (overrides: Partial<HomeOverview> = {}): HomeOverview => ({
  month: "2026-10", day_of_month: 5, days_in_month: 31, currency: "TWD", spent: null, money: null, pace: null,
  quality: null, timeline: null, campaigns: [homeCampaign()], sync: null,
  ...overrides,
});

describe("bandState", () => {
  it("(i) spend unknown because a day is unread: names the day and points at that campaign", () => {
    const home = homeOverview({ campaigns: [homeCampaign({ campaign_id: "cmp_ok" }), homeCampaign({ campaign_id: "cmp_gap", missing_days: ["2026-10-03"] })] });
    expect(bandState(home)).toEqual({ kind: "missing_days", sentence: "10 月已花還不完整（10/03 沒讀到），先不分級", campaign_id: "cmp_gap" });
  });

  it("(i) several unread days are listed once each; more than three become a count", () => {
    const two = homeOverview({ campaigns: [homeCampaign({ missing_days: ["2026-10-03", "2026-10-01"] }), homeCampaign({ campaign_id: "c2", missing_days: ["2026-10-03"] })] });
    expect(bandState(two)).toMatchObject({ sentence: "10 月已花還不完整（10/01、10/03 沒讀到），先不分級" });
    const many = homeOverview({ campaigns: [homeCampaign({ missing_days: ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"] })] });
    expect(bandState(many)).toMatchObject({ sentence: "10 月已花還不完整（4 天沒讀到），先不分級" });
  });

  it("(ii) spend known but the quality block failed reads as a failure, never as no data", () => {
    expect(bandState(homeOverview({ spent: 10081, quality: null }))).toEqual({ kind: "read_failed", sentence: "分級讀取失敗" });
    // A gap elsewhere does not turn a failed block into 「還不完整」.
    expect(bandState(homeOverview({ spent: 10081, quality: null, campaigns: [homeCampaign({ missing_days: ["2026-10-03"] })] }))).toMatchObject({ kind: "read_failed" });
  });

  it("(iii) nothing spent: empty buckets, or unknown／zero spend with every day read", () => {
    const sentence = "10 月還沒有花費資料，先不分級";
    expect(bandState(homeOverview({ spent: 0, quality: { buckets: [] } }))).toEqual({ kind: "no_spend", sentence });
    expect(bandState(homeOverview({ spent: 0, quality: { buckets: [{ grade: "on_target", amount: 0, count: 0, ads: [] }] } }))).toMatchObject({ kind: "no_spend" });
    expect(bandState(homeOverview({ spent: null, quality: null }))).toMatchObject({ kind: "no_spend", sentence });
    expect(bandState(homeOverview({ spent: null, quality: null, campaigns: null }))).toMatchObject({ kind: "no_spend" });
  });

  it("normal: any graded amount draws the band", () => {
    expect(bandState(homeOverview({ spent: 10081, quality: { buckets: [{ grade: "on_target", amount: 3120, count: 1, ads: [] }, { grade: "ungraded", amount: 6961, count: 3, ads: [] }] } }))).toEqual({ kind: "band" });
  });
});
