/** frontend/src/components/intake/product/SellWaysStep.test.tsx — product onboarding step 4 怎麼賣、賣多少 (F45-I02):
 * 基本賣法 / 組合賣法 summary rows, one row open inline as the editor, derived numbers labelled 推算, the cost gap with
 * 「去填單盒的成本 →」 and the way back, the contents (base × qty, Σqty ≥ 2, this product's bases only), the `used_by`
 * delete guard, the free-shipping sentence and the PUT body (composed rows name their bases, no `qty`). Fixtures are the
 * prototype's product (`.harness/scratch/prototype/f45-sell-way-components`) shaped like
 * `app/intake/product_onboarding.py::_sell_way_row()` (see `app/tests/test_intake_product_api.py` `_b1`). No server. */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
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

const PRODUCT = "Beast Gummy 能量軟糖";
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
    id: "sw_x", name: "", shape: "base", components: [],
    price: null, price_derived: false, price_note: "",
    list_price: null, list_price_derived: false, list_price_note: "",
    cost: null, cost_derived: false, cost_note: "", cost_estimate: null, cost_missing: [],
    shipping: 60, free_shipping: false, break_even: null, break_even_derived: false,
    cap_per_sale: null, cap_is_default: true, landing_url: "https://beastgummy.tw/shop/energy", landing_is_default: true,
    offer_sentences: [], offer_labels: [], offer_notes: [], assumptions: [], used_by: [], source: "saved", note: "",
    ...over,
  };
}

const TRIAL = way({ id: "sw_trial", name: "體驗包（3 顆）", price: 100, cost: 25, shipping: 35, break_even: 40, cap_per_sale: 40, used_by: ["5 盒＋2 包"] });
const BOX = way({ id: "sw_box", name: "單盒", price: 180, cost: 50, break_even: 70, cap_per_sale: 70, used_by: ["12 盒", "5 盒＋2 包"] });
const C12 = way({
  id: "sw_c12", name: "12 盒", shape: "composed",
  components: [{ sell_way_id: "sw_box", name: "單盒", qty: 12, price: 180, cost: 50 }],
  price: 1980, list_price: 2160, list_price_derived: true, list_price_note: "推算：單盒 180 × 12",
  cost: 600, cost_derived: true, cost_note: "推算：單盒 50 × 12", cost_estimate: 600,
  free_shipping: true, break_even: 1320, break_even_derived: true, cap_per_sale: 1320,
  offer_sentences: ["優惠價 NT$1,980（原價 NT$2,160）", "這組免運"], offer_labels: ["組合價 省 180", "這組免運"],
});
const C52 = way({
  id: "sw_c52", name: "5 盒＋2 包", shape: "composed",
  components: [
    { sell_way_id: "sw_box", name: "單盒", qty: 5, price: 180, cost: 50 },
    { sell_way_id: "sw_trial", name: "體驗包（3 顆）", qty: 2, price: 100, cost: 25 },
  ],
  price: 990, list_price: 1100, list_price_derived: true, list_price_note: "推算：單盒 180 × 5 ＋ 體驗包（3 顆） 100 × 2",
  cost: 300, cost_derived: true, cost_note: "推算：單盒 50 × 5 ＋ 體驗包（3 顆） 25 × 2", cost_estimate: 300,
  break_even: 630, break_even_derived: true, cap_per_sale: 630,
  offer_sentences: ["優惠價 NT$990（原價 NT$1,100）"], offer_labels: ["組合價 省 110"],
});

/** 單盒 without a cost: neither composed cost can be derived. */
const NO_COST = {
  box: way({ ...BOX, cost: null, break_even: null, cap_per_sale: null }),
  c12: way({ ...C12, cost: null, cost_derived: false, cost_note: "", cost_estimate: null, cost_missing: [{ sell_way_id: "sw_box", name: "單盒" }], break_even: null, break_even_derived: false, cap_per_sale: null }),
  c52: way({ ...C52, cost: null, cost_derived: false, cost_note: "", cost_estimate: null, cost_missing: [{ sell_way_id: "sw_box", name: "單盒" }], break_even: null, break_even_derived: false, cap_per_sale: null }),
};

function sellWays(list: SellWayRow[] = [TRIAL, BOX, C12, C52], over: Partial<ProductSellWays> = {}): ProductSellWays {
  return {
    sell_ways: list,
    show_close_rate: false,
    assumptions: {
      gross_margin: { value: 0.65, source_text: "軟糖類同業毛利約 65%（假設值，之後拿到真成本再改）" },
      shipping_cost: { value: 80, source_text: "運費假設 NT$80 · 台灣宅配均價" },
    },
    ...over,
  };
}

