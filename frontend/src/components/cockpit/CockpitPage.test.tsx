import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({
    identity: { user: { id: "user-1" }, org: { id: "org-1", timezone: "Asia/Taipei", today: "2026-10-04" } },
    scope: "user-1:org-1",
    brands: [{ brand_id: "brd_1", brand_name: "測試品牌" }],
    brandsLoading: false,
    brandsError: null,
    refreshBrands: () => undefined,
  }),
}));
vi.mock("./DashboardWidgets", () => ({
  CampaignTable: () => <p>活動表</p>,
  InboxWidget: () => <p>收件匣</p>,
  PerformanceWidget: () => <p>成效</p>,
  SpendDistribution: () => <p>花費分布</p>,
  number: (value: number) => value.toLocaleString("zh-TW"),
}));
vi.mock("@/lib/metaApi", () => ({ fetchMetaSpend: vi.fn() }));
vi.mock("@/lib/intakeProductApi", () => ({ fetchProductsPage: vi.fn() }));
vi.mock("@/lib/useAuthedImage", () => ({ useAuthedImage: () => ({ src: undefined }) }));

import { fetchMetaSpend, type MetaSpendSummary } from "@/lib/metaApi";
import { fetchProductsPage, type ProductsPage } from "@/lib/intakeProductApi";
import { CockpitPage } from "./CockpitPage";

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();

// Real shape of GET /api/meta/brands/{b}/spend (app/meta/routes.py SpendSummaryResponse).
function spend(overrides: Partial<MetaSpendSummary> = {}): MetaSpendSummary {
  const total = {
    campaign_id: "total", campaign_name: "總計", spend: 1200, impressions: 3000, clicks: 90,
    roas: 2.2,
  };
  return {
    last_pull_at: null,
    data_pulled_at: hoursAgo(3),
    attribution_label: "點擊後 7 天＋瀏覽後 1 天",
    campaigns: [{ ...total, campaign_id: "c-1", campaign_name: "活動一" }],
    total,
    ...overrides,
  };
}

// Real shape of GET /api/intake/brands/{b}/products (app/intake/product_onboarding.py): a ready
// product with two sell-ways, a draft stopped at step 2, and a bundle of both.
function productsPage(overrides: Partial<ProductsPage> = {}): ProductsPage {
  return {
    products: [
      {
        id: "prd_multi", name: "綜合維他命軟糖", thumbnail_url: null, state: "ready", step: null,
        summary: "2 群顧客・證據 2・說法 3",
        sell_ways: [
          { id: "sw_one", name: "單盒", price: 399, break_even: 249, offer_labels: [] },
          { id: "sw_three", name: "三盒組", price: 999, break_even: 669, offer_labels: ["組合價 省 198"] },
        ],
      },
      {
        id: "prd_bio", name: "益生菌軟糖", thumbnail_url: null, state: "draft", step: 2,
        summary: "建到一半：還沒確認顧客", sell_ways: [],
      },
    ],
    bundles: [
      {
        id: "bdl_duo", name: "雙效組", price: 799, break_even: 539, offer_labels: ["組合價 省 59"],
        thumbnails: [], state: "ready",
        components: [
          { product_id: "prd_multi", name: "綜合維他命軟糖", qty: 1 },
          { product_id: "prd_bio", name: "益生菌軟糖", qty: 1 },
        ],
      },
    ],
    suggestions: [],
    ...overrides,
  };
}

