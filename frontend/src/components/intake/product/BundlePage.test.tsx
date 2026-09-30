/** frontend/src/components/intake/product/BundlePage.test.tsx — 新增組合 / edit a bundle `#/bundle` (F43-I13): the picker
 * offers finished products only; two products + name + price + landing page post `POST …/bundles` (raw inputs only) and go
 * back to the products page; the landing page and a second product are required; an existing bundle shows the server's
 * derived 原價／成本 (with source lines), 打平線, offers and the reused 顧客／證據, saves a qty change with `PUT` and shows the
 * recomputed numbers; 儲存組合 puts and goes back. Fixtures mirror `app/intake/product_onboarding.py::get_bundle()` and
 * `list_page()`. No server: the API calls are fakes. */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeProductApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeProductApi")>("@/lib/intakeProductApi");
  return { ...actual, fetchProductsPage: vi.fn(), fetchBundle: vi.fn(), createBundle: vi.fn(), saveBundle: vi.fn() };
});
vi.mock("@/lib/useAuthedImage", () => ({
  useAuthedImage: (url: string | undefined) => ({ src: url ? `blob:${url}` : null, failed: !url }),
}));

import type { Bundle, ProductsPage } from "@/lib/intakeProductApi";
import { createBundle, fetchBundle, fetchProductsPage, saveBundle } from "@/lib/intakeProductApi";
import { BundlePage } from "./BundlePage";

const mockPage = vi.mocked(fetchProductsPage);
const mockFetch = vi.mocked(fetchBundle);
const mockCreate = vi.mocked(createBundle);
const mockSave = vi.mocked(saveBundle);
const B = "brd_1";
const VIT = "綜合維他命軟糖";
const PRO = "益生菌軟糖";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const PAGE: ProductsPage = {
  products: [
    {
      id: "prd_vit", name: VIT, thumbnail_url: `/api/library/brands/${B}/assets/file/ast_1`, state: "ready", step: null,
      summary: "2 群顧客・證據 2・說法 3", sell_ways: [{ id: "sw_one", name: "單盒", price: 399, break_even: 249, offer_labels: [] }],
    },
    {
      id: "prd_pro", name: PRO, thumbnail_url: null, state: "ready", step: null,
      summary: "1 群顧客・證據 1・說法 2", sell_ways: [{ id: "sw_pro", name: "單盒", price: 459, break_even: 289, offer_labels: [] }],
    },
    {
      id: "prd_draft", name: "膠原蛋白飲", thumbnail_url: null, state: "draft", step: 2,
      summary: "建到一半：還沒確認顧客", sell_ways: [],
    },
  ],
  bundles: [],
  suggestions: [],
};

function bundle(over: Partial<Bundle> = {}): Bundle {
  return {
    id: "sw_duo", name: "雙效組：維他命＋益生菌", status: "active",
    components: [
      { product_id: "prd_vit", name: VIT, qty: 1, thumbnail_url: `/api/library/brands/${B}/assets/file/ast_1`, unit_price: 399, unit_cost: 90 },
      { product_id: "prd_pro", name: PRO, qty: 1, thumbnail_url: null, unit_price: 459, unit_cost: 110 },
    ],
    price: 799, list_price: 858, list_price_derived: true, list_price_note: "2 件單價相加",
    cost: 200, cost_derived: true, cost_note: "2 件成本相加", shipping: 60, break_even: 539,
    cap_per_sale: 539, cap_is_default: true, landing_url: "https://beastgummy.tw/shop/duo", landing_is_default: false,
    offer_labels: ["組合價 省 59"], offer_notes: ["售價未滿 NT$999，不適用滿額免運"], assumptions: [],
    show_close_rate: false,
    benchmarks: {
      gross_margin: { value: 0.45, source_text: "毛利率假設 45%" },
      shipping_cost: { value: 80, source_text: "運費假設 NT$80" },
    },
    reused: {
      groups: [
        { product_id: "prd_vit", product_name: VIT, who: "上班族", pain_labels: ["太麻煩"] },
        { product_id: "prd_pro", product_name: PRO, who: "腸胃敏感族", pain_labels: ["用起來不舒服"] },
      ],
      proof: [
        { product_id: "prd_vit", product_name: VIT, fact_key: "certification", label: "檢驗報告", text: "SGS 檢驗" },
        { product_id: "prd_vit", product_name: VIT, fact_key: "customer_quote", label: "顧客原話", text: "吃了半年" },
        { product_id: "prd_pro", product_name: PRO, fact_key: "customer_quote", label: "顧客原話", text: "不再脹氣" },
      ],
    },
    ...over,
  } as Bundle;
}

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
const breakEven = () => document.querySelector("[data-break-even]")?.textContent;

