/** frontend/src/components/ads/StrategyTab.test.tsx — F04-I14: 策略分頁重做成一張建議卡
 * ＋一顆主要按鈕，其餘全部收在 Disclosure 裡（R9）。這支測試是「預設看不到進階內容」的
 * 機器證明，以及主要按鈕依 `budget_scenario` 走對 API 順序。 */
import type { ReactElement } from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import type { AdRow, CampaignDetail, DeliveryGroupRow } from "@/lib/adsApi";
import { adoptStrategy, selectScenario } from "@/lib/adsApi";
import { StrategyTab } from "./StrategyTab";

function renderWithRouter(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return {
    ...actual,
    generateStrategy: vi.fn(),
    patchCampaign: vi.fn(),
    selectScenario: vi.fn(),
    setAllocation: vi.fn(),
    adoptStrategy: vi.fn(),
  };
});

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

function campaign(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    id: "cmp_1",
    name: "測試 Campaign",
    goal_text: "想在雙十一衝一波業績",
    objective: "增加新客購買",
    success_metric: "cpa",
    success_target: null,
    success_basis: null,
    start_date: "2026-01-01",
    end_date: "2026-01-15",
    status: "draft",
    budget_planned: null,
    budget_scenario: null,
    budget_basis_json: {
      strategy: {
        allocation: [
          { role: "new", label: "新客", pct: 70, rationale: null, amount: 21000 },
          { role: "retarget", label: "再行銷", pct: 20, rationale: null, amount: 6000 },
          { role: "explore", label: "探索", pct: 10, rationale: null, amount: 3000 },
        ],
        why: ["你的產品在相似受眾中有高轉換表現"],
        unknowns: ["新受眾的實際轉換率仍需驗證"],
        alternatives: [],
        learning_goals: [],
      },
      scenarios: {
        mode: "cold_start",
        scenarios: [
          { key: "minimum", label: "保守", daily: 1000, total: 15000, caption: "最低可行" },
          { key: "recommended", label: "推薦", daily: 2000, total: 30000, caption: "建議規模" },
          { key: "aggressive", label: "積極", daily: 3000, total: 45000, caption: "衝刺規模" },
        ],
        recommended: "recommended",
        basis: {},
      },
      basis: {
        knowledge_item_ids: [],
        llm_task_id: "task_1",
        input_context_hash: "hash",
        brand_facts: [],
        prices: [],
        learnings: [],
        estimated_fields: [],
      },
    },
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

function renderTab(c: CampaignDetail, onCampaignChange = vi.fn(), onChangeTab = vi.fn()) {
  return { onCampaignChange, onChangeTab, ...renderWithRouter(
    <StrategyTab brandId="brd_1" campaign={c} onCampaignChange={onCampaignChange} onChangeTab={onChangeTab} />,
  ) };
}

describe("StrategyTab（F04-I14）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("預設畫面上看不到「平台結構」「預算情境」「合計」——三個收合都是關的", () => {
    renderTab(campaign());
    expect(screen.queryByText("平台結構")).toBeNull();
    expect(screen.queryByText("預算情境選擇")).toBeNull();
    expect(screen.queryByText(/合計 \d+%/)).toBeNull();
  });

  it("budget_scenario 是 null：按下主要按鈕先 selectScenario 再 adoptStrategy", async () => {
    const user = userEvent.setup();
    vi.mocked(selectScenario).mockResolvedValue(campaign({ budget_scenario: "recommended" }));
    vi.mocked(adoptStrategy).mockResolvedValue(campaign({ budget_scenario: "recommended", groups: [group()] }));
    const { onChangeTab } = renderTab(campaign({ budget_scenario: null }));

    await user.click(screen.getByRole("button", { name: "照這個方式進行 →" }));

    expect(selectScenario).toHaveBeenCalledTimes(1);
    expect(adoptStrategy).toHaveBeenCalledTimes(1);
    const scenarioOrder = vi.mocked(selectScenario).mock.invocationCallOrder[0];
    const adoptOrder = vi.mocked(adoptStrategy).mock.invocationCallOrder[0];
    expect(scenarioOrder).toBeLessThan(adoptOrder);
    expect(onChangeTab).toHaveBeenCalledTimes(1);
    expect(onChangeTab).toHaveBeenCalledWith("structure");
  });

  it("budget_scenario 已經是 recommended：按下主要按鈕不呼叫 selectScenario", async () => {
    const user = userEvent.setup();
    vi.mocked(adoptStrategy).mockResolvedValue(campaign({ budget_scenario: "recommended", groups: [group()] }));
    renderTab(campaign({ budget_scenario: "recommended" }));

    await user.click(screen.getByRole("button", { name: "照這個方式進行 →" }));

    expect(selectScenario).not.toHaveBeenCalled();
    expect(adoptStrategy).toHaveBeenCalledTimes(1);
  });

  it("cpa／300／30000：印「預估購買 100 筆」與推估說明；roas 時改印算不出推估購買", () => {
    const { rerender } = renderWithRouter(
      <StrategyTab
        brandId="brd_1"
        campaign={campaign({ success_metric: "cpa", success_target: 300, budget_planned: 30000 })}
        onCampaignChange={vi.fn()}
        onChangeTab={vi.fn()}
      />,
    );
    expect(screen.getByText(/預估購買 100 筆/)).toBeTruthy();
    expect(screen.getByText("推估（CPA 不變的算術）")).toBeTruthy();

    rerender(
      <MemoryRouter>
        <StrategyTab
          brandId="brd_1"
          campaign={campaign({ success_metric: "roas", success_target: 3, budget_planned: 30000 })}
          onCampaignChange={vi.fn()}
          onChangeTab={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByText(/預估購買/)).toBeNull();
    expect(screen.getByText("目標不是 CPA，或還沒有總預算，算不出推估購買。")).toBeTruthy();
  });

  it("labels 是名單時：預估文字改印「名單」，不是寫死的「購買」", () => {
    renderTab(
      campaign({
        success_metric: "cpa", success_target: 300, budget_planned: 30000,
        labels: { conversion: "名單", count: "名單數", cpa: "每筆名單成本" },
      }),
    );

    expect(screen.getByText(/預估名單 100 筆/)).toBeTruthy();
    expect(screen.queryByText(/預估購買/)).toBeNull();
  });

  it("labels 是名單時：編輯成功條件的下拉選單印「每筆名單成本（CPA）」", async () => {
    const user = userEvent.setup();
    renderTab(
      campaign({
        success_metric: "cpa", success_target: 300, budget_planned: 30000,
        labels: { conversion: "名單", count: "名單數", cpa: "每筆名單成本" },
      }),
    );

    await user.click(screen.getByRole("button", { name: "調整建議" }));
    await user.click(screen.getByRole("button", { name: "編輯" }));
    expect(screen.getByText("每筆名單成本（CPA）")).toBeTruthy();
  });

  it("有假設值時：策略依據面板印出 assumption_note 那句話", async () => {
    const user = userEvent.setup();
    const base = campaign();
    renderTab(
      campaign({
        budget_basis_json: {
          ...base.budget_basis_json,
          basis: {
            ...base.budget_basis_json.basis!,
            assumption_note: "用的是假設：單品的成交率假設 20%——之後用真實數字取代。",
          },
        },
      }),
    );

    await user.click(screen.getByRole("button", { name: "查看完整判斷" }));
    await user.click(screen.getByRole("button", { name: /查看策略依據/ }));
    expect(screen.getByText(/用的是假設：單品的成交率假設 20%/)).toBeTruthy();
  });

  it("learning_goals 空陣列印「這一輪沒有設定學習目標」；有三條時三條都在畫面上", () => {
    const c = campaign();
    const { rerender } = renderWithRouter(
      <StrategyTab brandId="brd_1" campaign={c} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} />,
    );
    expect(screen.getByText("這一輪沒有設定學習目標")).toBeTruthy();

    const withGoals = campaign({
      budget_basis_json: {
        ...c.budget_basis_json,
        strategy: {
          ...c.budget_basis_json.strategy!,
          learning_goals: ["學習目標一", "學習目標二", "學習目標三"],
        },
      },
    });
    rerender(
      <MemoryRouter>
        <StrategyTab brandId="brd_1" campaign={withGoals} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByText("學習目標一")).toBeTruthy();
    expect(screen.getByText("學習目標二")).toBeTruthy();
    expect(screen.getByText("學習目標三")).toBeTruthy();
  });

  it("已刪掉的永遠 disabled 採用按鈕不再出現", () => {
    renderTab(campaign());
    expect(screen.queryByText("採用流程將在下一步開放")).toBeNull();
    expect(screen.queryByText("採用策略（建立投放結構）")).toBeNull();
  });

  it("budget_planned 與 scenarios 都是 null：預算格印「尚未設定」，不印「累積中」", () => {
    const c = campaign();
    renderTab(
      campaign({
        budget_planned: null,
        budget_basis_json: { ...c.budget_basis_json, scenarios: undefined },
      }),
    );
    expect(screen.getByText("尚未設定")).toBeTruthy();
    expect(screen.queryByText("累積中")).toBeNull();
  });

  it("有一個投放組、一則廣告、還沒交棒：不出現「調整建議」收合，改印預算改在投放結構分頁；" +
     "主要按鈕是「前往投放結構 →」，按下去呼叫 onChangeTab(\"structure\")", async () => {
    const user = userEvent.setup();
    const { onChangeTab } = renderTab(
      campaign({ groups: [group({ ads: [ad()] })], asset_readiness: { ready_count: 0, total: 1 } }),
    );
    expect(screen.queryByRole("button", { name: "調整建議" })).toBeNull();
    expect(screen.getByText(/投放結構已經建立，預算改在投放結構分頁的每個投放組日預算。/)).toBeTruthy();
    const button = screen.getByRole("button", { name: "前往投放結構 →" });
    await user.click(button);
    expect(onChangeTab).toHaveBeenCalledWith("structure");
  });

  function campaignWithUnknownAmounts(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
    const c = campaign();
    return campaign({
      budget_scenario: null,
      context_json: { product_ids: ["prd_1"] },
      constraints_json: { budget: 28000 },
      budget_basis_json: {
        ...c.budget_basis_json,
        scenarios: {
          ...c.budget_basis_json.scenarios!,
          scenarios: c.budget_basis_json.scenarios!.scenarios.map((s) => ({ ...s, daily: null, total: null })),
        },
      },
      ...overrides,
    });
  }

  it("三個情境都算不出金額：按主要按鈕不打 API，展開自訂預算框並預填 constraints_json.budget", async () => {
    const user = userEvent.setup();
    const { onChangeTab } = renderTab(campaignWithUnknownAmounts());

    await user.click(screen.getByRole("button", { name: "先設定預算 →" }));

    expect(selectScenario).not.toHaveBeenCalled();
    expect(adoptStrategy).not.toHaveBeenCalled();
    expect(onChangeTab).not.toHaveBeenCalled();
    const input = screen.getByPlaceholderText("輸入自訂預算") as HTMLInputElement;
    expect(input.value).toBe("28000");
    expect(document.activeElement).toBe(input);
  });

  it("算不出金額時看得到補商品數字的提示與連到商品頁的連結", async () => {
    const user = userEvent.setup();
    renderTab(campaignWithUnknownAmounts());

    await user.click(screen.getByRole("button", { name: "先設定預算 →" }));

    expect(screen.getByText("要估金額需要商品的售價與成本")).toBeTruthy();
    const link = screen.getByRole("link", { name: "去補商品數字" });
    expect(link.getAttribute("href")).toContain("/products/");
  });

  it("budget_scenario 是 custom：主要按鈕直接 adoptStrategy，不重新 selectScenario", async () => {
    const user = userEvent.setup();
    vi.mocked(adoptStrategy).mockResolvedValue(campaign({ budget_scenario: "custom", groups: [group()] }));
    renderTab(campaignWithUnknownAmounts({ budget_scenario: "custom", budget_planned: 28000 }));

    await user.click(screen.getByRole("button", { name: "照這個方式進行 →" }));

    expect(adoptStrategy).toHaveBeenCalledWith("brd_1", "cmp_1");
    expect(selectScenario).not.toHaveBeenCalled();
  });

  it("status live、沒投放組：規則的答案是查看成效，不是採用；沒有「照這個方式進行 →」與「調整建議」", async () => {
    const user = userEvent.setup();
    const { onChangeTab } = renderTab(campaign({ status: "live", groups: [] }));

    const button = screen.getByRole("button", { name: "查看成效 →" });
    expect(screen.queryByRole("button", { name: "照這個方式進行 →" })).toBeNull();
    expect(screen.queryByRole("button", { name: "調整建議" })).toBeNull();

    await user.click(button);

    expect(onChangeTab).toHaveBeenCalledWith("performance");
  });
});