function view(data: MetaSpendSummary, products: ProductsPage | Error = productsPage({ products: [], bundles: [] })) {
  vi.mocked(fetchMetaSpend).mockResolvedValue(data);
  if (products instanceof Error) vi.mocked(fetchProductsPage).mockRejectedValue(products);
  else vi.mocked(fetchProductsPage).mockResolvedValue(products);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CockpitPage brandId="brd_1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe("CockpitPage 資料時間與歸因", () => {
  it("有數字但帳號還沒完成拉取時，寫資料讀取時間，不寫尚未成功拉取", async () => {
    view(spend());
    expect(await screen.findByText("資料讀取於 3 小時前")).toBeTruthy();
    expect(screen.getByText("1,200")).toBeTruthy();
    expect(screen.queryByText("尚未成功拉取")).toBeNull();
  });

  it("帳號拉取成功時寫更新時間", async () => {
    view(spend({ last_pull_at: hoursAgo(2) }));
    expect(await screen.findByText("更新於 2 小時前")).toBeTruthy();
  });

  it("past 24 hours the stamp is the org clock's MM/DD HH:mm (F50-I14): 00:30Z prints 08:30 in Taipei", async () => {
    view(spend({ last_pull_at: "2026-01-01T00:30:00Z" }));
    expect(await screen.findByText("更新於 01/01 08:30")).toBeTruthy();
  });

  it("兩個時間都沒有時才寫尚未成功拉取", async () => {
    view(spend({ data_pulled_at: null, attribution_label: null }));
    expect(await screen.findByText("尚未成功拉取")).toBeTruthy();
  });

  it("ROAS 卡寫出歸因窗", async () => {
    view(spend());
    expect(
      await screen.findByText("平台回報 · 非全通路 · 歸因：點擊後 7 天＋瀏覽後 1 天"),
    ).toBeTruthy();
  });
});

describe("CockpitPage 品牌資料入口（F42-I12）", () => {
  it("標題列右側有「品牌資料（建檔時填的）」連到品牌建檔", async () => {
    view(spend());
    const link = await screen.findByRole("link", { name: "品牌資料（建檔時填的）" });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/intake");
  });
});

describe("CockpitPage 你的商品（F43-I14）", () => {
  const block = () => screen.getByRole("region", { name: "你的商品" });

  it("商品與組合各一張精簡卡片，動作連到建新商品與新增組合", async () => {
    view(spend(), productsPage());
    expect(await screen.findByText("單盒 399・三盒組 999")).toBeTruthy();
    const region = block();
    expect(within(region).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
      "/brands/brd_1/products/bundles/new",
      "/brands/brd_1/products/new",
      "/brands/brd_1/products/prd_multi/onboarding",
      "/brands/brd_1/products/prd_bio/onboarding?step=2",
      "/brands/brd_1/products/prd_bio/onboarding?step=2",
      "/brands/brd_1/products/bundles/bdl_duo",
    ]);
    expect(within(region).getByRole("link", { name: "＋建新商品" })).toBeTruthy();
    expect(within(region).getByRole("link", { name: "＋新增組合" })).toBeTruthy();
    expect(within(region).getByRole("link", { name: "繼續 →" }).getAttribute("href")).toBe(
      "/brands/brd_1/products/prd_bio/onboarding?step=2",
    );
    expect(within(region).getByText("建到一半：還沒確認顧客")).toBeTruthy();
    expect(within(region).getByText("組合・799")).toBeTruthy();
    expect(within(region).getAllByText("可以投放")).toHaveLength(2);
  });

  it("還沒有商品：只留標題與兩個動作，不另外說話", async () => {
    view(spend());
    await screen.findByText("資料讀取於 3 小時前");
    const region = block();
    await vi.waitFor(() => expect(fetchProductsPage).toHaveBeenCalledWith("brd_1"));
    await vi.waitFor(() => expect(region.querySelectorAll(".animate-pulse")).toHaveLength(0));
    expect(region.querySelector("[data-slot=product-card]")).toBeNull();
    expect(within(region).getAllByRole("link")).toHaveLength(2);
    expect(within(region).queryByRole("alert")).toBeNull();
  });

  it("讀取失敗只在區塊內顯示重試，經營概況其他內容照常", async () => {
    view(spend(), new Error("讀取商品失敗。"));
    expect(await within(block()).findByRole("alert")).toBeTruthy();
    expect(within(block()).getByText("商品讀取失敗：讀取商品失敗。")).toBeTruthy();
    expect(within(block()).getByRole("link", { name: "＋建新商品" })).toBeTruthy();
    expect(screen.getByText("1,200")).toBeTruthy();
    expect(screen.getByText("活動表")).toBeTruthy();

    vi.mocked(fetchProductsPage).mockResolvedValue(productsPage());
    await userEvent.click(within(block()).getByRole("button", { name: "重新載入" }));
    expect(await within(block()).findByText("單盒 399・三盒組 999")).toBeTruthy();
    expect(within(block()).queryByRole("alert")).toBeNull();
  });
});
