/** frontend/src/components/intake/product/ProductsPage.test.tsx — the products page `#/plist` (F43-I07): cards from a
 * fixture shaped like `app/intake/product_onboarding.py::list_page()` (a ready product with two sell-ways, a draft, a
 * brand-scan suggestion, a bundle); 「繼續建檔 →」 on a suggestion posts the create and opens step 1; an empty brand gets
 * one empty state; a failed read keeps the actions and retries. No server: the API calls are fakes. */
import type { ReactNode } from "react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeProductApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeProductApi")>("@/lib/intakeProductApi");
  return { ...actual, fetchProductsPage: vi.fn(), createProduct: vi.fn() };
});
vi.mock("@/lib/useAuthedImage", () => ({
  useAuthedImage: (url: string | undefined) => ({ src: url ? `blob:${url}` : null, failed: !url }),
}));

import { createProduct, fetchProductsPage, type ProductsPage as PageData } from "@/lib/intakeProductApi";
import { ProductCard } from "./ProductCard";
import { ProductsPage } from "./ProductsPage";

const mockFetch = vi.mocked(fetchProductsPage);
const mockCreate = vi.mocked(createProduct);
const B = "brd_1";

const fixture: PageData = {
  products: [
    {
      id: "prd_vit",
      name: "綜合維他命軟糖（成人每日補給・草莓口味 60 粒裝）",
      thumbnail_url: `/api/library/brands/${B}/assets/file/ast_1`,
      state: "ready",
      step: null,
      summary: "2 群顧客・證據 2・說法 3",
      sell_ways: [
        { id: "sw_one", name: "單盒", price: 399, break_even: 249, offer_labels: [] },
        { id: "sw_three", name: "三盒組", price: 999, break_even: 668.5, offer_labels: ["組合價 省 198", "滿 NT$999 免運"] },
      ],
    },
    {
      id: "prd_pro",
      name: "益生菌軟糖",
      thumbnail_url: null,
      state: "draft",
      step: 2,
      summary: "建到一半：還沒確認顧客",
      sell_ways: [{ id: "sw_pro", name: "單盒", price: 459, break_even: null, offer_labels: [] }],
    },
  ],
  bundles: [
    {
      id: "sw_duo",
      name: "雙效組：維他命＋益生菌",
      price: 799,
      break_even: 539,
      offer_labels: ["組合價 省 59"],
      thumbnails: [`/api/library/brands/${B}/assets/file/ast_1`],
      state: "draft",
      components: [
        { product_id: "prd_vit", name: "綜合維他命軟糖", qty: 1 },
        { product_id: "prd_pro", name: "益生菌軟糖", qty: 1 },
      ],
    },
  ],
  suggestions: [{ name: "膠原蛋白軟糖", url: "https://beastgummy.tw/shop/collagen" }],
};

