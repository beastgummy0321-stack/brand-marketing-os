import {render, screen, within} from "@testing-library/react";
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

  it("keeps same-known-unit money tags and spend shares", () => {
    const {container} = show([observed("TWD")]);
    expect(screen.getByRole("region", {name: "TWD活動"}).textContent).toContain("在虧");
    expect(container.querySelector<HTMLElement>('[data-slot="grade-bar"] i[data-grade]')!.style.width).toBe("100%");
  });

  it("does not compare known USD aggregate CPA against a TWD cap", () => {
    show([observed("USD")]);
    const numbers = screen.getByRole("region", {name: "這期數字"});
    expect(within(numbers).getByText("546 USD")).toBeTruthy();
    expect(numbers.textContent).toContain("不能比較");
    expect(numbers.textContent).not.toContain("在每個活動自己的上限內");
  });
});
