import { describe, expect, it } from "vitest";
import type { QueueCleanupProposal, QueueItem, QueueReviewProposal, TriageItem } from "@/lib/adsTriageApi";
import { cleanupAction, isQueueItemDone } from "./status";

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
