import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { IntakeDraft } from "@/lib/intakeApi";
import { BudgetPanel } from "./BudgetPanel";
import { CostGauge } from "./CostGauge";

vi.mock("@/lib/intakeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeApi")>("@/lib/intakeApi");
  return { ...actual, saveBudget: vi.fn() };
});

// Only the cost fields are read by these two components; the rest of the draft is irrelevant here.
const draft = {
  budget_limit: 3,
  cost_spent: 0.42,
  cost_items: [{ label: "掃描網站", amount: 0.42, failed: false }],
} as unknown as IntakeDraft;

describe("AI cost is never read as ad spend (drill item 7c)", () => {
  it("the wizard gauge says the US$ amount is the AI cost, not ad spend", () => {
    render(<CostGauge draft={draft} onAdjust={vi.fn()} />);
    expect(screen.getByText(/US\$ 0\.42/)).toBeTruthy();
    expect(screen.getByText("這是 AI 整理資料的費用，不是廣告費。")).toBeTruthy();
  });

  it("the gauge keeps the note before a draft exists", () => {
    render(<CostGauge draft={null} onAdjust={vi.fn()} />);
    expect(screen.getByText("這是 AI 整理資料的費用，不是廣告費。")).toBeTruthy();
  });

  it("the spending-cap panel says the same next to its US$ amounts", () => {
    render(<BudgetPanel brandId="b1" draft={draft} onClose={vi.fn()} onSaved={vi.fn()} />);
    expect(screen.getByText(/目前已花費 US\$ 0\.42.*不是廣告費/)).toBeTruthy();
  });
});
