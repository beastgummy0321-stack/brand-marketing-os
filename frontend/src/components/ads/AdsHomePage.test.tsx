vi.mock("@/lib/figures", async (actual) => ({ ...await actual<typeof import("@/lib/figures")>(), useFigureBases: () => ({earn_after_cost_and_ads: {label: "扣掉商品成本和廣告費", formula: "成交數 ×（售價 − 成本含運）− 廣告費", unit: "money"}}) }));
/** frontend/src/components/ads/AdsHomePage.test.tsx — F28-I08: the ads-centre home as board D (prototype v9
 * `home()`). Page-level behaviour only: the two requests (`GET …/home` and the brand queue) load and fail on their
 * own, today's decisions are the open cleanup／worse／refresh rows (three cards, the rest in one fold), the 調整 entry
 * opens the existing monthly-budget editor, and the F27-I17 recovery banner still works. Block details are in
 * `home/HomeBoard.test.tsx`. */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getHomeOverview, type HomeOverview } from "@/lib/adsHomeApi";
import { refreshQueue, type CloseoutQueueRow, type QueueItem, type QueueKind, type QueuePayload, type QueueProposal, type SettleQueueRow, type TriageItem } from "@/lib/adsTriageApi";
import { getMonthlyBudget, saveMonthlyBudget, type MonthlyBudget } from "@/lib/adsChangeApi";
import { getRecovery, type AdsRecovery } from "@/lib/adsStatusApi";
import { AdsHomePage } from "./AdsHomePage";
import { ApiNetworkError } from "@/lib/http";
// F50 Contract K: the org clock reads the workspace org zone; dates assert Asia/Taipei output, never the runner's.
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-10-01" }, orgs: [] } }) }));

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
  return { ...actual, getMonthlyBudget: vi.fn(), saveMonthlyBudget: vi.fn() };
});
vi.mock("@/lib/adsStatusApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsStatusApi")>("@/lib/adsStatusApi");
  return { ...actual, getRecovery: vi.fn() };
});

function home(overrides: Partial<HomeOverview> = {}): HomeOverview {
  return {
    closed_this_month: 0, month: "2026-09", day_of_month: 23, days_in_month: 30, currency: "TWD", spent: 22000,
    commerce: null, money: {
      purchases: 158, cost_per_purchase: 139.24, cap: { value: 450, basis: "own", break_even: 520 }, earn_after_cost_and_ads: 60163.5, earn_missing: [], estimate_basis: { kind: "platform_purchase_margin", assumptions: [], missing: [] }, excluded: [],
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
        cost_per_purchase: 130.31, cap: { value: 450, basis: "own", break_even: 520 }, active_ads: 8, daily_budget: 1200, missing_days: [], sync_state: "ok",
        data_status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: "2026-09-23T00:40:00Z" }, handoff: null, draft: null },
    ],
    sync: { last_success_at: "2026-09-23T00:40:00Z", next_at: "2026-09-23T04:40:00Z",
      eligible_at: "2026-09-23T04:40:00Z", worker_health: { state: "alive", checked_at: "2026-09-23T00:40:00Z", last_heartbeat_at: "2026-09-23T00:40:00Z", reason_code: "heartbeat_fresh" } },
    ...overrides,
  };
}

function triage(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "ad_1", native_id: "n_1", name: "再行銷・兩入組 NT$1,580 免運 - 複本 2", campaign_id: "cmp_daily", campaign_name: "日常商品推廣・轉換",
    thumbnail_url: null, class: "worse", label: "變差", reason_code: "worse", grade: "over", grade_label: "太貴", previous_grade: "on_target", grade_move: { from: "on_target", to: "over" },
    window: { start: "2026-09-16", end: "2026-09-22", days: 7, previous_start: "2026-09-09", previous_end: "2026-09-15", extended_from: null },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 3120, result_count: 6, cost_per_result: 520, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    previous: { spend: 3080, result_count: 7, cost_per_result: 440, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: 0.182, sample: { gate: true, spend_multiple: 6.9, days_with_events: 7 },
    ...overrides,
  };
}

