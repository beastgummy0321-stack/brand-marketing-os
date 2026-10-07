import type { LearningEvidence, LearningEvidenceContext } from "@/lib/adsLearningEvidence";

function learningEvidence(id = "learning-fixture"): LearningEvidence {
  return {
    schema_version: 1, id, meaning_revision: "meaning-fixture", display_text: "歷史紀錄",
    support_label: "來源尚未核實", provenance: "unknown",
    sources: [{kind: null, id: null, version: null, period: {start: null, end: null}, label: null}],
    scope: {product_id: null, product_label: null, audience_key: null, customer_group_id: null,
      claim_key: null, claim_family: null, objective_family: null, result_kind: null, currency: null, attribution: null},
    conditions: {price_version: null, offer_key: null, offer_version: null, material_version: null,
      target_version: null, valid_until: null},
    sample: {result_events: null, sufficient: null}, independent_count: 0, same_direction_count: 0,
    contrary_count: 0, use_state: "history", reason_codes: ["unknown_source"],
    reason_labels: ["來源尚未核實，保留為歷史"], allowed_uses: [], limits: ["conditions_unknown"],
  };
}
const evidenceContext: LearningEvidenceContext = {
  schema_version: 1, revision: "context-fixture", scope_product_id: null, scope_label: null,
  eligible_count: 0, items: [], omitted: 0,
};
vi.mock("@/lib/figures", async (actual) => ({ ...await actual<typeof import("@/lib/figures")>(), useFigureBases: () => ({roas_at_cap: {label: "花到上限時", formula: "售價 ÷ 每筆上限", unit: "ratio"}, roas_all_spend: {label: "保守", formula: "營收 ÷ 全部花費", unit: "ratio"}, roas_tracked_spend: {label: "樂觀", formula: "營收 ÷ 有追到營收的那部分花費", unit: "ratio"}}) }));
/** frontend/src/components/ads/StrategyTab.test.tsx — F28-I09: the strategy tab is 一個上限 → 這一期的總預算 → 這期怎麼安排
 * → two folds, with one bottom bar. These tests pin the bar's order of precedence (open over-cap sheet > unsaved pick >
 * adopt > the workspace's next step), that nothing is chosen or saved for the user, and the imported campaign's shape. */
import { ApiResponseError } from "@/lib/http";
import { useState, type ReactElement } from "react";
import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import type { AdsBudgetBasisJson, BudgetScenarioRow, CampaignDetail, DeliveryGroupRow, StrategyBasis } from "@/lib/adsApi";
import { adoptStrategy, generateStrategy, getCampaign, patchCampaign, selectScenario } from "@/lib/adsApi";
import { getTriage, type CapView } from "@/lib/adsTriageApi";
import type { CoordinateLearnings } from "@/lib/adsLearningsApi";
import { getLaunchSettings, type LaunchSettingsValues, type LaunchSettingsView } from "@/lib/adsLaunchSettingsApi";
import { StrategyTab } from "./StrategyTab";
import { strategyFixture } from "./strategy/strategyEvidence.fixtures";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return {
    ...actual, generateStrategy: vi.fn(), getCampaign: vi.fn(), patchCampaign: vi.fn(), selectScenario: vi.fn(),
    setAllocation: vi.fn(), adoptStrategy: vi.fn(), setBudgetCap: vi.fn(),
  };
});
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ brands: [], scope: "test" }) }));
vi.mock("@/lib/adsLaunchSettingsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsLaunchSettingsApi")>("@/lib/adsLaunchSettingsApi");
  return { ...actual, getLaunchSettings: vi.fn(), saveLaunchSettings: vi.fn() };
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
        decision: {schema_version: 1, revision: "displayed-revision", state: "proposed", slots: [
          {id: "slot-new", role: "new", customer_group_id: "students", offer_key: "free_shipping",
            carry_from_ad_id: null, test_intent: "測試通勤者的購買理由", rationale: "依登記事實提出假設，尚無投放樣本。", evidence_refs: [],
            display: {customer_group_label: "通勤者", offer_label: "免運：三盒以上免運", carried_ad_label: null, evidence: [], evidence_omitted: 0}},
        ],
          facts: {available: {customer_groups: 5, customer_group_names: ["健身者", "通勤者"]},
            proposed: {customer_groups: 1, delivery_groups: 1, ads: 1, customer_group_names: ["通勤者"], unknown_audience_ads: 0},
            actual: {customer_groups: 0, delivery_groups: 0, ads: 0, customer_group_names: [], unknown_audience_ads: 0}},
          feasibility: {state: "ready", reasons: []}},
        allocation: [
          { role: "new", label: "新客", pct: 60, rationale: null, amount: null },
          { role: "retarget", label: "再行銷", pct: 30, rationale: null, amount: null },
          { role: "explore", label: "探索", pct: 10, rationale: null, amount: null },
        ],
        why: ["新客比例高：通勤情境近 30 天在新客的每筆成本最低"], unknowns: ["新受眾的實際轉換率仍需驗證"], alternatives: [], learning_goals: [],
      },
      scenarios: { mode: "cold_start", scenarios: ROWS, recommended: "cap", basis: {}, budget_cap: 30000 },
      basis: { evidence_context: evidenceContext, knowledge_item_ids: [], llm_task_id: "t", input_context_hash: "h", brand_facts: [], prices: [], learnings: [], estimated_fields: [] },
    },
    budget_total: null, context_json: {}, constraints_json: { budget: 30000 }, verdict: null, verdict_json: {}, closed_at: null,
    created_by: null, created_at: "2026-09-01T00:00:00Z", groups: [], actions: [], outcome: { spend: 0, purchases: 0, revenue: 0 },
    asset_readiness: { ready_count: 0, total: 0 }, external_id: null, external_name: null, external_status: null,
    local_state: "unbound", bound_at: null, ...overrides,
  } as CampaignDetail;
}

function renderTab(c: CampaignDetail, launchApproved: boolean | null = false) {
  const onCampaignChange = vi.fn();
  const onChangeTab = vi.fn();
  const ui: ReactElement = <StrategyTab brandId="brd_1" campaign={c} onCampaignChange={onCampaignChange} onChangeTab={onChangeTab} launchApproved={launchApproved} />;
  return { onCampaignChange, onChangeTab, ...render(<MemoryRouter>{ui}</MemoryRouter>) };
}

const bar = () => screen.getByRole("button", { name: /確認策略，查看投放結構|儲存預算|下一步：素材/ });
const barEl = () => document.querySelector("[data-slot=action-bar]") as HTMLElement;

