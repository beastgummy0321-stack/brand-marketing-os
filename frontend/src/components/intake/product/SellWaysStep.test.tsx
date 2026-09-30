/** frontend/src/components/intake/product/SellWaysStep.test.tsx — product onboarding `#/p4` 怎麼賣、賣多少 (F43-I11):
 * one `SellWayTable` row per sell-way (derived 原價／成本 as the server's placeholder with its source line, 打平線 and
 * offers from the server), 成交率 only for lead/booking brands, 「＋新增賣法」, refused prices, 每筆上限 above 打平線
 * marked, the reference-value fold, and 完成商品建檔 = PUT (raw inputs only) → complete → next. The fixture mirrors
 * `app/intake/product_onboarding.py::get_sell_ways()`. No server: the API calls are fakes. */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeProductApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeProductApi")>("@/lib/intakeProductApi");
  return { ...actual, fetchProductSellWays: vi.fn(), saveProductSellWays: vi.fn(), completeProductOnboarding: vi.fn() };
});

import type { ProductSellWays, SellWayRow } from "@/lib/intakeProductApi";
import { completeProductOnboarding, fetchProductSellWays, saveProductSellWays } from "@/lib/intakeProductApi";
import type { StepNav } from "../OnboardingStepHead";
import { SellWaysStep } from "./SellWaysStep";

const mockFetch = vi.mocked(fetchProductSellWays);
const mockSave = vi.mocked(saveProductSellWays);
const mockComplete = vi.mocked(completeProductOnboarding);

