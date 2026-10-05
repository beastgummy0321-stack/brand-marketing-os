/** frontend/src/components/ads/AllCampaignsPage.test.tsx — F04-I10: 所有 Campaign 清單頁，
 * 篩選 pill 的筆數對得上、篩選後表格只剩對應的列、budget_progress.total 是 null 時不准印 0%。 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { CampaignCard, LifecycleState } from "@/lib/adsApi";
import { listCampaigns } from "@/lib/adsApi";
import { AllCampaignsPage } from "./AllCampaignsPage";
// F50 Contract K: the org clock reads the workspace org zone; dates assert Asia/Taipei output, never the runner's.
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-10-01" }, orgs: [] } }) }));

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

/** F49 Contract L: the served lifecycle (state + its word) a campaign read carries. */
const LABEL: [LifecycleState, string][] = [["draft", "草稿"], ["live", "投放中"], ["ended", "已結束・待結案"], ["closed", "已結案"]];
function lc(state: LifecycleState, label = LABEL.find(([s]) => s === state)?.[1] ?? "") {
  return { lifecycle: { state, label, can_close: state === "live" || state === "ended" } };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AllCampaignsPage brandId="brd_1" />
    </MemoryRouter>,
  );
}

describe("AllCampaignsPage（F04-I10）", () => {
  it("pills count the served lifecycle state: 已結束 (待結案) and 已結案 are separate", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCard({ id: "l1", name: "live 1", status: "live", ...lc("live") }),
      campaignCard({ id: "l2", name: "live 2", status: "live", ...lc("live") }),
      // Stored `live` past its end date: the served state says ended, and the list follows it.
      campaignCard({ id: "l3", name: "past end", status: "live", ...lc("ended") }),
      campaignCard({ id: "r1", name: "ready 1", status: "ready", ...lc("draft") }),
      campaignCard({ id: "r2", name: "ready on platform", status: "ready", ...lc("live") }),
      campaignCard({ id: "c1", name: "closed 1", status: "closed", ...lc("closed") }),
      campaignCard({ id: "i1", name: "imported ended", status: "draft", origin: "imported", ...lc("ended", "已結束") }),
    ]);

    renderPage();

    expect(await screen.findByRole("button", { name: "全部 7" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "既有平台活動 1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "進行中 3" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "即將上線 1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "已結束 1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "已結案 1" })).toBeTruthy();
  });

  it("點「已結束」只剩待結案的那一筆；點「已結案」只剩結案的那一筆", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCard({ id: "l1", name: "live 1", status: "live", ...lc("live") }),
      campaignCard({ id: "e1", name: "ended 1", status: "live", ...lc("ended") }),
      campaignCard({ id: "c1", name: "closed 1", status: "closed", ...lc("closed") }),
    ]);

    const { default: userEvent } = await import("@testing-library/user-event");
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "已結束 1" }));
    expect(screen.getByText("ended 1")).toBeTruthy();
    expect(screen.queryByText("closed 1")).toBeNull();
    expect(screen.queryByText("live 1")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "已結案 1" }));
    expect(screen.getByText("closed 1")).toBeTruthy();
    expect(screen.queryByText("ended 1")).toBeNull();
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

  it("F47-I08／F49 Contract L：狀態欄每個活動一個字＝後端給的 lifecycle.label，不看 status", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCard({ id: "d1", name: "草稿活動", status: "draft", ...lc("draft") }),
      campaignCard({ id: "r1", name: "待發布活動", status: "ready", ...lc("draft") }),
      campaignCard({ id: "l1", name: "投放中活動", status: "live", ...lc("live") }),
      campaignCard({ id: "e1", name: "過了結束日", status: "live", ...lc("ended") }),
      campaignCard({ id: "i1", name: "匯入活動", status: "draft", origin: "imported", ...lc("live") }),
      campaignCard({ id: "c1", name: "結案活動", status: "closed", ...lc("closed") }),
    ]);
    renderPage();
    await screen.findByText("草稿活動");
    const words = [...document.querySelectorAll("tbody tr")].map((tr) => tr.querySelectorAll("td")[1].textContent);
    expect(words).toEqual(["草稿", "草稿", "投放中", "已結束・待結案", "投放中", "已結案"]);
    expect(screen.queryByText("待發布")).toBeNull();
    expect(screen.queryByText("平台狀態見原始資料")).toBeNull();
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
