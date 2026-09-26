import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({
    identity: { user: { id: "user-1" }, org: { id: "org-1" } },
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

import { fetchMetaSpend, type MetaSpendSummary } from "@/lib/metaApi";
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

function view(data: MetaSpendSummary) {
  vi.mocked(fetchMetaSpend).mockResolvedValue(data);
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
