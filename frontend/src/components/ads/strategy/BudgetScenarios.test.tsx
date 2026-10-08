/** F28-I09: 「這一期的總預算」 — API rows against the budget cap, the in-place 改預算上限 (`setBudgetCap`), the over-cap
 * confirmation, 自己填總額, and that a changed budget cap never re-chooses anything for the user. */
import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectScenario, setBudgetCap, type BudgetScenarioRow, type CampaignDetail, type ResplitRow } from "@/lib/adsApi";
import { BudgetScenarios, type OverCapPending } from "./BudgetScenarios";
import type { BudgetAdvice } from "@/lib/adsStrategyTypes";

vi.mock("@/lib/adsApi", async () => ({
  ...(await vi.importActual<object>("@/lib/adsApi")), selectScenario: vi.fn(), setBudgetCap: vi.fn(),
}));

function rows(budgetCap: number | null): BudgetScenarioRow[] {
  const over = (t: number) => (budgetCap === null ? null : Math.max(t - budgetCap, 0));
  const base: BudgetScenarioRow[] = [
    { key: "minimum", label: "最低", daily: 900, total: 27900, caption: "冷啟動估算：上限 x 每天 2 筆購買", over_cap: over(27900) },
    { key: "recommended", label: "穩定成長", daily: 2250, total: 69750, caption: "冷啟動估算：上限 x 每天 5 筆購買", over_cap: over(69750) },
    { key: "aggressive", label: "積極", daily: 4500, total: 139500, caption: "冷啟動估算：上限 x 每天 10 筆購買", over_cap: over(139500) },
  ];
  if (budgetCap !== null) base.splice(1, 0, { key: "cap", label: "照預算上限", daily: null, total: budgetCap, caption: `用滿你設的預算上限 NT$${budgetCap}`, over_cap: 0 });
  return base.map(row => ({...row, currency: "TWD"}));
}

function campaign(budgetCap: number | null, extra: Partial<CampaignDetail> = {}, scenarioRows = rows(budgetCap)): CampaignDetail {
  return {
    id: "cmp_1", origin: "internal", start_date: "2026-09-08", end_date: "2026-10-08", budget_planned: null, budget_scenario: null,
    cap: { value: 450, basis: "own" },
    budget_basis_json: { scenarios: { mode: "cold_start", scenarios: scenarioRows, recommended: "cap", basis: {}, budget_cap: budgetCap } },
    ...extra,
  } as unknown as CampaignDetail;
}

/** The tab owns `picked`／`pending`; this harness plays that part and lets a test swap the campaign in. */
function Harness({ initial, onChange }: { initial: CampaignDetail; onChange: (c: CampaignDetail) => void }) {
  const [c, setC] = useState(initial);
  const [picked, setPicked] = useState<string | null>(null);
  const [pending, setPending] = useState<OverCapPending | null>(null);
  const [resplit, setResplit] = useState<ResplitRow[] | null>(null);
  return (
    <>
      <BudgetScenarios
        brandId="brd_1" campaign={c} picked={picked} onPick={setPicked} pending={pending} onPending={setPending}
        onCampaignChange={(next) => { onChange(next); setC(next); }}
        onBudgetSaved={(result) => { onChange(result.campaign); setC(result.campaign); setResplit(result.resplit); }}
        resplit={resplit}
      />
      <output data-testid="picked">{picked ?? ""}</output>
    </>
  );
}

function renderCard(c: CampaignDetail) {
  const onChange = vi.fn();
  render(<Harness initial={c} onChange={onChange} />);
  return { onChange };
}

