import { describe, expect, it } from "vitest";
import type { CloseoutQueueRow, QueueCleanupProposal, QueueItem, QueuePayload, QueueReviewProposal, SettleQueueRow, TriageItem } from "@/lib/adsTriageApi";
import type { HomeCampaign, HomeOverview } from "@/lib/adsHomeApi";
import { bandState, cleanupAction, decisionBoard, decisionPosition, isQueueItemDone, proposalAction, settleAction, settlePosition } from "./status";
import { nextOpenQueueItem } from "../flow/changeFlow";

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

  it("F49 Contract B: an approved set's label is the served verification word; the state only picks the step", () => {
    const base = "/brands/brd_1/ads/campaigns/cmp_1/changes/cs_1";
    const served = (state: QueueCleanupProposal["verification_state"], label: string) => ({ ...cleanupSet("approved", state), verification_label: label });
    expect(cleanupAction("brd_1", "cmp_1", served("pending", "尚未回報"), null)).toEqual({ label: "尚未回報", href: `${base}/handoff`, done: false });
    expect(cleanupAction("brd_1", "cmp_1", served("unknown", "讀到了，還不能確認"), null)).toEqual({ label: "讀到了，還不能確認", href: `${base}/verify`, done: false });
    expect(cleanupAction("brd_1", "cmp_1", served("deviated", "與核准內容不同"), null)).toEqual({ label: "與核准內容不同", href: `${base}/verify`, done: false });
    expect(cleanupAction("brd_1", "cmp_1", served("confirmed", "已核對相符"), null)).toEqual({ label: "已核對相符", href: `${base}/verify`, done: true });
    // A worse row's copy set carries its own served word through the review round.
    const review: QueueReviewProposal = { ...deferredReviewShape, status: "completed", decision: "completed", change_set_id: "cs_9",
      change_set_status: "approved", verification_state: "reported", verification_label: "已回報，待讀回" };
    expect(proposalAction("brd_1", "cmp_1", "ad_1", review, "review")).toEqual({
      label: "已回報，待讀回", href: "/brands/brd_1/ads/campaigns/cmp_1/changes/cs_9/verify", done: false,
    });
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
const deferredReviewShape: QueueReviewProposal = {
  kind: "review", review_id: "arv_1", status: "deferred", decision: "deferred", reason: "下週再看",
  revisit_at: null, recommendation_id: null, change_set_id: null, change_set_status: null,
  verification_state: null, multi: false,
};
const deferredReview: QueueReviewProposal = {
  kind: "review", review_id: "arv_1", status: "deferred", decision: "deferred", reason: "下週再看",
  revisit_at: null, recommendation_id: null, change_set_id: null, change_set_status: null,
  verification_state: null, multi: false,
};
const queueItem = (overrides: Partial<QueueItem>): QueueItem => ({
  id: "itr_1", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: "k", category: "ads_triage_worse",
  kind: null, severity: "rule_warning", message: "", action_url: null, visible_from: null, status: "open",
  created_at: "2026-09-23T00:00:00Z", resolved_at: null, kind_key: "worse", triage: triageItem(), proposal: null, done: false,
  ...overrides,
});

// F47 Contract D: done-ness is the row's own `done` (app/ads/queue_done.py) — the frontend never re-derives it.
describe("isQueueItemDone", () => {
  it("reads the row's own done, whatever its proposal says", () => {
    expect(isQueueItemDone(queueItem({ proposal: deferredReview, done: true }))).toBe(true);
    expect(isQueueItemDone(queueItem({ proposal: deferredReview, done: false }))).toBe(false);
    expect(isQueueItemDone(queueItem({ proposal: null, done: false }))).toBe(false);
  });
});

// F49 Contract Q: the board, 「第 N 件」 and 「共 M 件」 read the served `decision`／`position`／`decisions.open` — the
// served order here (refresh, settle, closeout, worse) is not the old local list (cleanup, worse, settle, refresh).
const closeoutRow = (overrides: Partial<CloseoutQueueRow> = {}): CloseoutQueueRow => ({
  id: "itr_c", dedupe_key: "closeout", category: "ads_triage_closeout", severity: "rule_warning", message: "「秋季檔期」已結束，待結案",
  action_url: "/brands/brd_1/ads/campaigns/cmp_9?tab=perf&close=1", visible_from: null, status: "open", created_at: "2026-10-10T00:00:00Z",
  campaign_id: "cmp_9", decision: true, position: 3, done: false,
  closeout: { campaign_id: "cmp_9", campaign_name: "秋季檔期", end_date: "2026-10-09", running: { count: 2, read_at: "2026-10-10T02:00:00Z" } },
  ...overrides,
});
const served = (items: QueueItem[], extra: Partial<QueuePayload> = {}): QueuePayload => ({
  items, counts: { stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 }, total_ads: 0,
  kinds_available: [], kinds_pending: [], settle: null, closeouts: [], ...extra,
});

describe("decisionBoard／decisionPosition（F49 Contract Q）", () => {
  const refresh = queueItem({ id: "r", kind_key: "refresh_creative", decision: true, position: 1 });
  const worse = queueItem({ id: "w", decision: true, position: 4 });
  const handled = queueItem({ id: "h", decision: true, position: null, done: true });
  const gap = queueItem({ id: "g", kind_key: "insufficient_data", decision: false, position: null });
  const scale = queueItem({ id: "s", kind_key: "scale_budget", decision: false, position: null });
  const q = served([worse, handled, gap, refresh, scale], {
    settle: settleRow({ decision: true, position: 2, done: false }), closeouts: [closeoutRow()],
    decisions: { kinds: ["cleanup", "worse", "closeout", "refresh_creative"], open: 4 },
  });

  it("lists open decision rows by served position, then the handled ones; notices never", () => {
    const board = decisionBoard("brd_1", q);
    expect(board.open.map((d) => (d.kind === "item" ? d.item.id : d.row.id))).toEqual(["r", "itr_s", "itr_c", "w"]);
    expect(board.done.map((d) => (d.kind === "item" ? d.item.id : d.row.id))).toEqual(["h"]);
  });

  it("「第 N 件／共 M 件」 is the row's served position over decisions.open", () => {
    expect(decisionPosition(q, worse)).toEqual({ pos: 4, total: 4 });
    expect(decisionPosition(q, refresh)).toEqual({ pos: 1, total: 4 });
    expect(settlePosition("brd_1", q)).toEqual({ pos: 2, total: 4 });
    // The total is the served count, even when this read carries fewer rows than it counts.
    expect(decisionPosition({ ...q, decisions: { kinds: [], open: 7 } }, worse)).toEqual({ pos: 4, total: 7 });
  });

  it("a handled row, a notice row, or no queue has no position", () => {
    expect(decisionPosition(q, handled)).toBeNull();
    expect(decisionPosition(q, gap)).toBeNull();
    expect(decisionPosition(q, scale)).toBeNull();
    expect(decisionPosition(null, worse)).toBeNull();
    expect(settlePosition("brd_1", served([]))).toBeNull();
  });

  it("a payload without the served fields (older fixtures only) counts its open rows in served order", () => {
    const one = queueItem({ id: "w1" });
    expect(decisionPosition(served([one]), one)).toEqual({ pos: 1, total: 1 });
  });
});

describe("nextOpenQueueItem", () => {
  const set = (id: string, status: "draft" | "deferred") => ({
    change_set_id: id, campaign_id: "cmp_1", kind: "cleanup" as const, status, verification_state: "pending" as const,
    reason: null, revisit_at: null, multi: true,
  });
  const queue = (items: QueueItem[]) => ({
    items, counts: { stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 }, total_ads: 0,
    kinds_available: [], kinds_pending: [],
  });

  it("skips done rows", () => {
    const deferred = queueItem({ id: "a", triage: triageItem({ entity_id: "ad_a" }), proposal: deferredReview, done: true });
    const open = queueItem({ id: "b", triage: triageItem({ entity_id: "ad_b" }) });
    expect(nextOpenQueueItem("brd_1", queue([deferred, open]), null)?.href).toBe("/brands/brd_1/ads/campaigns/cmp_1/review/ad_b");
    expect(nextOpenQueueItem("brd_1", queue([deferred]), null)).toBeNull();
  });

  // F49 Contract Q: 下一件 is the open decision row with the lowest served position other than this page's own row.
  it("follows the served position, skips notice rows and the current row (drill-11 R4 H4)", () => {
    const current = queueItem({ id: "w1", triage: triageItem({ entity_id: "ad_1" }), decision: true, position: 1 });
    const later = queueItem({ id: "w3", triage: triageItem({ entity_id: "ad_3" }), decision: true, position: 3 });
    const sooner = queueItem({ id: "w2", triage: triageItem({ entity_id: "ad_2" }), decision: true, position: 2 });
    const gap = queueItem({
      id: "g", kind_key: "insufficient_data", decision: false, position: null, action_url: "/brands/brd_1/ads/campaigns/cmp_2/wait",
      insufficient: { campaign_id: "cmp_2", campaign_name: "活動二", missing_days: ["2026-10-03"], sync_state: "ok", coverage: null },
    });
    const q = served([gap, later, current, sooner]);
    expect(nextOpenQueueItem("brd_1", q, current)?.href).toBe("/brands/brd_1/ads/campaigns/cmp_1/review/ad_2");
    // Only notices and handled rows left → nothing next (the page shows ← 回投放中心), never the 資料不足 row.
    const handled = queueItem({ id: "h", decision: true, position: null, done: true });
    expect(nextOpenQueueItem("brd_1", served([gap, current, handled]), current)).toBeNull();
  });

  it("a cleanup row on the same campaign is not mistaken for the current one; a draft-less one opens its proposal", () => {
    const refresh = queueItem({
      id: "r", kind_key: "refresh_creative", decision: true, position: 1,
      refresh: { campaign_id: "cmp_1", campaign_name: "活動", readable_count: 1, classified_count: 3, thumbnails: [] },
    });
    const cleanup = queueItem({
      id: "c", kind_key: "cleanup", decision: true, position: 2, proposal: null,
      cleanup: { campaign_id: "cmp_1", campaign_name: "活動", can_support: 1, active_ads: 3, ads: [], keep: [], short: 0, daily_saving: null, scale_owner_id: null },
    });
    expect(nextOpenQueueItem("brd_1", served([refresh, cleanup]), refresh)).toEqual({
      label: "看提議", href: "/brands/brd_1/ads/campaigns/cmp_1/propose/cleanup/cmp_1", done: false,
    });
    expect(nextOpenQueueItem("brd_1", served([refresh, cleanup]), cleanup)?.href).toBe("/brands/brd_1/ads/campaigns/cmp_1?tab=assets&material_new=1");
    expect(nextOpenQueueItem("brd_1", served([refresh, { ...cleanup, proposal: set("acs_1", "draft") }]), refresh)?.href)
      .toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/confirm");
  });

  it("a closeout row next links to the campaign's closeout (「結案這一期」); the settle row to its settle page", () => {
    const current = queueItem({ id: "w1", decision: true, position: 1 });
    const later = queueItem({ id: "w9", triage: triageItem({ entity_id: "ad_9" }), decision: true, position: 4 });
    const q = served([current, later], { closeouts: [closeoutRow({ position: 3 })], settle: settleRow({ decision: true, position: 2, done: false }) });
    expect(nextOpenQueueItem("brd_1", q, current)).toEqual({ label: "開始結算", href: "/brands/brd_1/ads/settle/2026-08/result", done: false });
    const noSettle = { ...q, settle: null };
    expect(nextOpenQueueItem("brd_1", noSettle, current)).toEqual({
      label: "結案這一期", href: "/brands/brd_1/ads/campaigns/cmp_9?tab=perf&close=1", done: false, closeout: true,
    });
    // A closeout is never the current row of a flow page: the same campaign's cleanup row does not hide it.
    const sameCampaign = closeoutRow({ campaign_id: "cmp_1", position: 2, action_url: "/brands/brd_1/ads/campaigns/cmp_1?tab=perf&close=1" });
    expect(nextOpenQueueItem("brd_1", served([current], { closeouts: [sameCampaign] }), current)?.href)
      .toBe("/brands/brd_1/ads/campaigns/cmp_1?tab=perf&close=1");
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
