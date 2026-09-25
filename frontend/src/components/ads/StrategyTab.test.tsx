/** frontend/src/components/ads/StrategyTab.test.tsx — F28-I09: the strategy tab is 一個上限 → 這一期的總預算 → 預算怎麼分
 * → two folds, with one bottom bar. These tests pin the bar's order of precedence (open over-cap sheet > unsaved pick >
 * adopt > the workspace's next step), that nothing is chosen or saved for the user, and the imported campaign's shape. */
import type { ReactElement } from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import type { BudgetScenarioRow, CampaignDetail, DeliveryGroupRow } from "@/lib/adsApi";
import { adoptStrategy, patchCampaign, selectScenario } from "@/lib/adsApi";
import { getTriage, type CapView } from "@/lib/adsTriageApi";
import { StrategyTab } from "./StrategyTab";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return {
    ...actual, generateStrategy: vi.fn(), getCampaign: vi.fn(), patchCampaign: vi.fn(), selectScenario: vi.fn(),
    setAllocation: vi.fn(), adoptStrategy: vi.fn(), setBudgetCap: vi.fn(),
  };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, putTarget: vi.fn(), getTarget: vi.fn(), getTriage: vi.fn() };
});

function cap(value: number | null, basis: CapView["basis"] = value === null ? null : "own", extra: Partial<CapView> = {}): CapView {
  return {
    value, basis, own_value: basis === "own" ? value : null, break_even: null, price: null,
    product_id: null, result_kind: "purchase", result_label: "購買", missing: value === null ? ["product_cost"] : [], revision: 0, ...extra,
  };
}

/** Cold start, cap 450, 31 days, budget cap 30,000 — the API's own rows (`budget._with_budget_cap`). */
const ROWS: BudgetScenarioRow[] = [
  { key: "minimum", label: "最低", daily: 900, total: 27900, caption: "冷啟動估算：上限 x 每天 2 筆購買", over_cap: 0 },
  { key: "cap", label: "照預算上限", daily: 968, total: 30000, caption: "用滿你設的預算上限 NT$30,000", over_cap: 0 },
  { key: "recommended", label: "穩定成長", daily: 2250, total: 69750, caption: "冷啟動估算：上限 x 每天 5 筆購買", over_cap: 39750 },
  { key: "aggressive", label: "積極", daily: 4500, total: 139500, caption: "冷啟動估算：上限 x 每天 10 筆購買", over_cap: 109500 },
];

function group(): DeliveryGroupRow {
  return {
    id: "grp_1", campaign_id: "cmp_1", channel_key: "meta", name: "投放組", role: "new", daily_budget: 1000, start_date: null,
    end_date: null, ads: [], external_id: null, external_name: null, external_status: null, local_state: "unbound", bound_at: null,
  };
}

function campaign(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    id: "cmp_1", name: "日常商品推廣・轉換", goal_text: "通勤族保溫杯", objective: "購買", cap: cap(450),
    start_date: "2026-09-08", end_date: "2026-10-08", status: "draft", budget_planned: null, budget_scenario: null,
    budget_basis_json: {
      strategy: {
        allocation: [
          { role: "new", label: "新客", pct: 60, rationale: null, amount: null },
          { role: "retarget", label: "再行銷", pct: 30, rationale: null, amount: null },
          { role: "explore", label: "探索", pct: 10, rationale: null, amount: null },
        ],
        why: ["新客比例高：通勤情境近 30 天在新客的每筆成本最低"], unknowns: ["新受眾的實際轉換率仍需驗證"], alternatives: [], learning_goals: [],
      },
      scenarios: { mode: "cold_start", scenarios: ROWS, recommended: "cap", basis: {}, budget_cap: 30000 },
      basis: { knowledge_item_ids: [], llm_task_id: "t", input_context_hash: "h", brand_facts: [], prices: [], learnings: [], estimated_fields: [] },
    },
    budget_total: null, context_json: {}, constraints_json: { budget: 30000 }, verdict: null, verdict_json: {}, closed_at: null,
    created_by: null, created_at: "2026-09-01T00:00:00Z", groups: [], actions: [], outcome: { spend: 0, purchases: 0, revenue: 0 },
    asset_readiness: { ready_count: 0, total: 0 }, external_id: null, external_name: null, external_status: null,
    local_state: "unbound", bound_at: null, ...overrides,
  } as CampaignDetail;
}

