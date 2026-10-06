/** frontend/src/components/intake/product/BundlePage.test.tsx — 新增組合 / 編輯組合 (F45-I03, prototype
 * `f45-sell-way-components/variant-bundle.html`): the picker groups every finished product's base sell-ways by product
 * (no composed sell-way, no draft product); each content row shows its product, the base's name and that base's own
 * 售價・成本 (`unit_price` / `unit_cost`); bodies carry `components: [{sell_way_id, qty}]` and raw inputs only, as typed
 * (an empty 售價 = derived; F50 Contract I: the server parses and refuses, its sentences shown under their fields); the price block shows the server's derived numbers with their 「推算：…」 notes and 推算 on 打平,
 * 「這個賣法免運」 sends `free_shipping` and shows the server's 「這組免運」; a base without a cost says where to fill it
 * (no jump to another product); the server's refusals (one product only, a taken name) are shown as it words them.
 * Fixtures mirror `app/intake/product_onboarding.py::get_bundle()` / `list_page()` after F45 (shapes of
 * `app/tests/test_intake_product_api.py::test_bundle_create_edit_reused_and_validation`). No server: the API calls
 * are fakes. */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeProductApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeProductApi")>("@/lib/intakeProductApi");
  return { ...actual, fetchProductsPage: vi.fn(), fetchBundle: vi.fn(), createBundle: vi.fn(), saveBundle: vi.fn(), previewBundle: vi.fn() };
});
vi.mock("@/lib/useAuthedImage", () => ({
  useAuthedImage: (url: string | undefined) => ({ src: url ? `blob:${url}` : null, failed: !url }),
}));

import { ApiResponseError } from "@/lib/http";
import type { Bundle, BundleComponent, BundlePreview, ProductsPage } from "@/lib/intakeProductApi";
import { createBundle, fetchBundle, fetchProductsPage, previewBundle, saveBundle } from "@/lib/intakeProductApi";
import { BundlePage } from "./BundlePage";

const mockPage = vi.mocked(fetchProductsPage);
const mockFetch = vi.mocked(fetchBundle);
const mockCreate = vi.mocked(createBundle);
const mockSave = vi.mocked(saveBundle);
const mockPreview = vi.mocked(previewBundle);
const B = "brd_1";
const EN = "Beast Gummy 能量軟糖";
const PRO = "Beast Gummy 益生菌軟糖";
const NAME = "能量＋益生菌 雙效組";
const PHOTO = `/api/library/brands/${B}/assets/file/ast_1`;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const PAGE: ProductsPage = {
  products: [
    {
      id: "prd_en", name: EN, thumbnail_url: PHOTO, state: "ready", step: null, summary: "2 群顧客・證據 2・說法 3",
      sell_ways: [
        { id: "sw_trial", name: "體驗包（3 顆）", shape: "base", price: 100, break_even: 40, offer_labels: [] },
        { id: "sw_box", name: "單盒", shape: "base", price: 180, break_even: 70, offer_labels: [] },
        { id: "sw_c12", name: "12 盒", shape: "composed", price: 1980, break_even: 1320, offer_labels: ["組合價 省 180"] },
      ],
    },
    {
      id: "prd_pro", name: PRO, thumbnail_url: null, state: "ready", step: null, summary: "1 群顧客・證據 1・說法 2",
      sell_ways: [{ id: "sw_pbox", name: "單盒", shape: "base", price: 220, break_even: 90, offer_labels: [] }],
    },
    {
      id: "prd_draft", name: "膠原蛋白飲", thumbnail_url: null, state: "draft", step: 2,
      summary: "建到一半：還沒確認顧客", sell_ways: [{ id: "sw_col", name: "單瓶", shape: "base", price: 500, break_even: null, offer_labels: [] }],
    },
  ],
  bundles: [],
  suggestions: [],
};

const comp = (over: Partial<BundleComponent> & Pick<BundleComponent, "sell_way_id">): BundleComponent => ({
  ...(over.sell_way_id === "sw_box"
    ? { product_id: "prd_en", product_name: EN, name: "單盒", thumbnail_url: PHOTO, unit_price: 180, unit_cost: 50 }
    : { product_id: "prd_pro", product_name: PRO, name: "單盒", thumbnail_url: null, unit_price: 220, unit_cost: 70 }),
  qty: 1,
  ...over,
});