/** `GET …/launch-settings` in its real shape: recommended values, a two-pixel account. */
const VALUES: LaunchSettingsValues = {
  optimization_event: "purchase", bid_strategy: "lowest_cost", placement: { mode: "auto", positions: [] },
  audience: { age_min: 25, age_max: 54, gender: "all", countries: ["TW"] }, pixel_id: "px_4821", utm: "utm_source=meta&utm_campaign=daily",
};
const SETTINGS: LaunchSettingsView = {
  values: VALUES, recommended: VALUES, edited: [], errors: [],
  options: {
    optimization_event: [{ value: "purchase", label: "購買", note: "Meta 要幫你找哪種人：會買的人" }, { value: "add_to_cart", label: "加入購物車", note: "會放進購物車的人" }, { value: "initiate_checkout", label: "開始結帳", note: "會開始結帳的人" }, { value: "view_content", label: "內容瀏覽", note: "會點進來看的人" }],
    bid_strategy: [{ value: "lowest_cost", label: "最低成本", note: "讓 Meta 用最少的錢買到結果" }, { value: "cost_cap", label: "單次成果成本上限", note: "每筆盡量不超過你設的金額" }, { value: "bid_cap", label: "出價上限", note: "懂競價再用" }],
    positions: [{ value: "facebook_feed", label: "Facebook 動態", note: "" }],
    countries: [{ value: "TW", label: "台灣", note: "" }],
    pixels: [{ id: "px_4821", name: "晨光官網像素" }], pixels_error: null,
    placement_modes: [{ value: "auto", label: "自動版位", note: "讓 Meta 自己挑" }, { value: "manual", label: "手動", note: "自己選" }],
    genders: [{ value: "all", label: "不限", note: "" }], ages: [18, 25, 35, 45, 54, 65],
    field_notes: { audience: "年齡、性別、地區", pixel_id: "追蹤購買用", utm: "追蹤來源用" },
  },
};

