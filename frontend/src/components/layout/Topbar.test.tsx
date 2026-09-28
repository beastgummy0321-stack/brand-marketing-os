/** frontend/src/components/layout/Topbar.test.tsx — F27-I20 (feature Decisions "Screens → Top
 * bar", Contract I `status-summary`): the shell's sync/queue chip. Only on brand routes; a
 * failed status-summary request renders nothing (never an error in the shell); the chip refetches
 * when the route changes. Mirrors the prototype's `.top` button
 * (`docs/design/ads/prototype-v7-ads-center.html` line ~127): dot + 「最近同步 M/D HH:MM」
 * (browser-local; `null` → 「尚未同步」; `failing_campaigns > 0` adds 「・N 個活動讀取異常」 and
 * a warn dot) + chip 「N 項待處理」 (warn when > 0, hidden when 0), linking to
 * `/brands/:b/ads/connections`. */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { Topbar } from "./Topbar";
import { getStatusSummary } from "@/lib/adsStatusApi";
import type { Identity } from "@/lib/identityApi";
import type { DashboardBrandCard } from "@/lib/api";

vi.mock("@/lib/adsStatusApi", () => ({
  getStatusSummary: vi.fn(),
}));

vi.mock("@/lib/jobsApi", () => ({
  fetchActiveJobs: vi.fn().mockResolvedValue({
    data: [], total: 0, other_count: 0, done_today: 0, failed_today: 0, generated_at: "2026-09-23T02:40:00Z",
  }),
  ACTIVE_JOB_KIND_LABELS: {},
}));

const IDENTITY: Identity = {
  user: { id: "usr_1", email: "beastgummy0321@gmail.com" },
  org: { id: "org_bughunt", name: "示例組織", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-09-28" },
  orgs: [{ id: "org_bughunt", name: "示例組織", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-09-28" }],
};

const BRANDS: DashboardBrandCard[] = [
  { brand_id: "brd_bughunt", brand_name: "示例品牌", health: "green", revenue_this_month: null, revenue_mom_pct: null, next_step: null },
];

vi.mock("./WorkspaceContext", () => ({
  useWorkspace: () => ({ identity: IDENTITY, scope: "usr_1:org_bughunt", brands: BRANDS, brandsLoading: false, brandsError: null, refreshBrands: () => {} }),
}));

function renderTopbar(path = "/brands/brd_bughunt/ads") {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Topbar brandId="brd_bughunt" collapsed={false} onToggleSidebar={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(getStatusSummary).mockReset();
});

describe("Topbar sync status", () => {
  it("非品牌路由（brandId 為 null）不打 status-summary、不畫同步晶片", () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/brands"]}>
          <Topbar brandId={null} collapsed={false} onToggleSidebar={() => {}} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(getStatusSummary).not.toHaveBeenCalled();
    expect(screen.queryByText(/最近同步|尚未同步/)).toBeNull();
  });

  it("有資料：綠點＋M/D HH:MM（瀏覽器本地時區）＋待處理晶片，連去 connections", async () => {
    vi.mocked(getStatusSummary).mockResolvedValue({
      last_success_at: "2026-09-19T14:40:00Z",
      failing_campaigns: 0,
      open_items: 3,
    });
    renderTopbar();
    const link = await screen.findByRole("link", { name: /最近同步/ });
    expect(link.getAttribute("href")).toBe("/brands/brd_bughunt/ads/connections");
    const d = new Date("2026-09-19T14:40:00Z");
    const expected = `最近同步 ${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    expect(link.textContent).toContain(expected);
    expect(link.textContent).toContain("3 項待處理");
    expect(link.querySelector(".bg-success")).toBeTruthy();
    expect(link.querySelector(".bg-warning")).toBeNull();
  });

  it("last_success_at 為 null：「尚未同步」", async () => {
    vi.mocked(getStatusSummary).mockResolvedValue({ last_success_at: null, failing_campaigns: 0, open_items: 0 });
    renderTopbar();
    expect(await screen.findByText("尚未同步")).toBeTruthy();
  });

  it("failing_campaigns > 0：警示點＋「・N 個活動讀取異常」", async () => {
    vi.mocked(getStatusSummary).mockResolvedValue({
      last_success_at: "2026-09-19T14:40:00Z",
      failing_campaigns: 2,
      open_items: 0,
    });
    renderTopbar();
    const link = await screen.findByRole("link", { name: /最近同步/ });
    expect(link.textContent).toContain("2 個活動讀取異常");
    expect(link.querySelector(".bg-warning")).toBeTruthy();
    expect(link.querySelector(".bg-success")).toBeNull();
  });

  it("open_items 為 0：不畫「項待處理」晶片", async () => {
    vi.mocked(getStatusSummary).mockResolvedValue({ last_success_at: "2026-09-19T14:40:00Z", failing_campaigns: 0, open_items: 0 });
    renderTopbar();
    await screen.findByText(/最近同步/);
    expect(screen.queryByText(/項待處理/)).toBeNull();
  });

  it("讀取失敗：殼層整塊不畫，絕不現錯誤字", async () => {
    vi.mocked(getStatusSummary).mockRejectedValue(new Error("讀取同步狀態摘要失敗。"));
    renderTopbar();
    await waitFor(() => expect(getStatusSummary).toHaveBeenCalled());
    expect(screen.queryByText(/最近同步|尚未同步|項待處理/)).toBeNull();
    expect(screen.queryByText(/失敗|錯誤/)).toBeNull();
  });

  it("換頁（route 變）重打一次 status-summary", async () => {
    vi.mocked(getStatusSummary).mockResolvedValue({ last_success_at: "2026-09-19T14:40:00Z", failing_campaigns: 0, open_items: 1 });
    const client = new QueryClient();
    function Harness() {
      const navigate = useNavigate();
      return (
        <div>
          <button onClick={() => navigate("/brands/brd_bughunt/ads/campaigns/cmp_1/detail")}>go</button>
          <Topbar brandId="brd_bughunt" collapsed={false} onToggleSidebar={() => {}} />
        </div>
      );
    }
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/brands/brd_bughunt/ads"]}>
          <Harness />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(getStatusSummary).toHaveBeenCalledTimes(1));

    await userEvent.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(getStatusSummary).toHaveBeenCalledTimes(2));
  });
});
