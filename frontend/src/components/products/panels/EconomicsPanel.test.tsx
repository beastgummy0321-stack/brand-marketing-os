import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiResponseError } from "@/lib/http";
import { saveProductEconomics } from "@/lib/productsApi";
import { EconomicsPanel } from "./EconomicsPanel";

vi.mock("@/lib/productsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/productsApi")>("@/lib/productsApi");
  return { ...actual, saveProductEconomics: vi.fn() };
});

beforeEach(() => {
  vi.mocked(saveProductEconomics).mockReset();
});

function renderPanel(onSaved = vi.fn()) {
  render(<EconomicsPanel brandId="b1" productId="p1" economics={null} onClose={vi.fn()} onSaved={onSaved} />);
  return onSaved;
}

function input(label: string): HTMLInputElement {
  return screen.getByText(label).closest("label")!.querySelector("input")!;
}

describe("EconomicsPanel cost help (drill item 7a)", () => {
  it("explains fixed cost and unit variable cost in one line each", () => {
    renderPanel();
    const fixed = screen.getByText("固定成本").closest("label");
    const variable = screen.getByText("單位變動成本").closest("label");
    expect(fixed?.textContent).toContain("每月不管賣幾件都要付的錢");
    expect(variable?.textContent).toContain("每賣一件多花的錢");
  });
});

describe("EconomicsPanel sends what was typed (F47-I03, drill-10 乙 #8 #9)", () => {
  it("no longer says shipping may be negative", () => {
    renderPanel();
    expect(screen.queryByText(/可填負數/)).toBeNull();
    expect(screen.getByText("運費")).toBeTruthy();
  });

  it("sends typed numbers as typed and empty costs as null (never 0)", async () => {
    vi.mocked(saveProductEconomics).mockResolvedValue(undefined);
    const onSaved = renderPanel();
    fireEvent.change(input("售價"), { target: { value: "500" } });
    fireEvent.change(input("確認人是誰？"), { target: { value: "小陳" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存這筆經濟數字" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(vi.mocked(saveProductEconomics).mock.calls[0][2]).toMatchObject({
      selling_price: 500, fixed_cost: null, unit_variable_cost: null, shipping_cost: null, close_rate: null,
    });
  });

  it("shows the server's sentence under the refused field, keeps the value, and clears it on edit", async () => {
    vi.mocked(saveProductEconomics).mockRejectedValue(
      new ApiResponseError("運費不能是負數。", 400, { shipping_cost: "運費不能是負數。" }),
    );
    const onSaved = renderPanel();
    fireEvent.change(input("售價"), { target: { value: "500" } });
    fireEvent.change(input("運費"), { target: { value: "-20" } });
    fireEvent.change(input("確認人是誰？"), { target: { value: "小陳" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存這筆經濟數字" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("運費不能是負數。");
    // Under its own field, once (not repeated at the bottom of the form).
    expect(screen.getByText("運費").closest("label")?.contains(alert)).toBe(true);
    expect(screen.getAllByText("運費不能是負數。")).toHaveLength(1);
    expect(vi.mocked(saveProductEconomics).mock.calls[0][2]).toMatchObject({ shipping_cost: -20 });
    expect(input("運費").value).toBe("-20");
    expect(onSaved).not.toHaveBeenCalled();

    fireEvent.change(input("運費"), { target: { value: "20" } });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a sentence with no field at the bottom of the form", async () => {
    vi.mocked(saveProductEconomics).mockRejectedValue(new ApiResponseError("請選擇幣別。", 400));
    renderPanel();
    fireEvent.change(input("售價"), { target: { value: "500" } });
    fireEvent.change(input("確認人是誰？"), { target: { value: "小陳" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存這筆經濟數字" }));
    expect((await screen.findByRole("alert")).textContent).toBe("請選擇幣別。");
  });
});