describe("BundlePage — 新增組合", () => {
  it("只能挑建好的商品；放兩個、填名稱／售價／落地頁後 POST 原始輸入，回到商品頁", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockCreate.mockResolvedValue(bundle());
    renderPage(null);
    const user = userEvent.setup();

    expect(await screen.findByRole("button", { name: `放進「${VIT}」` })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "放進「膠原蛋白飲」" })).toBeNull();
    await user.click(screen.getByRole("button", { name: `放進「${VIT}」` }));
    await user.click(screen.getByRole("button", { name: "＋加一個商品" }));
    // A product already in the bundle is not offered again.
    expect(screen.queryByRole("button", { name: `放進「${VIT}」` })).toBeNull();
    await user.click(screen.getByRole("button", { name: `放進「${PRO}」` }));

    const list = screen.getByRole("list", { name: "組合裡的商品" });
    expect(within(list).getByText(VIT)).toBeTruthy();
    expect(within(list).getByText(PRO)).toBeTruthy();
    // Nothing derived before the server has seen the bundle.
    expect(screen.getByLabelText("還沒算")).toBeTruthy();

    await user.type(input("組合名稱"), "雙效組：維他命＋益生菌");
    await user.clear(input(`${PRO}的數量`));
    await user.type(input(`${PRO}的數量`), "2");
    await user.type(input("雙效組：維他命＋益生菌的售價"), "799");
    await user.type(input("雙效組：維他命＋益生菌的運費成本"), "60");
    await user.type(input("落地頁"), "https://beastgummy.tw/shop/duo");
    await user.click(screen.getByRole("button", { name: "建立組合 →" }));

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1));
    expect(mockCreate).toHaveBeenCalledWith(B, {
      name: "雙效組：維他命＋益生菌",
      components: [{ product_id: "prd_vit", qty: 1 }, { product_id: "prd_pro", qty: 2 }],
      price: 799, list_price: null, cost: null, shipping: 60, cap_per_sale: null,
      landing_url: "https://beastgummy.tw/shop/duo", assumptions: [],
    });
    expect(mockSave).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe(`/brands/${B}/products`));
  });

  it("落地頁必填、至少兩個商品：缺了不送出並寫出原因", async () => {
    mockPage.mockResolvedValue(PAGE);
    renderPage(null);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: `放進「${VIT}」` }));
    await user.type(input("組合名稱"), "雙效組");
    await user.type(input("雙效組的售價"), "799");
    await user.click(screen.getByRole("button", { name: "建立組合 →" }));

    expect(screen.getByText("落地頁要填")).toBeTruthy();
    expect(screen.getByText("至少放兩個不同的商品")).toBeTruthy();
    expect(input("落地頁").getAttribute("aria-invalid")).toBe("true");
    expect(mockCreate).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "＋加一個商品" }));
    await user.click(screen.getByRole("button", { name: `放進「${PRO}」` }));
    await user.type(input("落地頁"), "https://beastgummy.tw/shop/duo");
    expect(screen.queryByText("落地頁要填")).toBeNull();
    expect(screen.queryByText("至少放兩個不同的商品")).toBeNull();
  });

  it("伺服器拒絕（例如名稱重複）時留在本頁並顯示原因", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockCreate.mockRejectedValue(new Error("已經有叫「雙效組」的商品或組合了，換個名字。"));
    renderPage(null);
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: `放進「${VIT}」` }));
    await user.click(screen.getByRole("button", { name: "＋加一個商品" }));
    await user.click(screen.getByRole("button", { name: `放進「${PRO}」` }));
    await user.type(input("組合名稱"), "雙效組");
    await user.type(input("雙效組的售價"), "799");
    await user.type(input("落地頁"), "https://beastgummy.tw/shop/duo");
    await user.click(screen.getByRole("button", { name: "建立組合 →" }));

    expect(await screen.findByText("已經有叫「雙效組」的商品或組合了，換個名字。")).toBeTruthy();
    expect(screen.getByTestId("where").textContent).toBe(`/brands/${B}/products/bundles/new`);
  });
});

