import type {LearningEvidence} from "@/lib/adsLearningEvidence";
import type {ChangeSet} from "@/lib/adsChangeApi";

/** Synthetic local receipts, never platform or market proof. */
export function pauseEvidenceFixture(overrides: Partial<LearningEvidence> = {}): LearningEvidence {
  return {schema_version: 1, id: "lrn_pause_ui", meaning_revision: "pause-meaning-v1",
    display_text: "暫停反光訊息 · 下班後夜跑者", support_label: "操作觀察 · 原因未確認", provenance: "operation_readback",
    sources: [{kind: "pause", id: "aci_f53_ui", version: "pause-source-v1", period: {start: "2026-10-08", end: "2026-10-08"}, label: "反光訊息廣告"}],
    scope: {product_id: "prd_fixture", product_label: "反光夜跑背心 · 單件", audience_key: null,
      customer_group_id: "pcg_run", claim_key: "pause:反光訊息", claim_family: "operation", objective_family: "sales",
      result_kind: null, currency: "TWD", attribution: null},
    conditions: {price_version: "price-v1", offer_key: "none", offer_version: "no-offer-v1", material_version: "creative-v1", target_version: "target-v1", valid_until: null},
    sample: {result_events: null, sufficient: null}, independent_count: 0, same_direction_count: 0, contrary_count: 0,
    use_state: "history", reason_codes: ["operation_only"], reason_labels: ["暫停設定已核對；還不能據此判定這個訊息對受眾無效。"],
    allowed_uses: ["operation"], limits: ["operation_only"], ...overrides};
}

export function verifyReceiptFixture(): ChangeSet {
  return {id: "acs_f53_ui", campaign_id: "cmp_f53_ui", title: "暫停 · 反光訊息廣告", month: "2026-10",
    operation_id: "fixture-operation", content_hash: "fixture-approved-hash", status: "approved", reason: null, revisit_at: null,
    approval_id: "approval-fixture", created_at: "2026-10-08T00:00:00Z", approved_at: "2026-10-08T00:01:00Z", can_revise: false,
    verification_state: "confirmed", verification_label: "已核對相符",
    items: [{id: "aci_f53_ui", kind: "pause", target_id: "entity_f53_ui",
      target: {id: "entity_f53_ui", name: "反光訊息廣告", platform: "meta", source_account: "account-fixture", native_kind: "ad", native_id: "native-fixture"},
      before: {status: "ACTIVE"}, after: {status: "PAUSED"}, reason: "核准暫停本則廣告", verification_state: "confirmed", verification_label: "已核對相符",
      evidence_json: {setting_matches: true, observed_at: "2026-10-08T00:02:00Z", expected: {status: "PAUSED"}, observed: {status: "PAUSED"}},
      status_labels: {before: "投遞中", after: "已暫停", observed: "已暫停"}, reported_at: "2026-10-08T00:01:30Z",
      first_observed_at: "2026-10-08T00:02:00Z", verified_at: "2026-10-08T00:02:00Z", platform_url: null,
      learning: {recorded: true, confidence: "observed", count: 0, evidence: pauseEvidenceFixture()},
      timeline: {spend_stopped: null, delivery_started: null, next_review_at: null}}]};
}

export function comparativeEvidenceFixture(overrides: Partial<LearningEvidence> = {}): LearningEvidence {
  const base = pauseEvidenceFixture();
  return {...base, id: "lrn_ab_ui", meaning_revision: "ab-meaning-v1",
    display_text: "這兩個開場版本的相對比較", support_label: "多次同向觀察 · 僅能比較兩個版本",
    provenance: "platform_observation", sources: [{kind: "ab", id: "pair-fixture", version: "ab-source-v1",
      label: "開場 A/B 比較", period: {start: "2026-09-10", end: "2026-09-16"}}],
    scope: {...base.scope, claim_family: "performance", claim_key: "pair-fixture", result_kind: "purchase", attribution: "7d_click"},
    sample: {result_events: 20, sufficient: true}, independent_count: 3, same_direction_count: 3, contrary_count: 0,
    use_state: "usable", reason_codes: ["relative_comparison_only"], reason_labels: ["僅支持這兩個版本在已核實條件下的比較，不保證全面有效。"],
    allowed_uses: ["retain_control", "market_support"], limits: ["relative_comparison_only"], ...overrides};
}