function item(id: string, kind_key: QueueKind, extra: Partial<QueueItem> = {}, t: Partial<TriageItem> = {}): QueueItem {
  return {
    id, org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: `k_${id}`, category: "ads", kind: null,
    severity: "rule_warning", message: "", action_url: null, visible_from: null, status: "open", created_at: "2026-09-23T00:00:00Z",
    resolved_at: null, kind_key, triage: triage({ entity_id: `ad_${id}`, ...t }), proposal: null, done: false, ...extra,
  };
}

function cleanupItem(id: string, campaignName = "日常商品推廣・轉換"): QueueItem {
  return item(id, "cleanup", {
    action_url: `/brands/brd_1/ads/campaigns/cmp_daily/propose/cleanup/cmp_daily`,
    cleanup: {
      campaign_id: "cmp_daily", campaign_name: campaignName, can_support: 6, active_ads: 8, short: 0, daily_saving: 257, scale_owner_id: null, keep: [],
      ads: [{ entity_id: "a9", name: "秋季新色預告・直式 9:16 短影音", thumbnail_url: null, spend_7d: 770, grade: "wasted", cost_per_result: null, spend: 1480, result_count: 0, daily_spend: 110, rejected_before: null }],
    },
  }, { class: "stop_loss", grade: "wasted" });
}

/** The brand's open period-settle row for August, raised on 9/2 (Contract E). */
function settleRow(): SettleQueueRow {
  return {
    id: "itr_settle", dedupe_key: "k_settle", category: "ads_triage_settle", severity: "rule_warning", message: "結算上一期（8 月），待寫進筆記本",
    action_url: "/brands/brd_1/ads/settle/2026-08/result", visible_from: null, status: "open", created_at: "2026-09-02T00:00:00Z",
    settle: { month: "2026-08", start: "2026-08-01", end: "2026-08-31", campaign_count: 2, imported_count: 1, learnable_count: 5, buckets: [
      { grade: "on_target", amount: 15300, count: 2, ads: [] }, { grade: "watch", amount: 3900, count: 1, ads: [] },
      { grade: "over", amount: 9340, count: 2, ads: [] }, { grade: "wasted", amount: 1600, count: 1, ads: [] },
      { grade: "insufficient", amount: 1600, count: 2, ads: [] },
    ] },
  };
}

function queue(items: QueueItem[]): QueuePayload {
  return { items, counts: { stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 }, total_ads: 0, kinds_available: [], kinds_pending: [] };
}

/** A queue as F49 Contract Q serves it: rows stamped with `decision`／`position`, `decisions.open` the count. */
function served(items: QueueItem[], open: number, extra: Partial<QueuePayload> = {}): QueuePayload {
  return { ...queue(items), settle: null, closeouts: [], decisions: { kinds: ["cleanup", "worse", "closeout", "refresh_creative"], open }, ...extra };
}

/** An ended campaign's closeout row (Contract Q), as `splitQueue` hands it over. */
function closeout(overrides: Partial<CloseoutQueueRow> = {}): CloseoutQueueRow {
  return {
    id: "itr_close", dedupe_key: "k_close", category: "ads_triage_closeout", severity: "rule_warning", message: "「秋季檔期・第三期」已結束，待結案",
    action_url: "/brands/brd_1/ads/campaigns/cmp_fall?tab=perf&close=1", visible_from: null, status: "open", created_at: "2026-10-10T00:00:00Z",
    campaign_id: "cmp_fall", decision: true, position: 1, done: false,
    closeout: { campaign_id: "cmp_fall", campaign_name: "秋季檔期・第三期", end_date: "2026-10-09", running: { count: 2, read_at: "2026-10-10T02:00:00Z" } },
    ...overrides,
  };
}

const notRecovering: AdsRecovery = { recovering: false, gap: null, steps: [] };
const budget: MonthlyBudget = {
  month: "2026-09", currency: "TWD", amount: 60000, revision: 1, known_spend: 22000, ongoing_estimate: 14400, reserved_increases: 0,
  available: 23600, uncertainties: [], can_increase: true, period_end: "2026-09-30", confirmed_at: null, notice: "",
};

function renderPage() {
  return render(<MemoryRouter><AdsHomePage brandId="brd_1" /></MemoryRouter>);
}