describe("StrategyTab (F28-I09)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTriage).mockResolvedValue({ window_days: 14, items: [], closed: { groups: [], total: 0, items: [], truncated: false } });
  });

  it("shows the three cards in prototype order; the folds start closed", async () => {
    renderTab(campaign());
    const headings = (await screen.findAllByRole("heading", { level: 2 })).map((h) => h.textContent);
    expect(headings).toEqual(["這期策略", "這期怎麼安排", "為什麼這樣安排", "一個上限", "這一期的總預算"]);
    for (const label of ["為什麼是這幾個數字", "自己填總額", "為什麼這樣建議", "進階設定"]) {
      expect(screen.getByRole("button", { name: label }).getAttribute("aria-expanded")).toBe("false");
    }
  });

  it("nothing is preselected: no row is checked and adopting waits for a budget the user chose", async () => {
    renderTab(campaign());
    await screen.findByText("一個上限");
    expect(screen.getAllByRole("radio").every((r) => r.getAttribute("aria-checked") === "false")).toBe(true);
    expect(bar().textContent).toBe("確認策略，查看投放結構 →");
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

  it.each([0, -1])("a nonpositive cap (%s) never permits adoption", async (value) => {
    renderTab(campaign({cap: cap(value), budget_planned: 30000, budget_scenario: "cap"}));
    expect((await screen.findByRole("button", {name: "確認策略，查看投放結構 →"})).hasAttribute("disabled")).toBe(true);
    expect(within(barEl()).getByText("先設上限")).toBeTruthy();
  });

  it("an in-cap pick is saved by the bar as the user's choice, then adopting is the next action", async () => {
    const user = userEvent.setup();
    const saved = campaign({ budget_planned: 27900, budget_scenario: "minimum" });
    vi.mocked(selectScenario).mockResolvedValue({ campaign: saved, resplit: null });
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
    vi.mocked(selectScenario).mockResolvedValue({ campaign: saved, resplit: null });
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
    expect(await screen.findByText("確認後會建立以上安排；不會操作廣告平台。")).toBeTruthy();
    await user.click(await screen.findByRole("button", { name: "確認策略，查看投放結構 →" }));
    expect(adoptStrategy).toHaveBeenCalledWith("brd_1", "cmp_1", {
      expected_revision: "displayed-revision", operation_id: expect.any(String),
    });
    expect(selectScenario).not.toHaveBeenCalled();
    expect(onChangeTab).toHaveBeenCalledWith("structure");
  });

  it("an unknown network result retries the same displayed revision with the same operation", async () => {
    const user = userEvent.setup();
    vi.mocked(adoptStrategy).mockRejectedValue(new Error("Connection lost"));
    renderTab(campaign({ budget_planned: 30000, budget_scenario: "cap" }));
    await user.click(await screen.findByRole("button", { name: "確認策略，查看投放結構 →" }));
    await screen.findByText("Connection lost");
    await user.click(screen.getByRole("button", { name: "確認策略，查看投放結構 →" }));
    expect(adoptStrategy).toHaveBeenCalledTimes(2);
    expect(vi.mocked(adoptStrategy).mock.calls[0][2]).toEqual(vi.mocked(adoptStrategy).mock.calls[1][2]);
    expect(getCampaign).not.toHaveBeenCalled();
  });

  it("a displayed changed revision creates a new operation, without an implicit reread", async () => {
    const user = userEvent.setup();
    vi.mocked(adoptStrategy).mockRejectedValue(new Error("Connection lost"));
    const initial = campaign({ budget_planned: 30000, budget_scenario: "cap" });
    const callbacks = { onCampaignChange: vi.fn(), onChangeTab: vi.fn() };
    const view = render(<MemoryRouter><StrategyTab brandId="brd_1" campaign={initial} {...callbacks} launchApproved={false} /></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "確認策略，查看投放結構 →" }));
    await screen.findByText("Connection lost");
    const changed = { ...initial, budget_basis_json: { ...initial.budget_basis_json, strategy: {
      ...initial.budget_basis_json.strategy!, decision: { ...initial.budget_basis_json.strategy!.decision!, revision: "changed-revision" },
    } } };
    view.rerender(<MemoryRouter><StrategyTab brandId="brd_1" campaign={changed} {...callbacks} launchApproved={false} /></MemoryRouter>);
    await user.click(screen.getByRole("button", { name: "確認策略，查看投放結構 →" }));
    const first = vi.mocked(adoptStrategy).mock.calls[0][2];
    const second = vi.mocked(adoptStrategy).mock.calls[1][2];
    expect(second.expected_revision).toBe("changed-revision");
    expect(second.operation_id).not.toBe(first.operation_id);
    expect(getCampaign).not.toHaveBeenCalled();
  });

  it("a legacy unbound strategy cannot submit an empty approval", async () => {
    const user = userEvent.setup();
    const initial = campaign({ budget_planned: 30000, budget_scenario: "cap" });
    initial.budget_basis_json.strategy!.decision = undefined;
    renderTab(initial);
    expect((await screen.findByRole("button", { name: "確認策略，查看投放結構 →" })).hasAttribute("disabled")).toBe(true);
    vi.mocked(generateStrategy).mockResolvedValue(campaign());
    await user.click(screen.getByRole("button", { name: "重新產生策略" }));
    expect(generateStrategy).toHaveBeenCalledWith("brd_1", "cmp_1");
    expect(adoptStrategy).not.toHaveBeenCalled();
  });

  it("a blocked served decision keeps budget revision usable and cannot be adopted", async () => {
    const user = userEvent.setup();
    const c = campaign({ budget_planned: 30000, budget_scenario: "cap" });
    c.budget_basis_json.strategy!.decision!.feasibility = {state: "blocked", reasons: [
      {code: "capacity_exceeded", message: "目前預算無法容納這份安排，請調整預算或重新產生。", slot_ids: ["slot-new"]},
    ]};
    renderTab(c);
    expect((await screen.findByRole("button", { name: "確認策略，查看投放結構 →" })).hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("目前預算無法容納這份安排，請調整預算或重新產生。")).toBeTruthy();
    await user.click(screen.getByRole("radio", {name: /最低/}));
    expect(screen.getByRole("button", {name: "儲存預算 27,900"}).hasAttribute("disabled")).toBe(false);
    expect(adoptStrategy).not.toHaveBeenCalled();
  });

  it("modified rationale never re-enables adoption merely because feasibility is ready", async () => {
    const user = userEvent.setup();
    const c = campaign({ budget_planned: 30000, budget_scenario: "cap" });
    c.budget_basis_json.strategy!.decision!.state = "modified";
    c.budget_basis_json.strategy!.rationale_state = "stale";
    renderTab(c);
    expect((await screen.findByRole("button", {name: "確認策略，查看投放結構 →"})).hasAttribute("disabled")).toBe(true);
    expect(screen.getAllByText("安排或預算已修改，原建議理由已失效。請重新產生策略。").length).toBeGreaterThan(0);
    expect(screen.queryByText("依登記事實提出假設，尚無投放樣本。")).toBeNull();
    await user.click(screen.getByRole("button", {name: "為什麼這樣建議"}));
    expect(screen.getByText("原建議理由已失效；重新產生後再確認新安排。")).toBeTruthy();
  });

  it("shows each served binding and distinct server counts without pairing aggregate names", async () => {
    const user = userEvent.setup();
    const c = campaign({budget_planned: 30000, budget_scenario: "cap"});
    c.budget_basis_json.strategy!.decision!.slots.push({
      id: "slot-carry", role: "new", customer_group_id: "fitness", offer_key: "none", carry_from_ad_id: "original",
      test_intent: null, rationale: "保留相對有效的內容，仍需再驗證。", evidence_refs: [{kind: "result", id: "original"}],
      display: {customer_group_label: "健身者", offer_label: "不使用優惠", carried_ad_label: "健身原版",
        evidence: [{kind: "result", id: "original", label: "上期／健身原版"}], evidence_omitted: 0},
    });
    renderTab(c);
    await screen.findByText("通勤者");
    expect(screen.getByText("免運：三盒以上免運")).toBeTruthy();
    expect(screen.getByText("新提案仍待驗證，不代表已證明有效。")).toBeTruthy();
    const rows = Array.from(document.querySelectorAll("[data-slot=strategy-commitment]"));
    expect(rows[0].textContent).toContain("新測試：測試通勤者的購買理由");
    expect(rows[0].textContent).not.toContain("健身者");
    expect(rows[1].textContent).toContain("健身者");
    expect(within(rows[1] as HTMLElement).getByText("不使用優惠")).toBeTruthy();
    expect(rows[1].textContent).toContain("保留原廣告：健身原版");
    await user.click(screen.getByRole("button", {name: "為什麼這樣建議"}));
    expect(screen.getByText("依據：上期／健身原版")).toBeTruthy();
    const summary = document.querySelector("[data-slot=assignment-summary]")!;
    expect(summary.textContent).toContain("可選顧客群5 群");
    expect(summary.textContent).toContain("提議安排1 群・1 個投放組・1 則廣告");
    expect(summary.textContent).toContain("實際投放結構0 群・0 個投放組・0 則廣告");
    expect(getCampaign).not.toHaveBeenCalled();
  });

  it("unsaved allocation editing cannot adopt a revision the user has not applied", async () => {
    const user = userEvent.setup();
    renderTab(campaign({budget_planned: 30000, budget_scenario: "cap"}));
    await user.click(await screen.findByRole("button", {name: "調整比例"}));
    expect(bar().hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("先套用或取消比例調整")).toBeTruthy();
    expect(adoptStrategy).not.toHaveBeenCalled();
  });

  it("a server revision refusal stays blocked until a fresh displayed revision arrives", async () => {
    const user = userEvent.setup();
    vi.mocked(adoptStrategy).mockRejectedValue(new ApiResponseError("安排已更新，請重新確認。", 409, {}, {code: "strategy_changed"}));
    const c = campaign({budget_planned: 30000, budget_scenario: "cap"});
    const callbacks = {onCampaignChange: vi.fn(), onChangeTab: vi.fn()};
    const view = render(<MemoryRouter><StrategyTab brandId="brd_1" campaign={c} {...callbacks} launchApproved={false} /></MemoryRouter>);
    await user.click(await screen.findByRole("button", {name: "確認策略，查看投放結構 →"}));
    await screen.findByText("安排已更新，請重新確認。");
    expect(bar().hasAttribute("disabled")).toBe(true);
    view.rerender(<MemoryRouter><StrategyTab brandId="brd_1" campaign={{...c}} {...callbacks} launchApproved={false} /></MemoryRouter>);
    expect(bar().hasAttribute("disabled")).toBe(true);
    const fresh = campaign({budget_planned: 30000, budget_scenario: "cap"});
    fresh.budget_basis_json.strategy!.decision!.revision = "freshly-reviewed";
    view.rerender(<MemoryRouter><StrategyTab brandId="brd_1" campaign={fresh} {...callbacks} launchApproved={false} /></MemoryRouter>);
    expect(bar().hasAttribute("disabled")).toBe(false);
    expect(getCampaign).not.toHaveBeenCalled();
  });

  it("on a platform (live) the bar has no next step here and the allocation is no longer editable", async () => {
    renderTab(campaign({ status: "live", budget_planned: 30000, budget_scenario: "cap", groups: [group()] }));
    expect(await screen.findByText("以 30,000 計")).toBeTruthy();
    expect(barEl().textContent).toBe("← 總覽查看品牌學習");
    expect(screen.queryByRole("button", { name: "調整比例" })).toBeNull();
  });

  it("a draft after adoption: the bar says 下一步：素材 and opens the assets tab (v10 tabStrategy)", async () => {
    const user = userEvent.setup();
    const { onChangeTab } = renderTab(campaign({ budget_planned: 30000, budget_scenario: "cap", groups: [group()] }));
    await user.click(await screen.findByRole("button", { name: "下一步：素材 →" }));
    expect(onChangeTab).toHaveBeenCalledWith("assets");
  });

  it("a draft after adoption without a cap: 下一步：素材 waits for the cap", async () => {
    renderTab(campaign({ cap: cap(null), budget_planned: 30000, budget_scenario: "cap", groups: [group()] }));
    expect((await screen.findByRole("button", { name: "下一步：素材 →" })).hasAttribute("disabled")).toBe(true);
    expect(within(barEl()).getByText("先設上限")).toBeTruthy();
  });

  it("進階設定 holds the launch settings: editable on a draft whose launch is not approved; read only once approved or unknown", async () => {
    const user = userEvent.setup();
    vi.mocked(getLaunchSettings).mockResolvedValue(SETTINGS);
    const { unmount } = renderTab(campaign({ budget_planned: 30000, budget_scenario: "cap", groups: [group()] }), false);
    expect(getLaunchSettings).not.toHaveBeenCalled(); // folded content is not read before it is opened
    await user.click(await screen.findByRole("button", { name: "進階設定" }));
    const select = await screen.findByLabelText(/出價方式/);
    expect(select.matches(":disabled")).toBe(false);
    expect(screen.getByRole("button", { name: "前往人工上架設定" })).toBeTruthy();
    unmount();
    for (const approved of [true, null]) {
      const view = renderTab(campaign({ budget_planned: 30000, budget_scenario: "cap", groups: [group()] }), approved);
      await user.click(await screen.findByRole("button", { name: "進階設定" }));
      expect((await screen.findByLabelText(/出價方式/)).matches(":disabled")).toBe(true);
      view.unmount();
    }
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

  describe("F41-I04: reasons per role and the learnings the plan used (prototype f41-drill8 ②)", () => {
    /** Realistic shapes: three roles with one null rationale; amounts the API split from the saved 30,000. */
    function withReasons(basis: Partial<StrategyBasis> = {}): CampaignDetail {
      const c = campaign({ budget_planned: 30000, budget_scenario: "cap" });
      const json = c.budget_basis_json as AdsBudgetBasisJson;
      json.basis = { ...json.basis, ...basis };
      json.strategy.allocation = [
        { role: "new", label: "新客", pct: 60, rationale: "沿用上一期划算的「高強度日程中的輕鬆準備」，新客預算大多給它。", amount: 18000 },
        { role: "retarget", label: "再行銷", pct: 30, rationale: null, amount: 9000 },
        { role: "explore", label: "探索", pct: 10, rationale: "試「三盒 NT$999 另送一盒」，看優惠拉不拉得動新客。", amount: 3000 },
      ];
      return c;
    }
    const LONG_AD = "高強度日程中的輕鬆準備・通勤族上班前三十秒就能完成的每日營養補給方案（第二版）";
    const COORD = [
      {
        grade: "on_target" as const, grade_label: "划算", cost_per_result: 421.6, ad_name: LONG_AD, campaign_name: "綜合維他命軟糖・10/03～10/09",
        coordinates: [{ dimension: "audience", dimension_label: "受眾", label: "陌生、知道問題" }, { dimension: "effort", dimension_label: "痛點", label: "太麻煩" }],
      },
      {
        grade: "over" as const, grade_label: "太貴", cost_per_result: null, ad_name: "考前一週的安心", campaign_name: "綜合維他命軟糖・10/03～10/09",
        coordinates: [{ dimension: "format", dimension_label: "格式", label: "輪播" }],
      },
    ];
    const VERDICT = { id: "lrn_1", text: "綜合維他命軟糖：新客在通勤情境划算", level: "product", evidence: {...learningEvidence("lrn_1"), display_text: "綜合維他命軟糖：新客在通勤情境划算"}, needs_revalidation: false };

    it("each role row prints its percent, amount and the planner's reason; a null reason leaves no empty line", async () => {
      renderTab(withReasons());
      const rows = await screen.findAllByRole("listitem");
      const byRole = (role: string) => document.querySelector(`[data-slot=allocation-row][data-role=${role}]`) as HTMLElement;
      expect(rows.length).toBeGreaterThanOrEqual(3);
      expect(within(byRole("new")).getByText("60%")).toBeTruthy();
      expect(within(byRole("new")).getByText("18,000 元")).toBeTruthy();
      expect(within(byRole("new")).getByText("沿用上一期划算的「高強度日程中的輕鬆準備」，新客預算大多給它。")).toBeTruthy();
      expect(byRole("retarget").textContent).toBe("再行銷30%9,000 元");
      expect(byRole("retarget").querySelector("p")).toBeNull();
      expect(within(byRole("explore")).getByText("試「三盒 NT$999 另送一盒」，看優惠拉不拉得動新客。")).toBeTruthy();
      // The bar is the thin one: no legend line repeating the rows.
      expect(document.querySelector("[data-slot=allocation-bar]")).toBeNull();
    });

    it("F48 Contract M: each row prints the payload's own amount — never total × pct priced in the browser", async () => {
      const c = withReasons();
      // The API's split of 30,001 (`budget.split`): 18,001／9,000／3,000 — not round(30,001 × pct).
      c.budget_planned = 30001;
      c.budget_basis_json.strategy!.allocation = c.budget_basis_json.strategy!.allocation.map((item) => ({
        ...item, amount: { new: 18001, retarget: 9000, explore: 3000 }[item.role],
      }));
      renderTab(c);
      const byRole = (role: string) => document.querySelector(`[data-slot=allocation-row][data-role=${role}]`) as HTMLElement;
      expect((await screen.findByText("以 30,001 計"))).toBeTruthy();
      expect(within(byRole("new")).getByText("18,001 元")).toBeTruthy();
      expect(within(byRole("retarget")).getByText("9,000 元")).toBeTruthy();
      expect(within(byRole("explore")).getByText("3,000 元")).toBeTruthy();
    });

    it("an unsaved pick is not priced in the browser: the rows print the percent only until it is saved", async () => {
      const user = userEvent.setup();
      renderTab(withReasons());
      await user.click(await screen.findByRole("radio", { name: /最低/ }));
      expect(screen.getByText("以 27,900 計")).toBeTruthy();
      const row = document.querySelector("[data-slot=allocation-row][data-role=new]") as HTMLElement;
      expect(row.textContent).toContain("60%");
      expect(row.textContent).not.toContain("元");
    });

    it("F48 Contract S: the program's facts print as one list above the model's prose, each under its lead word", async () => {
      const user = userEvent.setup();
      const c = withReasons();
      c.budget_basis_json.strategy!.facts = [
        { kind: "groups", text: "這期打 2 群：學生備考、通勤上班族" },
        { kind: "offers", text: "可用的優惠：〈折扣特價〉優惠價 NT$999（原價 NT$1,500）" },
        { kind: "numbers", text: "上限每筆 450；上一期最好的是「考前一週」每筆 392（賣出 6 筆）；已結案 2 期" },
        { kind: "capacity", text: "這期每天 1,500，撐得起 3 則（另加 1 則探索）；最多 4 則（上限每筆 450）" },
        { kind: "learnings", text: "讀了上幾期的排名：留下 2 則、換掉 1 則；過去的學習 3 條" },
      ];
      renderTab(c);
      await user.click(await screen.findByRole("button", { name: "為什麼這樣建議" }));
      const list = document.querySelector("[data-slot=strategy-facts]") as HTMLElement;
      const rows = Array.from(list.querySelectorAll("li"));
      expect(rows.map((li) => li.getAttribute("data-kind"))).toEqual(["groups", "offers", "numbers", "capacity", "learnings"]);
      expect(rows.map((li) => li.querySelector("span")?.textContent)).toEqual(["顧客群", "優惠", "數字", "預算", "學習"]);
      expect(rows[2].textContent).toContain("上一期最好的是「考前一週」每筆 392（賣出 6 筆）");
      const prose = screen.getByText("新客比例高：通勤情境近 30 天在新客的每筆成本最低");
      expect(list.compareDocumentPosition(prose) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("before a budget is chosen the rows print only the percent, even though generating filled `amount`", async () => {
      const c = withReasons();
      c.budget_planned = null;
      c.budget_scenario = null;
      renderTab(c);
      expect(await screen.findByText("選好預算後算金額")).toBeTruthy();
      const row = document.querySelector("[data-slot=allocation-row][data-role=new]") as HTMLElement;
      expect(row.textContent).toContain("60%");
      expect(row.textContent).not.toContain("元");
    });

    it("用到的學習 in the why fold: grade chip with its cost, 「ad」（period）, Chinese coordinate chips, never a raw key", async () => {
      const user = userEvent.setup();
      renderTab(withReasons({ coordinate_learnings: COORD, learnings: [VERDICT] }));
      await user.click(await screen.findByRole("button", { name: "為什麼這樣建議" }));
      const [good, bad] = screen.getAllByRole("listitem").filter((li) => li.getAttribute("data-slot") === "coordinate-learning");
      expect(within(good).getByText("划算・每筆 422").getAttribute("data-tone")).toBe("ok"); // F47-I06: 421.6 rounds (one per-sale rule), never floors
      expect(good.textContent).toContain(`「${LONG_AD}」（綜合維他命軟糖・10/03～10/09）`);
      expect(within(good).getByText("受眾：陌生、知道問題")).toBeTruthy();
      expect(within(good).getByText("痛點：太麻煩")).toBeTruthy();
      expect(good.textContent).not.toMatch(/effort|audience/);
      expect(within(bad).getByText("太貴・每筆 —").getAttribute("data-tone")).toBe("over");
      // 策略依據 lists what the model read: the coordinate rows, then the surviving verdict line.
      await user.click(screen.getByRole("button", { name: /查看策略依據/ }));
      const panel = screen.getByRole("dialog", { name: "策略依據" });
      expect(within(panel).getByText("划算・每筆 422")).toBeTruthy();
      expect(within(panel).getByText(VERDICT.text)).toBeTruthy();
      expect(within(panel).getByText("這份安排尚未列出已核實的學習引用。")).toBeTruthy();
    });

    it("a strategy from before F41 (no coordinate_learnings) shows the verdict lines only", async () => {
      const user = userEvent.setup();
      renderTab(withReasons({ learnings: [VERDICT] }));
      await user.click(await screen.findByRole("button", { name: "為什麼這樣建議" }));
      expect(screen.queryByRole("heading", { name: "原活動排名與觀察" })).toBeNull();
      await user.click(screen.getByRole("button", { name: /查看策略依據/ }));
      const panel = screen.getByRole("dialog", { name: "策略依據" });
      expect(panel.querySelector("[data-slot=coordinate-learning]")).toBeNull();
      expect(within(panel).getByText(VERDICT.text)).toBeTruthy();
    });

    it("no learnings of either kind: the panel keeps today's empty line", async () => {
      const user = userEvent.setup();
      renderTab(withReasons());
      await user.click(await screen.findByRole("button", { name: "為什麼這樣建議" }));
      await user.click(screen.getByRole("button", { name: /查看策略依據/ }));
      expect(within(screen.getByRole("dialog", { name: "策略依據" })).getByText("這份安排尚未列出已核實的學習引用。")).toBeTruthy();
    });

    // F46-I07 (prototype f46-learnings `#/strategy`): a strategy made since F46 stores the Contract L view it was
    // prompted with as `basis.ranked_learnings`; the panel and the why fold show that ranking, not the F41 rows.
    const RANKED: CoordinateLearnings = {
      evidence_context: evidenceContext, campaigns: [{
        campaign_id: "adc_B", campaign_name: "三盒組・09/19～10/01", sell_way_id: "prd_box",
        start_date: "2026-09-19", end_date: "2026-10-01", closed_on: "2026-10-02", cap: 450, currency: "TWD",
        spend: 9781, sales: 13, cost_per_sale: 752.4, counts: { keep: 2, replace: 1 },
        rule_text: "沒有一則低於上限 450 → 留下最好的 555 和 721 以內的；其餘換掉", empty_reason: null,
        rows: [
          { rank: 1, of: 3, ad_id: "ada_b1", ad_name: "考前一週・書包一盒", customer_group: { id: "pcg_study", who: "學生備考" },
            coordinates: [{ dimension: "angle", dimension_label: "角度", key: "box", label: "書包裡放一盒就好" }],
            spend: 2775, sales: 5, cost_per_sale: 555, verdict: "keep_relative", verdict_label: "留下", flags: ["相對最好，仍高於上限"], evidence: learningEvidence(), learning_id: "lrn_b1" },
          { rank: 2, of: 3, ad_id: "ada_b2", ad_name: "通勤族・地鐵十分鐘", customer_group: { id: "pcg_commute", who: "通勤上班族" },
            coordinates: [], spend: 3720, sales: 6, cost_per_sale: 620, verdict: "keep_relative", verdict_label: "留下", flags: ["相對最好，仍高於上限"], evidence: learningEvidence(), learning_id: "lrn_b2" },
          { rank: 3, of: 3, ad_id: "ada_b3", ad_name: "通勤族・下班後加班", customer_group: { id: "pcg_commute", who: "通勤上班族" },
            coordinates: [], spend: 3286, sales: 2, cost_per_sale: 1643, verdict: "replace", verdict_label: "換掉", flags: ["樣本少"], evidence: learningEvidence(), learning_id: "lrn_b3" },
        ],
      }, {
        campaign_id: "adc_A", campaign_name: "三盒組・09/05～09/18", sell_way_id: "prd_box",
        start_date: "2026-09-05", end_date: "2026-09-18", closed_on: "2026-09-19", cap: 450, currency: "TWD",
        spend: 1160, sales: 4, cost_per_sale: 290, counts: { keep: 1, replace: 0 },
        rule_text: "1 則每筆低於上限 450 → 留下；其餘換掉", empty_reason: null,
        rows: [
          { rank: 1, of: 1, ad_id: "ada_a1", ad_name: "備考生・讀到深夜", customer_group: { id: "pcg_study", who: "學生備考" },
            coordinates: [], spend: 1160, sales: 4, cost_per_sale: 290, verdict: "keep", verdict_label: "留下", flags: ["樣本少"], evidence: learningEvidence(), learning_id: "lrn_a1" },
        ],
      }],
      groups: [
        { customer_group_id: "pcg_study", who: "學生備考", ads: 2, spend: 3935, sales: 9, cap: 450, cost_per_sale: 437.2 },
        { customer_group_id: "pcg_commute", who: "通勤上班族", ads: 2, spend: 7006, sales: 8, cap: 450, cost_per_sale: 875.75 },
      ],
      next: { sell_way_id: "prd_box", new_campaign_href: "/brands/brd_1/ads/new?sell_way=prd_box" },
    };

    it("ranked_learnings: the panel says it is the library's ranking, then group summary, compact tables per campaign and the full-table link", async () => {
      const user = userEvent.setup();
      renderTab(withReasons({ ranked_learnings: RANKED, learnings: [] }));
      await user.click(await screen.findByRole("button", { name: "為什麼這樣建議" }));
      await user.click(screen.getByRole("button", { name: /查看策略依據/ }));
      const panel = screen.getByRole("dialog", { name: "策略依據" });
      // Actual citations and unused inputs precede the preserved original ranking and brand/price facts.
      expect(within(panel).getAllByRole("heading", { level: 4 }).map((h) => h.textContent)).toEqual(["用到的學習", "未用於提案的資料", "原活動排名與觀察", "品牌事實", "商品價格"]);
      expect(within(panel).getByText("和品牌智庫「投放學到的」同一份排名")).toBeTruthy();
      const groups = within(panel).getByRole("list", { name: "各顧客群每筆成本" });
      expect(within(groups).getAllByRole("listitem").map((li) => li.getAttribute("data-group"))).toEqual(["pcg_study", "pcg_commute"]);
      const b = within(panel).getByRole("table", { name: "三盒組・09/19～10/01 每則廣告排名" });
      expect(within(b).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["#", "廣告｜顧客群", "每筆", "判定", "座標"]);
      const rowsB = within(b).getAllByRole("row").slice(1);
      expect(rowsB.map((r) => r.getAttribute("data-ad"))).toEqual(["ada_b1", "ada_b2", "ada_b3"]);
      expect(within(rowsB[2]).getByText("1,643")).toBeTruthy();
      expect(within(rowsB[2]).getByText("換掉")).toBeTruthy();
      expect(within(panel).getByRole("table", { name: "三盒組・09/05～09/18 每則廣告排名" })).toBeTruthy();
      expect(within(panel).getByRole("link", { name: "到品牌智庫看完整表 →" }).getAttribute("href")).toBe("/brands/brd_1/library?tab=ads-learnings");
      expect(panel.querySelector("[data-slot=coordinate-learning]")).toBeNull();
      expect(within(panel).getByText("這份安排尚未列出已核實的學習引用。")).toBeTruthy();
    });

    it("the why fold follows the same rule: ranked_learnings → the same ranking; it wins over old coordinate_learnings", async () => {
      const user = userEvent.setup();
      renderTab(withReasons({ ranked_learnings: RANKED, coordinate_learnings: COORD }));
      await user.click(await screen.findByRole("button", { name: "為什麼這樣建議" }));
      const section = screen.getByRole("heading", { name: "原活動排名與觀察" }).closest("section") as HTMLElement;
      expect(within(section).getByText("和品牌智庫「投放學到的」同一份排名")).toBeTruthy();
      expect(within(section).getByRole("table", { name: "三盒組・09/19～10/01 每則廣告排名" })).toBeTruthy();
      expect(section.querySelector("[data-slot=coordinate-learning]")).toBeNull();
    });

    it("an empty ranked view (nothing closed yet) shows no learnings section and the panel's empty line", async () => {
      const user = userEvent.setup();
      renderTab(withReasons({ ranked_learnings: { evidence_context: evidenceContext, campaigns: [], groups: [], next: null } }));
      await user.click(await screen.findByRole("button", { name: "為什麼這樣建議" }));
      expect(screen.queryByRole("heading", { name: "原活動排名與觀察" })).toBeNull();
      await user.click(screen.getByRole("button", { name: /查看策略依據/ }));
      expect(within(screen.getByRole("dialog", { name: "策略依據" })).getByText("這份安排尚未列出已核實的學習引用。")).toBeTruthy();
    });

    it("brand facts print 「MM/DD 更新」 on the org calendar and prices 〈sell way〉 〈price〉・〈MM/DD〉 起 — never a raw ISO string", async () => {
      const user = userEvent.setup();
      renderTab(withReasons({
        brand_facts: [
          // 17:30 UTC on 09/11 is already 09/12 in Taipei (the org default).
          { id: "bfa_1", label: "每顆含 50mg 咖啡因", updated_at: "2026-09-11T17:30:00.123456+00:00" },
          { id: "bfa_2", label: "顧客原話「比排咖啡快」", updated_at: "2026-09-20T03:00:00+00:00" },
        ],
        prices: [
          { product_id: "prd_box", price: 999, effective_from: "2026-09-01", stale: false, assumptions: [], sell_way_name: "三盒組" },
          { product_id: "prd_one", price: null, effective_from: null, stale: false, assumptions: [], sell_way_name: "單盒" },
        ],
      }));
      await user.click(await screen.findByRole("button", { name: "為什麼這樣建議" }));
      await user.click(screen.getByRole("button", { name: /查看策略依據/ }));
      const panel = screen.getByRole("dialog", { name: "策略依據" });
      const facts = Array.from(panel.querySelectorAll("[data-slot=basis-fact]")).map((li) => li.textContent);
      expect(facts).toEqual(["每顆含 50mg 咖啡因09/12 更新", "顧客原話「比排咖啡快」09/20 更新"]);
      const prices = Array.from(panel.querySelectorAll("[data-slot=basis-price]")).map((li) => li.textContent);
      expect(prices).toEqual(["三盒組 999 TWD09/01 起", "單盒 價格尚未設定起始日不明"]);
      expect(panel.textContent).not.toMatch(/\d{4}-\d{2}-\d{2}/);
    });
  });

  describe("F52-I03: available materials inside the existing allocation card", () => {
    /** `app/ads/materials_in_hand.py::read` in its real shape: two policy-backed offers, one confirmed proof, photo only. */
    const MATERIALS: NonNullable<CampaignDetail["materials"]> = {
      offers: [
        { key: "bundle", label: "組合加贈", sentence: "三盒 NT$999 另送一盒" },
        { key: "free_shipping", label: "免運", sentence: "三盒以上免運" },
      ],
      proof: [{ key: "lab_test", label: "檢驗報告", text: "SGS 檢驗：重金屬、塑化劑未檢出（2026/08）" }],
      media: "photo",
    };
    const row = () => document.querySelector("[data-slot=materials-used]") as HTMLElement | null;

    it("one chip per offer 「label：sentence」, per proof its label (text in title and name), then the media chip — above the bar", async () => {
      const user = userEvent.setup();
      renderTab(campaign({ materials: MATERIALS }));
      const fold = await screen.findByRole("button", {name: "為什麼這樣建議"});
      await user.click(fold);
      const section = document.getElementById(fold.getAttribute("aria-controls")!)!;
      const used = row();
      expect(used && section.contains(used)).toBe(true);
      expect(used!.compareDocumentPosition(section.querySelector("[data-slot=allocation-bar]")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      const chips = Array.from(used!.querySelectorAll("[data-slot=chip]")).map((el) => el.textContent);
      expect(chips).toEqual(["組合加贈：三盒 NT$999 另送一盒", "免運：三盒以上免運", "檢驗報告", "只排照片（單圖、輪播）"]);
      expect(used!.textContent).toMatch(/^可用素材：/);
      const proof = within(used!).getByLabelText("檢驗報告：SGS 檢驗：重金屬、塑化劑未檢出（2026/08）");
      expect(proof.getAttribute("title")).toBe("SGS 檢驗：重金屬、塑化劑未檢出（2026/08）");
      expect(used!.textContent).not.toMatch(/bundle|free_shipping|lab_test/);
    });

    it("photo and video reads 照片和影片; media never asked (null) leaves no media chip", async () => {
      const user = userEvent.setup();
      const { unmount } = renderTab(campaign({ materials: { ...MATERIALS, media: "photo_video" } }));
      await user.click(screen.getByRole("button", {name: "為什麼這樣建議"}));
      expect(await screen.findByText("照片和影片")).toBeTruthy();
      unmount();
      renderTab(campaign({ materials: { ...MATERIALS, media: null } }));
      await user.click(screen.getByRole("button", {name: "為什麼這樣建議"}));
      await screen.findByText("組合加贈：三盒 NT$999 另送一盒");
      expect(row()!.querySelector("[data-kind=media]")).toBeNull();
    });

    it("nothing registered: one muted chip says the ads talk about the product only, beside the media chip", async () => {
      const user = userEvent.setup();
      renderTab(campaign({ materials: { offers: [], proof: [], media: "photo" } }));
      await user.click(screen.getByRole("button", {name: "為什麼這樣建議"}));
      await screen.findByRole("heading", { name: "這期怎麼安排" });
      const chips = Array.from(row()!.querySelectorAll("[data-slot=chip]"));
      expect(chips.map((el) => el.textContent)).toEqual(["沒有登記優惠與證據，廣告只講產品本身", "只排照片（單圖、輪播）"]);
      expect(chips[0].getAttribute("data-tone")).toBe("neutral");
    });

    it("materials absent (imported, or null from the API) → no row", async () => {
      renderTab(campaign({ materials: null }));
      await screen.findByRole("heading", { name: "這期怎麼安排" });
      expect(row()).toBeNull();
      expect(screen.queryByText("可用素材：")).toBeNull();
    });
  });

  it("imported: the cap block is shown, the budget and allocation cards are not, the internal goal saves", async () => {
    const user = userEvent.setup();
    const imported = campaign({ origin: "imported", budget_basis_json: {}, status: "live" });
    vi.mocked(patchCampaign).mockResolvedValue({ ...imported, goal_text: "內部管理目標" });
    const { onCampaignChange } = renderTab(imported);
    expect(await screen.findByText("一個上限")).toBeTruthy();
    expect(screen.queryByText("這一期的總預算")).toBeNull();
    expect(screen.queryByText("這期怎麼安排")).toBeNull();
    expect(screen.queryByText("改預算上限")).toBeNull();
    expect(barEl().textContent).toBe("← 總覽查看品牌學習");
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
    expect(screen.queryByRole("button", { name: /確認策略，查看投放結構/ })).toBeNull();
  });
});

describe("F50 Contract J (R7 B4／B3): a running planner call survives a reload; a refusal prints its reason", () => {
  const SINCE = "2026-10-05T02:00:00Z";
  /** The workspace keeps the campaign: `onCampaignChange` replaces it, as `CampaignWorkspace` does. */
  function Host({ initial }: { initial: CampaignDetail }) {
    const [c, setC] = useState(initial);
    return <StrategyTab brandId="brd_1" campaign={c} onCampaignChange={setC} onChangeTab={vi.fn()} launchApproved={false} />;
  }
  const mount = (c: CampaignDetail) => render(<MemoryRouter><Host initial={c} /></MemoryRouter>);
  const tick = () => act(async () => { await vi.advanceTimersByTimeAsync(3000); });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(getTriage).mockResolvedValue({ window_days: 14, items: [], closed: { groups: [], total: 0, items: [], truncated: false } });
  });
  afterEach(() => { vi.useRealTimers(); });

  it("mounted while 展開投放結構 still runs: 處理中… until a re-read serves busy null, then the adopted campaign", async () => {
    const running = campaign({ budget_planned: 30000, budget_scenario: "cap", busy: { kind: "plan", since: SINCE } });
    vi.mocked(getCampaign)
      .mockResolvedValueOnce(running)
      .mockResolvedValueOnce(campaign({ budget_planned: 30000, budget_scenario: "cap", groups: [group()], busy: null }));
    mount(running);
    const pressed = await screen.findByRole("button", { name: "處理中…" });
    expect((pressed as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: /確認策略，查看投放結構/ })).toBeNull();
    await tick(); // still running
    expect(getCampaign).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "處理中…" })).toBeTruthy();
    await tick(); // done: the fresh campaign reloads the tab
    expect(getCampaign).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole("button", { name: "下一步：素材 →" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "處理中…" })).toBeNull();
    expect(adoptStrategy).not.toHaveBeenCalled();
    await tick();
    expect(getCampaign).toHaveBeenCalledTimes(2); // polling stopped
  });

  it("mounted while the strategy is generated: 產生中… (never an idle 產生策略), then the strategy once it lands", async () => {
    const running = campaign({ budget_basis_json: {}, busy: { kind: "strategy", since: SINCE } });
    vi.mocked(getCampaign).mockResolvedValueOnce(campaign({ busy: null }));
    mount(running);
    const generating = await screen.findByRole("button", { name: "產生中…" });
    expect((generating as HTMLButtonElement).disabled).toBe(true);
    await tick();
    expect(await screen.findByRole("heading", { name: "這期怎麼安排" })).toBeTruthy();
    expect(screen.queryByText("這個活動還沒有策略建議")).toBeNull();
    expect(generateStrategy).not.toHaveBeenCalled();
  });

  it("a 409 campaign_busy prints the served sentence and keeps re-reading until the call is done", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    vi.mocked(generateStrategy).mockRejectedValue(new ApiResponseError("上一次還在處理，等它好了再看。", 409, {}, { code: "campaign_busy" }));
    vi.mocked(getCampaign)
      .mockResolvedValueOnce(campaign({ budget_basis_json: {}, busy: { kind: "strategy", since: SINCE } }))
      .mockResolvedValueOnce(campaign({ busy: null }));
    mount(campaign({ budget_basis_json: {} }));
    await user.click(await screen.findByRole("button", { name: "產生策略" }));
    expect(await screen.findByText("上一次還在處理，等它好了再看。")).toBeTruthy();
    expect(screen.getByRole("button", { name: "產生中…" })).toBeTruthy();
    await tick();
    await tick();
    expect(getCampaign).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("這個活動還沒有策略建議")).toBeNull();
    expect(screen.queryByText("上一次還在處理，等它好了再看。")).toBeNull();
  });

  it("a 502 planner refusal prints the served message with its reason, not a fixed sentence", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const served = "產生策略失敗，請稍後再試。（模型的分配加起來不是 100%）";
    vi.mocked(generateStrategy).mockRejectedValue(new ApiResponseError(served, 502, {}, { code: "strategy_failed" }));
    mount(campaign({ budget_basis_json: {} }));
    await user.click(await screen.findByRole("button", { name: "產生策略" }));
    expect(await screen.findByText(served)).toBeTruthy();
    expect(screen.getByRole("button", { name: "產生策略" })).toBeTruthy(); // not busy: pressing again is allowed
    await tick();
    expect(getCampaign).not.toHaveBeenCalled();
  });

  it("a 502 on 確認策略，查看投放結構 prints the served message with its reason in the bar", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const served = "展開投放結構失敗，請稍後再試。（有一組沒有綁定顧客群）";
    vi.mocked(adoptStrategy).mockRejectedValue(new ApiResponseError(served, 502, {}, { code: "plan_failed" }));
    mount(campaign({ budget_planned: 30000, budget_scenario: "cap" }));
    await user.click(await screen.findByRole("button", { name: "確認策略，查看投放結構 →" }));
    expect(await screen.findByText(served)).toBeTruthy();
  });
});


