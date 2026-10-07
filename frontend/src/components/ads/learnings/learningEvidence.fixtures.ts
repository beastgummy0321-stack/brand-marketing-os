import type {CoordinateLearnings} from "@/lib/adsLearningsApi";
import type {LibraryData} from "@/lib/libraryApi";
import type {WizardOptions} from "@/lib/adsWizardApi";
import {evidenceFixture} from "../strategy/strategyEvidence.fixtures";

/** Synthetic receipts for local UI checks; they establish no market result. */
export function libraryEvidenceFixture(): CoordinateLearnings {
  const first = evidenceFixture("current");
  const second = evidenceFixture("repeat", {display_text: "清楚交代穿著情境，可作為下一個訊息提案",
    support_label: "重複觀察 · 未證明因果", sample: {result_events: 18, sufficient: true}, independent_count: 2, same_direction_count: 2});
  const expired = evidenceFixture("changed", {display_text: "會員優惠訊息在先前活動中表現較佳", use_state: "revalidation",
    support_label: "歷史觀察", reason_codes: ["offer_expired"], reason_labels: ["先前優惠已結束，這期不能沿用它的優惠承諾。"], allowed_uses: []});
  const unknown = evidenceFixture("unknown", {display_text: "通勤族曾對輕量訊息有回應", use_state: "history",
    support_label: "適用條件未確認", reason_labels: ["來源適用條件尚未核實。"], allowed_uses: [], sample: {result_events: null, sufficient: null}});
  const simulation = evidenceFixture("simulation", {display_text: "備考情境在演練中取得較低每筆成本", provenance: "simulation", use_state: "excluded",
    support_label: "非市場實證", reason_labels: ["演練資料不能作為市場成效。"], allowed_uses: [], sample: {result_events: 0, sufficient: false}});
  const other = evidenceFixture("other", {display_text: "另一商品的免運訊息曾有較好結果", use_state: "excluded",
    scope: {...first.scope, product_id: "prd_coat", product_label: "輕量通勤外套 · 單件"}, reason_labels: ["本商品不適用。"], allowed_uses: []});
  return {evidence_context: {schema_version: 1, revision: "library-fixture", scope_product_id: "prd_fixture", scope_label: "反光夜跑背心 · 單件",
    eligible_count: 2, items: [first, second, expired, unknown, simulation, other], omitted: 0},
    campaigns: [{campaign_id: "cmp_f53_ui", campaign_name: "九月夜跑活動", sell_way_id: "prd_fixture", start_date: "2026-09-01",
      end_date: "2026-09-30", closed_on: "2026-10-01", cap: 450, currency: "TWD", spend: 1200, sales: 6, cost_per_sale: 200,
      counts: {keep: 1, replace: 0}, rule_text: "1 則每筆低於上限 450 → 留下；其餘換掉", empty_reason: null,
      rows: [{evidence: first, learning_id: first.id, rank: 1, of: 1, ad_id: "ad_original", ad_name: "反光訊息 · 下班後夜跑",
        customer_group: {id: "pcg_run", who: "下班後夜跑者"}, coordinates: [], spend: 1200, sales: 6, cost_per_sale: 200,
        verdict: "keep", verdict_label: "留下", flags: ["樣本少"]}]}],
    groups: [{customer_group_id: "pcg_run", who: "下班後夜跑者", ads: 1, spend: 1200, sales: 6, cap: 450, cost_per_sale: 200}],
    next: {sell_way_id: "prd_fixture", new_campaign_href: "/brands/brd_f53_ui/ads/new?sell_way=prd_fixture"}};
}

export const libraryShellFixture: LibraryData = {
  brand: {id: "brd_f53_ui", name: "夜行裝備", client_name: null, status: "active", market_region: "TW", conversion_goal: "purchase",
    advertising_history: null, regulatory_regime: null, delete_impact: []},
  products: [], facts: [], rules: [], claims: [], assets: [], channels: [], customer_voices: [],
};

export const libraryOptionsFixture: WizardOptions = {products: [{id: "prd_fixture", name: "反光夜跑背心 · 單件", display_name: "單件",
  kind: "single", knowledge_product_id: "kp_fixture", knowledge_product_name: "反光夜跑背心", price: 1580, currency: "TWD",
  thumbnail_url: null, has_cost: true, break_even: 450, cap_per_sale: 450, derived_fields: [], offer_labels: [],
  customer_groups: [{id: "pcg_run", who: "下班後夜跑者"}], landing_url: null, previous: null, learned: null}],
  objectives: [], default_objective: "購買", default_platform: null};
