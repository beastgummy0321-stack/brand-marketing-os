/** frontend/src/components/ads/AllCampaignsPage.test.tsx — F04-I10: 所有 Campaign 清單頁，
 * 篩選 pill 的筆數對得上、篩選後表格只剩對應的列、budget_progress.total 是 null 時不准印 0%。 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { CampaignCard } from "@/lib/adsApi";
import { listCampaigns } from "@/lib/adsApi";
import { AllCampaignsPage } from "./AllCampaignsPage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, listCampaigns: vi.fn() };
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

function renderPage() {
  return render(
    <MemoryRouter>
      <AllCampaignsPage brandId="brd_1" />
    </MemoryRouter>,
  );
}

describe("AllCampaignsPage（F04-I10）", () => {
  it("六筆（3 live／2 ready／1 closed）→ 四顆 pill 的數字是 6／3／2／1", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCard({ id: "l1", name: "live 1", status: "live" }),
      campaignCard({ id: "l2", name: "live 2", status: "live" }),
      campaignCard({ id: "l3", name: "live 3", status: "live" }),
      campaignCard({ id: "r1", name: "ready 1", status: "ready" }),
      campaignCard({ id: "r2", name: "ready 2", status: "ready" }),
      campaignCard({ id: "c1", name: "closed 1", status: "closed" }),
    ]);

    renderPage();

    expect(await screen.findByRole("button", { name: "全部 6" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "進行中 3" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "即將上線 2" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "已結束 1" })).toBeTruthy();
  });

  it("點「已結束」→ 表格只剩 1 列，而且是那一筆 closed 的名稱", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCard({ id: "l1", name: "live 1", status: "live" }),
      campaignCard({ id: "c1", name: "closed 1", status: "closed" }),
    ]);

    const { default: userEvent } = await import("@testing-library/user-event");
    renderPage();

    const endedBtn = await screen.findByRole("button", { name: "已結束 1" });
    await userEvent.click(endedBtn);

    expect(screen.getByText("closed 1")).toBeTruthy();
    expect(screen.queryByText("live 1")).toBeNull();
  });

  it("budget_progress.total = null 的那一列印「尚未設定總預算」且沒有 0%", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCard({
        id: "l1",
        name: "沒有預算的 Campaign",
        status: "live",
        budget_progress: { spent: null, total: null, pct: null },
      }),
    ]);

    renderPage();

    expect(await screen.findByText("尚未設定總預算")).toBeTruthy();
    expect(screen.queryByText("0%")).toBeNull();
  });

  it("不印建立者 uuid（F04-I22）", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCard({
        id: "l1",
        name: "有建立者的 Campaign",
        status: "live",
        created_by: "b0a57eef-0000-4000-8000-000000000123",
      }),
    ]);

    renderPage();

    expect(await screen.findByText("有建立者的 Campaign")).toBeTruthy();
    expect(screen.queryByText(/由 .* 建立/)).toBeNull();
    expect(document.body.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-/);
  });
});
