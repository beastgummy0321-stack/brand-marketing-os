/** frontend/src/components/ads/StrategyTab.test.tsx — F04-I14: 策略分頁重做成一張建議卡
 * ＋一顆主要按鈕，其餘全部收在 Disclosure 裡（R9）。這支測試是「預設看不到進階內容」的
 * 機器證明，以及主要按鈕依 `budget_scenario` 走對 API 順序。 */
import type { ReactElement } from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import type { AdRow, CampaignDetail, DeliveryGroupRow } from "@/lib/adsApi";
import { adoptStrategy, selectScenario, patchCampaign, generateStrategy, getCampaign } from "@/lib/adsApi";
import { putTarget, type CapView } from "@/lib/adsTriageApi";
import { StrategyTab } from "./StrategyTab";

vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, putTarget: vi.fn() };
});

/** F28-I01: the one cost-per-result cap, as `campaign.cap` carries it. */
function cap(value: number | null, basis: CapView["basis"] = value === null ? null : "own"): CapView {
  return {
    value, basis, own_value: basis === "own" ? value : null, break_even: null, price: null,
    product_id: null, result_kind: "purchase", result_label: "購買", missing: [], revision: 0,
  };
}

function renderWithRouter(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return {
    ...actual,
    generateStrategy: vi.fn(),
    getCampaign: vi.fn(),
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
    cap: { value: null, basis: null, own_value: null, break_even: null, price: null, product_id: null, result_kind: "purchase", result_label: "購買", missing: ["product"], revision: 0 },
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
          { key: "minimum", label: "保守", daily: 1000, total: 15000, caption: "最低可行", over_cap: null },
          { key: "recommended", label: "推薦", daily: 2000, total: 30000, caption: "建議規模", over_cap: null },
          { key: "aggressive", label: "積極", daily: 3000, total: 45000, caption: "衝刺規模", over_cap: null },
        ],
        recommended: "recommended",
        basis: {},
        budget_cap: null,
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

  it("上限 300／30000：印「預估購買 100 筆」與推估說明；沒有上限時改印算不出推估購買", () => {
    const { rerender } = renderWithRouter(
      <StrategyTab
        brandId="brd_1"
        campaign={campaign({ cap: cap(300), budget_planned: 30000 })}
        onCampaignChange={vi.fn()}
        onChangeTab={vi.fn()}
      />,
    );
    expect(screen.getByText(/預估購買 100 筆/)).toBeTruthy();
    expect(screen.getByText("推估（每筆成本等於上限的算術）")).toBeTruthy();

    rerender(
      <MemoryRouter>
        <StrategyTab
          brandId="brd_1"
          campaign={campaign({ cap: cap(null), budget_planned: 30000 })}
          onCampaignChange={vi.fn()}
          onChangeTab={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByText(/預估購買/)).toBeNull();
    expect(screen.getByText("還沒有上限或總預算，算不出推估購買。")).toBeTruthy();
  });

  it("labels 是名單時：預估文字改印「名單」，不是寫死的「購買」", () => {
    renderTab(
      campaign({
        cap: cap(300), budget_planned: 30000,
        labels: { conversion: "名單", count: "名單數", cpa: "每筆名單成本" },
      }),
    );

    expect(screen.getByText(/預估名單 100 筆/)).toBeTruthy();
    expect(screen.queryByText(/預估購買/)).toBeNull();
  });

  it("labels 是名單時：上限輸入框印「每筆名單成本上限」，沒有指標下拉選單", async () => {
    const user = userEvent.setup();
    renderTab(
      campaign({
        cap: cap(300), budget_planned: 30000,
        labels: { conversion: "名單", count: "名單數", cpa: "每筆名單成本" },
      }),
    );

    await user.click(screen.getByRole("button", { name: "調整建議" }));
    await user.click(screen.getByRole("button", { name: "編輯" }));
    expect(screen.getByLabelText(/每筆名單成本上限/)).toBeTruthy();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("演練五：只輸入 450、其他都不動，存的就是每筆成本上限 450（PUT target，不是 ROAS）", async () => {
    const user = userEvent.setup();
    const refreshed = campaign({ cap: cap(450) });
    vi.mocked(putTarget).mockResolvedValue({ ...cap(450), campaign_id: "cmp_1", product_ids: [], result_kinds: [] });
    vi.mocked(getCampaign).mockResolvedValue(refreshed);
    const { onCampaignChange } = renderTab(campaign({ cap: { ...cap(null), revision: 2 } }));

    await user.click(screen.getByRole("button", { name: "調整建議" }));
    await user.click(screen.getByRole("button", { name: "編輯" }));
    await user.type(screen.getByLabelText(/成本上限/), "450");
    await user.click(screen.getByRole("button", { name: "儲存" }));

    expect(putTarget).toHaveBeenCalledWith("brd_1", "cmp_1", { basis: "own", value: 450, expected_revision: 2 });
    expect(patchCampaign).not.toHaveBeenCalled();
    expect(onCampaignChange).toHaveBeenCalledWith(refreshed);
  });

  it("上限只收大於 0 的整數：小數不能存", async () => {
    const user = userEvent.setup();
    renderTab(campaign());

    await user.click(screen.getByRole("button", { name: "調整建議" }));
    await user.click(screen.getByRole("button", { name: "編輯" }));
    await user.type(screen.getByLabelText(/成本上限/), "12.5");

    expect(screen.getByText("請輸入大於 0 的整數。")).toBeTruthy();
    expect(screen.getByRole("button", { name: "儲存" }).hasAttribute("disabled")).toBe(true);
  });

  it("上限是打平暫用值時印「暫用打平」", async () => {
    const user = userEvent.setup();
    renderTab(campaign({ cap: cap(600, "break_even") }));

    await user.click(screen.getByRole("button", { name: "調整建議" }));
    expect(screen.getByText("暫用打平 NT$ 600")).toBeTruthy();
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

  it("learning_goals 收在詳情，展開後空陣列與三條內容都如實顯示", async () => {
    const user = userEvent.setup();
    const c = campaign();
    const { rerender } = renderWithRouter(
      <StrategyTab brandId="brd_1" campaign={c} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} />,
    );
    expect(screen.queryByText("這一輪沒有設定學習目標")).toBeNull();

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
    await user.click(screen.getByRole("button", { name: "查看完整判斷" }));
    expect(screen.getByText("學習目標一")).toBeTruthy();
    expect(screen.getByText("學習目標二")).toBeTruthy();
    expect(screen.getByText("學習目標三")).toBeTruthy();
  });

  it("主要原因與學習目標收在完整判斷；影響判讀的未知直接顯示", async () => {
    const user = userEvent.setup();
    renderTab(campaign());
    expect(screen.getByText("新受眾的實際轉換率仍需驗證")).toBeTruthy();
    expect(screen.queryByText("主要原因")).toBeNull();
    expect(screen.queryByText("這一輪沒有設定學習目標")).toBeNull();
    await user.click(screen.getByRole("button", { name: "查看完整判斷" }));
    expect(screen.getByText("主要原因")).toBeTruthy();
    expect(screen.getByText("這一輪沒有設定學習目標")).toBeTruthy();
  });

  it("人工上架必填缺漏直接列出 entity 與欄位，按鈕只承諾前往投放結構", async () => {
    const user = userEvent.setup();
    const { onChangeTab } = renderTab(campaign({
      manual_handoff: {
        fields: [], pending_count: 1,
        groups: [{ id: "grp_1", name: "新客組", values: {}, missing: ["版位", "歸因期間"],
          status: "待補", saved_at: null, saved_by: null, ads: [] }],
      },
    }));
    expect(screen.getByText("新客組：版位、歸因期間")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "前往投放結構補齊" }));
    expect(onChangeTab).toHaveBeenCalledWith("structure");
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

    expect(screen.getByText(/要估金額需要上限與活動期間/)).toBeTruthy();
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


it("shows the current cap, preserves selected money and labels scenarios beyond the budget cap", async () => {
  const c = campaign({ cap: cap(300), budget_planned: 14700, budget_scenario: "recommended",
    start_date: "2026-09-01", end_date: "2026-09-14", constraints_json: { budget: 15000 } });
  if (!c.budget_basis_json.scenarios) throw new Error("scenario fixture missing");
  c.budget_basis_json.scenarios.scenarios = [
    { key: "minimum", label: "最低", daily: 600, total: 8400, caption: "CPA × 2", over_cap: 0 },
    { key: "recommended", label: "推薦", daily: 1500, total: 21000, caption: "CPA × 5", over_cap: 6000 },
    { key: "aggressive", label: "積極", daily: 3000, total: 42000, caption: "CPA × 10", over_cap: 27000 },
  ];
  c.budget_basis_json.scenarios.budget_cap = 15000;
  renderTab(c);
  await userEvent.click(screen.getByRole("button", { name: "調整建議" }));
  expect(screen.getByText(/計算依據：目前上限 NT\$ 300/).textContent).toContain("14 天");
  expect(screen.getByText(/已選預算.*14,700/)).toBeTruthy();
  expect(screen.getAllByText(/超過預算上限/)).toHaveLength(2);
});


it("keeps imported strategy in the existing disclosures and saves only the internal goal", async () => {
  vi.clearAllMocks();
  const user = userEvent.setup();
  const imported = campaign({origin: "imported", groups: [], budget_basis_json: {}});
  const changed = vi.fn();
  vi.mocked(patchCampaign).mockResolvedValue({...imported, goal_text: "內部管理目標"});
  renderWithRouter(<StrategyTab brandId="brd_1" campaign={imported} onCampaignChange={changed} onChangeTab={vi.fn()} />);
  expect(screen.getByText("這個 Campaign 尚無內部策略建議")).toBeTruthy();
  await user.click(screen.getByText("調整建議"));
  expect(screen.getByRole("button", {name: "產生策略"}).hasAttribute("disabled")).toBe(true);
  await user.click(screen.getByText("進階設定"));
  await user.clear(screen.getByLabelText("內部活動目標"));
  await user.type(screen.getByLabelText("內部活動目標"), "內部管理目標");
  await user.click(screen.getByRole("button", {name: "儲存目標"}));
  expect(patchCampaign).toHaveBeenCalledWith("brd_1", imported.id, {goal_text: "內部管理目標", objective: "內部管理目標"});
  expect(changed).toHaveBeenCalled();
  expect(generateStrategy).not.toHaveBeenCalled();
  expect(adoptStrategy).not.toHaveBeenCalled();
  expect(selectScenario).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", {name: "編輯上限"}));
  expect(screen.getByLabelText(/成本上限/)).toBeTruthy();
});

it("opens an imported campaign whose goal was never set", async () => {
  const imported = campaign({origin: "imported", groups: [], budget_basis_json: {}, goal_text: null});
  renderWithRouter(<StrategyTab brandId="brd_1" campaign={imported} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} />);
  await userEvent.setup().click(screen.getByText("進階設定"));
  expect((screen.getByLabelText("內部活動目標") as HTMLTextAreaElement).value).toBe("");
});