function Search() {
  return <output aria-label="search">{useLocation().search}</output>;
}
/** F46-I09: the page as a 「設定／提高 N 月月預算」 link opens it. */
function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes><Route path="/brands/:b/ads" element={<><AdsHomePage brandId="brd_1" /><Search /></>} /></Routes>
    </MemoryRouter>,
  );
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

  // F49 Contract Q: which rows are decisions (`decision`), their order (`position`) and the count (`decisions.open`)
  // are served; the order here (worse, refresh, cleanup) is not the old local list (cleanup, worse, refresh).
  it("decisions: the served decision rows in their served position; notice rows (stop_loss, scale) are not cards", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(served([
      item("w1", "worse", { decision: true, position: 1 }),
      item("s1", "stop_loss", { decision: false, position: null }, { class: "stop_loss" }),
      item("r1", "refresh_creative", { decision: true, position: 2, action_url: "/brands/brd_1/ads/campaigns/cmp_daily?tab=assets", refresh: { campaign_id: "cmp_daily", campaign_name: "日常商品推廣・轉換", readable_count: 2, classified_count: 5, thumbnails: [null] } }),
      { ...cleanupItem("c1"), decision: true, position: 3 },
    ], 3));
    renderPage();
    const section = await screen.findByRole("region", { name: /需要你決定/ });
    const cards = await within(section).findAllByRole("article");
    expect(cards.map((c) => c.getAttribute("aria-label"))).toEqual(["再行銷・兩入組 NT$1,580 免運 - 複本 2", "能判讀的素材只剩 2 則", "關 1 則、留 0 則"]);
    expect(within(section).getByText("3 件")).toBeTruthy();
    expect(within(cards[2]).getByRole("link", { name: "決定要不要關 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_daily/propose/cleanup/cmp_daily");
    expect(within(cards[0]).getByRole("link", { name: "查原因 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_daily/review/ad_w1");
    expect(within(cards[1]).getByRole("link", { name: "準備新素材 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_daily?tab=assets");
    expect(await screen.findByRole("button", { name: "3 件要你決定 ↓" })).toBeTruthy();
  });

  it("the count is the served decisions.open: 今天 and the chip say it even when it differs from the rows in this read", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(served([item("w1", "worse", { decision: true, position: 1 })], 2));
    renderPage();
    const section = await screen.findByRole("region", { name: /需要你決定/ });
    expect(await within(section).findAllByRole("article")).toHaveLength(1);
    expect(within(section).getByText("2 件")).toBeTruthy();
    expect(await screen.findByRole("button", { name: "2 件要你決定 ↓" })).toBeTruthy();
  });

  it("an ended campaign's closeout row is a decision card: the served sentence, its end and running ads, 結案這一期 to its own link", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(served([item("w1", "worse", { decision: true, position: 2 })], 2, {
      closeouts: [closeout({ position: 1 })],
    }));
    renderPage();
    const section = await screen.findByRole("region", { name: /需要你決定/ });
    const cards = await within(section).findAllByRole("article");
    expect(cards.map((c) => c.getAttribute("aria-label"))).toEqual(["「秋季檔期・第三期」已結束，待結案", "再行銷・兩入組 NT$1,580 免運 - 複本 2"]);
    expect(within(cards[0]).getByText("10/09 結束・平台上還開著 2 則")).toBeTruthy();
    expect(within(cards[0]).getByRole("link", { name: "結案這一期 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_fall?tab=perf&close=1");
    expect(within(section).getByText("2 件")).toBeTruthy();
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

  it("a handled decision leaves the cards and the count, and sits in the 今天處理過 fold", async () => {
    const rejected: QueueProposal = { kind: "cleanup", change_set_id: "cs_1", campaign_id: "cmp_daily", status: "rejected", verification_state: "pending", reason: null, revisit_at: null, multi: true };
    vi.mocked(refreshQueue).mockResolvedValue(queue([{ ...cleanupItem("c1"), proposal: rejected, done: true }, item("w1", "worse")]));
    renderPage();
    const section = await screen.findByRole("region", { name: /需要你決定/ });
    expect(await within(section).findAllByRole("article")).toHaveLength(1);
    expect(within(section).getByText("1 件")).toBeTruthy();
    await userEvent.click(within(section).getByRole("button", { name: "今天處理過 1 件" }));
    expect(within(section).getByText("清理：關 1 則、留 0 則")).toBeTruthy();
    expect(within(section).getByText("已拒絕")).toBeTruthy();
  });

  // F29-I11: the period settle is one of today's decisions (QueuePayload.settle, Contract E).
  it("settle row present: counted and placed by its served position; the card spans the row and opens the settle page", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(served([
      item("r1", "refresh_creative", { decision: true, position: 1, action_url: "/brands/brd_1/ads/campaigns/cmp_daily?tab=assets", refresh: { campaign_id: "cmp_daily", campaign_name: "日常商品推廣・轉換", readable_count: 2, classified_count: 5, thumbnails: [null] } }),
      item("w1", "worse", { decision: true, position: 3 }),
    ], 3, { settle: { ...settleRow(), decision: true, position: 2, done: false } }));
    renderPage();
    const section = await screen.findByRole("region", { name: /需要你決定/ });
    const cards = await within(section).findAllByRole("article");
    expect(cards.map((c) => c.getAttribute("aria-label"))).toEqual(["能判讀的素材只剩 2 則", "結算上一期", "再行銷・兩入組 NT$1,580 免運 - 複本 2"]);
    expect(cards[1].className).toContain("col-span-full");
    expect(within(cards[1]).getByRole("link", { name: "開始結算 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/settle/2026-08/result");
    expect(within(section).getByText("3 件")).toBeTruthy();
    expect(await screen.findByRole("button", { name: "3 件要你決定 ↓" })).toBeTruthy();
  });

  it("settle as the fourth open decision folds under the three cards with its own row", async () => {
    vi.mocked(refreshQueue).mockResolvedValue({ ...queue([cleanupItem("c1"), item("w1", "worse"), item("w2", "worse")]), settle: settleRow() });
    renderPage();
    const section = await screen.findByRole("region", { name: /需要你決定/ });
    expect(await within(section).findAllByRole("article")).toHaveLength(3);
    expect(within(section).queryByRole("article", { name: "結算上一期" })).toBeNull();
    await userEvent.click(within(section).getByRole("button", { name: "還有 1 件要決定" }));
    expect(within(section).getByRole("link", { name: "開始結算 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/settle/2026-08/result");
    expect(within(section).getByText("4 件")).toBeTruthy();
  });

  it("settle row absent (null): no settle card and it adds nothing to the count", async () => {
    vi.mocked(refreshQueue).mockResolvedValue({ ...queue([item("w1", "worse")]), settle: null });
    renderPage();
    const section = await screen.findByRole("region", { name: /需要你決定/ });
    expect(await within(section).findAllByRole("article")).toHaveLength(1);
    expect(within(section).queryByText(/結算上一期/)).toBeNull();
    expect(await screen.findByRole("button", { name: "1 件要你決定 ↓" })).toBeTruthy();
  });

  it("only a settle row open: today is not 沒有要決定的事", async () => {
    vi.mocked(refreshQueue).mockResolvedValue({ ...queue([]), settle: settleRow() });
    renderPage();
    expect(await screen.findByRole("article", { name: "結算上一期" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "1 件要你決定 ↓" })).toBeTruthy();
    expect(screen.queryByText("今天沒有要決定的事")).toBeNull();
  });

  it("no open decision: honest empty card with the sync time, and 今天 says nothing to decide", async () => {
    renderPage();
    expect(await screen.findByText("今天沒有要決定的事")).toBeTruthy();
    expect(screen.getByText("沒有要決定的事")).toBeTruthy();
    expect(screen.getByRole("link", { name: "看每月回顧" }).getAttribute("href")).toBe("/brands/brd_1/ads/month");
  });

  it.each(["home", "queue", "both"])("shows the central network reason for %s failure and retries independently", async (failed) => {
    const error = new ApiNetworkError(false);
    if (failed !== "queue") vi.mocked(getHomeOverview).mockRejectedValueOnce(error).mockResolvedValue(home());
    if (failed !== "home") vi.mocked(refreshQueue).mockRejectedValueOnce(error).mockResolvedValue(queue([]));
    renderPage();
    expect(await screen.findAllByText(error.message)).toHaveLength(failed === "both" ? 2 : 1);
    if (failed !== "queue") {
      const money = screen.getByRole("region", { name: "這個月的錢" });
      expect(within(money).getByText(error.message)).toBeTruthy();
      await userEvent.click(within(money).getByRole("button", { name: "重新讀取" }));
      expect(await screen.findByText("60,000 TWD")).toBeTruthy();
      if (failed === "both") expect(screen.getAllByText(error.message)).toHaveLength(1);
    }
    if (failed !== "home") {
      const decisions = screen.getByRole("region", { name: /需要你決定/ });
      expect(within(decisions).getByText(error.message)).toBeTruthy();
      await userEvent.click(within(decisions).getByRole("button", { name: "重新讀取" }));
      expect(await screen.findByText("今天沒有要決定的事")).toBeTruthy();
    }
    expect(screen.queryByText(error.message)).toBeNull();
  });

  it("preserves a served error and the POST queue's uncertain-outcome message without translating them again", async () => {
    const queueError = new ApiNetworkError(true);
    vi.mocked(getHomeOverview).mockRejectedValueOnce(new Error("花費資料暫時無法提供"));
    vi.mocked(refreshQueue).mockRejectedValueOnce(queueError);
    renderPage();
    expect(await screen.findByText("花費資料暫時無法提供")).toBeTruthy();
    expect(await screen.findByText(queueError.message)).toBeTruthy();
  });

  it("queue read fails: only the decisions block fails (hero + retry); the money, band and rows still render; retry recovers", async () => {
    vi.mocked(refreshQueue).mockRejectedValueOnce(new Error("讀取失敗")).mockResolvedValueOnce(queue([item("w1", "worse")]));
    renderPage();
    expect(await screen.findByText("今天的判斷讀取失敗")).toBeTruthy();
    expect(screen.getByRole("button", { name: "判斷讀取失敗 ↓" })).toBeTruthy();
    expect(await screen.findByText("60,000 TWD")).toBeTruthy();
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
    expect(await screen.findByText("60,000 TWD")).toBeTruthy();
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

  it("?budget=edit (the 月預算 links) opens the editor with the saved amount and scrolls it into view; closing drops the param", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    renderAt("/brands/brd_1/ads?budget=edit");
    expect(await screen.findByRole("heading", { name: "本月廣告預算" })).toBeTruthy();
    expect(((await screen.findByRole("spinbutton", { name: "每月品牌總額" })) as HTMLInputElement).value).toBe("60000");
    expect(screen.getByRole("button", { name: "確認月總額" })).toBeTruthy();
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status", { name: "search" }).textContent).toBe("?budget=edit");
    await userEvent.click(screen.getByRole("button", { name: "← 收起" }));
    expect(screen.queryByRole("heading", { name: "本月廣告預算" })).toBeNull();
    expect(screen.getByRole("status", { name: "search" }).textContent).toBe("");
    // A later 調整 opens the panel as before, not straight into the form.
    await userEvent.click(screen.getByRole("button", { name: "調整" }));
    expect(await screen.findByRole("button", { name: "調整月總額" })).toBeTruthy();
    expect(screen.queryByRole("spinbutton", { name: "每月品牌總額" })).toBeNull();
  });

  it("?budget=edit with no budget saved yet opens the form empty (no invented default)", async () => {
    vi.mocked(getMonthlyBudget).mockResolvedValue({ ...budget, amount: null, revision: 0, currency: null, available: null, can_increase: false });
    renderAt("/brands/brd_1/ads?budget=edit");
    expect(((await screen.findByRole("spinbutton", { name: "每月品牌總額" })) as HTMLInputElement).value).toBe("");
  });

  it("F47-I06 (W3): a saved monthly total reads the money card again at once (no reload needed)", async () => {
    vi.mocked(saveMonthlyBudget).mockResolvedValue({ ...budget, amount: 45000, revision: 2 });
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "調整" }));
    await userEvent.click(await screen.findByRole("button", { name: "調整月總額" }));
    const reads = vi.mocked(getHomeOverview).mock.calls.length;
    const amount = screen.getByRole("spinbutton", { name: "每月品牌總額" });
    await userEvent.clear(amount);
    await userEvent.type(amount, "45000");
    await userEvent.click(screen.getByRole("button", { name: "確認月總額" }));
    await waitFor(() => expect(vi.mocked(getHomeOverview).mock.calls.length).toBe(reads + 1));
    expect(saveMonthlyBudget).toHaveBeenCalledWith("brd_1", expect.objectContaining({ amount: 45000 }), expect.any(AbortSignal));
  });

  // F49 Contract Q (drill-11 Q4): an approval's month-budget gate links here with `return=<its path>`.
  it("?budget=edit&return=<approval>: after saving, 「← 回到剛才的核准」 leads back; it stays after the area closes", async () => {
    vi.mocked(saveMonthlyBudget).mockResolvedValue({ ...budget, amount: 70000, revision: 2 });
    const back = "/brands/brd_1/ads/campaigns/cmp_daily/changes/acs_1/confirm";
    renderAt(`/brands/brd_1/ads?budget=edit&return=${encodeURIComponent(back)}`);
    const amount = await screen.findByRole("spinbutton", { name: "每月品牌總額" });
    expect(screen.queryByRole("link", { name: "← 回到剛才的核准" })).toBeNull();
    await userEvent.clear(amount);
    await userEvent.type(amount, "70000");
    await userEvent.click(screen.getByRole("button", { name: "確認月總額" }));
    expect((await screen.findByRole("link", { name: "← 回到剛才的核准" })).getAttribute("href")).toBe(back);
    await userEvent.click(screen.getByRole("button", { name: "← 收起" }));
    expect(screen.getByRole("status", { name: "search" }).textContent).toBe("");
    expect(screen.getByRole("link", { name: "← 回到剛才的核准" }).getAttribute("href")).toBe(back);
  });

  it("closing the area without saving also offers the way back", async () => {
    const back = "/brands/brd_1/ads/campaigns/cmp_daily/propose/budget/adset_A";
    renderAt(`/brands/brd_1/ads?budget=edit&return=${encodeURIComponent(back)}`);
    await screen.findByRole("spinbutton", { name: "每月品牌總額" });
    await userEvent.click(screen.getByRole("button", { name: "← 收起" }));
    expect(screen.getByRole("link", { name: "← 回到剛才的核准" }).getAttribute("href")).toBe(back);
  });

  it("a return outside this brand's ads centre (or without budget=edit) is ignored", async () => {
    for (const bad of ["https://evil.example/x", "//evil.example/brands/brd_1/ads/x", "/brands/brd_2/ads/campaigns/c", "/settings"]) {
      const { unmount } = renderAt(`/brands/brd_1/ads?budget=edit&return=${encodeURIComponent(bad)}`);
      await screen.findByRole("spinbutton", { name: "每月品牌總額" });
      await userEvent.click(screen.getByRole("button", { name: "← 收起" }));
      expect(screen.queryByRole("link", { name: "← 回到剛才的核准" })).toBeNull();
      unmount();
    }
    renderAt(`/brands/brd_1/ads?return=${encodeURIComponent("/brands/brd_1/ads/campaigns/c")}`);
    await userEvent.click(await screen.findByRole("button", { name: "調整" }));
    await userEvent.click(screen.getByRole("button", { name: "← 收起" }));
    expect(screen.queryByRole("link", { name: "← 回到剛才的核准" })).toBeNull();
  });

  it("without the param the home opens with the editor closed", async () => {
    renderAt("/brands/brd_1/ads");
    expect(await screen.findByRole("button", { name: "調整" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "本月廣告預算" })).toBeNull();
    expect(getMonthlyBudget).not.toHaveBeenCalled();
  });

  it("zero campaigns and nothing spent: one empty card whose primary action is 建立活動; no board that could only print zeros", async () => {
    vi.mocked(getHomeOverview).mockResolvedValue(home({
      spent: null, campaigns: [], quality: null, timeline: [{ date: "2026-09-23", kind: "today", campaign_id: null, name: null, ready: null }],
      money: { purchases: null, cost_per_purchase: null, cap: null, earn_after_cost_and_ads: null, earn_missing: ["no_purchase_campaign"], estimate_basis: { kind: "platform_purchase_margin", assumptions: [], missing: ["no_purchase_campaign"] }, excluded: [], previous_same_period: null },
      pace: { budget_amount: null, available: null, daily: [], projected_month_end: null },
    }));
    renderPage();
    const empty = await screen.findByRole("region", { name: "還沒有進行中的活動" });
    const create = within(empty).getByRole("link", { name: "建立活動" });
    expect(create.getAttribute("href")).toBe("/brands/brd_1/ads/new");
    expect(create.getAttribute("data-variant")).toBe("default");
    expect(screen.getAllByRole("link", { name: "建立活動" })).toHaveLength(1);
    expect(within(empty).getByRole("button", { name: "加入既有活動" })).toBeTruthy();
    expect(screen.queryByText("的廣告費花得划算")).toBeNull();
    expect(screen.queryByRole("region", { name: /需要你決定/ })).toBeNull();
    expect(screen.queryByText(/算不出來|還沒有購買|NT\$0|0 筆/)).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "9 月的廣告" })).toBeTruthy();
  });

  it("no campaign in progress and nothing spent, but campaigns closed this month (drill-11 N3): never 「還沒有活動」 or a first-run card", async () => {
    vi.mocked(getHomeOverview).mockResolvedValue(home({
      spent: null, campaigns: [], quality: null, closed_this_month: 3,
      money: { purchases: null, cost_per_purchase: null, cap: null, earn_after_cost_and_ads: null, earn_missing: ["no_purchase_campaign"], estimate_basis: { kind: "platform_purchase_margin", assumptions: [], missing: ["no_purchase_campaign"] }, excluded: [], previous_same_period: null },
    }));
    renderPage();
    const rows = await screen.findByTestId("campaign-grid");
    expect(rows.textContent).toContain("這個月沒有進行中的活動・已結案 3 個");
    expect(within(rows).getByRole("link", { name: "已結案 3 個" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns");
    expect(screen.queryByText("還沒有活動")).toBeNull();
    expect(screen.queryByRole("region", { name: "還沒有進行中的活動" })).toBeNull();
  });

  it("no open campaign but spend this month (a campaign closed mid-month): the board still shows that spend", async () => {
    vi.mocked(getHomeOverview).mockResolvedValue(home({ campaigns: [] }));
    renderPage();
    expect(await screen.findByText("9 月已花 22,000 元")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "還沒有進行中的活動" })).toBeNull();
    expect(screen.getByText("還沒有活動")).toBeTruthy();
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

// F29-I10 Contract K (drill-5 item 7): the 「今天」 count and the decision cards are one queue read — while it is slow
// both wait, when it fails both say so, and neither ever says 「沒有要決定的事」 in the meantime.
describe("AdsHomePage (F29-I10) one queue read for the count and the cards", () => {
  it("slow queue read: 今天 and the decisions both wait (never 沒有要決定的事); when it lands, count and cards agree", async () => {
    let resolveQueue!: (q: QueuePayload) => void;
    vi.mocked(refreshQueue).mockReturnValue(new Promise<QueuePayload>((res) => { resolveQueue = res; }));
    renderPage();
    expect(await screen.findByText("60,000 TWD")).toBeTruthy();
    expect(screen.getByText("正在整理今天的判斷")).toBeTruthy();
    const section = screen.getByRole("region", { name: /需要你決定/ });
    expect(section.querySelector('[aria-busy="true"]')).toBeTruthy();
    expect(screen.queryByText("沒有要決定的事")).toBeNull();
    expect(screen.queryByText("今天沒有要決定的事")).toBeNull();

    resolveQueue(queue([item("w1", "worse"), cleanupItem("c1")]));
    const cards = await within(section).findAllByRole("article");
    expect(cards).toHaveLength(2);
    expect(within(section).getByText("2 件")).toBeTruthy();
    expect(screen.getByRole("button", { name: "2 件要你決定 ↓" })).toBeTruthy();
    expect(vi.mocked(refreshQueue)).toHaveBeenCalledTimes(1);
  });

  it("failed queue read: 今天 and the decisions both say it failed, never 沒有要決定的事; one retry re-reads both", async () => {
    vi.mocked(refreshQueue).mockRejectedValueOnce(new Error("讀取失敗")).mockResolvedValueOnce(queue([]));
    renderPage();
    expect(await screen.findByText("今天的判斷讀取失敗")).toBeTruthy();
    expect(screen.getByRole("button", { name: "判斷讀取失敗 ↓" })).toBeTruthy();
    expect(screen.queryByText("沒有要決定的事")).toBeNull();
    expect(screen.queryByText("今天沒有要決定的事")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "重新讀取" }));
    expect(await screen.findByText("今天沒有要決定的事")).toBeTruthy();
    expect(screen.getByText("沒有要決定的事")).toBeTruthy();
    expect(vi.mocked(refreshQueue)).toHaveBeenCalledTimes(2);
  });
});

