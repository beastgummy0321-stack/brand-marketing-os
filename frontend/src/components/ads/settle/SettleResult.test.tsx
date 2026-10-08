import {fireEvent, render, screen, within} from "@testing-library/react";
import {MemoryRouter} from "react-router-dom";
import {describe, expect, it} from "vitest";
import type {SettleRow, SettleView} from "@/lib/adsSettleApi";
import {SettleResult} from "./SettleResult";

/** Source shape/numerics follow the actual isolated public monthly USD/TWD receipt. */
function observed(currency: string, beCurrency: string | null = currency): SettleRow {
  const reason = currency === "TWD" ? null : "cap_currency_mismatch";
  return {campaign_id: currency, campaign_name: `${currency}活動`, origin: "internal", entity_id: currency,
    name: `${currency}廣告`, group_name: null, thumbnail_url: null, spend: 23499, results: 43,
    cost_per_result: 23499 / 43, cap: 350, break_even: 520, currency,
    result_kind: "purchase", result_label: "購買", result_action: "omni_purchase", result_attribution: "7d_click+1d_view",
    grade: reason ? "insufficient" : "over", grade_label: reason ? "資料不足" : "太貴", reason_code: reason,
    cap_comparison: {basis: "own", currency: "TWD", source: "user", unit_basis: "manual_ntd_input", reason,
      message: reason ? "上限與本期成效的幣別不同或尚未核實，不能比較。" : null},
    break_even_unit: {basis: "break_even", currency: beCurrency, source: "product_economics", unit_basis: beCurrency ? "confirmed_product_economics" : null},
    rank: 1, of: 1, sales: 43, few: false, verdict: "keep", verdict_label: "留下", flags: [], fate: "effective",
    skip_reason: null, copy_text: null, angles: {status: "not_needed", candidates: []}, written_angle: null};
}
function view(rows: SettleRow[]): SettleView {
  const currency = rows.every((row) => row.currency === rows[0].currency) ? rows[0].currency : null;
  return {month: "2026-10", start: "2026-10-01", end: "2026-10-31", days: 31, status: "not_ended", currency,
    spent: currency ? rows.reduce((sum, row) => sum + row.spend!, 0) : null, budget: null,
    results: 43 * rows.length, cost_per_result: currency ? 23499 / 43 : null, on_target_results: 43 * rows.length,
    result_comparison: {reason: null}, result_definition: {kind: "purchase", action: "omni_purchase", attribution: "7d_click+1d_view", window: {start: "2026-10-01", end: "2026-10-31"}},
    on_target_spend_share: null, notebook: {count: 0}, written: null, rows,
    buckets: rows.map((row) => ({grade: row.grade, amount: row.spend, count: 1, currency: row.currency,
      reason_codes: row.reason_code ? [row.reason_code] : [], messages: row.cap_comparison?.message ? [row.cap_comparison.message] : [], ads: []})),
    campaigns: rows.map((row) => ({campaign_id: row.campaign_id, name: row.campaign_name, origin: row.origin,
      cap: {value: row.cap!, basis: "own"}, break_even: row.break_even,
      data_status: {state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: null}}))};
}
function show(rows: SettleRow[]) {
  return render(<MemoryRouter><SettleResult view={view(rows)} header={null} homeHref="/" angleHref="/" noteHref="/" /></MemoryRouter>);
}

