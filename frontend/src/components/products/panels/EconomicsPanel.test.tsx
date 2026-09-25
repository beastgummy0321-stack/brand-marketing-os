import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EconomicsPanel } from "./EconomicsPanel";

vi.mock("@/lib/productsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/productsApi")>("@/lib/productsApi");
  return { ...actual, saveProductEconomics: vi.fn() };
});

describe("EconomicsPanel cost help (drill item 7a)", () => {
  it("explains fixed cost and unit variable cost in one line each", () => {
    render(<EconomicsPanel brandId="b1" productId="p1" economics={null} onClose={vi.fn()} onSaved={vi.fn()} />);
    const fixed = screen.getByText("固定成本").closest("label");
    const variable = screen.getByText("單位變動成本").closest("label");
    expect(fixed?.textContent).toContain("每月不管賣幾件都要付的錢");
    expect(variable?.textContent).toContain("每賣一件多花的錢");
  });
});