function Where() {
  const location = useLocation();
  return <p data-testid="where">{location.pathname + location.search}</p>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/brands/${B}/products`]}>
      <Routes>
        <Route path="/brands/:brandId/products" element={<ProductsPage brandId={B} />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("ProductsPage", () => {
  it("renders products with their sell-ways, the draft's continue link, the suggestion and the bundle", async () => {
    mockFetch.mockResolvedValue(fixture);
    renderPage();

    const products = await screen.findByRole("region", { name: "商品" });
    expect(screen.getByRole("heading", { level: 1, name: "商品" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "＋新增商品" }).getAttribute("href")).toBe(`/brands/${B}/products/new`);
    expect(screen.getByRole("link", { name: "＋新增組合" }).getAttribute("href")).toBe(`/brands/${B}/products/bundles/new`);

    const names = [...products.querySelectorAll("[data-slot=product-card]")].map((card) => card.querySelector("a, b")?.textContent);
    expect(names).toEqual([
      "綜合維他命軟糖（成人每日補給・草莓口味 60 粒裝）", "益生菌軟糖", "膠原蛋白軟糖",
    ]);

    const ready = screen.getByRole("link", { name: /綜合維他命軟糖（成人/ }).closest("[data-slot=product-card]") as HTMLElement;
    expect(within(ready).getByText("2 群顧客・證據 2・說法 3")).toBeTruthy();
    expect(within(ready).getByText("可以投放")).toBeTruthy();
    expect(within(ready).getByText("399・打平 249")).toBeTruthy();
    // Money is printed as whole numbers; offer labels come verbatim from the server.
    expect(within(ready).getByText("999・打平 669")).toBeTruthy();
    expect(within(ready).getByText("組合價 省 198")).toBeTruthy();
    expect(within(ready).getByText("滿 NT$999 免運")).toBeTruthy();
    expect(within(ready).queryByRole("link", { name: /繼續建檔/ })).toBeNull();

    const draft = screen.getByRole("link", { name: "益生菌軟糖" }).closest("[data-slot=product-card]") as HTMLElement;
    expect(within(draft).getByText("建到一半")).toBeTruthy();
    expect(within(draft).getByText("建到一半：還沒確認顧客")).toBeTruthy();
    // An unknown cost is said once as unknown, never printed as 0.
    expect(within(draft).getByText("459・打平 未知")).toBeTruthy();
    expect(within(draft).getByRole("link", { name: "繼續建檔 →" }).getAttribute("href")).toBe(`/brands/${B}/products/prd_pro/onboarding?step=2`,
    );

    const suggestion = screen.getByText("膠原蛋白軟糖").closest("[data-slot=product-card]") as HTMLElement;
    expect(within(suggestion).getByText("AI 讀到了，還沒確認")).toBeTruthy();

    const bundles = screen.getByRole("region", { name: "組合" });
    expect(within(bundles).getByRole("link", { name: "雙效組：維他命＋益生菌" }).getAttribute("href")).toBe(`/brands/${B}/products/bundles/sw_duo`,
    );
    expect(within(bundles).getByText("事實與證據沿用 2 個商品")).toBeTruthy();
    expect(within(bundles).getByText("組合價 省 59")).toBeTruthy();
    expect(within(bundles).getByText("799・打平 539")).toBeTruthy();
    expect(within(bundles).getByText("建到一半")).toBeTruthy();
  });

  it("「繼續建檔」 on a suggestion creates the product with its page URL, then opens step 1", async () => {
    mockFetch.mockResolvedValue(fixture);
    mockCreate.mockResolvedValue({ product_id: "prd_new", created: true });
    renderPage();

    const suggestion = (await screen.findByText("膠原蛋白軟糖")).closest("[data-slot=product-card]") as HTMLElement;
    await userEvent.click(within(suggestion).getByRole("button", { name: "繼續建檔 →" }));

    expect(mockCreate).toHaveBeenCalledWith(B, { name: "膠原蛋白軟糖", page_url: "https://beastgummy.tw/shop/collagen" });
    expect((await screen.findByTestId("where")).textContent).toContain(`/brands/${B}/products/prd_new/onboarding?step=1`);
  });

  it("a failed create stays on the page with the server's message on that card", async () => {
    mockFetch.mockResolvedValue({ ...fixture, suggestions: [{ name: "膠原蛋白軟糖", url: null }] });
    mockCreate.mockRejectedValue(new Error("商品名稱太長了"));
    renderPage();

    const suggestion = (await screen.findByText("膠原蛋白軟糖")).closest("[data-slot=product-card]") as HTMLElement;
    await userEvent.click(within(suggestion).getByRole("button", { name: "繼續建檔 →" }));

    expect(mockCreate).toHaveBeenCalledWith(B, { name: "膠原蛋白軟糖" });
    expect((await within(suggestion).findByRole("alert")).textContent).toContain("商品名稱太長了");
    expect(within(suggestion).getByRole("button", { name: "繼續建檔 →" }).hasAttribute("disabled")).toBe(false);
    expect(screen.queryByTestId("where")).toBeNull();
  });

  it("an empty brand gets one empty state with 「＋新增商品」", async () => {
    mockFetch.mockResolvedValue({ products: [], bundles: [], suggestions: [] });
    renderPage();

    expect(await screen.findByText("還沒有商品")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "＋新增商品" })).toHaveLength(1);
    expect(screen.queryByRole("link", { name: "＋新增組合" })).toBeNull();
    expect(screen.queryByRole("region", { name: "商品" })).toBeNull();
  });

  it("a failed read keeps the actions and retries", async () => {
    mockFetch.mockRejectedValueOnce(new Error("讀取商品失敗（狀態碼 500）")).mockResolvedValueOnce(fixture);
    renderPage();

    expect((await screen.findByRole("alert")).textContent).toContain("讀取商品失敗（狀態碼 500）");
    expect(screen.getByRole("link", { name: "＋新增商品" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "＋新增組合" })).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "重新載入" }));
    expect(await screen.findByRole("region", { name: "組合" })).toBeTruthy();
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
  });
});

describe("ProductCard compact (the 經營概況 block)", () => {
  function renderCompact(ui: ReactNode) {
    return render(<MemoryRouter>{ui}</MemoryRouter>);
  }

  it("a ready product reads its sell-ways on one line; a draft gets 「繼續 →」 instead of the chip", () => {
    const [ready, draft] = fixture.products;
    renderCompact(
      <>
        <ProductCard brandId={B} product={ready} compact />
        <ProductCard brandId={B} product={draft} compact />
        <ProductCard brandId={B} bundle={fixture.bundles[0]} compact />
      </>,
    );
    expect(screen.getByText("單盒 399・三盒組 999")).toBeTruthy();
    expect(screen.queryByText("399・打平 249")).toBeNull();
    expect(screen.getByRole("link", { name: "繼續 →" }).getAttribute("href")).toBe(`/brands/${B}/products/prd_pro/onboarding?step=2`);
    expect(screen.getByText("組合・799")).toBeTruthy();
    expect(screen.getAllByText("可以投放")).toHaveLength(1);
  });
});
