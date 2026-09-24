/** F28-I09: 「這一期的總預算」 — API rows against the budget cap, the in-place 改預算上限 (`setBudgetCap`), the over-cap
 * confirmation, 自己填總額, and that a changed budget cap never re-chooses anything for the user. */
import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { selectScenario, setBudgetCap, type BudgetScenarioRow, type CampaignDetail } from "@/lib/adsApi";
import { BudgetScenarios, type OverCapPending } from "./BudgetScenarios";

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
  return base;
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
  return (
    <>
      <BudgetScenarios
        brandId="brd_1" campaign={c} picked={picked} onPick={setPicked} pending={pending} onPending={setPending}
        onCampaignChange={(next) => { onChange(next); setC(next); }}
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

  it("prints the API rows against the budget cap: 推薦, 已儲存, 超出 amounts, 約 N 筆購買", async () => {
    renderCard(campaign(30000, { budget_planned: 30000, budget_scenario: "cap" }));
    const capRow = await screen.findByRole("radio", { name: /照預算上限/ });
    expect(capRow.textContent).toContain("推薦");
    expect(capRow.textContent).toContain("已儲存");
    expect(capRow.textContent).toContain("約 66 筆購買");
    expect(capRow.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: /穩定成長/ }).textContent).toContain("超出 39,750");
    expect(screen.getByText("你的預算上限 30,000")).toBeTruthy();
    expect(screen.getByText("09/08 – 10/08・31 天")).toBeTruthy();
  });

  it("a row the API cannot price (no cost cap) says 要先設上限 and cannot be picked", async () => {
    const c = campaign(30000, {}, rows(30000).map((r) => (r.key === "cap" ? r : { ...r, total: null, over_cap: null })));
    renderCard(c);
    expect((await screen.findAllByText("要先設上限")).length).toBe(3);
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
    vi.mocked(selectScenario).mockResolvedValue(campaign(30000, { budget_planned: 25000, budget_scenario: "custom" }));
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

  it("為什麼是這幾個數字 lists each row's own caption", async () => {
    const user = userEvent.setup();
    renderCard(campaign(30000));
    await user.click(await screen.findByRole("button", { name: "為什麼是這幾個數字" }));
    expect(screen.getByText("積極：冷啟動估算：上限 x 每天 10 筆購買")).toBeTruthy();
    expect(screen.getByText("約幾筆購買＝總額 ÷ 每筆上限；每筆都花到上限時的估計")).toBeTruthy();
  });
});
