vi.mock("@/lib/figures", async (actual) => ({ ...await actual<typeof import("@/lib/figures")>(), useFigureBases: () => ({roas_platform: {label: "平台回報", formula: "平台回報的購買金額 ÷ 花費", unit: "ratio"}}) }));
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
import { defaultLayout, layoutKey, type DashboardView } from "@/lib/dashboardLayout";

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString();

// Real shape of GET /api/meta/brands/{b}/spend (app/meta/routes.py SpendSummaryResponse).
function spend(overrides: Partial<MetaSpendSummary> = {}): MetaSpendSummary {
  const total = {
    campaign_id: "total", campaign_name: "總計", spend: 1200, impressions: 3000, clicks: 90,
    roas_platform: 2.2, currency: "TWD",
  };
  return {
    last_pull_at: null,
    data_pulled_at: hoursAgo(3),
    attribution_label: "點擊後 7 天＋瀏覽後 1 天",
    campaigns: [{ ...total, campaign_id: "c-1", campaign_name: "活動一" }],
    totals: [total],
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
    expect(screen.getByText("1,200 TWD")).toBeTruthy();
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
    expect(screen.getByText("1,200 TWD")).toBeTruthy();
    expect(screen.getByText("活動表")).toBeTruthy();

    vi.mocked(fetchProductsPage).mockResolvedValue(productsPage());
    await userEvent.click(within(block()).getByRole("button", { name: "重新載入" }));
    expect(await within(block()).findByText("單盒 399・三盒組 999")).toBeTruthy();
    expect(within(block()).queryByRole("alert")).toBeNull();
  });
});


describe("Cockpit currency totals", () => {
  it("prints each currency on its own line", async () => {
    view(spend({ totals: [
      { currency: "TWD", spend: 1200, impressions: 3000, clicks: 90, roas_platform: 2.2 },
      { currency: "USD", spend: 40, impressions: 1000, clicks: 20, roas_platform: 1.5 },
    ] }));
    expect(await screen.findByText("1,200 TWD")).toBeTruthy();
    expect(screen.getByText("40 USD")).toBeTruthy();
    expect(screen.queryByText(/1,240/)).toBeNull();
  });
});

describe("Cockpit last visible block (F52-I16)", () => {
  it.each([
    { label: "廣告花費", metrics: ["spend"], widgets: [], other: "活動概況" },
    { label: "活動概況", metrics: [], widgets: [{ id: "campaigns", width: "wide" }], other: "廣告花費" },
  ] satisfies Array<Pick<DashboardView, "metrics" | "widgets"> & { label: string; other: string }>)
  ("explains $label on keyboard focus, persists the last block and restores defaults", async ({ label, metrics, widgets, other }) => {
    const user = userEvent.setup();
    const key = layoutKey("user-1", "org-1", "brd_1");
    localStorage.setItem(key, JSON.stringify({
      version: 1, activeId: "ads",
      views: [{ id: "ads", name: "廣告成效", metrics, widgets }],
    }));
    let rendered = view(spend());
    await user.click(await screen.findByRole("button", { name: "自訂版面" }));
    let panel = screen.getByRole("dialog", { name: "自訂看板版面" });
    const checkbox = within(panel).getByRole("checkbox", { name: label }) as HTMLInputElement;
    const reason = within(panel).getByText("至少保留一個區塊；先勾選其他指標或區塊，才能取消這項。");
    const group = within(panel).getByRole("group", { name: label });
    expect(checkbox.checked).toBe(true);
    expect(checkbox.disabled).toBe(true);
    expect(checkbox.getAttribute("aria-describedby")).toBe(reason.id);
    expect(group.getAttribute("aria-describedby")).toBe(reason.id);
    expect(group.getAttribute("aria-disabled")).toBe("true");
    within(panel).getByRole("textbox", { name: "檢視名稱" }).focus();
    for (let i = 0; i < 10 && document.activeElement !== group; i++) await user.tab();
    expect(document.activeElement).toBe(group);
    await user.keyboard(" ");
    expect(checkbox.checked).toBe(true);

    await user.click(within(panel).getByRole("button", { name: "完成" }));
    rendered.unmount();
    rendered = view(spend());
    await user.click(await screen.findByRole("button", { name: "自訂版面" }));
    panel = screen.getByRole("dialog", { name: "自訂看板版面" });
    const restored = within(panel).getByRole("checkbox", { name: label }) as HTMLInputElement;
    expect(restored.checked).toBe(true);
    expect(restored.disabled).toBe(true);
    await user.click(within(panel).getByRole("checkbox", { name: other }));
    expect(restored.disabled).toBe(false);
    expect(restored.hasAttribute("aria-describedby")).toBe(false);
    expect(within(panel).queryByRole("group", { name: label })).toBeNull();
    expect(within(panel).queryByText(reason.textContent!)).toBeNull();
    await user.click(restored);
    expect(restored.checked).toBe(false);
    expect((within(panel).getByRole("checkbox", { name: other }) as HTMLInputElement).disabled).toBe(true);

    await user.click(within(panel).getByRole("button", { name: "重設此檢視" }));
    expect(within(panel).getAllByRole("checkbox").every((input) => !(input as HTMLInputElement).disabled)).toBe(true);
    expect(within(panel).queryByText(reason.textContent!)).toBeNull();
    const expected = defaultLayout().views[0];
    expect(JSON.parse(localStorage.getItem(key)!).views[0]).toEqual(expected);
    await user.click(within(panel).getByRole("button", { name: "完成" }));
    rendered.unmount();
    view(spend());
    await user.click(await screen.findByRole("button", { name: "自訂版面" }));
    panel = screen.getByRole("dialog", { name: "自訂看板版面" });
    expect(within(panel).getAllByRole("checkbox").filter((input) => (input as HTMLInputElement).checked)).toHaveLength(9);
    expect(within(panel).getAllByRole("checkbox").every((input) => !(input as HTMLInputElement).disabled)).toBe(true);
  });
});
