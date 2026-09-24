/** frontend/src/components/ads/AdsHomePage.test.tsx — F28-I08: the ads-centre home as board D (prototype v9
 * `home()`). Page-level behaviour only: the two requests (`GET …/home` and the brand queue) load and fail on their
 * own, today's decisions are the open cleanup／worse／refresh rows (three cards, the rest in one fold), the 調整 entry
 * opens the existing monthly-budget editor, and the F27-I17 recovery banner still works. Block details are in
 * `home/HomeBoard.test.tsx`. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getHomeOverview, type HomeOverview } from "@/lib/adsHomeApi";
import { refreshQueue, type QueueItem, type QueueKind, type QueuePayload, type QueueProposal, type TriageItem } from "@/lib/adsTriageApi";
import { getMonthlyBudget, type MonthlyBudget } from "@/lib/adsChangeApi";
import { getRecovery, type AdsRecovery } from "@/lib/adsStatusApi";
import { AdsHomePage } from "./AdsHomePage";

vi.mock("@/lib/adsHomeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsHomeApi")>("@/lib/adsHomeApi");
  return { ...actual, getHomeOverview: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, refreshQueue: vi.fn() };
});
vi.mock("@/lib/adsChangeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsChangeApi")>("@/lib/adsChangeApi");
  return { ...actual, getMonthlyBudget: vi.fn() };
});
vi.mock("@/lib/adsStatusApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsStatusApi")>("@/lib/adsStatusApi");
  return { ...actual, getRecovery: vi.fn() };
});

function home(overrides: Partial<HomeOverview> = {}): HomeOverview {
  return {
    month: "2026-09", day_of_month: 23, days_in_month: 30, currency: "TWD", spent: 22000,
    money: {
      purchases: 158, cost_per_purchase: 139.24, cap: { value: 450, basis: "own" }, earn: 60163.5, earn_missing: [], excluded: [],
      previous_same_period: { days: 22, purchases: 118, cost_per_purchase: 221.37 },
    },
    pace: { budget_amount: 60000, available: 23600, daily: [{ day: "2026-09-01", cumulative: 900 }, { day: "2026-09-22", cumulative: 22000 }], projected_month_end: 28695.65 },
    quality: { buckets: [
      { grade: "on_target", amount: 14300, count: 6, ads: [] },
      { grade: "watch", amount: 3120, count: 1, ads: [{ entity_id: "a7", name: "再行銷・兩入組", thumbnail_url: null, spend: 3120 }] },
      { grade: "over", amount: 2470, count: 1, ads: [{ entity_id: "a8", name: "提問式貼文", thumbnail_url: null, spend: 2470 }] },
      { grade: "wasted", amount: 1480, count: 1, ads: [{ entity_id: "a9", name: "秋季新色預告", thumbnail_url: null, spend: 1480 }] },
      { grade: "insufficient", amount: 630, count: 4, ads: [] },
    ] },
    timeline: [
      { date: "2026-09-23", kind: "today", campaign_id: null, name: null, ready: null },
      { date: "2026-09-30", kind: "month_review", campaign_id: null, name: null, ready: null },
    ],
    campaigns: [
      { campaign_id: "cmp_daily", name: "日常商品推廣・轉換", origin: "internal", status: "live", month_spend: 15767, purchases: 121,
        cost_per_purchase: 130.31, cap: { value: 450, basis: "own" }, active_ads: 8, daily_budget: 1200, missing_days: [], sync_state: "ok", draft: null },
    ],
    sync: { last_success_at: "2026-09-23T00:40:00Z", next_at: "2026-09-23T04:40:00Z" },
    ...overrides,
  };
}

function triage(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "ad_1", native_id: "n_1", name: "再行銷・兩入組 NT$1,580 免運 - 複本 2", campaign_id: "cmp_daily", campaign_name: "日常商品推廣・轉換",
    thumbnail_url: null, class: "worse", label: "變差", reason_code: "worse", grade: "over", grade_label: "太貴",
    window: { start: "2026-09-16", end: "2026-09-22", days: 7, previous_start: "2026-09-09", previous_end: "2026-09-15", extended_from: null },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 3120, result_count: 6, cost_per_result: 520, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    previous: { spend: 3080, result_count: 7, cost_per_result: 440, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: 18.2, sample: { gate: true, spend_multiple: 6.9, days_with_events: 7 },
    ...overrides,
  };
}

function item(id: string, kind_key: QueueKind, extra: Partial<QueueItem> = {}, t: Partial<TriageItem> = {}): QueueItem {
  return {
    id, org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: `k_${id}`, category: "ads", kind: null,
    severity: "rule_warning", message: "", action_url: null, visible_from: null, status: "open", created_at: "2026-09-23T00:00:00Z",
    resolved_at: null, kind_key, triage: triage({ entity_id: `ad_${id}`, ...t }), proposal: null, ...extra,
  };
}

function cleanupItem(id: string, campaignName = "日常商品推廣・轉換"): QueueItem {
  return item(id, "cleanup", {
    action_url: `/brands/brd_1/ads/campaigns/cmp_daily/propose/cleanup/cmp_daily`,
    cleanup: {
      campaign_id: "cmp_daily", campaign_name: campaignName, can_support: 6, active_ads: 8, short: 0, daily_saving: 257, scale_owner_id: null, keep: [],
      ads: [{ entity_id: "a9", name: "秋季新色預告・直式 9:16 短影音", thumbnail_url: null, spend_7d: 770, grade: "wasted", cost_per_result: null, spend: 1480, result_count: 0, daily_spend: 110 }],
    },
  }, { class: "stop_loss", grade: "wasted" });
}

function queue(items: QueueItem[]): QueuePayload {
  return { items, counts: { stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 }, total_ads: 0, kinds_available: [], kinds_pending: [] };
}

const notRecovering: AdsRecovery = { recovering: false, gap: null, steps: [] };
const budget: MonthlyBudget = {
  month: "2026-09", currency: "TWD", amount: 60000, revision: 1, known_spend: 22000, ongoing_estimate: 14400, reserved_increases: 0,
  available: 23600, uncertainties: [], can_increase: true, period_end: "2026-09-30", confirmed_at: null, notice: "",
};

function renderPage() {
  return render(<MemoryRouter><AdsHomePage brandId="brd_1" /></MemoryRouter>);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getHomeOverview).mockResolvedValue(home());
  vi.mocked(refreshQueue).mockResolvedValue(queue([]));
  vi.mocked(getRecovery).mockResolvedValue(notRecovering);
  vi.mocked(getMonthlyBudget).mockResolvedValue(budget);
});

describe("AdsHomePage (F28-I08 board D)", () => {
  it("title is the month and its day; the two header actions link to month review and new campaign", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "9 月的廣告" })).toBeTruthy();
    expect(await screen.findByText("第 23 天／共 30 天")).toBeTruthy();
    expect(screen.getByRole("link", { name: "每月回顧" }).getAttribute("href")).toBe("/brands/brd_1/ads/month");
    expect(screen.getByRole("link", { name: "建立活動" }).getAttribute("href")).toBe("/brands/brd_1/ads/new");
    expect(screen.getByRole("button", { name: "加入既有活動" })).toBeTruthy();
    expect(vi.mocked(refreshQueue)).toHaveBeenCalledTimes(1);
  });

  it("decisions: open cleanup, worse and refresh rows only, in that order; stop_loss and scale rows are not cards", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue([
      item("w1", "worse"),
      item("s1", "stop_loss", {}, { class: "stop_loss" }),
      item("r1", "refresh_creative", { action_url: "/brands/brd_1/ads/campaigns/cmp_daily?tab=assets", refresh: { campaign_id: "cmp_daily", campaign_name: "日常商品推廣・轉換", readable_count: 2, classified_count: 5, thumbnails: [null] } }),
      cleanupItem("c1"),
    ]));
    renderPage();
    const section = await screen.findByRole("region", { name: /需要你決定/ });
    const cards = await within(section).findAllByRole("article");
    expect(cards.map((c) => c.getAttribute("aria-label"))).toEqual(["關 1 則、留 0 則", "再行銷・兩入組 NT$1,580 免運 - 複本 2", "能判讀的素材只剩 2 則"]);
    expect(within(section).getByText("3 件")).toBeTruthy();
    expect(within(cards[0]).getByRole("link", { name: "決定要不要關 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_daily/propose/cleanup/cmp_daily");
    expect(within(cards[1]).getByRole("link", { name: "查原因 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_daily/review/ad_w1");
    expect(within(cards[2]).getByRole("link", { name: "準備新素材 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_daily?tab=assets");
    expect(await screen.findByRole("button", { name: "3 件要你決定 ↓" })).toBeTruthy();
  });

  it("more than three open decisions: three cards, the rest behind one closed fold that uses the cleanup cut mark", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue([item("w1", "worse"), cleanupItem("c1"), cleanupItem("c2"), cleanupItem("c3"), cleanupItem("c4", "中秋限定活動・送禮受眾")]));
    renderPage();
    const section = await screen.findByRole("region", { name: /需要你決定/ });
    expect(await within(section).findAllByRole("article")).toHaveLength(3);
    const fold = within(section).getByRole("button", { name: "還有 2 件要決定" });
    expect(fold.getAttribute("aria-expanded")).toBe("false");
    await userEvent.click(fold);
    expect(within(section).getByText("中秋限定活動")).toBeTruthy();
    const cut = section.querySelector('[data-slot="kind-mark"][data-variant="cut"]');
    expect(cut?.textContent).toBe("✂清理");
    expect(within(section).getByText("5 件")).toBeTruthy();
  });

  it("a handled decision leaves the cards and the count, and sits in the 處理過 fold", async () => {
    const rejected: QueueProposal = { kind: "cleanup", change_set_id: "cs_1", campaign_id: "cmp_daily", status: "rejected", verification_state: "pending", reason: null, revisit_at: null, multi: true };
    vi.mocked(refreshQueue).mockResolvedValue(queue([{ ...cleanupItem("c1"), proposal: rejected }, item("w1", "worse")]));
    renderPage();
    const section = await screen.findByRole("region", { name: /需要你決定/ });
    expect(await within(section).findAllByRole("article")).toHaveLength(1);
    expect(within(section).getByText("1 件")).toBeTruthy();
    expect(within(section).getByRole("button", { name: "處理過 1 件" })).toBeTruthy();
  });

  it("no open decision: honest empty card with the sync time, and 今天 says nothing to decide", async () => {
    renderPage();
    expect(await screen.findByText("今天沒有要決定的事")).toBeTruthy();
    expect(screen.getByText("沒有要決定的事")).toBeTruthy();
    expect(screen.getByRole("link", { name: "看每月回顧" }).getAttribute("href")).toBe("/brands/brd_1/ads/month");
  });

  it("queue read fails: only the decisions block fails (hero + retry); the money, band and rows still render; retry recovers", async () => {
    vi.mocked(refreshQueue).mockRejectedValueOnce(new Error("讀取失敗")).mockResolvedValueOnce(queue([item("w1", "worse")]));
    renderPage();
    expect(await screen.findByText("今天的判斷讀取失敗")).toBeTruthy();
    expect(screen.getByRole("button", { name: "判斷讀取失敗 ↓" })).toBeTruthy();
    expect(screen.getByText("約 NT$60,000")).toBeTruthy();
    expect(screen.getByText("65%")).toBeTruthy();
    expect(screen.getByRole("link", { name: "日常商品推廣・轉換" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "重新讀取" }));
    expect(await screen.findByRole("link", { name: "查原因 →" })).toBeTruthy();
  });

  it("home overview read fails: money, band and rows say so with a retry; the decisions still render", async () => {
    vi.mocked(getHomeOverview).mockRejectedValueOnce(new Error("x")).mockResolvedValueOnce(home());
    vi.mocked(refreshQueue).mockResolvedValue(queue([item("w1", "worse")]));
    renderPage();
    expect(await screen.findByText("這個月的花費與預算暫時讀取不到・已保存的資料都還在")).toBeTruthy();
    expect(screen.getByText("分級暫時讀取不到")).toBeTruthy();
    expect(screen.getByText("活動暫時讀取不到")).toBeTruthy();
    expect(await screen.findByRole("link", { name: "查原因 →" })).toBeTruthy();
    expect(screen.queryByText(/NT\$0/)).toBeNull();
    await userEvent.click(screen.getAllByRole("button", { name: "重新讀取" })[0]);
    expect(await screen.findByText("約 NT$60,000")).toBeTruthy();
  });

  it("a running platform read holds the judgement: 同步中 chip, skeleton cards, and 今天 waits", async () => {
    vi.mocked(getHomeOverview).mockResolvedValue(home({ campaigns: home().campaigns!.map((c) => ({ ...c, sync_state: "syncing" as const })) }));
    vi.mocked(refreshQueue).mockResolvedValue(queue([item("w1", "worse")]));
    renderPage();
    expect(await screen.findByText("同步中・完成後才判斷")).toBeTruthy();
    expect(screen.getByText("同步中，完成後再判斷")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "查原因 →" })).toBeNull();
  });

  it("an open scale_budget row becomes 看加預算建議 on the pace card; 調整 opens the existing monthly-budget editor", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue([item("s1", "scale_budget", {
      scale: { owner: { id: "adset_A", name: "A", native_kind: "adset", native_id: "n", ads_count: 3, currency: "TWD" }, from: 400, to: 480, cost_per_result: 48,
        previous_cost_per_result: 52, target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] }, window_days: 7, month: { available: 23600, extra_needed: 640 } },
    }, { class: "better", grade: "on_target" })]));
    renderPage();
    expect((await screen.findByRole("link", { name: "看加預算建議 →" })).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_daily/propose/budget/adset_A");
    await userEvent.click(screen.getByRole("button", { name: "調整" }));
    expect(await screen.findByRole("heading", { name: "本月廣告預算" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "← 收起" }));
    expect(vi.mocked(getHomeOverview)).toHaveBeenCalledTimes(2);
  });

  describe("F27-I17 recovery (getRecovery)", () => {
    it("recovering: the banner shows and every decision action is replaced by the placeholder", async () => {
      vi.mocked(refreshQueue).mockResolvedValue(queue([item("w1", "worse")]));
      vi.mocked(getRecovery).mockResolvedValue({
        recovering: true, gap: { start: "2026-09-22T09:10:00Z", end: "2026-09-22T11:30:00Z", minutes: 140 },
        steps: [{ key: "resync", label: "補 2 小時的資料", state: "active" }],
      });
      renderPage();
      expect(await screen.findByText("系統暫停了 2 小時 20 分，正在補資料")).toBeTruthy();
      expect(await screen.findByText("補完資料後更新")).toBeTruthy();
      expect(screen.queryByRole("link", { name: "查原因 →" })).toBeNull();
    });

    it("getRecovery fails: no banner, the rest of the page still renders", async () => {
      vi.mocked(getRecovery).mockRejectedValue(new Error("x"));
      renderPage();
      expect(await screen.findByText("今天沒有要決定的事")).toBeTruthy();
      expect(screen.queryByText(/系統暫停了/)).toBeNull();
    });
  });
});