describe("BundlePage — 編輯組合", () => {
  it("顯示伺服器算好的單件價、原價／成本（含來源）、打平線、優惠與沿用的顧客／證據", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockFetch.mockResolvedValue(bundle());
    renderPage("sw_duo");

    expect(await screen.findByRole("heading", { name: "編輯組合" })).toBeTruthy();
    expect(mockFetch).toHaveBeenCalledWith(B, "sw_duo");
    expect(input("組合名稱").value).toBe("雙效組：維他命＋益生菌");
    expect(screen.getByText("單件 399・成本 90")).toBeTruthy();
    expect(screen.getByText("單件 459・成本 110")).toBeTruthy();
    expect(input(`${VIT}的數量`).value).toBe("1");

    const label = "雙效組：維他命＋益生菌";
    expect(input(`${label}的售價`).value).toBe("799");
    expect(input(`${label}的原價`).value).toBe("");
    expect(input(`${label}的原價`).placeholder).toBe("858");
    expect(screen.getByText("2 件單價相加")).toBeTruthy();
    expect(input(`${label}的成本`).placeholder).toBe("200");
    expect(screen.getByText("2 件成本相加")).toBeTruthy();
    expect(input(`${label}的每筆上限`).placeholder).toBe("539");
    expect(breakEven()).toBe("539");
    expect(screen.queryByRole("columnheader", { name: "賣法" })).toBeNull();

    expect(screen.getByText("組合價 省 59").getAttribute("data-tone")).toBe("ok");
    expect(screen.getByText("售價未滿 NT$999，不適用滿額免運")).toBeTruthy();
    expect(input("落地頁").value).toBe("https://beastgummy.tw/shop/duo");

    const reused = screen.getByRole("region", { name: "廣告會用到的" });
    expect(within(reused).getByText("沿用 2 個商品，不用重填")).toBeTruthy();
    expect(within(reused).getByText("上班族（太麻煩）・腸胃敏感族（用起來不舒服）")).toBeTruthy();
    expect(within(reused).getByText("檢驗報告・顧客原話 2 則")).toBeTruthy();
  });

  it("改數量後離開欄位就 PUT，畫面換成伺服器重算的原價／成本／打平線", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockFetch.mockResolvedValue(bundle());
    mockSave.mockResolvedValue(bundle({
      components: [
        { product_id: "prd_vit", name: VIT, qty: 2, thumbnail_url: null, unit_price: 399, unit_cost: 90 },
        { product_id: "prd_pro", name: PRO, qty: 1, thumbnail_url: null, unit_price: 459, unit_cost: 110 },
      ],
      list_price: 1257, list_price_note: "3 件單價相加", cost: 290, cost_note: "3 件成本相加",
      break_even: 449, cap_per_sale: 449, offer_labels: ["組合價 省 458"],
    }));
    renderPage("sw_duo");
    const user = userEvent.setup();

    const qty = await screen.findByRole("textbox", { name: `${VIT}的數量` });
    await user.clear(qty);
    await user.type(qty, "2");
    expect(mockSave).not.toHaveBeenCalled();
    await user.tab();

    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    expect(mockSave).toHaveBeenCalledWith(B, "sw_duo", expect.objectContaining({
      name: "雙效組：維他命＋益生菌",
      components: [{ product_id: "prd_vit", qty: 2 }, { product_id: "prd_pro", qty: 1 }],
      price: 799, list_price: null, cost: null, cap_per_sale: null,
    }));
    const label = "雙效組：維他命＋益生菌";
    await waitFor(() => expect(input(`${label}的原價`).placeholder).toBe("1,257"));
    expect(screen.getByText("3 件單價相加")).toBeTruthy();
    expect(input(`${label}的成本`).placeholder).toBe("290");
    expect(breakEven()).toBe("449");
    expect(screen.getByText("組合價 省 458")).toBeTruthy();
    expect(screen.queryByText("組合價 省 59")).toBeNull();
  });

  it("儲存組合：有改就 PUT 再回商品頁；沒改不重送", async () => {
    mockPage.mockResolvedValue(PAGE);
    mockFetch.mockResolvedValue(bundle());
    mockSave.mockResolvedValue(bundle({ name: "雙效組" }));
    renderPage("sw_duo");
    const user = userEvent.setup();

    const name = await screen.findByRole("textbox", { name: "組合名稱" });
    await user.clear(name);
    await user.type(name, "雙效組");
    await user.click(screen.getByRole("button", { name: "儲存組合 →" }));

    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe(`/brands/${B}/products`));
    expect(mockSave).toHaveBeenCalledTimes(1);
    expect(mockSave).toHaveBeenCalledWith(B, "sw_duo", expect.objectContaining({ name: "雙效組", landing_url: "https://beastgummy.tw/shop/duo" }));
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