/** `GET …/bundles/{id}`: 單盒 × 2 ＋ 益生菌・單盒 × 1 at a typed 499; 原價 and 成本 derived from the bases. */
function bundle(over: Partial<Bundle> = {}): Bundle {
  return {
    id: "sw_duo", name: NAME, status: "active",
    components: [comp({ sell_way_id: "sw_box", qty: 2 }), comp({ sell_way_id: "sw_pbox" })],
    price: 499, price_derived: false, price_note: "",
    list_price: 580, list_price_derived: true, list_price_note: `推算：${EN}・單盒 180 × 2 ＋ ${PRO}・單盒 220 × 1`,
    cost: 170, cost_derived: true, cost_note: `推算：${EN}・單盒 50 × 2 ＋ ${PRO}・單盒 70 × 1`,
    cost_estimate: 170, cost_missing: [],
    shipping: 60, free_shipping: false, break_even: 269, break_even_derived: true,
    cap_per_sale: 269, cap_is_default: true, landing_url: "https://beastgummy.tw/shop/duo", landing_is_default: false,
    offer_sentences: ["優惠價 NT$ 499（原價 NT$ 580）"], offer_labels: ["組合價 省 81"], offer_notes: [], assumptions: [],
    show_close_rate: false,
    benchmarks: {
      gross_margin: { value: 45, source_text: "毛利率假設 45%" },
      shipping_cost: { value: 80, source_text: "運費假設 NT$ 80" },
    },
    reused: {
      groups: [
        { product_id: "prd_en", product_name: EN, who: "上班族", pain_labels: ["太麻煩"] },
        { product_id: "prd_pro", product_name: PRO, who: "腸胃敏感族", pain_labels: ["用起來不舒服"] },
      ],
      proof: [
        { product_id: "prd_en", product_name: EN, fact_key: "lab_report", label: "檢驗報告／認證", text: "SGS 檢驗" },
        { product_id: "prd_en", product_name: EN, fact_key: "customer_review", label: "顧客評論原話", text: "吃了半年" },
        { product_id: "prd_pro", product_name: PRO, fact_key: "customer_review", label: "顧客評論原話", text: "不再脹氣" },
      ],
    },
    ...over,
  };
}

/** `POST …/bundles/preview`: the GET shape of a bundle not created yet (id null, landing = the first product's page). */
function preview(over: Partial<Bundle> = {}): BundlePreview {
  return { ...bundle({ landing_url: "https://beastgummy.tw/shop/energy", landing_is_default: true, ...over }), id: null };
}

/** The new-bundle preview where nothing is typed but the name: 售價 derived too. */
const derivedPrice = {
  price: 580, price_derived: true, price_note: `推算：${EN}・單盒 180 × 2 ＋ ${PRO}・單盒 220 × 1`,
  break_even: 350, cap_per_sale: 350, offer_sentences: [], offer_labels: [],
};

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>;
}

