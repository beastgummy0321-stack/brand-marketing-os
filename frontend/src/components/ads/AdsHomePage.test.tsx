/** frontend/src/components/ads/AdsHomePage.test.tsx — F04-I09: 首頁四塊全部照 `getAdsHome`
 * 給的字串印，前端不重拼判斷句、不算百分比、不印假 0。 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdsHome, CampaignCard } from "@/lib/adsApi";
import { getAdsHome } from "@/lib/adsApi";
import type { LaunchReadiness } from "@/lib/adsLaunchApi";
import { fetchLaunchReadiness } from "@/lib/adsLaunchApi";
import { AdsHomePage } from "./AdsHomePage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, getAdsHome: vi.fn() };
});

vi.mock("@/lib/adsLaunchApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsLaunchApi")>("@/lib/adsLaunchApi");
  return { ...actual, fetchLaunchReadiness: vi.fn() };
});

function readiness(overrides: Partial<LaunchReadiness> = {}): LaunchReadiness {
  return {
    state: "green",
    items: [
      { key: "offering", label: "賣的東西", state: "green", reason: "已經填好", fix_label: "去改", fix_href: "/brands/brd_1/intake" },
      { key: "goal", label: "廣告目標", state: "green", reason: "已經設定", fix_label: "去改", fix_href: "/brands/brd_1/intake" },
      { key: "account", label: "廣告帳戶", state: "green", reason: "已經接上", fix_label: "去接廣告帳戶", fix_href: "/brands/brd_1/intake" },
    ],
    notes: [],
    primary: { label: "開始建立", href: "/brands/brd_1/ads/new" },
    secondary: null,
    ...overrides,
  };
}

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
  beforeEach(() => {
    vi.mocked(fetchLaunchReadiness).mockResolvedValue(readiness());
  });

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

describe("AdsHomePage 建立 Campaign 卡的可投放檢查表（F05-I10）", () => {
  it("green：沒有檢查表，按鈕仍是「開始建立」", async () => {
    vi.mocked(getAdsHome).mockResolvedValue(home());
    vi.mocked(fetchLaunchReadiness).mockResolvedValue(readiness({ state: "green" }));

    renderPage();

    expect(await screen.findByText("開始建立")).toBeTruthy();
    expect(screen.queryByText(/還缺/)).toBeNull();
  });

  it("red：三句 reason 都印出來、主要按鈕是「先補齊地基」、次要「還是要先建立」沒有 disabled", async () => {
    vi.mocked(getAdsHome).mockResolvedValue(home());
    vi.mocked(fetchLaunchReadiness).mockResolvedValue(
      readiness({
        state: "red",
        items: [
          { key: "offering", label: "賣的東西", state: "red", reason: "還沒有填任何一項商品或服務。", fix_label: "去填", fix_href: "/brands/brd_1/intake" },
          { key: "goal", label: "廣告目標", state: "red", reason: "還沒有設定成效目標。", fix_label: "去設定", fix_href: "/brands/brd_1/intake" },
          { key: "account", label: "廣告帳戶", state: "red", reason: "還沒接上廣告帳戶。", fix_label: "去接廣告帳戶", fix_href: "/brands/brd_1/intake" },
        ],
        primary: { label: "先補齊地基", href: "/brands/brd_1/intake" },
        secondary: { label: "還是要先建立", href: "/brands/brd_1/ads/new" },
      }),
    );

    renderPage();

    expect(await screen.findByText("還沒有填任何一項商品或服務。")).toBeTruthy();
    expect(screen.getByText("還沒有設定成效目標。")).toBeTruthy();
    expect(screen.getByText("還沒接上廣告帳戶。")).toBeTruthy();
    const secondaryButton = screen.getByText("還是要先建立").closest("button");
    expect(secondaryButton).toBeTruthy();
    expect(secondaryButton?.hasAttribute("disabled")).toBe(false);
    expect(screen.getByText("先補齊地基")).toBeTruthy();
  });

  it("yellow：主要按鈕是「進入投放中心（有假設值）」且沒有次要按鈕", async () => {
    vi.mocked(getAdsHome).mockResolvedValue(home());
    vi.mocked(fetchLaunchReadiness).mockResolvedValue(
      readiness({
        state: "yellow",
        items: [
          { key: "offering", label: "賣的東西", state: "yellow", reason: "用的是假設成交率 20%。", fix_label: "去改", fix_href: "/brands/brd_1/intake" },
          { key: "goal", label: "廣告目標", state: "green", reason: "已經設定。", fix_label: "去改", fix_href: "/brands/brd_1/intake" },
          { key: "account", label: "廣告帳戶", state: "green", reason: "已經接上。", fix_label: "去接廣告帳戶", fix_href: "/brands/brd_1/intake" },
        ],
        primary: { label: "進入投放中心（有假設值）", href: "/brands/brd_1/ads/new" },
        secondary: null,
      }),
    );

    renderPage();

    expect(await screen.findByText("進入投放中心（有假設值）")).toBeTruthy();
    expect(screen.queryByText("還是要先建立")).toBeNull();
  });
});

it("renders imported campaign in the existing campaign grid", async () => {
  vi.mocked(getAdsHome).mockResolvedValue(home({ imported_campaigns: [campaignCard({ id: "imported1", name: "BP AD existing", origin: "imported", status: "draft" })] }));
  vi.mocked(fetchLaunchReadiness).mockResolvedValue(readiness());
  renderPage();
  expect(await screen.findByRole("heading", { name: "BP AD existing" })).toBeTruthy();
  expect(screen.getByTestId("campaign-grid").textContent).toContain("BP AD existing");
  expect(screen.queryByText("已納入的既有平台活動")).toBeNull();
  expect(screen.queryByText("草稿")).toBeNull();
});
