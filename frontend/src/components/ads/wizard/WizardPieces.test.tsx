import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { WizardProduct } from "@/lib/adsWizardApi";
import { UnderstandingView, UnderstoodField, priceText, sellWayNote, wizardSteps } from "./WizardPieces";

describe("wizard pieces (F30-I05)", () => {
  it("prints a price with the kit formatter, a foreign currency by code, and 價格未填 for unknown, zero or non-finite prices", () => {
    expect(priceText(1580, "TWD")).toBe("NT$1,580");
    expect(priceText(399.5, null)).toBe("NT$399.5");
    expect(priceText(12.3456, "USD")).toBe("USD 12.35");
    expect(priceText(null, "TWD")).toBe("價格未填");
    expect(priceText(Number.NaN, "TWD")).toBe("價格未填");
    expect(priceText(0, "TWD")).toBe("價格未填");
  });

  it("a sell-way note is 打平・offers: 缺成本 without a cost, 打平算不出 with a cost but no price, 沒有優惠 without offers", () => {
    const way = (over: Partial<WizardProduct>) => ({ break_even: 669, has_cost: true, derived_fields: [], offer_labels: ["組合價", "免運"], ...over }) as WizardProduct;
    expect(sellWayNote(way({}))).toBe("打平 669・組合價＋免運");
    expect(sellWayNote(way({ break_even: 249.5, offer_labels: [] }))).toBe("打平 249.5・沒有優惠");
    expect(sellWayNote(way({ break_even: null, has_cost: false }))).toBe("缺成本・組合價＋免運");
    expect(sellWayNote(way({ break_even: null, offer_labels: [] }))).toBe("打平算不出・沒有優惠");
  });

  it("marks a break-even built on a derived price or cost 「（推算）」 (F45, ads §6.49 Picker); a derived list price alone does not", () => {
    const way = (over: Partial<WizardProduct>) => ({ break_even: 669, has_cost: true, derived_fields: [], offer_labels: ["組合價"], ...over }) as WizardProduct;
    expect(sellWayNote(way({ derived_fields: ["list_price", "unit_variable_cost"] }))).toBe("打平 669（推算）・組合價");
    expect(sellWayNote(way({ derived_fields: ["selling_price"] }))).toBe("打平 669（推算）・組合價");
    expect(sellWayNote(way({ derived_fields: ["list_price"] }))).toBe("打平 669・組合價");
    expect(sellWayNote(way({}))).toBe("打平 669・組合價");
    expect(sellWayNote(way({ break_even: null, derived_fields: ["unit_variable_cost"] }))).toBe("打平算不出・組合價");
  });

  it("links step 1 back only once a campaign exists", () => {
    expect(wizardSteps("b").map((s) => s.to)).toEqual([undefined, undefined, undefined]);
    expect(wizardSteps("b", "c 1")[0].to).toBe("/brands/b/ads/new?created=c%201");
  });

  it("a guessed field is dashed with 「猜的，請確認」 and opens its editor when pressed", async () => {
    const onEdit = vi.fn();
    const { rerender } = render(<UnderstoodField field="audience" label="受眾方向" value="上班族" guessed editing={false} onEdit={onEdit} editor={<input aria-label="編輯中" />} />);
    const button = screen.getByRole("button", { name: "改受眾方向" });
    expect(button.className).toContain("border-dashed");
    expect(screen.getByText("猜的，請確認")).toBeTruthy();
    await userEvent.click(button);
    expect(onEdit).toHaveBeenCalledTimes(1);
    rerender(<UnderstoodField field="audience" label="受眾方向" value="上班族" guessed editing onEdit={onEdit} editor={<input aria-label="編輯中" />} />);
    expect(screen.getByLabelText("編輯中")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "改受眾方向" })).toBeNull();
  });

  it("a field without onEdit is plain text, not a control, and not dashed when owned", () => {
    render(<UnderstoodField field="platform" label="平台" value="Meta" guessed={false} editing={false} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("Meta").closest("[data-field]")?.className).not.toContain("border-dashed");
  });

  it("understanding: a running wait line that never claims a queue position; failed: ReadFailed with 重試", async () => {
    const onRetry = vi.fn();
    const { rerender } = render(<MemoryRouter><UnderstandingView brandId="b" failed={null} waitedSeconds={0} onRetry={onRetry} /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "系統理解中" })).toBeTruthy();
    expect(screen.getByText("AI 正在處理・剛開始")).toBeTruthy();
    expect(screen.queryByText(/第 0 件/)).toBeNull();
    rerender(<MemoryRouter><UnderstandingView brandId="b" failed="離線" waitedSeconds={3} onRetry={onRetry} /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "系統理解" })).toBeTruthy();
    expect(screen.getByText(/系統理解的結果讀不到（離線）；你選的商品和目標都還在/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