function renderPage(bundleId: string | null) {
  const path = bundleId ? `/brands/${B}/products/bundles/${bundleId}` : `/brands/${B}/products/bundles/new`;
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:brandId/products/bundles/*" element={<><BundlePage brandId={B} bundleId={bundleId} /><Where /></>} />
        <Route path="/brands/:brandId/products" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

const input = (name: string) => screen.getByRole("textbox", { name }) as HTMLInputElement;
const breakEven = () => document.querySelector("[data-break-even]")?.textContent ?? "";
const picker = () => document.querySelector('[data-slot="sell-way-picker"]') as HTMLElement;
const pick = async (user: ReturnType<typeof userEvent.setup>, label: string) => {
  if (!document.querySelector('[data-slot="sell-way-picker"]')) await user.click(screen.getByRole("button", { name: "＋再放一種賣法" }));
  await user.click(await within(picker()).findByRole("button", { name: `放進「${label}」` }));
};

describe("BundlePage — 新增組合", () => {
  it("選單依商品分組、只有建好商品的基本賣法；放進兩種、填名稱／數量／落地頁後 POST {sell_way_id, qty}，售價空著＝推算", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockPreview.mockResolvedValue(preview(derivedPrice));
    mockCreate.mockResolvedValue(bundle());
    renderPage(null);
    const user = userEvent.setup();

    expect(await within(picker()).findByRole("group", { name: EN })).toBeTruthy();
    const en = within(picker()).getByRole("group", { name: EN });
    expect(within(en).getAllByRole("button").map((b) => b.textContent)).toEqual(["體驗包（3 顆）售價 100", "單盒售價 180"]);
    expect(within(picker()).getByRole("group", { name: PRO })).toBeTruthy();
    // A composed sell-way is not a component; a product still being built is not offered.
    expect(within(picker()).queryByText("12 盒")).toBeNull();
    expect(within(picker()).queryByText("膠原蛋白飲")).toBeNull();

    await pick(user, `${EN}・單盒`);
    // The new row waits for its quantity (focused); the base's own price is known, its cost is not yet.
    const rows = screen.getByRole("list", { name: "裡面有什麼" });
    expect(within(rows).getByText(EN)).toBeTruthy();
    expect(within(rows).getByText("售價 180・成本 —")).toBeTruthy();
    expect(document.activeElement).toBe(input(`${EN}・單盒的數量`));
    await user.type(input(`${EN}・單盒的數量`), "2");
    await user.click(screen.getByRole("button", { name: "＋再放一種賣法" }));
    // Already in → not offered again.
    expect(within(picker()).queryByRole("button", { name: `放進「${EN}・單盒」` })).toBeNull();
    await pick(user, `${PRO}・單盒`);
    expect(picker()).toBeNull();
    await user.type(input(`${PRO}・單盒的數量`), "1");

    await user.type(input("組合名稱"), NAME);
    await user.type(input("運費成本"), "60");
    await user.type(input("落地頁"), "https://beastgummy.tw/shop/duo");
    await user.click(screen.getByRole("button", { name: "建立組合 →" }));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate).toHaveBeenCalledWith(B, {
      name: NAME,
      components: [{ sell_way_id: "sw_box", qty: "2" }, { sell_way_id: "sw_pbox", qty: "1" }],
      price: null, list_price: null, cost: null, shipping: "60", cap_per_sale: null,
      landing_url: "https://beastgummy.tw/shop/duo", assumptions: [], free_shipping: false,
    });
    expect(mockSave).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe(`/brands/${B}/products`));
  }, 15000);

  it("名稱、數量、落地頁缺了不送出（數量沒有自己的規則）；只放一個商品時照伺服器的話說", async () => {
    const one = "組合至少要放兩個不同商品的賣法；同一個商品的組合，請到那個商品的賣法新增。";
    mockPage.mockResolvedValue(PAGE);
    mockPreview.mockRejectedValue(new Error(one));
    mockCreate.mockRejectedValue(new Error(one));
    renderPage(null);
    const user = userEvent.setup();

    await pick(user, `${EN}・單盒`);
    await user.click(screen.getByRole("button", { name: "建立組合 →" }));
    expect(screen.getByText("請填組合名稱")).toBeTruthy();
    // A quantity not typed yet is waited for, not judged on the page (F50 Contract I).
    expect(screen.queryByText(/數量要是/)).toBeNull();
    expect(screen.getByText("落地頁要填")).toBeTruthy();
    expect(input("落地頁").getAttribute("aria-invalid")).toBe("true");
    expect(breakEven()).toContain("還算不出來：先填數量");
    expect(mockCreate).not.toHaveBeenCalled();

    await user.type(input(`${EN}・單盒的數量`), "6");
    await user.type(input("組合名稱"), "六盒組");
    await user.type(input("落地頁"), "https://beastgummy.tw/shop/six");
    await user.tab();
    // The server refuses one product: its words, once, and the numbers stay empty.
    expect(await screen.findByText(one)).toBeTruthy();
    expect(breakEven()).toContain("還算不出來：先改好下面的紅字");
    await user.click(screen.getByRole("button", { name: "建立組合 →" }));
    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(screen.getAllByText(one)).toHaveLength(1);
    expect(screen.getByTestId("where").textContent).toBe(`/brands/${B}/products/bundles/new`);
  });

  it("數量、售價照打的送；伺服器擋下的句子寫在那一格下面（F50 Contract I）", async () => {
    const qtySentence = `「${EN}・單盒」的數量要是 1 以上的整數。`;
    const priceSentence = "「能量＋益生菌 雙效組」的售價要大於 0。";
    mockPage.mockResolvedValue(PAGE);
    mockPreview.mockRejectedValue(new ApiResponseError(qtySentence, 400, { "components.0.qty": qtySentence, price: priceSentence }));
    renderPage(null);
    const user = userEvent.setup();

    await pick(user, `${EN}・單盒`);
    await user.type(input(`${EN}・單盒的數量`), "0");
    await pick(user, `${PRO}・單盒`);
    await user.type(input(`${PRO}・單盒的數量`), "1");
    await user.type(input("組合名稱"), NAME);
    await user.type(input("售價"), "0");
    await user.tab();

    await waitFor(() => expect(mockPreview).toHaveBeenCalled());
    expect(mockPreview.mock.lastCall?.[1]).toMatchObject({
      components: [{ sell_way_id: "sw_box", qty: "0" }, { sell_way_id: "sw_pbox", qty: "1" }], price: "0",
    });
    const rows = screen.getByRole("list", { name: "裡面有什麼" });
    expect(await within(rows).findByText(qtySentence)).toBeTruthy();
    expect(input(`${EN}・單盒的數量`).getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText(priceSentence)).toBeTruthy();
    expect(input("售價").getAttribute("aria-invalid")).toBe("true");
    expect(breakEven()).toContain("還算不出來：先改好下面的紅字");
  });

  it("預覽：每列是那個基本賣法自己的售價・成本；空著的售價／原價／成本照內容推算並標推算，打平也標推算", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockPreview.mockResolvedValue(preview(derivedPrice));
    renderPage(null);
    const user = userEvent.setup();

    await pick(user, `${EN}・單盒`);
    await user.type(input(`${EN}・單盒的數量`), "2");
    await pick(user, `${PRO}・單盒`);
    await user.type(input(`${PRO}・單盒的數量`), "1");
    expect(mockPreview).not.toHaveBeenCalled();
    await user.type(input("組合名稱"), NAME);
    await user.tab();

    await waitFor(() => expect(breakEven()).toContain("每筆最多花 NT$ 350"));
    expect(mockPreview).toHaveBeenCalledWith(B, {
      name: NAME,
      components: [{ sell_way_id: "sw_box", qty: "2" }, { sell_way_id: "sw_pbox", qty: "1" }],
      price: null, list_price: null, cost: null, shipping: null, cap_per_sale: null, landing_url: null, assumptions: [],
      free_shipping: false,
    });
    const rows = screen.getByRole("list", { name: "裡面有什麼" });
    expect(within(rows).getByText("售價 180・成本 50")).toBeTruthy();
    expect(within(rows).getByText("售價 220・成本 70")).toBeTruthy();
    expect(input("售價").value).toBe("");
    expect(input("售價").placeholder).toBe("580");
    expect(input("原價").placeholder).toBe("580");
    expect(screen.getAllByText(`推算：${EN}・單盒 180 × 2 ＋ ${PRO}・單盒 220 × 1`)).toHaveLength(2);
    expect(input("成本").placeholder).toBe("170");
    expect(screen.getByText(`推算：${EN}・單盒 50 × 2 ＋ ${PRO}・單盒 70 × 1`)).toBeTruthy();
    const be = document.querySelector("[data-break-even]") as HTMLElement;
    expect(within(be).getByText("推算")).toBeTruthy();
    expect(be.textContent).toContain("售價 580（推算） − 成本 170（推算） − 運費成本 60");
    expect(within(document.querySelector('[data-slot="offer-sentences"]') as HTMLElement).getByText("沒有優惠")).toBeTruthy();
    const reused = screen.getByRole("region", { name: "廣告會用到的" });
    expect(within(reused).getByText("上班族（太麻煩）・腸胃敏感族（用起來不舒服）")).toBeTruthy();
    // The landing field stays as typed (empty): the preview's default page does not fill it.
    expect(input("落地頁").value).toBe("");
  });

  it("勾「這個賣法免運」就重算，廣告裡的優惠出現伺服器的「這組免運」", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockPreview.mockImplementation(async (_brand, body) => (body.free_shipping
      ? preview({ free_shipping: true, offer_sentences: ["優惠價 NT$ 499（原價 NT$ 580）", "這組免運"] })
      : preview()));
    renderPage(null);
    const user = userEvent.setup();

    await pick(user, `${EN}・單盒`);
    await user.type(input(`${EN}・單盒的數量`), "2");
    await pick(user, `${PRO}・單盒`);
    await user.type(input(`${PRO}・單盒的數量`), "1");
    await user.type(input("組合名稱"), NAME);
    await user.type(input("售價"), "499");
    await user.tab();
    await waitFor(() => expect(screen.getByText("「優惠價 NT$ 499（原價 NT$ 580）」")).toBeTruthy());
    expect(screen.queryByText("「這組免運」")).toBeNull();
    const calls = mockPreview.mock.calls.length;

    await user.click(screen.getByRole("checkbox", { name: "這個賣法免運" }));
    await waitFor(() => expect(mockPreview).toHaveBeenCalledTimes(calls + 1));
    expect(mockPreview.mock.lastCall?.[1]).toMatchObject({ price: "499", free_shipping: true });
    expect(await screen.findByText("「這組免運」")).toBeTruthy();
  });

  it("有基本賣法還沒填成本：寫出是哪個商品的哪個賣法、到那個商品的賣法填（不跳去別的商品）", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockPreview.mockResolvedValue(preview({
      components: [comp({ sell_way_id: "sw_box", qty: 2, unit_cost: null }), comp({ sell_way_id: "sw_pbox" })],
      cost: null, cost_derived: false, cost_note: "", cost_estimate: null, cost_missing: [{ sell_way_id: "sw_box", name: "單盒" }],
      break_even: null, break_even_derived: false, cap_per_sale: null,
    }));
    renderPage(null);
    const user = userEvent.setup();

    await pick(user, `${EN}・單盒`);
    await user.type(input(`${EN}・單盒的數量`), "2");
    await pick(user, `${PRO}・單盒`);
    await user.type(input(`${PRO}・單盒的數量`), "1");
    await user.type(input("組合名稱"), NAME);
    await user.type(input("售價"), "499");
    await user.tab();

    await waitFor(() => expect(breakEven()).toContain(`還算不出來：${EN}・單盒還沒填成本`));
    expect(screen.getByText(`${EN}・單盒還沒填成本，推算不出來`)).toBeTruthy();
    expect(screen.getByText(`到「${EN}」的賣法填`)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /去填/ })).toBeNull();
    expect(within(screen.getByRole("list", { name: "裡面有什麼" })).getByText("還沒填")).toBeTruthy();
  });
});

describe("BundlePage — 編輯組合", () => {
  it("顯示伺服器的內容列、推算的原價／成本、打平（推算）、優惠句與沿用的顧客／證據", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockFetch.mockResolvedValue(bundle());
    renderPage("sw_duo");

    expect(await screen.findByRole("heading", { name: "編輯組合" })).toBeTruthy();
    expect(mockFetch).toHaveBeenCalledWith(B, "sw_duo");
    expect(input("組合名稱").value).toBe(NAME);
    const rows = screen.getByRole("list", { name: "裡面有什麼" });
    expect(within(rows).getByText("售價 180・成本 50")).toBeTruthy();
    expect(within(rows).getByText("售價 220・成本 70")).toBeTruthy();
    expect(input(`${EN}・單盒的數量`).value).toBe("2");
    expect(input(`${PRO}・單盒的數量`).value).toBe("1");

    expect(input("售價").value).toBe("499");
    expect(input("原價").value).toBe("");
    expect(input("原價").placeholder).toBe("580");
    expect(input("成本").placeholder).toBe("170");
    expect(screen.getByText(`推算：${EN}・單盒 50 × 2 ＋ ${PRO}・單盒 70 × 1`)).toBeTruthy();
    expect(breakEven()).toContain("每筆最多花 NT$ 269");
    expect(breakEven()).toContain("推算");
    expect(screen.getByText("「優惠價 NT$ 499（原價 NT$ 580）」").getAttribute("data-tone")).toBe("ok");
    expect((screen.getByRole("checkbox", { name: "這個賣法免運" }) as HTMLInputElement).checked).toBe(false);
    expect(input("落地頁").value).toBe("https://beastgummy.tw/shop/duo");

    const reused = screen.getByRole("region", { name: "廣告會用到的" });
    expect(within(reused).getByText("沿用 2 個商品，不用重填")).toBeTruthy();
    expect(within(reused).getByText("檢驗報告／認證・顧客評論原話 2 則")).toBeTruthy();
  });

  it("推算出來的售價不會被當成自己填的值送回去", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockFetch.mockResolvedValue(bundle(derivedPrice));
    mockSave.mockResolvedValue(bundle({ ...derivedPrice, name: "雙效組" }));
    renderPage("sw_duo");
    const user = userEvent.setup();

    const name = await screen.findByRole("textbox", { name: "組合名稱" });
    expect(input("售價").value).toBe("");
    expect(input("售價").placeholder).toBe("580");
    await user.clear(name);
    await user.type(name, "雙效組");
    await user.tab();
    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    expect(mockSave.mock.lastCall?.[2]).toMatchObject({ name: "雙效組", price: null });
  });

  it("改數量後離開欄位就 PUT {sell_way_id, qty}，畫面換成伺服器重算的數字", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockFetch.mockResolvedValue(bundle());
    mockSave.mockResolvedValue(bundle({
      components: [comp({ sell_way_id: "sw_box", qty: 3 }), comp({ sell_way_id: "sw_pbox" })],
      list_price: 760, list_price_note: `推算：${EN}・單盒 180 × 3 ＋ ${PRO}・單盒 220 × 1`,
      cost: 220, cost_note: `推算：${EN}・單盒 50 × 3 ＋ ${PRO}・單盒 70 × 1`, cost_estimate: 220,
      break_even: 219, cap_per_sale: 219, offer_sentences: ["優惠價 NT$ 499（原價 NT$ 760）"],
    }));
    renderPage("sw_duo");
    const user = userEvent.setup();

    const qty = await screen.findByRole("textbox", { name: `${EN}・單盒的數量` });
    await user.clear(qty);
    await user.type(qty, "3");
    expect(mockSave).not.toHaveBeenCalled();
    await user.tab();

    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    expect(mockSave).toHaveBeenCalledWith(B, "sw_duo", {
      name: NAME,
      components: [{ sell_way_id: "sw_box", qty: "3" }, { sell_way_id: "sw_pbox", qty: "1" }],
      price: "499", list_price: null, cost: null, shipping: "60", cap_per_sale: null,
      landing_url: "https://beastgummy.tw/shop/duo", assumptions: [], free_shipping: false,
    });
    await waitFor(() => expect(input("原價").placeholder).toBe("760"));
    expect(input("成本").placeholder).toBe("220");
    expect(breakEven()).toContain("每筆最多花 NT$ 219");
    expect(screen.getByText("「優惠價 NT$ 499（原價 NT$ 760）」")).toBeTruthy();
  });

  it("儲存組合：有改就 PUT 再回商品頁；伺服器拒絕時留在本頁並照它的話說", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockFetch.mockResolvedValue(bundle());
    mockSave.mockRejectedValue(new Error("已經有叫「雙效組」的商品或組合了，換個名字。"));
    renderPage("sw_duo");
    const user = userEvent.setup();

    const name = await screen.findByRole("textbox", { name: "組合名稱" });
    await user.clear(name);
    await user.type(name, "雙效組");
    await user.click(screen.getByRole("button", { name: "儲存組合 →" }));
    expect(await screen.findByText("已經有叫「雙效組」的商品或組合了，換個名字。")).toBeTruthy();
    expect(screen.getByTestId("where").textContent).toBe(`/brands/${B}/products/bundles/sw_duo`);

    mockSave.mockResolvedValue(bundle({ name: "雙效組 2" }));
    await user.type(name, " 2");
    await user.click(screen.getByRole("button", { name: "儲存組合 →" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe(`/brands/${B}/products`));
    expect(mockSave.mock.lastCall?.[2]).toMatchObject({ name: "雙效組 2", landing_url: "https://beastgummy.tw/shop/duo" });
    expect(mockCreate).not.toHaveBeenCalled();
  });

  it("讀不到組合時說原因，仍可回商品頁", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockFetch.mockRejectedValue(new Error("找不到這個組合。"));
    renderPage("sw_gone");
    const user = userEvent.setup();

    expect(await screen.findByText("找不到這個組合。")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "← 商品" }));
    expect(screen.getByTestId("where").textContent).toBe(`/brands/${B}/products`);
  });
});


it("shared bundle price preserves the drill loss and explicit cap", async () => {
  mockPage.mockResolvedValue(PAGE);
  mockFetch.mockResolvedValue(bundle({ price: 100, cost: 25, shipping: 80, break_even: -5, cap_per_sale: 450, cap_is_default: false }));
  renderPage("sw_duo");
  await screen.findByRole("heading", { name: "編輯組合" });
  expect(breakEven()).toContain("打平 NT$ -5");
  expect(breakEven()).toContain("未投廣告已虧損");
  expect(breakEven()).not.toContain("每筆最多花");
  expect(input("每筆上限（空著＝打平）").value).toBe("450");
  expect(screen.getByText("高於打平")).toBeTruthy();
});