const PRODUCT = "綜合維他命軟糖（成人款・60 顆）";
const NAV: StepNav = {
  crumb: [{ label: "商品" }, { label: "商品建檔", strong: true }, { label: PRODUCT }],
  steps: ["商品是什麼", "誰會買", "證據與說法", "賣法與價格", "完成"],
  current: 4,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function way(over: Partial<SellWayRow>): SellWayRow {
  return {
    id: "sw_1", name: "單盒", components: [{ product_id: "prd_1", name: PRODUCT, qty: 1 }], qty: 1,
    price: 399, list_price: 399, list_price_derived: true, list_price_note: "同售價",
    cost: 90, cost_derived: false, cost_note: "", shipping: 60, break_even: 249,
    cap_per_sale: 249, cap_is_default: true, landing_url: "https://beastgummy.tw/p/multi", landing_is_default: true,
    offer_labels: [], offer_notes: ["售價未滿 NT$999，不適用滿額免運"], assumptions: [], source: "saved", note: "",
    ...over,
  };
}

const SINGLE = way({});
const TRIPLE = way({
  id: "sw_3", name: "三盒組", components: [{ product_id: "prd_1", name: PRODUCT, qty: 3 }], qty: 3,
  price: 999, list_price: 1197, list_price_derived: true, list_price_note: "3 件單價相加",
  cost: 270, cost_derived: true, cost_note: "3 件成本相加", break_even: 669, cap_per_sale: 669,
  offer_labels: ["組合價 省 198", "滿 NT$999 免運"], offer_notes: [],
});

function sellWays(over: Partial<ProductSellWays> = {}): ProductSellWays {
  return {
    sell_ways: [SINGLE, TRIPLE],
    show_close_rate: false,
    assumptions: {
      gross_margin: { value: 0.45, source_text: "毛利率假設 45% · 美國 2025 基準，起點用" },
      shipping_cost: { value: 80, source_text: "運費假設 NT$80 · 台灣宅配均價" },
    },
    ...over,
  };
}

function renderStep(onNext = vi.fn()) {
  render(<SellWaysStep brandId="brd_1" productId="prd_1" nav={NAV} back={{ label: "證據與說法", onClick: vi.fn() }} onNext={onNext} />);
  return onNext;
}

const finish = () => screen.getByRole("button", { name: "完成商品建檔 →" });
const row = (key: string) => document.querySelector(`tr[data-row="${key}"]`) as HTMLElement;
const input = (name: string) => screen.getByRole("textbox", { name }) as HTMLInputElement;

describe("SellWaysStep", () => {
  it("每種賣法一列：推算的原價／成本是伺服器的值並寫出來源；打平線與優惠照伺服器", async () => {
    mockFetch.mockResolvedValue(sellWays());
    renderStep();

    const triple = await screen.findByRole("textbox", { name: "三盒組的原價" }) as HTMLInputElement;
    expect(mockFetch).toHaveBeenCalledWith("brd_1", "prd_1");
    // A derived value is the placeholder of an empty input, with its source line.
    expect(triple.value).toBe("");
    expect(triple.placeholder).toBe("1,197");
    expect(screen.getByText("3 件單價相加")).toBeTruthy();
    expect(input("三盒組的成本").placeholder).toBe("270");
    expect(screen.getByText("3 件成本相加")).toBeTruthy();
    expect(input("單盒的成本").value).toBe("90");
    expect(input("單盒的原價").placeholder).toBe("399");
    // 每筆上限 defaults to the break-even without being typed.
    expect(input("三盒組的每筆上限").value).toBe("");
    expect(input("三盒組的每筆上限").placeholder).toBe("669");

    const breakEvens = [...document.querySelectorAll("[data-break-even]")].map((td) => td.textContent);
    expect(breakEvens).toEqual(["249", "669"]);
    expect(screen.getByText("組合價 省 198").getAttribute("data-tone")).toBe("ok");
    expect(screen.getByText("滿 NT$999 免運")).toBeTruthy();
    expect(screen.getAllByText("沒有優惠")).toHaveLength(1);
    expect(screen.getAllByText("落地頁：商品頁")).toHaveLength(2);
    expect(screen.getAllByText(`${PRODUCT} ×3`)).toHaveLength(1);
    expect(screen.queryByRole("columnheader", { name: "成交率" })).toBeNull();
    expect(screen.getByText(/打平線＝售價 − 成本 − 運費成本/)).toBeTruthy();
  });

  it("名單／預約型品牌才多一欄成交率（百分比）", async () => {
    mockFetch.mockResolvedValue(sellWays({
      show_close_rate: true,
      sell_ways: [way({ close_rate: 0.2, break_even: 49.8, cap_per_sale: 49.8 })],
    }));
    renderStep();

    expect(await screen.findByRole("columnheader", { name: "成交率" })).toBeTruthy();
    expect(input("單盒的成交率").value).toBe("20");
    expect(document.querySelector("[data-break-even]")?.textContent).toBe("50");
    expect(screen.getByText(/打平線＝（售價 − 成本 − 運費成本）× 成交率/)).toBeTruthy();
  });

  it("售價空白、0 或負數不送出，並在那一格寫出原因", async () => {
    mockFetch.mockResolvedValue(sellWays());
    const onNext = renderStep();

    const price = await screen.findByRole("textbox", { name: "單盒的售價" });
    await userEvent.clear(price);
    await userEvent.type(price, "0");
    await userEvent.click(finish());
    expect(await within(row("sw0")).findByText("售價要大於 0")).toBeTruthy();

    await userEvent.clear(price);
    await userEvent.type(price, "-5");
    expect(within(row("sw0")).getByText("售價要大於 0")).toBeTruthy();
    await userEvent.clear(price);
    await userEvent.click(finish());
    expect(within(row("sw0")).getByText("售價要大於 0")).toBeTruthy();

    const ship = input("三盒組的運費成本");
    await userEvent.clear(ship);
    await userEvent.type(ship, "-1");
    await userEvent.click(finish());
    expect(within(row("sw1")).getByText("不能是負數")).toBeTruthy();
    expect(mockSave).not.toHaveBeenCalled();
    expect(mockComplete).not.toHaveBeenCalled();
    expect(onNext).not.toHaveBeenCalled();
  });

  it("每筆上限可以高於打平線，但會標出來", async () => {
    mockFetch.mockResolvedValue(sellWays());
    renderStep();

    const cap = await screen.findByRole("textbox", { name: "單盒的每筆上限" });
    await userEvent.type(cap, "300");
    expect(within(row("sw0")).getByText("高於打平線")).toBeTruthy();
    await userEvent.clear(cap);
    await userEvent.type(cap, "200");
    expect(within(row("sw0")).queryByText("高於打平線")).toBeNull();
  });

  it("新增一列（名稱、幾件、數字），離開這列就存；打平線與優惠換成伺服器重算的結果", async () => {
    mockFetch.mockResolvedValue(sellWays());
    const six = way({
      id: "sw_6", name: "六盒組", components: [{ product_id: "prd_1", name: PRODUCT, qty: 6 }], qty: 6,
      price: 1899, list_price: 2394, list_price_note: "6 件單價相加", cost: 540, cost_derived: true, cost_note: "6 件成本相加",
      break_even: 1299, cap_per_sale: 1299, offer_labels: ["組合價 省 495", "滿 NT$999 免運"], offer_notes: [],
    });
    mockSave.mockResolvedValue(sellWays({ sell_ways: [SINGLE, TRIPLE, six] }));
    renderStep();

    await userEvent.click(await screen.findByRole("button", { name: "＋新增賣法（例如六盒組）" }));
    const names = screen.getAllByRole("textbox", { name: "賣法名稱" });
    await userEvent.type(names[2], "六盒組");
    const qty = input("六盒組的數量");
    await userEvent.clear(qty);
    await userEvent.type(qty, "0");
    await userEvent.click(document.body);
    expect(await within(row("sw2")).findByText("數量要是正整數")).toBeTruthy();
    expect(mockSave).not.toHaveBeenCalled();
    await userEvent.clear(qty);
    await userEvent.type(qty, "6");
    await userEvent.type(input("六盒組的售價"), "1899");
    expect(row("sw2").querySelector("[data-break-even]")?.textContent).toBe("—");
    await userEvent.click(document.body);

    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    expect(mockSave.mock.calls[0][2][2]).toEqual({
      id: null, name: "六盒組", qty: 6, price: 1899, list_price: null, cost: null, shipping: null,
      cap_per_sale: null, landing_url: null, assumptions: [],
    });
    await waitFor(() => expect(row("sw2").querySelector("[data-break-even]")?.textContent).toBe("1,299"));
    expect(within(row("sw2")).getByText("6 件單價相加")).toBeTruthy();
    expect(screen.getByText("組合價 省 495")).toBeTruthy();
  });

  it("完成商品建檔：PUT 只帶使用者填的原始值（推算值不當成使用者的值送），再 complete，成功才往下", async () => {
    mockFetch.mockResolvedValue(sellWays());
    mockSave.mockResolvedValue(sellWays());
    mockComplete.mockResolvedValue({ step: 5, completed: true, prefill_status: "done", prefill_error: null });
    const onNext = renderStep();

    await screen.findByRole("textbox", { name: "三盒組的原價" });
    await userEvent.click(screen.getByRole("button", { name: "換「三盒組」的落地頁" }));
    await userEvent.type(input("三盒組的落地頁"), "https://beastgummy.tw/shop/three");
    await userEvent.click(finish());

    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
    expect(mockSave).toHaveBeenCalledWith("brd_1", "prd_1", [
      { id: "sw_1", name: "單盒", qty: 1, price: 399, list_price: null, cost: 90, shipping: 60, cap_per_sale: null, landing_url: null, assumptions: [] },
      { id: "sw_3", name: "三盒組", qty: 3, price: 999, list_price: null, cost: null, shipping: 60, cap_per_sale: null, landing_url: "https://beastgummy.tw/shop/three", assumptions: [] },
    ]);
    expect(mockComplete).toHaveBeenCalledWith("brd_1", "prd_1");
    expect(mockSave.mock.invocationCallOrder[mockSave.mock.invocationCallOrder.length - 1]).toBeLessThan(mockComplete.mock.invocationCallOrder[0]);
  });

  it("沒改過任何東西時完成不重送，直接 complete；complete 失敗就留在這步並顯示原因", async () => {
    mockFetch.mockResolvedValue(sellWays());
    mockComplete.mockRejectedValue(new Error("「證據與說法」還沒存，先存好這一步再完成。"));
    const onNext = renderStep();

    await screen.findByRole("textbox", { name: "三盒組的原價" });
    await userEvent.click(finish());
    expect(await screen.findByText("「證據與說法」還沒存，先存好這一步再完成。")).toBeTruthy();
    expect(mockSave).not.toHaveBeenCalled();
    expect(onNext).not.toHaveBeenCalled();
  });

  it("商品頁讀到的建議列（還沒存）可以拿掉；沒有任何賣法時先給一列空白", async () => {
    mockFetch.mockResolvedValue(sellWays({
      sell_ways: [
        way({ id: null, name: "單盒", source: "ai", list_price: 450, list_price_derived: false, list_price_note: "", cost: null, shipping: null, break_even: null, cap_per_sale: null, offer_labels: [], offer_notes: [] }),
        way({ id: null, name: "兩盒組", qty: 2, components: [{ product_id: "prd_1", name: PRODUCT, qty: 2 }], source: "ai", price: 760, list_price: null, list_price_derived: false, list_price_note: "", cost: null, shipping: null, break_even: null, cap_per_sale: null, offer_labels: [], offer_notes: [] }),
      ],
    }));
    renderStep();

    expect((await screen.findByRole("textbox", { name: "單盒的原價" }) as HTMLInputElement).value).toBe("450");
    expect(input("兩盒組的數量").value).toBe("2");
    await userEvent.click(screen.getByRole("button", { name: "拿掉「兩盒組」" }));
    expect(screen.queryByRole("textbox", { name: "兩盒組的售價" })).toBeNull();
    // The last row has no ×.
    expect(screen.queryByRole("button", { name: "拿掉「單盒」" })).toBeNull();

    cleanup();
    mockFetch.mockResolvedValue(sellWays({ sell_ways: [] }));
    renderStep();
    const names = await screen.findAllByRole("textbox", { name: "賣法名稱" });
    expect(names).toHaveLength(1);
    expect(input("新的賣法的數量").value).toBe("1");
  });

  it("進階：不知道成本就用同業參考值填空著的格子，標「假設」並送出旗標；改掉就不再是假設", async () => {
    mockFetch.mockResolvedValue(sellWays({ sell_ways: [way({ cost: null, break_even: null, cap_per_sale: null, shipping: null })] }));
    mockSave.mockResolvedValue(sellWays({ sell_ways: [way({ cost: 219, shipping: 80, break_even: 100, assumptions: ["cost", "shipping"] })] }));
    renderStep();

    await userEvent.click(await screen.findByText("進階：不知道成本？用同業參考值（會標示是假設）"));
    expect(screen.getByText("毛利率假設 45% · 美國 2025 基準，起點用")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "空著的成本填參考值" }));
    await userEvent.click(screen.getByRole("button", { name: "空著的運費成本填參考值" }));
    expect(input("單盒的成本").value).toBe("219");
    expect(input("單盒的運費成本").value).toBe("80");
    expect(within(row("sw0")).getAllByText("假設")).toHaveLength(2);

    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    expect(mockSave.mock.calls[mockSave.mock.calls.length - 1][2][0]).toMatchObject({ cost: 219, shipping: 80, assumptions: ["cost", "shipping"] });

    await userEvent.clear(input("單盒的成本"));
    await userEvent.type(input("單盒的成本"), "150");
    expect(within(row("sw0")).getAllByText("假設")).toHaveLength(1);
  });
});
