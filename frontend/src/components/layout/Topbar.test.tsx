/** frontend/src/components/layout/Topbar.test.tsx — F27-I20 (feature Decisions "Screens → Top
 * bar", Contract I `status-summary`): the shell's sync/queue chip. Only on brand routes; a
 * failed status-summary request renders nothing (never an error in the shell); the chip refetches
 * when the route changes. Mirrors the prototype's `.top` button
 * (`docs/design/ads/prototype-v7-ads-center.html` line ~127): dot + 「最近同步 M/D HH:MM」
 * (browser-local; `null` → 「尚未同步」; F47-I08: `attention.count > 0` adds 「・N 個資料來源要處理」 — the
 * connections page's own count — a warn dot and the page's first note as the link title) + chip 「N 項待處理」 (warn when > 0, hidden when 0), linking to
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

vi.mock("@/lib/jobsApi", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/jobsApi")>(),
  fetchActiveJobs: vi.fn().mockResolvedValue({
    data: [], total: 0, other_count: 0, done_today: 0, failed_today: 0, generated_at: "2026-09-23T02:40:00Z",
  }),
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

  it("有資料：綠點＋M/D HH:MM（組織時區，F50-I14）＋待處理晶片，連去 connections", async () => {
    vi.mocked(getStatusSummary).mockResolvedValue({
      last_success_at: "2026-09-19T14:40:00Z",
      attention: { count: 0, note: null },
      open_items: 3,
    });
    renderTopbar();
    const link = await screen.findByRole("link", { name: /最近同步/ });
    expect(link.getAttribute("href")).toBe("/brands/brd_bughunt/ads/connections");
    expect(link.textContent).toContain("最近同步 9/19 22:40");
    expect(link.textContent).toContain("3 項待處理");
    expect(link.querySelector(".bg-success")).toBeTruthy();
    expect(link.querySelector(".bg-warning")).toBeNull();
  });

  it("prints 08:30 for 00:30Z with the org in Taipei, whatever the runner's zone (F50-I14, Contract K)", async () => {
    vi.mocked(getStatusSummary).mockResolvedValue({
      last_success_at: "2026-10-03T00:30:00Z", attention: { count: 0, note: null }, open_items: 0,
    });
    renderTopbar();
    const link = await screen.findByRole("link", { name: /最近同步/ });
    expect(link.textContent).toContain("最近同步 10/3 08:30");
  });

  it("last_success_at 為 null：「尚未同步」", async () => {
    vi.mocked(getStatusSummary).mockResolvedValue({ last_success_at: null, attention: { count: 0, note: null }, open_items: 0 });
    renderTopbar();
    expect(await screen.findByText("尚未同步")).toBeTruthy();
  });

  it("attention.count > 0：警示點＋「・N 個資料來源要處理」，連結標題是資料連線頁第一句說明（drill-10 Q4）", async () => {
    vi.mocked(getStatusSummary).mockResolvedValue({
      last_success_at: "2026-09-19T14:40:00Z",
      attention: { count: 2, note: "來源讀取失敗；10/24、10/25 讀不到" },
      open_items: 0,
    });
    renderTopbar();
    const link = await screen.findByRole("link", { name: /最近同步/ });
    expect(link.textContent).toContain("2 個資料來源要處理");
    expect(link.textContent).not.toContain("活動讀取異常");
    expect(link.getAttribute("title")).toBe("來源讀取失敗；10/24、10/25 讀不到");
    expect(link.querySelector(".bg-warning")).toBeTruthy();
    expect(link.querySelector(".bg-success")).toBeNull();
  });

  it("attention.count 為 0：綠點、沒有「要處理」字樣，標題是同步句", async () => {
    vi.mocked(getStatusSummary).mockResolvedValue({
      last_success_at: null, attention: { count: 0, note: null }, open_items: 0,
    });
    renderTopbar();
    const link = await screen.findByRole("link", { name: /尚未同步/ });
    expect(link.textContent).not.toContain("要處理");
    expect(link.getAttribute("title")).toBe("尚未同步");
    expect(link.querySelector(".bg-success")).toBeTruthy();
  });

  it("open_items 為 0：不畫「項待處理」晶片", async () => {
    vi.mocked(getStatusSummary).mockResolvedValue({ last_success_at: "2026-09-19T14:40:00Z", attention: { count: 0, note: null }, open_items: 0 });
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
    vi.mocked(getStatusSummary).mockResolvedValue({ last_success_at: "2026-09-19T14:40:00Z", attention: { count: 0, note: null }, open_items: 1 });
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

describe("Topbar page label", () => {
  it("商品頁的位置標籤叫「商品」，跟頁面標題同一個詞（F43-I14）", async () => {
    vi.mocked(getStatusSummary).mockResolvedValue({ last_success_at: null, attention: { count: 0, note: null }, open_items: 0 });
    renderTopbar("/brands/brd_bughunt/products");
    const nav = screen.getByRole("navigation", { name: "目前位置" });
    expect(nav.textContent).toContain("商品");
    expect(nav.textContent).not.toContain("產品");
    await screen.findByText("尚未同步");
  });
});
