/** frontend/src/components/ads/OverviewTab.test.tsx — F03-I23: 總覽 tab is a pure-props
 * component (no fetch), so this hand-builds a `CampaignDetail` literal and asserts the two
 * bugs the integration review caught are gone: an untracked Meta `0` must never print as
 * 購買, and 目前投放組合計／採用時的計畫 must stay two separately-labelled numbers instead of
 * blending into one. */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AdsActionLine, CampaignDetail, CampaignJudgment, DeliveryGroupRow } from "@/lib/adsApi";
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
    judgment: { tone: "neutral", text: "投放中", detail: "還沒有花費資料" },
    action_lines: [],
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

  it("judgment 是後端組好的句子：畫面原樣印，前端不重拼", () => {
    const judgment: CampaignJudgment = {
      tone: "warn",
      text: "投放中，預算花得比時間快",
      detail: "第 3／10 天，已花費佔預算 45%",
    };
    render(<OverviewTab campaign={campaign({ judgment })} onChangeTab={vi.fn()} />);

    expect(screen.getByText("投放中，預算花得比時間快")).toBeTruthy();
  });

  it("action_lines 是空陣列：印誠實空狀態，且原始 JSON 鍵值不外洩", () => {
    render(<OverviewTab campaign={campaign({ action_lines: [] })} onChangeTab={vi.fn()} />);

    expect(screen.getByText("這個 Campaign 還沒有異動紀錄。")).toBeTruthy();
    expect(screen.queryByText(/daily_budget/)).toBeNull();
  });

  it("有異動紀錄時印後端組好的三句話", () => {
    const line: AdsActionLine = {
      campaign_id: "cmp_1",
      campaign_name: "測試 Campaign",
      time_text: "3 小時前",
      title: "調整了每日預算",
      detail: "從 NT$ 1,000 調整為 NT$ 1,500",
    };
    render(<OverviewTab campaign={campaign({ action_lines: [line] })} onChangeTab={vi.fn()} />);

    expect(screen.getByText("調整了每日預算")).toBeTruthy();
    expect(screen.queryByText(/daily_budget/)).toBeNull();
  });

  it("佔位卡與需要你決定的空狀態都在畫面上", () => {
    render(<OverviewTab campaign={campaign()} onChangeTab={vi.fn()} />);

    expect(screen.getByText("自動執行接上後開放")).toBeTruthy();
    expect(screen.getByText("目前沒有需要你決定的事")).toBeTruthy();
  });
});
