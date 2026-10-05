/** frontend/src/components/overview/BrandCard.test.tsx -- F47-I03 (drill-10 甲 總覽 #5, a-12-overview.png): one state per
 * card. Without a guide-card step, the line under the status comes from the same `health` as the dot: never
 * 「一切正常」 under 「有警示待處理」. */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { DashboardBrandCard } from "@/lib/api";
import { BrandCard } from "./BrandCard";

function card(over: Partial<DashboardBrandCard>): DashboardBrandCard {
  return {
    brand_id: "brd_1",
    brand_name: "Beast Prime 野獸至尊",
    health: "green",
    revenue_this_month: null,
    revenue_mom_pct: null,
    next_step: null,
    ...over,
  };
}

function renderCard(c: DashboardBrandCard) {
  return render(<MemoryRouter><BrandCard card={c} /></MemoryRouter>);
}

describe("BrandCard one state per card", () => {
  it.each([
    ["yellow", "有警示待處理"],
    ["red", "需要關注"],
  ] as const)("%s with no next step: the line under the dot links to the inbox with the dot's own words", (health, label) => {
    renderCard(card({ health }));
    const link = screen.getByRole("link", { name: `${label}：到收件匣查看 →` });
    expect(link.getAttribute("href")).toBe("/inbox");
    expect(screen.queryByText("一切正常")).toBeNull();
    expect(screen.queryByText("目前沒有要處理的下一步。")).toBeNull();
  });

  it("green with no next step reads 「目前沒有要處理的下一步。」 under 「一切正常」", () => {
    renderCard(card({ health: "green" }));
    expect(screen.getByText("一切正常")).toBeTruthy();
    expect(screen.getByText("目前沒有要處理的下一步。")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /到收件匣查看/ })).toBeNull();
  });

  it("a guide-card step shows that step, whatever the health", () => {
    renderCard(card({ health: "yellow", next_step: { title: "還沒設定廣告目標", action_url: "/brands/brd_1/library" } }));
    expect(screen.getByRole("link", { name: "還沒設定廣告目標 →" })).toBeTruthy();
    expect(screen.getByText("有警示待處理")).toBeTruthy();
    expect(screen.queryByText("一切正常")).toBeNull();
  });
});