describe("BudgetScenarios", () => {
  beforeEach(() => vi.clearAllMocks());

  it("summarizes a long choice name while the existing explanation reveals it in full", async () => {
    const user = userEvent.setup();
    const long = "夜跑與步行通勤、反光及輕量穿著的上班族完整商品情境".repeat(5);
    const c = campaign(30000, {}, [{key: "cap", label: long, currency: "TWD", total: 30000,
      daily: 1000, over_cap: 0, caption: "原始來源名稱"}]);
    renderCard(c);
    const choice = screen.getByRole("radio");
    expect(choice.textContent).toContain("…");
    expect(choice.textContent).not.toContain(long);
    await user.click(screen.getByRole("button", {name: "為什麼是這幾個數字"}));
    expect(screen.getByText(`${long}：原始來源名稱`)).toBeTruthy();
    await user.click(choice);
    expect(screen.getByTestId("picked").textContent).toBe("cap");
  });

  it.each(["currency", "total", "cap"])("a fresh %s change invalidates an old over-cap confirmation without saving", async (change) => {
    const c = campaign(change === "cap" ? 40000 : 30000);
    if (change === "currency") c.budget_basis_json.scenarios!.scenarios[2].currency = "USD";
    if (change === "total") c.budget_basis_json.scenarios!.scenarios[2].total = 70000;
    const onPending = vi.fn();
    render(<BudgetScenarios brandId="brd_1" campaign={c} picked={null} onPick={vi.fn()}
      pending={{key: "recommended", label: "穩定成長", total: 69750, over: 39750, customTotal: null}}
      onPending={onPending} onCampaignChange={vi.fn()} onBudgetSaved={vi.fn()} />);
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(await screen.findByText("預算選項或上限已更新，請重新選擇並確認金額。")).toBeTruthy();
    expect(onPending).toHaveBeenCalledWith(null);
    expect(selectScenario).not.toHaveBeenCalled();
  });

  it.each([
    ["retain", "可維持已知預算", "on_target_affordable", "目前成本達標，已知預算可負擔"],
    ["repair_before_budget", "先改善成本，再調預算", "cost_over", "成本超過上限，先改善再調預算"],
    ["insufficient_evidence", "證據不足，暫無建議金額", "continuation_outside_recent_window", "選定來源月份已不在近期預算判斷期間"],
    ["unaffordable", "已知資金不足，暫無建議金額", "period_budget_exceeded", "這期金額超過已確認的預算或可用資金"],
  ] as const)("prints served %s without reclassifying a nullable recommendation", async (state, title, reason, explanation) => {
    const user = userEvent.setup();
    const c = campaign(30000);
    const advice: BudgetAdvice = {state, recommended_key: state === "retain" ? "cap" : null,
      reason_codes: [reason], revision: "advice-current", evidence: {window: {start: "2026-09-15", end: "2026-09-21", campaign_id: "selected"},
        cost_per_result: 0, target: {value: 100, basis: "own", revision: 2, unit: {currency: "TWD"}}, grade: "on_target",
        currency: "TWD", attribution: {kind: "purchase", action: "omni_purchase", window: "7d_click"}, sample_flag: {few: true}}};
    c.budget_advice = advice;
    renderCard(c);
    expect(screen.getByText(title)).toBeTruthy();
    expect(screen.queryByText("推薦") !== null).toBe(state === "retain");
    expect(screen.getAllByRole("radio").every(row => row.getAttribute("aria-checked") === "false")).toBe(true);
    await user.click(screen.getByRole("button", {name: "預算建議依據"}));
    expect(screen.getByText(explanation)).toBeTruthy();
    expect(screen.getByText("TWD 0")).toBeTruthy();
    expect(screen.getByText("advice-current")).toBeTruthy();
    expect(selectScenario).not.toHaveBeenCalled();
  });

  it("keeps a legacy recommended key without a served recommendation neutral", () => {
    const c = campaign(null);
    c.budget_basis_json.scenarios!.recommended = null;
    renderCard(c);
    expect(screen.queryByText("推薦")).toBeNull();
    expect(screen.getByText("目前沒有可自動建議的預算")).toBeTruthy();
    expect(selectScenario).not.toHaveBeenCalled();
  });

  it.each([["USD", 14000], [null, 1200], [undefined, 0], ["TWD", 0], ["USD", -100]] as const)("retains %s source money %s without making it selectable as TWD", async (currency, total) => {
    const user = userEvent.setup();
    const c = campaign(30000, {}, [{key: "recommended", label: "照上一期", currency,
      total, daily: 0, over_cap: 0, caption: "原始來源"}]);
    c.budget_basis_json.scenarios!.recommended = "recommended";
    renderCard(c);
    const source = document.querySelector("[data-slot=unselectable-budget]")!;
    expect(source.textContent).toContain(currency ?? "幣別未知");
    expect(source.textContent).toContain(total.toLocaleString("en-US"));
    expect(screen.queryByRole("radio", {name: /照上一期/})).toBeNull();
    expect(screen.queryByText("推薦")).toBeNull();
    await user.click(screen.getByRole("button", {name: "自己填總額"}));
    await user.type(screen.getByLabelText("自己填這一期的總預算"), "1200");
    vi.mocked(selectScenario).mockRejectedValue(new Error("儲存失敗"));
    await user.click(screen.getByRole("button", {name: "套用"}));
    expect(await screen.findByText("儲存失敗")).toBeTruthy();
    expect(screen.getByLabelText("自己填這一期的總預算")).toHaveProperty("value", "1200");
    expect(selectScenario).toHaveBeenCalledWith("brd_1", "cmp_1", {scenario_key: "custom", custom_total: 1200});
  });

  it("prints the API rows against the budget cap: 推薦, 已儲存, 超出 amounts, 約 N 筆購買", async () => {
    renderCard(campaign(30000, { budget_planned: 30000, budget_scenario: "cap" }));
    const capRow = await screen.findByRole("radio", { name: /照預算上限/ });
    expect(capRow.textContent).not.toContain("推薦");
    expect(capRow.textContent).toContain("已儲存");
    expect(capRow.textContent).toContain("用滿你設的預算上限 NT$30000");
    expect(capRow.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: /穩定成長/ }).textContent).toContain("超出 39,750");
    expect(screen.getByText("你的預算上限 30,000")).toBeTruthy();
    expect(screen.getByText("09/08 – 10/08・31 天")).toBeTruthy();
  });

  it("a row the API cannot price (no cost cap) says 要先設上限 and cannot be picked", async () => {
    const c = campaign(30000, {}, rows(30000).map((r) => (r.key === "cap" ? r : { ...r, total: null, over_cap: null })));
    renderCard(c);
    expect((await screen.findAllByText("金額尚未核實")).length).toBe(3);
    expect(screen.getAllByRole("radio").map((r) => r.textContent)).toEqual([expect.stringContaining("照預算上限")]);
  });

  it("改預算上限 edits in place and saves through setBudgetCap; the saved row now over the cap shows its mark and stays chosen", async () => {
    const user = userEvent.setup();
    const saved = { budget_planned: 27900, budget_scenario: "minimum" };
    const after = campaign(20000, saved);
    vi.mocked(setBudgetCap).mockResolvedValue(after);
    const { onChange } = renderCard(campaign(30000, saved));
    await user.click(await screen.findByRole("button", { name: "改預算上限" }));
    const input = screen.getByLabelText("這一期的預算上限（留空＝不設）") as HTMLInputElement;
    expect(input.value).toBe("30000");
    await user.clear(input);
    await user.type(input, "20000");
    await user.click(screen.getByRole("button", { name: "儲存" }));
    expect(setBudgetCap).toHaveBeenCalledWith("brd_1", "cmp_1", 20000);
    expect(onChange).toHaveBeenCalledWith(after);
    const minimum = await screen.findByRole("radio", { name: /最低/ });
    expect(minimum.textContent).toContain("超出 7,900");
    expect(minimum.textContent).toContain("已儲存");
    expect(minimum.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("你的預算上限 20,000")).toBeTruthy();
    expect(selectScenario).not.toHaveBeenCalled();
  });

  it("a saved cap row whose total moved with the budget cap no longer wears 已儲存; the header keeps the saved money honest", async () => {
    renderCard(campaign(20000, { budget_planned: 30000, budget_scenario: "cap" }));
    expect(await screen.findByText("已儲存 30,000")).toBeTruthy();
    expect(screen.getByText("超出預算上限 10,000")).toBeTruthy();
    expect(screen.getAllByRole("radio").every((r) => r.getAttribute("aria-checked") === "false")).toBe(true);
  });

  it("empty clears the budget cap; a changed cap drops the unsaved pick", async () => {
    const user = userEvent.setup();
    vi.mocked(setBudgetCap).mockResolvedValue(campaign(null));
    renderCard(campaign(30000));
    await user.click(await screen.findByRole("radio", { name: /最低/ }));
    expect(screen.getByTestId("picked").textContent).toBe("minimum");
    await user.click(screen.getByRole("button", { name: "改預算上限" }));
    await user.clear(screen.getByLabelText("這一期的預算上限（留空＝不設）"));
    await user.click(screen.getByRole("button", { name: "儲存" }));
    expect(setBudgetCap).toHaveBeenCalledWith("brd_1", "cmp_1", null);
    expect(await screen.findByText("沒設預算上限")).toBeTruthy();
    expect(screen.getByRole("button", { name: "設預算上限" })).toBeTruthy();
    expect(screen.getByTestId("picked").textContent).toBe("");
  });

  it("a non-integer budget cap is refused before any request; 取消 leaves everything as it was", async () => {
    const user = userEvent.setup();
    renderCard(campaign(30000));
    await user.click(await screen.findByRole("button", { name: "改預算上限" }));
    const input = screen.getByLabelText("這一期的預算上限（留空＝不設）");
    await user.clear(input);
    await user.type(input, "1.5");
    expect(screen.getByText("預算上限要是大於 0 的整數；留空＝不設上限。")).toBeTruthy();
    expect(screen.getByRole("button", { name: "儲存" }).hasAttribute("disabled")).toBe(true);
    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.getByText("你的預算上限 30,000")).toBeTruthy();
    expect(setBudgetCap).not.toHaveBeenCalled();
  });

  it("a failed budget-cap save keeps the editor open with the server's message", async () => {
    const user = userEvent.setup();
    vi.mocked(setBudgetCap).mockRejectedValue(new Error("預算上限要是大於 0 的整數；要取消上限請送 null。"));
    renderCard(campaign(30000));
    await user.click(await screen.findByRole("button", { name: "改預算上限" }));
    await user.click(screen.getByRole("button", { name: "儲存" }));
    expect((await screen.findByRole("alert")).textContent).toContain("要取消上限請送 null");
    expect(screen.getByLabelText("這一期的預算上限（留空＝不設）")).toBeTruthy();
  });

  it("自己填總額 within the cap saves as custom; above it opens the sheet and confirms with custom_total", async () => {
    const user = userEvent.setup();
    vi.mocked(selectScenario).mockResolvedValue({ campaign: campaign(30000, { budget_planned: 25000, budget_scenario: "custom" }), resplit: null });
    renderCard(campaign(30000));
    await user.click(await screen.findByRole("button", { name: "自己填總額" }));
    const input = screen.getByLabelText("自己填這一期的總預算");
    await user.type(input, "25000");
    await user.click(screen.getByRole("button", { name: "套用" }));
    expect(selectScenario).toHaveBeenLastCalledWith("brd_1", "cmp_1", { scenario_key: "custom", custom_total: 25000 });
    expect(await screen.findByText("已儲存 25,000")).toBeTruthy();

    await user.type(input, "45000");
    await user.click(screen.getByRole("button", { name: "套用" }));
    expect((await screen.findByRole("alertdialog")).textContent).toContain("選「自己填 45,000」會超出預算上限 15,000 元");
    expect(selectScenario).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "超出預算上限也要用" }));
    expect(selectScenario).toHaveBeenLastCalledWith("brd_1", "cmp_1", { scenario_key: "custom", custom_total: 45000 }, { confirmOverCap: true });
  });

  it("a refused over-cap save (e.g. 409 from a cap changed elsewhere) stays in the sheet with the message", async () => {
    const user = userEvent.setup();
    vi.mocked(selectScenario).mockRejectedValue(new Error("這個預算 NT$139,500 超出你設的預算上限 NT$30,000"));
    renderCard(campaign(30000));
    await user.click(await screen.findByRole("radio", { name: /積極/ }));
    await user.click(await screen.findByRole("button", { name: "超出預算上限也要用" }));
    expect((await screen.findByRole("alert")).textContent).toContain("超出你設的預算上限");
    expect(screen.getByRole("alertdialog")).toBeTruthy();
  });

  it("F48 Contract M: the saved total's budget_preview prints under the title — 每天 X・這期實際 Y and the server's note", async () => {
    // 10,000 over 31 days: the whole daily is 322 and the period really spends 9,982 (`budget.preview`).
    renderCard(campaign(30000, {
      budget_planned: 10000, budget_scenario: "custom",
      budget_preview: { daily: 322, total: 9982, chosen: 10000, note: "每天要是整數，這期實際 9,982" },
    }));
    const line = await screen.findByText(/每天 322・這期實際 9,982/);
    expect(line.closest("[data-slot=budget-preview]")?.textContent).toBe("每天 322・這期實際 9,982每天要是整數，這期實際 9,982");
    const heading = screen.getByRole("heading", { name: "這一期的總預算" });
    expect(heading.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("a total that divides evenly has no note; no total chosen prints no preview line", async () => {
    const { unmount } = render(<Harness initial={campaign(30000, {
      budget_planned: 31000, budget_scenario: "custom", budget_preview: { daily: 1000, total: 31000, chosen: 31000, note: null },
    })} onChange={vi.fn()} />);
    expect((await screen.findByText(/每天 1,000・這期實際 31,000/)).closest("[data-slot=budget-preview]")?.textContent).toBe("每天 1,000・這期實際 31,000");
    unmount();
    renderCard(campaign(30000));
    await screen.findByRole("radio", { name: /最低/ });
    expect(document.querySelector("[data-slot=budget-preview]")).toBeNull();
  });

  it("F48 decision 8: a new total on an adopted plan prints the API's resplit list, under each role's served label", async () => {
    const user = userEvent.setup();
    const ready = campaign(30000, {
      status: "ready", budget_planned: 27900, budget_scenario: "minimum",
      groups: [{ id: "grp_new", name: "新客｜通勤族" }, { id: "grp_exp", name: "探索｜備考生" }] as unknown as CampaignDetail["groups"],
    });
    (ready.budget_basis_json as { strategy?: unknown }).strategy = {
      allocation: [
        { role: "new", label: "新客", pct: 70, rationale: null, amount: 19530 },
        { role: "explore", label: "探索", pct: 30, rationale: null, amount: 8370 },
      ],
      why: [], unknowns: [], alternatives: [],
    };
    vi.mocked(selectScenario).mockResolvedValue({
      campaign: { ...ready, budget_planned: 24986, budget_scenario: "custom" },
      resplit: [
        { group_id: "grp_new", role: "new", before: 630, after: 564 },
        { group_id: "grp_exp", role: "explore", before: 270, after: 242 },
      ],
    });
    renderCard(ready);
    await user.click(await screen.findByRole("button", { name: "自己填總額" }));
    await user.type(screen.getByLabelText("自己填這一期的總預算"), "25000");
    await user.click(screen.getByRole("button", { name: "套用" }));
    await screen.findByText(/已照比例重分到/);
    const note = document.querySelector("[data-slot=budget-resplit]") as HTMLElement;
    expect(note.getAttribute("role")).toBe("status");
    expect(note.textContent).toBe("已照比例重分到 2 個投放組：新客 630 → 564、探索 270 → 242");
  });

  it("a campaign with an ad set on the platform: the 409 campaign_bound sentence is shown as the server wrote it", async () => {
    const user = userEvent.setup();
    vi.mocked(selectScenario).mockRejectedValue(new Error("投放組已上架，改預算要走變更清單。"));
    renderCard(campaign(30000, { status: "ready", budget_planned: 27900, budget_scenario: "minimum" }));
    await user.click(await screen.findByRole("button", { name: "自己填總額" }));
    await user.type(screen.getByLabelText("自己填這一期的總預算"), "25000");
    await user.click(screen.getByRole("button", { name: "套用" }));
    expect((await screen.findByRole("alert")).textContent).toBe("投放組已上架，改預算要走變更清單。");
    expect(document.querySelector("[data-slot=budget-resplit]")).toBeNull();
  });

  it("為什麼是這幾個數字 lists each row's own caption", async () => {
    const user = userEvent.setup();
    renderCard(campaign(30000));
    await user.click(await screen.findByRole("button", { name: "為什麼是這幾個數字" }));
    expect(screen.getByText("積極：冷啟動估算：上限 x 每天 10 筆購買")).toBeTruthy();
    expect(screen.queryByText("約幾筆購買＝總額 ÷ 每筆上限；每筆都花到上限時的估計")).toBeNull();
  });
});