function renderTab(c: CampaignDetail) {
  const onCampaignChange = vi.fn();
  const onChangeTab = vi.fn();
  const ui: ReactElement = <StrategyTab brandId="brd_1" campaign={c} onCampaignChange={onCampaignChange} onChangeTab={onChangeTab} />;
  return { onCampaignChange, onChangeTab, ...render(<MemoryRouter>{ui}</MemoryRouter>) };
}

const bar = () => screen.getByRole("button", { name: /照這個方式進行|儲存預算|查看成效|安排自帶素材|前往/ });

describe("StrategyTab (F28-I09)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTriage).mockResolvedValue({ window_days: 14, items: [], closed: { paused: 0, archived: 0, other: 0, total: 0, items: [], truncated: false } });
  });

  it("shows the three cards in prototype order; the folds start closed", async () => {
    renderTab(campaign());
    const headings = (await screen.findAllByRole("heading", { level: 2 })).map((h) => h.textContent);
    expect(headings).toEqual(["一個上限", "這一期的總預算", "預算怎麼分"]);
    for (const label of ["為什麼是這幾個數字", "自己填總額", "為什麼這樣建議", "進階設定"]) {
      expect(screen.getByRole("button", { name: label }).getAttribute("aria-expanded")).toBe("false");
    }
  });

  it("nothing is preselected: no row is checked and adopting waits for a budget the user chose", async () => {
    renderTab(campaign());
    await screen.findByText("一個上限");
    expect(screen.getAllByRole("radio").every((r) => r.getAttribute("aria-checked") === "false")).toBe(true);
    expect(bar().textContent).toBe("照這個方式進行 →");
    expect(bar().hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("先選一個預算")).toBeTruthy();
    expect(screen.getByText("選好預算後算金額")).toBeTruthy();
    expect(selectScenario).not.toHaveBeenCalled();
  });

  it("no cap: adopting waits for the cap first", async () => {
    renderTab(campaign({ cap: cap(null), budget_planned: 30000, budget_scenario: "cap" }));
    await screen.findByText("先設上限");
    expect(bar().hasAttribute("disabled")).toBe(true);
  });

  it("an in-cap pick is saved by the bar as the user's choice, then adopting is the next action", async () => {
    const user = userEvent.setup();
    const saved = campaign({ budget_planned: 27900, budget_scenario: "minimum" });
    vi.mocked(selectScenario).mockResolvedValue(saved);
    const { onCampaignChange } = renderTab(campaign());
    await user.click(await screen.findByRole("radio", { name: /最低/ }));
    expect(screen.getByRole("radio", { name: /最低/ }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("以 27,900 計")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "儲存預算 27,900" }));
    expect(selectScenario).toHaveBeenCalledWith("brd_1", "cmp_1", { scenario_key: "minimum", custom_total: null });
    expect(onCampaignChange).toHaveBeenCalledWith(saved);
  });

  it("an over-cap row opens the confirm sheet, the bar's save stays disabled, and confirming sends confirm_over_cap", async () => {
    const user = userEvent.setup();
    const saved = campaign({ budget_planned: 69750, budget_scenario: "recommended" });
    vi.mocked(selectScenario).mockResolvedValue(saved);
    renderTab(campaign({ budget_planned: 30000, budget_scenario: "cap" }));
    await user.click(await screen.findByRole("radio", { name: /穩定成長/ }));
    const sheet = await screen.findByRole("alertdialog");
    expect(sheet.textContent).toContain("選「穩定成長 69,750」會超出預算上限 39,750 元");
    expect(screen.getByRole("button", { name: "儲存預算" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("先在上方確認要不要超出預算上限")).toBeTruthy();
    // The over-cap row is not picked while the sheet is open; the saved row stays the checked one.
    expect(screen.getByRole("radio", { name: /照預算上限/ }).getAttribute("aria-checked")).toBe("true");
    expect(document.activeElement?.textContent).toBe("維持 30,000");
    await user.click(screen.getByRole("button", { name: "超出預算上限也要用" }));
    expect(selectScenario).toHaveBeenCalledWith("brd_1", "cmp_1", { scenario_key: "recommended", custom_total: null }, { confirmOverCap: true });
  });

  it("維持 closes the sheet without saving anything", async () => {
    const user = userEvent.setup();
    renderTab(campaign({ budget_planned: 30000, budget_scenario: "cap" }));
    await user.click(await screen.findByRole("radio", { name: /積極/ }));
    await user.click(await screen.findByRole("button", { name: "維持 30,000" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(selectScenario).not.toHaveBeenCalled();
  });

  it("adopt: saved budget + cap → adoptStrategy, then the structure tab", async () => {
    const user = userEvent.setup();
    const adopted = campaign({ budget_planned: 30000, budget_scenario: "cap", groups: [group()] });
    vi.mocked(adoptStrategy).mockResolvedValue(adopted);
    const { onChangeTab } = renderTab(campaign({ budget_planned: 30000, budget_scenario: "cap" }));
    await user.click(await screen.findByRole("button", { name: "照這個方式進行 →" }));
    expect(adoptStrategy).toHaveBeenCalledWith("brd_1", "cmp_1");
    expect(selectScenario).not.toHaveBeenCalled();
    expect(onChangeTab).toHaveBeenCalledWith("structure");
  });

  it("after adoption the bar is the workspace's next step and the allocation is no longer editable", async () => {
    renderTab(campaign({ status: "live", budget_planned: 30000, budget_scenario: "cap", groups: [group()] }));
    expect((await screen.findByRole("button", { name: "查看成效 →" })).hasAttribute("disabled")).toBe(false);
    expect(screen.queryByRole("button", { name: "調整比例" })).toBeNull();
    expect(screen.getByText("以 30,000 計")).toBeTruthy();
  });

  it("history mode: the API's own labels and 推薦 are printed as sent", async () => {
    const c = campaign({ budget_planned: 30976, budget_scenario: "recommended" });
    c.budget_basis_json.scenarios = {
      mode: "history", recommended: "recommended", basis: {}, budget_cap: null,
      scenarios: [
        { key: "conservative", label: "保守", daily: 1162, total: 18592, caption: "上一期日預算 NT$1936 ×0.6", over_cap: null },
        { key: "recommended", label: "照上一期", daily: 1936, total: 30976, caption: "上一期日預算 NT$1936 ×1", over_cap: null },
        { key: "aggressive", label: "積極", daily: 3098, total: 49568, caption: "上一期日預算 NT$1936 ×1.6", over_cap: null },
      ],
    };
    renderTab(c);
    const row = await screen.findByRole("radio", { name: /照上一期/ });
    expect(row.getAttribute("aria-checked")).toBe("true");
    expect(row.textContent).toContain("推薦");
    expect(row.textContent).toContain("已儲存");
    expect(screen.getByText("沒設預算上限")).toBeTruthy();
    expect(screen.getByRole("button", { name: "設預算上限" })).toBeTruthy();
  });

  it("the why fold carries the reasons and unknowns", async () => {
    const user = userEvent.setup();
    renderTab(campaign());
    await user.click(await screen.findByRole("button", { name: "為什麼這樣建議" }));
    expect(screen.getByText("新客比例高：通勤情境近 30 天在新客的每筆成本最低")).toBeTruthy();
    expect(screen.getByText("新受眾的實際轉換率仍需驗證")).toBeTruthy();
  });

  it("imported: the cap block is shown, the budget and allocation cards are not, the internal goal saves", async () => {
    const user = userEvent.setup();
    const imported = campaign({ origin: "imported", budget_basis_json: {}, status: "live" });
    vi.mocked(patchCampaign).mockResolvedValue({ ...imported, goal_text: "內部管理目標" });
    const { onCampaignChange } = renderTab(imported);
    expect(await screen.findByText("一個上限")).toBeTruthy();
    expect(screen.queryByText("這一期的總預算")).toBeNull();
    expect(screen.queryByText("預算怎麼分")).toBeNull();
    expect(screen.queryByText("改預算上限")).toBeNull();
    expect(bar().textContent).toBe("安排自帶素材 →");
    await user.click(screen.getByRole("button", { name: "進階設定" }));
    await user.clear(screen.getByLabelText("內部活動目標"));
    await user.type(screen.getByLabelText("內部活動目標"), "內部管理目標");
    await user.click(screen.getByRole("button", { name: "儲存目標" }));
    expect(patchCampaign).toHaveBeenCalledWith("brd_1", "cmp_1", { goal_text: "內部管理目標", objective: "內部管理目標" });
    expect(onCampaignChange).toHaveBeenCalled();
    expect(selectScenario).not.toHaveBeenCalled();
  });

  it("no strategy yet: the cap block still shows above the generate empty state, and the bar offers no step", async () => {
    renderTab(campaign({ budget_basis_json: {} }));
    expect(await screen.findByText("這個活動還沒有策略建議")).toBeTruthy();
    expect(screen.getByText("一個上限")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /照這個方式進行/ })).toBeNull();
  });
});
