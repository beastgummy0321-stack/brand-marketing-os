/** frontend/src/components/ads/AdsHomePage.test.tsx — F04-I09: 首頁四塊全部照 `getAdsHome`
 * 給的字串印，前端不重拼判斷句、不算百分比、不印假 0。 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { AdsHome, CampaignCard } from "@/lib/adsApi";
import { getAdsHome } from "@/lib/adsApi";
import { AdsHomePage } from "./AdsHomePage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, getAdsHome: vi.fn() };
});

function campaignCard(overrides: Partial<CampaignCard> = {}): CampaignCard {
  return {
    id: "cmp_1",
    name: "測試 Campaign",
    status: "live",
    start_date: "2026-01-01",
    end_date: "2026-01-31",
    objective: "conversion",
    created_at: "2026-01-01T00:00:00Z",
    created_by: null,
    budget_planned: null,
    budget_total: null,
    budget_progress: { spent: null, total: null, pct: null },
    judgment: { tone: "neutral", text: "投放中", detail: "還沒有花費資料" },
    outcome: { spend: 0, purchases: 0, revenue: 0 },
    ...overrides,
  };
}

function home(overrides: Partial<AdsHome> = {}): AdsHome {
  return {
    headline: { text: "本月投放整體正常", facts: "3 個 Campaign 進行中" },
    counts: { running: 0, upcoming: 0, ended: 0, needs_decision: 0 },
    campaigns: [],
    actions: [],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AdsHomePage brandId="brd_1" />
    </MemoryRouter>,
  );
}

describe("AdsHomePage（F04-I09）", () => {
  it("空資料：三個空狀態句子都出現，畫面上沒有任何一格印 0", async () => {
    vi.mocked(getAdsHome).mockResolvedValue(home({ campaigns: [], actions: [] }));

    renderPage();

    expect(await screen.findByText("目前沒有需要你決定的事")).toBeTruthy();
    expect(screen.getByText("目前沒有進行中的 Campaign。")).toBeTruthy();
    expect(screen.getByText("還沒有任何紀錄。")).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("有 judgment.text 的 Campaign：那句話原樣出現，前端沒有自己重拼", async () => {
    vi.mocked(getAdsHome).mockResolvedValue(
      home({
        campaigns: [
          campaignCard({
            judgment: { tone: "warn", text: "投放中，預算花得比時間快", detail: "第 5／31 天" },
          }),
        ],
      }),
    );

    renderPage();

    expect(await screen.findByText("投放中，預算花得比時間快")).toBeTruthy();
  });

  it("席位保留卡：出現「自動執行接上後開放」，且沒有「不支援」「尚未開放使用」這些字", async () => {
    vi.mocked(getAdsHome).mockResolvedValue(home());

    renderPage();

    expect(await screen.findByText("自動執行接上後開放")).toBeTruthy();
    expect(screen.queryByText(/不支援/)).toBeNull();
    expect(screen.queryByText(/尚未開放使用/)).toBeNull();
  });

  it("Campaign 卡格線在 1024／1280 是兩欄、1536 以上才三欄", async () => {
    vi.mocked(getAdsHome).mockResolvedValue(home({ campaigns: [campaignCard()] }));

    renderPage();

    const grid = await screen.findByTestId("campaign-grid");
    expect(grid.className).toContain("sm:grid-cols-2");
    expect(grid.className).toContain("2xl:grid-cols-3");
    expect(grid.className).not.toContain("lg:grid-cols-3");
  });
});
