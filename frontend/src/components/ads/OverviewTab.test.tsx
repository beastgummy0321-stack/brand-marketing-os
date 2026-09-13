/** frontend/src/components/ads/OverviewTab.test.tsx — F03-I23: 總覽 tab is a pure-props
 * component (no fetch), so this hand-builds a `CampaignDetail` literal and asserts the two
 * bugs the integration review caught are gone: an untracked Meta `0` must never print as
 * 購買, and 目前投放組合計／採用時的計畫 must stay two separately-labelled numbers instead of
 * blending into one. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CampaignDetail, DeliveryGroupRow } from "@/lib/adsApi";
import { OverviewTab } from "./OverviewTab";

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
    status: "live",
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
    external_id: null,
    external_name: null,
    external_status: null,
    local_state: "unbound",
    bound_at: null,
    ...overrides,
  };
}

describe("OverviewTab（F03-I23）", () => {
  it("已發布但 outcome 全是 0：印「還沒有成效資料」，畫面上不出現「購買」這個假 0", () => {
    render(
      <OverviewTab
        campaign={campaign({ status: "live", outcome: { spend: 0, purchases: 0, revenue: 0 } })}
        onChangeTab={vi.fn()}
      />,
    );

    expect(screen.getByText("還沒有成效資料")).toBeTruthy();
    expect(screen.queryByText("購買")).toBeNull();
  });

  it("兩個投放組、10 天期間：目前投放組合計算對，且顯示日預算 × 天數的依據", () => {
    render(
      <OverviewTab
        campaign={campaign({
          groups: [
            group({ id: "g1", daily_budget: 1000 }),
            group({ id: "g2", daily_budget: 500 }),
          ],
          start_date: "2026-01-01",
          end_date: "2026-01-10",
        })}
        onChangeTab={vi.fn()}
      />,
    );

    expect(screen.getByText("NT$ 15,000")).toBeTruthy();
    expect(screen.getByText("日預算 NT$ 1,500／天 × 10 天")).toBeTruthy();
  });

  it("budget_planned 跟起訖日都是 null：顯示「尚未設定」，不顯示「累積中」", () => {
    render(
      <OverviewTab
        campaign={campaign({ budget_planned: null, start_date: null, end_date: null })}
        onChangeTab={vi.fn()}
      />,
    );

    expect(screen.getAllByText("尚未設定").length).toBeGreaterThan(0);
    expect(screen.queryByText(/累積中/)).toBeNull();
  });
});