describe("F53 strategy basis interaction", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  function mount(initial = strategyFixture()) {
    const onChangeTab = vi.fn();
    function Host() {
      const [value, setValue] = useState(initial);
      return <StrategyTab brandId="brd_f53_ui" campaign={value} onCampaignChange={setValue} onChangeTab={onChangeTab} launchApproved={false} />;
    }
    render(<MemoryRouter><Host /></MemoryRouter>);
    return {onChangeTab};
  }

  it("renders the served eligible count rather than counting the visible rows", async () => {
    const c = strategyFixture();
    c.budget_basis_json.basis!.evidence_context.eligible_count = 99;
    mount(c);
    expect(await screen.findByText("99 條可參考經驗")).toBeTruthy();
    expect(screen.getByText("單次觀察 · 樣本少")).toBeTruthy();
    expect(screen.queryByText("重複觀察 · 未證明因果")).toBeNull();
    expect(generateStrategy).not.toHaveBeenCalled();
  });

  it("keyboard source drilldown traps focus and Escape returns to the original trigger", async () => {
    const user = userEvent.setup();
    mount();
    const trigger = await screen.findByRole("button", {name: "查看依據 →"});
    trigger.focus();
    await user.keyboard("{Enter}");
    const basis = await screen.findByRole("dialog", {name: "策略依據"});
    expect(basis.contains(document.activeElement)).toBe(true);
    await user.click(within(basis).getAllByRole("button", {name: "查看來源與限制 →"})[0]);
    const source = await screen.findByRole("dialog", {name: "經驗來源與適用範圍"});
    expect(within(source).getByText("2026/09/01 至 2026/09/30")).toBeTruthy();
    for (let i = 0; i < 8; i++) { await user.tab(); expect(source.contains(document.activeElement)).toBe(true); }
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
    await user.click(trigger);
    expect(await screen.findByRole("dialog", {name: "策略依據"})).toBeTruthy();
    expect(screen.queryByRole("dialog", {name: "經驗來源與適用範圍"})).toBeNull();
  });

  it("failed reread keeps previous evidence and budget, blocks confirmation, and explicitly retries", async () => {
    const user = userEvent.setup();
    const fresh = strategyFixture();
    fresh.budget_basis_json.strategy!.decision!.revision = "fresh-revision";
    vi.mocked(getCampaign).mockRejectedValueOnce(new Error("Read unavailable")).mockResolvedValueOnce(fresh);
    const {onChangeTab} = mount();
    await user.click(await screen.findByRole("button", {name: "查看依據 →"}));
    await user.click(screen.getByRole("button", {name: "重新讀取依據"}));
    await user.keyboard("{Escape}");
    expect(await screen.findByText("最新依據讀不到，保留上次內容。")).toBeTruthy();
    expect(screen.getByText("單次觀察 · 樣本少")).toBeTruthy();
    expect(bar().hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("以 30,000 計")).toBeTruthy();
    expect(onChangeTab).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", {name: "重新讀取"}));
    expect(await screen.findByRole("button", {name: "查看依據 →"})).toBeTruthy();
    expect(screen.queryByText("最新依據讀不到，保留上次內容。")).toBeNull();
    expect(bar().hasAttribute("disabled")).toBe(false);
    expect(getCampaign).toHaveBeenCalledTimes(2);
    expect(adoptStrategy).not.toHaveBeenCalled();
  });

  it("loading and changed conditions preserve dirty allocation and custom total across reread", async () => {
    const user = userEvent.setup();
    let finishRead!: (value: CampaignDetail) => void;
    vi.mocked(getCampaign).mockImplementationOnce(() => new Promise(resolve => { finishRead = resolve; }));
    mount();
    await user.click(await screen.findByRole("button", {name: "調整比例"}));
    const inputs = screen.getAllByRole("spinbutton");
    await user.clear(inputs[0]); await user.type(inputs[0], "57.5");
    await user.click(screen.getByRole("button", {name: "自己填總額"}));
    await user.type(screen.getByLabelText("自己填這一期的總預算"), "12345");
    await user.click(screen.getByRole("button", {name: "查看依據 →"}));
    await user.click(screen.getByRole("button", {name: "重新讀取依據"}));
    await user.keyboard("{Escape}");
    expect(await screen.findByText("正在重新讀取依據，保留原內容與尚未儲存的輸入。")).toBeTruthy();
    expect(bar().hasAttribute("disabled")).toBe(true);
    const fresh = strategyFixture();
    fresh.budget_basis_json.strategy!.rationale_state = "stale";
    fresh.budget_basis_json.strategy!.decision!.feasibility = {state: "blocked", reasons: [{code: "strategy_changed", message: "優惠條件已改變", slot_ids: []}]};
    await act(async () => finishRead(fresh));
    expect(await screen.findByText("原策略需更新後再確認；目前預算與尚未儲存的輸入仍保留。")).toBeTruthy();
    expect(screen.getByText("優惠條件已改變")).toBeTruthy();
    expect((screen.getAllByRole("spinbutton")[0] as HTMLInputElement).value).toBe("57.5");
    expect((screen.getByLabelText("自己填這一期的總預算") as HTMLInputElement).value).toBe("12345");
    expect(bar().hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", {name: "重新產生策略"})).toBeTruthy();
    expect(adoptStrategy).not.toHaveBeenCalled();
  });

  it("contrary observations keep the backend support level and disclose the reverse count", async () => {
    const user = userEvent.setup();
    const c = strategyFixture();
    const evidence = c.budget_basis_json.basis!.learnings[0].evidence;
    evidence.contrary_count = 1; evidence.same_direction_count = 1; evidence.independent_count = 3;
    evidence.support_label = "一次可比觀察";
    mount(c);
    expect(await screen.findByText("依據含反向觀察，請連同來源與限制判讀。")).toBeTruthy();
    expect(screen.getByText("一次可比觀察")).toBeTruthy();
    await user.click(screen.getByRole("button", {name: "查看依據 →"}));
    await user.click(screen.getAllByRole("button", {name: "查看來源與限制 →"})[0]);
    const source = screen.getByRole("dialog", {name: "經驗來源與適用範圍"});
    expect(within(source).getByText("3 次")).toBeTruthy();
    const reverse = within(source).getByText("反向觀察").parentElement!;
    expect(within(reverse).getByText("1 次")).toBeTruthy();
  });

  it("cold history still allows a proposed hypothesis and a declined confirmation never navigates", async () => {
    const user = userEvent.setup();
    const c = strategyFixture();
    c.budget_basis_json.basis!.learnings = [];
    c.budget_basis_json.basis!.evidence_context = {...c.budget_basis_json.basis!.evidence_context, eligible_count: 0, items: []};
    vi.mocked(adoptStrategy).mockRejectedValue(new Error("Unknown result; retry original operation"));
    const {onChangeTab} = mount(c);
    expect(await screen.findByText("0 條可參考經驗")).toBeTruthy();
    expect(screen.getByText("尚無可用歷史")).toBeTruthy();
    await user.click(bar());
    await screen.findByText("Unknown result; retry original operation");
    await user.click(bar());
    const requests = vi.mocked(adoptStrategy).mock.calls;
    expect(requests).toHaveLength(2);
    expect(requests[0][2]).toEqual(requests[1][2]);
    expect(requests[0][2].expected_revision).toBe("decision-fixture");
    expect(requests[0][2].operation_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(onChangeTab).not.toHaveBeenCalled();
  });
});
