vi.mock("@/lib/figures", async (actual) => ({ ...await actual<typeof import("@/lib/figures")>(), useFigureBases: () => ({roas_platform: {label: "平台回報", formula: "平台回報的購買金額 ÷ 花費", unit: "ratio"}}) }));
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ scope: "user-1:org-1" }),
}));
vi.mock("@/lib/scheduleApi", () => ({
  fetchCreativePerformance: vi.fn(),
  fetchDiagnosis: vi.fn(),
}));

import type { MetaSpendSummary } from "@/lib/metaApi";
import {
  fetchCreativePerformance,
  fetchDiagnosis,
  type CreativePerformance,
  type CreativePerformanceValue,
  type Diagnosis,
} from "@/lib/scheduleApi";
import { CampaignTable, PerformanceWidget } from "./DashboardWidgets";

function value(overrides: Partial<CreativePerformanceValue> = {}): CreativePerformanceValue {
  return {
    key: "v1", label: "痛點直球", spend: 600, impressions: 100, clicks: 10,
    revenue: 1200, roas: 2.4, roas_coverage: 1, ad_count: 2, ...overrides,
  };
}

// Real shape of GET /api/schedule/brands/{b}/creative-performance (app/schedule/performance.py):
// per dimension, values[].spend + untagged.spend = total_spend.
function performance(untaggedAds: number, untaggedSpend: number): CreativePerformance {
  const untagged = { spend: untaggedSpend, ad_count: untaggedAds };
  return {
    window: { start_date: "2026-09-01", end_date: "2026-09-30" },
    currencies: [{
      currency: "TWD",
      total_spend: 1000 + untaggedSpend,
      untagged,
      dimensions: [{
        dimension: "angle",
        untagged,
        values: [value(), value({ key: "v2", label: "對比", spend: 400, revenue: 600, roas: 1.5 })],
      }],
    }],
  };
}

const noDiagnosis: Diagnosis = {
  status: null,
  window: { start_date: "2026-09-01", end_date: "2026-09-30", days_with_data: 25 },
  breakeven: { roas: 1.43, source: "規則卡毛利率 70%" },
  directional_only: true,
  suggestions: [],
  lenses: {},
  no_tagged_spend: false,
};

function renderWidget(data: CreativePerformance) {
  vi.mocked(fetchCreativePerformance).mockResolvedValue(data);
  vi.mocked(fetchDiagnosis).mockResolvedValue(noDiagnosis);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PerformanceWidget brandId="brd_1" onDetails={() => undefined} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("PerformanceWidget 座標覆蓋", () => {
  it("花費全部對到座標時明說，不是整行消失", async () => {
    renderWidget(performance(0, 0));
    expect(await screen.findByText("花費全部對到座標")).toBeTruthy();
    expect(screen.queryByText(/未標座標/)).toBeNull();
  });

  it("有未標座標的花費時照舊列出，不說全部對到", async () => {
    renderWidget(performance(1, 250));
    expect(await screen.findByText(/未標座標 1 則/)).toBeTruthy();
    expect(screen.queryByText("花費全部對到座標")).toBeNull();
  });
});

describe("CampaignTable 剛配對的活動", () => {
  it("表格下方說明剛配對的活動要等下一次每日讀取", () => {
    const total = {
      campaign_id: "total", campaign_name: "總計", spend: 1200, impressions: 3000, clicks: 90,
      roas_platform: 2.2, currency: "TWD",
    };
    const data: MetaSpendSummary = {
      last_pull_at: null,
      data_pulled_at: null,
      attribution_label: null,
      campaigns: [{ ...total, campaign_id: "c-1", campaign_name: "活動一" }],
      totals: [total],
    };
    render(
      <MemoryRouter>
        <CampaignTable data={data} />
      </MemoryRouter>,
    );
    expect(screen.getByText("剛配對的活動，下一次每日讀取後才會出現在這張表。")).toBeTruthy();
  });
});
