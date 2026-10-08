import type { CampaignDetail } from "@/lib/adsApi";
import type { LearningEvidence } from "@/lib/adsLearningEvidence";

/** Synthetic display receipts matching the approved prototype; never a live market receipt. */
export function evidenceFixture(id = "current", changes: Partial<LearningEvidence> = {}): LearningEvidence {
  return {
    schema_version: 1, id, meaning_revision: `meaning-${id}`, display_text: "夜跑上班族的反光訊息：最近一期值得保留作對照",
    support_label: "單次觀察 · 樣本少", provenance: "platform_observation",
    sources: [{kind: "campaign", id: "cmp_previous", version: "source-1", label: "九月夜跑活動", period: {start: "2026-09-01", end: "2026-09-30"}}],
    scope: {product_id: "prd_fixture", product_label: "反光夜跑背心 · 單件", audience_key: "customer-group:night-run",
      customer_group_id: "pcg_run", claim_key: "reflection", claim_family: "performance", objective_family: "sales",
      result_kind: "purchase", currency: "TWD", attribution: "7d_click"},
    conditions: {price_version: "price-1", offer_key: "none", offer_version: "offer-1", material_version: "material-1", target_version: "target-1", valid_until: null},
    sample: {result_events: 6, sufficient: false}, independent_count: 1, same_direction_count: 1, contrary_count: 0,
    use_state: "usable", reason_codes: ["small_sample"], reason_labels: ["沿用原訊息作對照，不自動加碼。"],
    allowed_uses: ["test", "retain_control"], limits: ["causality_unknown"], ...changes,
  };
}

export function strategyFixture(): CampaignDetail {
  const first = evidenceFixture();
  const second = evidenceFixture("repeat", {display_text: "清楚交代穿著情境，可作為下一個訊息提案",
    support_label: "重複觀察 · 未證明因果", independent_count: 2, same_direction_count: 2,
    sample: {result_events: 18, sufficient: true}, reason_labels: ["新提案測試下班後夜跑情境。"]});
  const historical = evidenceFixture("changed", {display_text: "會員優惠訊息在先前活動中表現較佳",
    use_state: "revalidation", allowed_uses: [], reason_labels: ["先前優惠已結束，這期不能沿用它的優惠承諾。"],
    support_label: "適用條件待核對"});
  return {
    id: "cmp_f53_ui", name: "十月夜跑安排", goal_text: "取得購買", objective: "取得購買",
    start_date: "2026-10-01", end_date: "2026-10-31", status: "draft", budget_planned: 30000, budget_scenario: "cap",
    cap: {value: 450, own_value: 450, basis: "own", break_even: null, price: null, product_id: "prd_fixture", result_kind: "purchase", result_label: "購買", missing: [], revision: 1,
      cap_unit: {currency: "TWD", basis: "own", source: "user", unit_basis: "purchase"}},
    budget_basis_json: {
      strategy: {
        decision: {schema_version: 1, revision: "decision-fixture", state: "proposed", slots: [
          {id: "slot-new", role: "new", customer_group_id: "pcg_run", offer_key: "none", carry_from_ad_id: "ad_control", test_intent: null,
            rationale: "沿用反光訊息與原素材，保留一份可比較的對照。", evidence_refs: [{kind: "learning", id: "current"}],
            display: {customer_group_label: "下班後夜跑者", offer_label: "原價溝通", carried_ad_label: "反光訊息原版", evidence: [{kind: "learning", id: "current", label: "最近一期原廣告"}], evidence_omitted: 0}},
          {id: "slot-explore", role: "explore", customer_group_id: "pcg_walk", offer_key: "none", carry_from_ad_id: null, test_intent: "通勤穿著情境",
            rationale: "提出通勤穿著情境；目前沒有證據證明這群人會購買。", evidence_refs: [{kind: "brand_fact", id: "fact_walk"}],
            display: {customer_group_label: "夜間步行通勤者", offer_label: "不使用優惠", carried_ad_label: null, evidence: [{kind: "brand_fact", id: "fact_walk", label: "品牌已建的顧客群"}], evidence_omitted: 0}},
        ], facts: {available: {customer_groups: 2, customer_group_names: ["下班後夜跑者", "夜間步行通勤者"]},
          proposed: {customer_groups: 2, delivery_groups: 2, ads: 2, customer_group_names: ["下班後夜跑者", "夜間步行通勤者"], unknown_audience_ads: 0},
          actual: {customer_groups: 0, delivery_groups: 0, ads: 0, customer_group_names: [], unknown_audience_ads: 0}}, feasibility: {state: "ready", reasons: []}},
        allocation: [{role: "new", label: "新客", pct: 60, amount: 18000, rationale: "沿用反光訊息與原素材，保留一份可比較的對照。"},
          {role: "explore", label: "探索", pct: 40, amount: 12000, rationale: "提出通勤穿著情境；目前沒有證據證明這群人會購買。"}],
        why: [], unknowns: ["目前無法證明哪個賣點造成結果，也不知道新受眾會不會購買。"], alternatives: [],
        learning_goals: ["保留可比較的對照，觀察穿著情境是否有助於購買；資料不足時不判定勝負。"],
      },
      basis: {evidence_context: {schema_version: 1, revision: "evidence-fixture", scope_product_id: "prd_fixture", scope_label: "反光夜跑背心 · 單件",
        eligible_count: 2, items: [first, second, historical], omitted: 0},
        knowledge_item_ids: [], llm_task_id: "fixture-task", input_context_hash: "fixture-hash",
        brand_facts: [{id: "fact_walk", label: "品牌已建夜間步行通勤者顧客群", updated_at: "2026-09-30T00:00:00Z"}],
        prices: [{product_id: "prd_fixture", sell_way_name: "反光夜跑背心 · 單件", price: 1580, effective_from: "2026-10-01", stale: false, assumptions: []}],
        learnings: [first, second].map((evidence) => ({id: evidence.id, text: evidence.display_text, level: "product", needs_revalidation: false, evidence})), estimated_fields: []},
      scenarios: {mode: "cold_start", recommended: "cap", basis: {}, budget_cap: 30000, scenarios: [
        {key: "cap", label: "照預算上限", currency: "TWD", total: 30000, daily: 968, caption: "沿用已選預算", over_cap: 0},
      ]},
    }, budget_total: null, context_json: {product_ids: ["prd_fixture"], field_sources: {cap: "user"}}, constraints_json: {budget: 30000},
    verdict: null, verdict_json: {}, closed_at: null, created_by: null, created_at: "2026-10-01T00:00:00Z", groups: [], actions: [],
    outcome: {spend: null, purchases: null, revenue: null}, asset_readiness: {ready_count: 0, total: 0},
    external_id: null, external_name: null, external_status: null, local_state: "unbound", bound_at: null,
  };
}
