import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { MonthGrades, PeriodGradeBucket, PeriodGradeRow } from "@/lib/adsMonthApi";
import { GradeBuckets, GradeSplit } from "./MonthGrades";
import { RULES_FIXTURE, seedAdsRules } from "../patterns/rulesFixture";

beforeEach(() => seedAdsRules(RULES_FIXTURE));

function row(currency: string, grade: PeriodGradeRow["grade"], spend: number): PeriodGradeRow {
  return {campaign_id: currency, campaign_name: currency, origin: "internal", entity_id: currency,
    name: currency, group_name: null, thumbnail_url: null, spend, results: 43, cost_per_result: spend / 43,
    cap: 350, break_even: null, grade, grade_label: grade === "insufficient" ? "資料不足" : "太貴", currency,
    reason_code: grade === "insufficient" ? "cap_currency_mismatch" : null,
    cap_comparison: {basis: "own", currency: "TWD", reason: grade === "insufficient" ? "cap_currency_mismatch" : null,
      message: grade === "insufficient" ? "上限與本期成效的幣別不同或尚未核實，不能比較。" : null}};
}
function bucket(row: PeriodGradeRow): PeriodGradeBucket {
  return {grade: row.grade, amount: row.spend, count: 1, currency: row.currency,
    reason_codes: row.reason_code ? [row.reason_code] : [], messages: row.cap_comparison?.message ? [row.cap_comparison.message] : [],
    ads: [{entity_id: row.entity_id, name: row.name, thumbnail_url: null, spend: row.spend}]};
}

describe("served monthly money evidence", () => {
  it("takes the insufficient word from served rules without inventing one while rules are missing", () => {
    const observed = row("USD", "insufficient", 50);
    const grades: MonthGrades = {spent: 50, currency: "USD", rows: [observed], buckets: [bucket(observed)], missing: []};
    seedAdsRules({...RULES_FIXTURE, labels: {...RULES_FIXTURE.labels, grade: {...RULES_FIXTURE.labels.grade, no_data: "尚待核實"}}});
    const view = render(<><GradeSplit month={10} grades={grades} /><GradeBuckets grades={grades} withAmounts /></>);
    expect(screen.getByRole("heading", {name: "尚待核實"})).toBeTruthy();
    expect(view.container.querySelector('[data-slot="grade-bar"]')!.textContent).toContain("尚待核實 1 則");
    view.unmount();
    seedAdsRules(null);
    const missing = render(<><GradeSplit month={10} grades={grades} /><GradeBuckets grades={grades} withAmounts /></>);
    expect(missing.container.querySelector('[data-bucket="insufficient"] h2')!.textContent).toBe("");
    expect(missing.container.querySelector('[data-slot="grade-bar"]')!.textContent).not.toContain("資料不足");
    expect(missing.container.querySelector('[data-slot="grade-bar"]')!.textContent).not.toContain("剛開始");
  });

  it("retains each observed unit and the actual mismatch reason without comparing TWD/USD shares", () => {
    const rows = [row("TWD", "over", 23499), row("USD", "insufficient", 23499)];
    const grades: MonthGrades = {spent: null, currency: null, rows, buckets: rows.map(bucket), missing: []};
    const {container} = render(<><GradeSplit month={10} grades={grades} /><GradeBuckets grades={grades} withAmounts /></>);
    expect(screen.getAllByText(/23,499 TWD/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/23,499 USD/).length).toBeGreaterThan(0);
    const unknown = container.querySelector('[data-bucket="insufficient"]') as HTMLElement;
    expect(within(unknown).getByRole("heading", {name: "資料不足"})).toBeTruthy();
    expect(unknown.textContent).toContain(rows[1].cap_comparison!.message);
    expect(unknown.textContent).not.toContain("還沒花到上限");
    expect(container.querySelectorAll('[data-slot="grade-bar"] i[data-grade]')).toHaveLength(0);
    expect(screen.getByText("幣別不同或尚未核實，不比較花費占比。")).toBeTruthy();
  });

  it("keeps the existing shares when all observed amounts have the same confirmed unit", () => {
    const rows = [row("TWD", "on_target", 300), {...row("TWD", "watch", 700), entity_id: "second"}];
    const grades: MonthGrades = {spent: 1000, currency: "TWD", rows, buckets: rows.map(bucket), missing: []};
    const {container} = render(<GradeSplit month={10} grades={grades} />);
    const segments = [...container.querySelectorAll<HTMLElement>('[data-slot="grade-bar"] i[data-grade]')];
    expect(segments.map((node) => node.style.width)).toEqual(["30%", "70%"]);
    expect(screen.getByRole("heading", {name: "10 月已花 1,000 TWD，分到這幾格"})).toBeTruthy();
  });

  it("keeps a supplied amount with unknown unit explicit without inventing zero", () => {
    const observed = row("USD", "insufficient", 50);
    const known = {...bucket(observed), currency: undefined, reason_codes: undefined, messages: undefined};
    const grades: MonthGrades = {spent: null, rows: [observed], buckets: [known], missing: []};
    const {container} = render(<><GradeSplit month={10} grades={grades} /><GradeBuckets grades={grades} withAmounts /></>);
    expect(screen.getAllByText(/50 幣別未知/).length).toBeGreaterThan(0);
    expect(container.querySelectorAll('[data-slot="grade-bar"] i[data-grade]')).toHaveLength(0);
    expect(container.querySelector('[data-bucket="insufficient"]')!.textContent).not.toContain("花 0");
  });

  it("never draws a partial share when another bucket's spend is unknown", () => {
    const known = row("TWD", "on_target", 300);
    const unknown = {...row("TWD", "watch", 700), spend: null};
    const grades: MonthGrades = {spent: null, currency: "TWD", rows: [known, unknown], buckets: [bucket(known), bucket(unknown)], missing: []};
    const {container} = render(<GradeSplit month={10} grades={grades} />);
    expect(container.querySelectorAll('[data-slot="grade-bar"] i[data-grade]')).toHaveLength(0);
    expect(screen.getByText(/1 則・金額未知/)).toBeTruthy();
    expect(screen.getByText(/300 TWD/)).toBeTruthy();
    expect(screen.getByText("花費金額未知，不比較花費占比。")).toBeTruthy();
    expect(container.textContent).not.toContain("幣別不同或尚未核實");
    expect(container.textContent).toContain("1 則・金額未知");
  });
});
