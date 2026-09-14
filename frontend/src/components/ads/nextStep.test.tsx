/** frontend/src/components/ads/nextStep.test.tsx — F06-I01: `nextStep()` is the workspace's
 * only next-step producer (ARCHITECTURE.md §6.2 decision 15). One case per rule-table row, in
 * table order, plus the regression that caught the bug this issue fixes (§0). */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AdRow, CampaignDetail, DeliveryGroupRow } from "@/lib/adsApi";
import { nextStep, NextStepButton } from "./nextStep";

function ad(overrides: Partial<AdRow> = {}): AdRow {
  return {
    id: "ad_1",
    campaign_id: "cmp_1",
    group_id: "grp_1",
    name: "廣告一",
    audience_key: null,
    pain_key: null,
    angle_key: null,
    hook_key: null,
    proof_key: null,
    offer_key: null,
    format_key: null,
    coordinates_snapshot_json: {},
    product_id: null,
    asset_ready_source: null,
    asset_ready_by: null,
    asset_ready_at: null,
    external_id: null,
    external_name: null,
    external_status: null,
    local_state: "unbound",
    bound_at: null,
    ...overrides,
  };
}

function group(overrides: Partial<DeliveryGroupRow> = {}): DeliveryGroupRow {
  return {
    id: "grp_1",
    campaign_id: "cmp_1",
    channel_key: "meta",
    name: "投放組",
    role: "new",
    daily_budget: 1000,
    start_date: null,
    end_date: null,
    ads: [],
    external_id: null,
    external_name: null,
    external_status: null,
    local_state: "unbound",
    bound_at: null,
    ...overrides,
  };
}

function campaign(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    id: "cmp_1",
    name: "測試 Campaign",
    goal_text: "想在雙十一衝一波業績",
    objective: "conversion",
    success_metric: "cpa",
    success_target: null,
    success_basis: null,
    start_date: null,
    end_date: null,
    status: "draft",
    budget_planned: null,
    budget_scenario: null,
    budget_basis_json: {},
    budget_total: null,
    context_json: {},
    constraints_json: {},
    verdict: null,
    verdict_json: {},
    closed_at: null,
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    groups: [],
    actions: [],
    outcome: { spend: 0, purchases: 0, revenue: 0 },
    asset_readiness: { ready_count: 0, total: 0 },
    action_lines: [],
    external_id: null,
    external_name: null,
    external_status: null,
    local_state: "unbound",
    bound_at: null,
    ...overrides,
  };
}

const WITH_STRATEGY = { strategy: { allocation: [{ role: "new" as const, label: "新客", pct: 100, rationale: null, amount: null }], why: [], unknowns: [], alternatives: [], learning_goals: [] } };

describe("nextStep（F06-I01）", () => {
  it("status closed：id performance、target performance、stageIndex 5", () => {
    const step = nextStep(campaign({ status: "closed", budget_basis_json: WITH_STRATEGY, groups: [group({ ads: [ad()] })] }));
    expect(step).toMatchObject({ id: "performance", target: "performance", stageIndex: 5, label: "查看成效 →" });
  });

  it("status live：id performance、stageIndex 4，句子提到「投放中」", () => {
    const step = nextStep(campaign({ status: "live", budget_basis_json: WITH_STRATEGY, groups: [group({ ads: [ad()] })] }));
    expect(step).toMatchObject({ id: "performance", target: "performance", stageIndex: 4 });
    expect(step.sentence).toContain("投放中");
  });

  it("status ended：id performance、stageIndex 4，句子提到「結束」", () => {
    const step = nextStep(campaign({ status: "ended", budget_basis_json: WITH_STRATEGY, groups: [group({ ads: [ad()] })] }));
    expect(step).toMatchObject({ id: "performance", target: "performance", stageIndex: 4 });
    expect(step.sentence).toContain("結束");
  });

  it("沒有策略：id strategy_generate、target strategy、stageIndex 0", () => {
    const step = nextStep(campaign({ budget_basis_json: {} }));
    expect(step).toMatchObject({ id: "strategy_generate", target: "strategy", stageIndex: 0, label: "前往策略 →" });
  });

  it("有策略、沒有投放組：id strategy_adopt、target strategy、stageIndex 1", () => {
    const step = nextStep(campaign({ budget_basis_json: WITH_STRATEGY, groups: [] }));
    expect(step).toMatchObject({ id: "strategy_adopt", target: "strategy", stageIndex: 1, label: "前往策略 →" });
  });

  it("有投放組、沒有廣告：id add_ad、target structure、stageIndex 2", () => {
    const step = nextStep(campaign({ budget_basis_json: WITH_STRATEGY, groups: [group({ ads: [] })] }));
    expect(step).toMatchObject({ id: "add_ad", target: "structure", stageIndex: 2, label: "前往投放結構 →" });
  });

  it("素材都就位（regression：兩則廣告、ready 2/2、status ready）：id publish、target publish、stageIndex 3、label 發布 →", () => {
    const step = nextStep(
      campaign({
        status: "ready",
        budget_basis_json: WITH_STRATEGY,
        groups: [group({ ads: [ad({ id: "ad_1" }), ad({ id: "ad_2" })] })],
        asset_readiness: { ready_count: 2, total: 2, pack_id: "pack_1" },
      }),
    );
    expect(step).toMatchObject({ id: "publish", target: "publish", stageIndex: 3, label: "發布 →" });
  });

  it("有廣告、還沒交棒（沒有 pack_id）：id dispatch、target structure、stageIndex 2", () => {
    const step = nextStep(
      campaign({
        budget_basis_json: WITH_STRATEGY,
        groups: [group({ ads: [ad()] })],
        asset_readiness: { ready_count: 0, total: 1, pack_id: null },
      }),
    );
    expect(step).toMatchObject({ id: "dispatch", target: "structure", stageIndex: 2, label: "前往投放結構 →" });
  });

  it("已交棒、素材還沒全部就位：id make_assets、target assets、stageIndex 3", () => {
    const step = nextStep(
      campaign({
        budget_basis_json: WITH_STRATEGY,
        groups: [group({ ads: [ad({ id: "ad_1" }), ad({ id: "ad_2" })] })],
        asset_readiness: { ready_count: 1, total: 2, pack_id: "pack_1" },
      }),
    );
    expect(step).toMatchObject({ id: "make_assets", target: "assets", stageIndex: 3, label: "前往素材 →" });
  });

  it("NextStepButton 按下去呼叫 onChangeTab(step.target)", async () => {
    const user = userEvent.setup();
    const onChangeTab = vi.fn();
    const step = nextStep(campaign({ budget_basis_json: {} }));
    render(<NextStepButton step={step} onChangeTab={onChangeTab} />);

    await user.click(screen.getByRole("button", { name: step.label }));
    expect(onChangeTab).toHaveBeenCalledWith(step.target);
  });
});