describe("settle served money evidence", () => {
  it("relays bucket currency/reason while preserving mixed-currency raw amounts and no share", () => {
    const {container} = show([observed("TWD"), observed("USD")]);
    const share = screen.getByRole("region", {name: "花在有效廣告的比例"});
    expect(share.textContent).toContain("23,499 TWD");
    expect(share.textContent).toContain("資料不足 1 則・23,499 USD");
    expect(share.textContent).toContain("不能比較");
    expect(container.querySelectorAll('[data-slot="grade-bar"] i[data-grade]')).toHaveLength(0);
    const usd = screen.getByRole("region", {name: "USD活動"});
    expect(within(usd).getByText("每筆 546 USD")).toBeTruthy();
    expect(usd.textContent).not.toContain("在虧");
  });

  it.each(["USD", null])("retains TWD graded CPA but never tags loss against a %s break-even", (currency) => {
    show([observed("TWD", currency)]);
    const card = screen.getByRole("region", {name: "TWD活動"});
    expect(within(card).getByText("每筆 546 TWD")).toBeTruthy();
    expect(card.textContent).not.toContain("在虧");
    expect(card.textContent).toContain("上限 350 TWD");
  });

  it("keeps same-known-unit raw facts and spend shares without verified-profit language", () => {
    const {container} = show([observed("TWD")]);
    expect(screen.getByRole("region", {name: "TWD活動"}).textContent).not.toContain("在虧");
    expect(screen.queryByText("有賺")).toBeNull();
    expect(container.querySelector<HTMLElement>('[data-slot="grade-bar"] i[data-grade]')!.style.width).toBe("100%");
  });

  it("does not compare known USD aggregate CPA against a TWD cap", () => {
    show([observed("USD")]);
    const numbers = screen.getByRole("region", {name: "這期數字"});
    expect(within(numbers).getByText("546 USD")).toBeTruthy();
    expect(numbers.textContent).toContain("不能比較");
    expect(numbers.textContent).not.toContain("在每個活動自己的上限內");
  });
  it("does not endorse an aggregate cap comparison rejected by the row target kind", () => {
    const row: SettleRow = {...observed("TWD"), spend: 200, results: 10, sales: 10, cost_per_result: 20,
      cap: 100, grade: "insufficient", grade_label: "資料不足", reason_code: "result_kind_mismatch", fate: "skip"};
    const summary = {...view([row]), spent: 200, results: 10, cost_per_result: 20, on_target_results: 0};
    render(<MemoryRouter><SettleResult view={summary} header={null} homeHref="/" angleHref="/" noteHref="/" /></MemoryRouter>);
    const numbers = screen.getByRole("region", {name: "這期數字"});
    expect(within(numbers).getByText("10 筆")).toBeTruthy();
    expect(within(numbers).getByText("20 TWD")).toBeTruthy();
    expect(numbers.textContent).toContain("成果類型與活動目標不同，不能比較上限");
    expect(numbers.textContent).not.toContain("在每個活動自己的上限內");
    expect(within(numbers).getByText("成果類型與活動目標不同，不能比較上限").className).toContain("text-muted-foreground");
    expect(screen.getByRole("region", {name: "TWD活動"}).textContent).toContain("每筆 20 TWD");
    expect(summary.result_comparison).toEqual({reason: null});
    expect(summary.result_definition?.kind).toBe("purchase");
  });

  it.each(["purchase", "lead"])("keeps %s cost and cap but shows economics only as a hypothesis", (kind) => {
    const row = {...observed("TWD"), result_kind: kind, result_label: kind === "lead" ? "名單" : "購買"};
    if (kind === "lead") {row.grade = "insufficient"; row.reason_code = "result_kind_mismatch"; row.fate = "skip";}
    show([row]);
    const card = screen.getByRole("region", {name: "TWD活動"});
    expect(within(card).getByText("每筆 546 TWD")).toBeTruthy();
    expect(card.textContent).toContain(kind === "lead" ? "不能比較上限" : "上限 350 TWD");
    fireEvent.click(within(card).getByRole("button", {name: /查看口徑/}));
    expect(card.textContent).toContain("商品假設打平線 520 TWD；不是已核實獲利");
    expect(document.body.textContent).not.toMatch(/有賺|在虧/);
  });
  it("known non-purchase zero retains the grade, spending and threshold without a sales claim", () => {
    const row = {...observed("TWD"), result_kind: "lead", result_label: "名單", results: 0, cost_per_result: null,
      grade: "wasted" as const, grade_label: "沒賣出", reason_code: "spend_over_target_no_result", fate: "ineffective" as const};
    show([row]);
    const card = screen.getByRole("region", {name: "TWD活動"});
    expect(card.querySelector('[data-grade="wasted"]')).toBeTruthy();
    expect(card.textContent).toContain("23,499 TWD・0 筆");
    expect(card.textContent).toContain("尚無成果");
    expect(document.body.textContent).not.toMatch(/有賺|在虧|沒賣出|都沒賣|成交 0/);
  });
});