function renderStep(onNext = vi.fn()) {
  render(
    <MemoryRouter>
      <SellWaysStep brandId="brd_1" productId="prd_1" nav={NAV} back={{ label: "證據與說法", onClick: vi.fn() }} onNext={onNext} />
    </MemoryRouter>,
  );
  return onNext;
}

const summary = (name: string) => document.querySelector(`[data-sw-row="${name}"]:not([data-state])`) as HTMLElement;
const editor = () => document.querySelector('[data-state="editing"]') as HTMLElement;
const field = (label: string) => within(editor()).getByLabelText(label) as HTMLInputElement;
const edit = async (name: string) => userEvent.click(await screen.findByRole("button", { name: `編輯「${name}」` }));
const finish = () => screen.getByRole("button", { name: "完成商品建檔 →" });
const lastBody = () => mockSave.mock.calls[mockSave.mock.calls.length - 1][2];

describe("SellWaysStep", () => {
  it("基本賣法／組合賣法兩段摘要：內容、售價、打平（推算）、成本還沒填、優惠句", async () => {
    mockFetch.mockResolvedValue(sellWays([TRIAL, NO_COST.box, C12, C52]));
    renderStep();

    await screen.findByRole("button", { name: "編輯「12 盒」" });
    expect(mockFetch).toHaveBeenCalledWith("brd_1", "prd_1");
    const base = document.querySelector('[data-section="base"]') as HTMLElement;
    const composed = document.querySelector('[data-section="composed"]') as HTMLElement;
    expect([...base.querySelectorAll("[data-sw-row]")].map((e) => e.getAttribute("data-sw-row"))).toEqual(["體驗包（3 顆）", "單盒"]);
    expect([...composed.querySelectorAll("[data-sw-row]")].map((e) => e.getAttribute("data-sw-row"))).toEqual(["12 盒", "5 盒＋2 包"]);
    expect(within(summary("單盒")).getByText("一份")).toBeTruthy();
    expect(within(summary("單盒")).getByText("成本還沒填")).toBeTruthy();
    expect(within(summary("單盒")).getByText("還算不出來")).toBeTruthy();
    expect(within(summary("5 盒＋2 包")).getByText("單盒 × 5 ＋ 體驗包（3 顆） × 2")).toBeTruthy();
    expect(within(summary("12 盒")).getByText("單盒 × 12")).toBeTruthy();
    expect(within(summary("12 盒")).getByText("1,320")).toBeTruthy();
    expect(within(summary("12 盒")).getByText("推算").getAttribute("data-tone")).toBe("accent");
    expect(within(summary("12 盒")).getByText("這組免運").getAttribute("data-tone")).toBe("ok");
    expect(within(summary("體驗包（3 顆）")).getByText("沒有優惠")).toBeTruthy();
    expect(within(summary("體驗包（3 顆）")).queryByText("推算")).toBeNull();
    // 單盒 has no cost and 組合 use it: the bar points at it.
    expect(screen.getByRole("button", { name: "單盒還沒填成本" })).toBeTruthy();
  });

  it("組合・成本空著：成本是伺服器推算的 placeholder 並寫出「推算：…」；打平帶推算；免運句子出現", async () => {
    mockFetch.mockResolvedValue(sellWays());
    renderStep();
    await edit("12 盒");

    expect(within(editor()).getByText("組合賣法")).toBeTruthy();
    expect(field("成本").value).toBe("");
    expect(field("成本").placeholder).toBe("600");
    expect(within(editor()).getByText("推算：單盒 50 × 12")).toBeTruthy();
    expect(field("原價").placeholder).toBe("2,160");
    expect(within(editor()).getByText("推算：單盒 180 × 12")).toBeTruthy();
    expect(field("售價").value).toBe("1980");
    const result = editor().querySelector('[data-slot="sell-way-result"]') as HTMLElement;
    expect(within(result).getByText("每筆最多花 NT$1,320")).toBeTruthy();
    expect(within(result).getByText("推算")).toBeTruthy();
    expect(within(result).getByText("售價 1,980 − 成本 600（推算） − 運費成本 60")).toBeTruthy();
    expect(within(result).getByText("「這組免運」")).toBeTruthy();
    expect(within(result).getByText("「優惠價 NT$1,980（原價 NT$2,160）」")).toBeTruthy();
    expect((within(editor()).getByRole("checkbox", { name: "這個賣法免運" }) as HTMLInputElement).checked).toBe(true);
    // Contents: 〈base〉 × qty with the base's own numbers.
    expect((within(editor()).getByRole("textbox", { name: "單盒的數量" }) as HTMLInputElement).value).toBe("12");
    expect(within(editor()).getByText(/售價 180・成本/)).toBeTruthy();
  });

  it("組合・成本自己填：沒有推算，旁邊寫「照內容推算是 600」", async () => {
    const typed = way({ ...C12, cost: 560, cost_derived: false, cost_note: "", break_even: 1360, break_even_derived: false, free_shipping: false, offer_sentences: ["優惠價 NT$1,980（原價 NT$2,160）"] });
    mockFetch.mockResolvedValue(sellWays([TRIAL, BOX, typed, C52]));
    renderStep();
    await edit("12 盒");

    expect(field("成本").value).toBe("560");
    expect(within(editor()).getByText("照內容推算是 600")).toBeTruthy();
    expect(within(editor()).queryByText("推算：單盒 50 × 12")).toBeNull();
    const result = editor().querySelector('[data-slot="sell-way-result"]') as HTMLElement;
    expect(within(result).getByText("每筆最多花 NT$1,360")).toBeTruthy();
    expect(within(result).queryByText("推算")).toBeNull();
    expect(within(result).queryByText("「這組免運」")).toBeNull();
  });

  it("單盒還沒填成本：組合寫「還算不出來」，「去填單盒的成本 →」打開單盒的成本，填好了回到組合", async () => {
    mockFetch.mockResolvedValue(sellWays([TRIAL, NO_COST.box, NO_COST.c12, NO_COST.c52]));
    mockSave.mockResolvedValue(sellWays());
    renderStep();
    await edit("5 盒＋2 包");

    expect(field("成本").placeholder).toBe("—");
    expect(within(editor()).getByText("單盒還沒填成本，推算不出來")).toBeTruthy();
    expect(within(editor()).getByText("還算不出來：單盒還沒填成本")).toBeTruthy();
    await userEvent.click(within(editor()).getByRole("button", { name: "去填單盒的成本 →" }));

    expect(editor().getAttribute("data-sw-row")).toBe("單盒");
    expect(within(editor()).getByText("「5 盒＋2 包」要用單盒的成本才算得出打平")).toBeTruthy();
    expect(within(editor()).getByText("一份就是一個單位，不用填數量")).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(field("成本")));
    await userEvent.type(field("成本"), "50");
    await userEvent.click(within(editor()).getByRole("button", { name: "填好了，回到「5 盒＋2 包」" }));

    await waitFor(() => expect(editor().getAttribute("data-sw-row")).toBe("5 盒＋2 包"));
    expect(lastBody().find((r) => r.name === "單盒")).toMatchObject({ id: "sw_box", cost: 50 });
    expect(screen.getByRole("status").textContent).toBe("「5 盒＋2 包」的打平算出來了：每筆最多花 NT$630");
    expect(within(editor()).getByText("每筆最多花 NT$630")).toBeTruthy();
  });

  it("新增組合：只能挑這個商品的基本賣法、數量要是正整數、只放 1 份不算組合；都放進來了就給「＋新增基本賣法」", async () => {
    mockFetch.mockResolvedValue(sellWays());
    renderStep();
    await userEvent.click(await screen.findByRole("button", { name: "＋組合賣法（例如 6 盒）" }));

    const picker = editor().querySelector('[data-slot="sell-way-picker"]') as HTMLElement;
    expect(within(picker).getAllByRole("button").map((b) => b.textContent)).toEqual(["體驗包（3 顆）售價 100", "單盒售價 180"]);
    await userEvent.type(field("名稱"), "6 盒");
    await userEvent.click(within(picker).getByRole("button", { name: /單盒/ }));
    const qty = within(editor()).getByRole("textbox", { name: "單盒的數量" });
    expect(document.activeElement).toBe(qty);
    await userEvent.type(qty, "0");
    expect(within(editor()).getByText("數量要是正整數")).toBeTruthy();
    await userEvent.clear(qty);
    await userEvent.type(qty, "1");
    expect(within(editor()).getByText("只放 1 份就跟「單盒」一樣；數量至少 2")).toBeTruthy();
    await userEvent.click(within(editor()).getByRole("button", { name: "完成" }));
    expect(mockSave).not.toHaveBeenCalled();

    await userEvent.click(within(editor()).getByRole("button", { name: "＋再放一種賣法" }));
    await userEvent.click(within(editor()).getByRole("button", { name: /體驗包/ }));
    await userEvent.click(within(editor()).getByRole("button", { name: "＋再放一種賣法" }));
    expect(within(editor()).getByText("這個商品的基本賣法都放進來了")).toBeTruthy();
    expect(within(editor()).getByRole("button", { name: "＋新增基本賣法" })).toBeTruthy();
  });

  it("新組合存檔：PUT 帶整份清單，組合用名字指基本賣法、沒有 qty；售價空著＝null（推算）", async () => {
    mockFetch.mockResolvedValue(sellWays());
    const six = way({ id: "sw_c6", name: "6 盒", shape: "composed", components: [{ sell_way_id: "sw_box", name: "單盒", qty: 6, price: 180, cost: 50 }], price: 1080, price_derived: true, price_note: "推算：單盒 180 × 6", break_even: 720, break_even_derived: true });
    mockSave.mockResolvedValue(sellWays([TRIAL, BOX, C12, C52, six]));
    renderStep();
    await userEvent.click(await screen.findByRole("button", { name: "＋組合賣法（例如 6 盒）" }));
    await userEvent.type(field("名稱"), "6 盒");
    await userEvent.click(within(editor()).getByRole("button", { name: /單盒/ }));
    await userEvent.type(within(editor()).getByRole("textbox", { name: "單盒的數量" }), "6");
    await userEvent.click(within(editor()).getByRole("button", { name: "完成" }));

    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    const body = lastBody();
    expect(body.map((r) => r.name)).toEqual(["體驗包（3 顆）", "單盒", "12 盒", "5 盒＋2 包", "6 盒"]);
    expect(body[4]).toEqual({
      id: null, name: "6 盒", price: null, list_price: null, cost: null, shipping: null, cap_per_sale: null, landing_url: null,
      assumptions: [], free_shipping: false, components: [{ base: "單盒", qty: 6 }],
    });
    expect(body[2]).toMatchObject({ id: "sw_c12", price: 1980, list_price: null, cost: null, free_shipping: true, components: [{ base: "單盒", qty: 12 }] });
    expect(body[1]).toEqual({
      id: "sw_box", name: "單盒", price: 180, list_price: null, cost: 50, shipping: 60, cap_per_sale: null, landing_url: null,
      assumptions: [], free_shipping: false,
    });
    for (const row of body) expect(row).not.toHaveProperty("qty");
    await waitFor(() => expect(editor()).toBeNull());
    expect(screen.getByRole("status").textContent).toBe("已儲存「6 盒」");
    expect(within(summary("6 盒")).getByText("1,080")).toBeTruthy();
    expect(within(summary("6 盒")).getAllByText("推算")).toHaveLength(2);
  });

  it("勾「這個賣法免運」就存，送 free_shipping，伺服器回的免運句子顯示在優惠", async () => {
    mockFetch.mockResolvedValue(sellWays());
    mockSave.mockResolvedValue(sellWays([TRIAL, way({ ...BOX, free_shipping: true, offer_sentences: ["免運"] }), C12, C52]));
    renderStep();
    await edit("單盒");

    await userEvent.click(within(editor()).getByRole("checkbox", { name: "這個賣法免運" }));
    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    expect(lastBody()[1]).toMatchObject({ name: "單盒", free_shipping: true });
    expect(await within(editor()).findByText("「免運」")).toBeTruthy();
  });

  it("被組合用到的基本賣法不能刪；刪組合被伺服器擋就照原文顯示並留著", async () => {
    mockFetch.mockResolvedValue(sellWays());
    mockSave.mockRejectedValue(new Error("「單盒」還在「12 盒」裡，先從組合拿掉。"));
    renderStep();
    await edit("單盒");

    expect(within(editor()).getByText("「12 盒」「5 盒＋2 包」用到它，先從組合拿掉才能刪")).toBeTruthy();
    expect(within(editor()).queryByRole("button", { name: "刪除這個賣法" })).toBeNull();

    await userEvent.click(within(editor()).getByRole("button", { name: "完成" }));
    await edit("12 盒");
    await userEvent.click(within(editor()).getByRole("button", { name: "刪除這個賣法" }));
    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    expect(lastBody().map((r) => r.name)).toEqual(["體驗包（3 顆）", "單盒", "5 盒＋2 包"]);
    expect(await screen.findByText("「單盒」還在「12 盒」裡，先從組合拿掉。")).toBeTruthy();
    expect(editor().getAttribute("data-sw-row")).toBe("12 盒");
  });

  it("基本賣法：售價要填、不能 0；不送出", async () => {
    mockFetch.mockResolvedValue(sellWays());
    const onNext = renderStep();
    await edit("單盒");

    await userEvent.clear(field("售價"));
    await userEvent.click(within(editor()).getByRole("button", { name: "完成" }));
    expect(within(editor()).getByText("售價要填")).toBeTruthy();
    await userEvent.type(field("售價"), "0");
    expect(within(editor()).getByText("售價要大於 0")).toBeTruthy();
    await userEvent.click(finish());
    expect(mockSave).not.toHaveBeenCalled();
    expect(mockComplete).not.toHaveBeenCalled();
    expect(onNext).not.toHaveBeenCalled();
  });

  it("完成商品建檔：沒改過就不重送，直接 complete；complete 失敗留在這步並顯示原因", async () => {
    mockFetch.mockResolvedValue(sellWays());
    mockComplete.mockRejectedValue(new Error("「證據與說法」還沒存，先存好這一步再完成。"));
    const onNext = renderStep();

    await screen.findByRole("button", { name: "編輯「12 盒」" });
    await userEvent.click(finish());
    expect(await screen.findByText("「證據與說法」還沒存，先存好這一步再完成。")).toBeTruthy();
    expect(mockSave).not.toHaveBeenCalled();
    expect(onNext).not.toHaveBeenCalled();

    mockComplete.mockResolvedValue({ step: 5, completed: true, prefill_status: "done", prefill_error: null });
    await userEvent.click(finish());
    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
  });

  it("商品頁讀到的建議（還沒存）：qty N 的是組合，指向一份的那個基本賣法；第一次存就一起送", async () => {
    mockFetch.mockResolvedValue(sellWays([
      way({ id: null, name: "三盒組", shape: "composed", source: "ai", note: "商品頁", price: 499, list_price: 540, shipping: null,
        components: [{ sell_way_id: null, name: "單盒", qty: 3, price: 180, cost: null }] }),
      way({ id: null, name: "單盒", source: "ai", note: "商品頁", price: 180, shipping: null }),
    ]));
    mockSave.mockResolvedValue(sellWays());
    const onNext = renderStep();
    mockComplete.mockResolvedValue({ step: 5, completed: true, prefill_status: "done", prefill_error: null });

    await screen.findByRole("button", { name: "編輯「三盒組」" });
    expect(within(summary("三盒組")).getByText("單盒 × 3")).toBeTruthy();
    expect(within(summary("單盒")).getByText("成本還沒填")).toBeTruthy();
    await userEvent.click(finish());
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(lastBody()).toEqual([
      { id: null, name: "三盒組", price: 499, list_price: 540, cost: null, shipping: null, cap_per_sale: null, landing_url: null, assumptions: [], free_shipping: false, components: [{ base: "單盒", qty: 3 }] },
      { id: null, name: "單盒", price: 180, list_price: null, cost: null, shipping: null, cap_per_sale: null, landing_url: null, assumptions: [], free_shipping: false },
    ]);
  });

  it("沒有任何賣法時先打開一個空白的基本賣法", async () => {
    mockFetch.mockResolvedValue(sellWays([]));
    renderStep();
    expect(await screen.findByText("新的基本賣法")).toBeTruthy();
    expect(field("名稱").value).toBe("");
    expect(within(editor()).getByText("一份就是一個單位，不用填數量")).toBeTruthy();
    expect(screen.getByText("還沒有組合")).toBeTruthy();
  });

  it("進階：不知道成本就用同業參考值填空著的基本賣法成本，標「假設」並送出旗標", async () => {
    mockFetch.mockResolvedValue(sellWays([TRIAL, NO_COST.box, NO_COST.c12, NO_COST.c52]));
    mockSave.mockResolvedValue(sellWays());
    renderStep();

    await userEvent.click(await screen.findByText("進階：不知道成本？用同業參考值（會標示是假設）"));
    await userEvent.click(screen.getByRole("button", { name: "空著的成本填參考值" }));
    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    const body = lastBody();
    expect(body[1]).toMatchObject({ name: "單盒", cost: 63, assumptions: ["cost"] });
    // A composed cost comes from its bases: not filled.
    expect(body[2]).toMatchObject({ name: "12 盒", cost: null, assumptions: [] });
    await edit("單盒");
    expect(field("成本").value).toBe("63");
    expect(within(editor()).getByText("假設")).toBeTruthy();
  });
});
