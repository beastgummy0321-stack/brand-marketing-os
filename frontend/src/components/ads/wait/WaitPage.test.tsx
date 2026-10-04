/** frontend/src/components/ads/wait/WaitPage.test.tsx — F24-I03／F49-I10：`vi.mock` 掉 `@/lib/adsApi`／
 * `@/lib/adsTriageApi`／`@/lib/ordersApi`／`@/lib/adsConnectionsApi`／`@/lib/adsExternalApi`，不打真的 API
 * （F31-I07：訂單缺口只讀 connections 的 `orders.missing_days`，`ordersApi` 留著 mock 證明不再被讀）。`useSyncOutcome`
 * 是真的，只換掉它底下的 `syncOutcome`。覆蓋：事實列（未連接／授權失效／缺天／訂單缺口）；F49 Contract Q 每個等待
 * 原因一列、字與出口來自 `rules.reasons`；Contract O 讀取失敗的頭部與重新讀取的結果句；Contract V 三種日子格；
 * Contract L 草稿與已結束的出口。 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CampaignCard as CampaignCardData, CampaignLifecycle } from "@/lib/adsApi";
import { listCampaigns } from "@/lib/adsApi";
import type { CampaignTriage, TriageClosedBlock, TriageData, TriageItem } from "@/lib/adsTriageApi";
import { getAdsRules, getTriage } from "@/lib/adsTriageApi";
import type { OrdersPageData } from "@/lib/ordersApi";
import { fetchOrders } from "@/lib/ordersApi";
import type { AdsConnections, ConnectionSource } from "@/lib/adsConnectionsApi";
import { getConnections } from "@/lib/adsConnectionsApi";
import type { CampaignSyncOutcome } from "@/lib/adsExternalApi";
import { syncCampaign, syncOutcome } from "@/lib/adsExternalApi";
import { RULES_FIXTURE, seedAdsRules } from "../patterns/rulesFixture";
import { WaitPage } from "./WaitPage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, listCampaigns: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, getTriage: vi.fn(), getAdsRules: vi.fn() };
});
vi.mock("@/lib/ordersApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/ordersApi")>("@/lib/ordersApi");
  return { ...actual, fetchOrders: vi.fn() };
});
vi.mock("@/lib/adsConnectionsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsConnectionsApi")>("@/lib/adsConnectionsApi");
  return { ...actual, getConnections: vi.fn() };
});
vi.mock("@/lib/adsExternalApi", () => ({ syncCampaign: vi.fn(), syncJob: vi.fn(), syncOutcome: vi.fn() }));

const mockListCampaigns = vi.mocked(listCampaigns);
const mockGetTriage = vi.mocked(getTriage);
const mockGetAdsRules = vi.mocked(getAdsRules);
const mockFetchOrders = vi.mocked(fetchOrders);
const mockGetConnections = vi.mocked(getConnections);
const mockSyncCampaign = vi.mocked(syncCampaign);
const mockSyncOutcome = vi.mocked(syncOutcome);

const LIVE: CampaignLifecycle = { state: "live", label: "投放中", can_close: true };

function campaignCard(overrides: Partial<CampaignCardData> = {}): CampaignCardData {
  return {
    id: "cmp_1", name: "【銷售】1150706 Beast Prime 最高數量", status: "live", lifecycle: LIVE,
    start_date: "2026-08-01", end_date: null, objective: "轉換",
    created_at: "2026-08-01T00:00:00Z", created_by: null,
    budget_planned: null, budget_total: null,
    budget_progress: { spent: null, total: null, pct: null },
    judgment: { tone: "neutral", text: "投放中", detail: "" },
    outcome: { spend: null, purchases: null, revenue: null },
    ...overrides,
  };
}

/** Defaults to a too_new ad (graded nothing yet, no trend). */
function triageItem(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "ad_1", native_id: "native_1", name: "1150706 健身情境單圖",
    campaign_id: "cmp_1", campaign_name: "【銷售】1150706 Beast Prime 最高數量", thumbnail_url: null,
    class: "insufficient", label: "資料不足", reason_code: "too_new",
    grade: "insufficient", grade_label: "剛開始、數字還不夠", previous_grade: null, grade_move: null,
    window: { start: "2026-09-13", end: "2026-09-19", days: 7, previous_start: "2026-09-06", previous_end: "2026-09-12", extended_from: null },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: null, result_count: null, cost_per_result: null, result_kind: null, result_label: "成果", derived_zero_days: 0, reason: "result_unknown_days" },
    previous: { spend: null, result_count: null, cost_per_result: null, result_kind: null, result_label: "成果", derived_zero_days: 0, reason: "result_unknown_days" },
    change_pct: null, sample: { gate: false, spend_multiple: null, days_with_events: 0 },
    ...overrides,
  };
}
/** A judged ad with its trend computed (a trend code, no wait). */
const judged = (overrides: Partial<TriageItem> = {}) =>
  triageItem({ class: "flat", reason_code: "cost_per_result_flat", grade: "on_target", grade_label: "划算", change_pct: 0.05, ...overrides });

// F26-I01: `closed` is always sent by the real backend -- an empty block here.
const EMPTY_CLOSED: TriageClosedBlock = {
  paused: 0, archived: 0, other: 0, total: 0, items: [], truncated: false,
};

const WINDOW = ["2026-09-13", "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-19"];
/** The served judged window, every day `data` unless named otherwise. */
function days(states: Record<string, "data" | "empty" | "missing"> = {}): TriageData["days"] {
  return WINDOW.map((day) => ({ day, state: states[day] ?? "data" }));
}

function data(overrides: Partial<TriageData> = {}): TriageData {
  return {
    sync: { state: "ok", error: null, last_success_at: "2026-09-19T14:40:00+00:00" },
    coverage: { start: "2026-09-13", end: "2026-09-19" },
    missing_days: [],
    days: days(),
    status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: "2026-09-19T14:40:00+00:00" },
    ...overrides,
  };
}

function triage(overrides: Partial<CampaignTriage> = {}): CampaignTriage {
  return { window_days: 7, items: [triageItem()], closed: EMPTY_CLOSED, data: data(), ...overrides };
}

function orders(overrides: Partial<OrdersPageData> = {}): OrdersPageData {
  return {
    brand: { id: "brd_1", name: "示例品牌" },
    summary: {
      since: "2026-08-23", until: "2026-09-22", has_history: true, order_count: 1,
      net_revenue: 100, average_order_value: 100, new_customers: 1, existing_customers: 0,
      repurchase_rate: null, repurchase_sample_size: 0, sku_margins: [],
    },
    orders: {
      items: [{ id: "ord_1", order_number: "#1", order_date: "2026-09-14", total_amount: 100, order_status: "Open", voucher_code: null }],
      page: 1, page_size: 12, total: 1,
    },
    policy_changes: [], channel_entries: [],
    ...overrides,
  };
}

/** The real `GET …/connections` shape (F30 Contract H), trimmed to the orders source the wait page reads. */
function ordersSource(overrides: Partial<ConnectionSource> = {}): ConnectionSource {
  return {
    key: "orders", kind: "orders", platform: null, name: "商城訂單報表", state: "missing_days",
    note: "最新到 09/14，缺 09/15 之後", last_success_at: null,
    missing_days: ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"],
    affected_campaigns: [], action: { label: "補報表", href: "/brands/brd_1/orders" }, reread: null,
    ...overrides,
  };
}
const ORDERS_OK = () => ordersSource({ state: "ok", note: "最新匯入 09/20", missing_days: [], action: null });

function connections(source: ConnectionSource = ordersSource()): AdsConnections {
  return {
    attention_count: source.state === "ok" ? 0 : 1,
    sources: [source],
    calendar: { month: "2026-09", today: "2026-09-19", rows: [] },
  };
}

function outcome(overrides: Partial<CampaignSyncOutcome> = {}): CampaignSyncOutcome {
  return { state: "found", code: null, text: "讀到了，數字已更新。", job_ids: ["job_1"], last_success_at: "2026-09-22T01:00:00+00:00", ...overrides };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/brands/brd_1/ads/campaigns/cmp_1/wait"]}>
      <Routes>
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/wait" element={<WaitPage brandId="brd_1" campaignId="cmp_1" />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** The row (TodoRow) whose title is `title`. */
function row(title: string): HTMLElement {
  const el = screen.getByText(title).closest("[data-slot='todo-row']");
  if (!el) throw new Error(`no row ${title}`);
  return el as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  mockListCampaigns.mockResolvedValue([campaignCard()]);
  // The orders list still says the latest order is 9/14; the wait page must not derive its gap from it (F31-I07).
  mockFetchOrders.mockResolvedValue(orders());
  mockGetConnections.mockResolvedValue(connections(ORDERS_OK()));
  mockSyncOutcome.mockResolvedValue(outcome());
});

describe("WaitPage 事實列", () => {
  it("帳戶未連接＋缺天＋訂單缺口三列", async () => {
    mockGetConnections.mockResolvedValue(connections());
    mockGetTriage.mockResolvedValue(triage({
      items: [],
      data: data({
        sync: { state: "disconnected", error: null, last_success_at: "2026-09-19T14:40:00+00:00" },
        missing_days: ["2026-09-17", "2026-09-18"],
        days: days({ "2026-09-17": "missing", "2026-09-18": "missing" }),
        status: { state: "disconnected", label: "廣告帳號已中斷連線，讀不到新資料。", missing_days: ["2026-09-17", "2026-09-18"], last_success_at: "2026-09-19T14:40:00+00:00" },
      }),
    }));
    renderPage();
    expect(await screen.findByText("廣告帳戶未連接")).toBeTruthy();
    expect(screen.getByRole("link", { name: "去連接 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/connections");
    expect(screen.getByText("缺 9/17、9/18（2 天）")).toBeTruthy();
    expect(screen.getByText("商城報表從 9/15 起還沒補")).toBeTruthy();
    expect(screen.getByText("補到 9/19 才能對照訂單")).toBeTruthy();
    expect(screen.getByRole("link", { name: "補報表 →" }).getAttribute("href")).toBe("/brands/brd_1/orders");
  });

  it("授權失效時列「Meta 讀取權限失效」，按鈕連到 /settings?tab=meta（F27-I21）", async () => {
    mockGetTriage.mockResolvedValue(triage({
      data: data({
        sync: { state: "auth_expired", error: "拒絕存取", last_success_at: "2026-09-19T14:40:00+00:00" },
        status: { state: "auth_expired", label: "平台授權已過期，重新連線後才能讀資料。", missing_days: [], last_success_at: "2026-09-19T14:40:00+00:00" },
      }),
    }));
    renderPage();
    expect(await screen.findByText("Meta 讀取權限失效")).toBeTruthy();
    expect(screen.getByRole("link", { name: "重新授權 →" }).getAttribute("href")).toBe("/settings?tab=meta");
    expect(screen.queryByText("廣告帳戶未連接")).toBeNull();
  });

  it("F31-I07：匯入已涵蓋、只是沒有訂單的日子不算缺，不列訂單缺口", async () => {
    mockGetTriage.mockResolvedValue(triage());
    renderPage();
    await screen.findByText("剛開始、數字還不夠");
    expect(screen.queryByText(/商城報表/)).toBeNull();
    expect(mockGetConnections).toHaveBeenCalledWith("brd_1");
    expect(mockFetchOrders).not.toHaveBeenCalled();
  });

  it("訂單讀取失敗不拖累整頁，只是不列訂單缺口那一列", async () => {
    mockGetConnections.mockRejectedValue(new Error("讀取失敗"));
    mockGetTriage.mockResolvedValue(triage());
    renderPage();
    await screen.findByText("剛開始、數字還不夠");
    expect(screen.queryByText(/商城報表/)).toBeNull();
  });
});

describe("WaitPage 等待原因（F49 Contract Q：字與出口來自 rules.reasons）", () => {
  const reasons = RULES_FIXTURE.reasons;
  const cases: { code: string; item: Partial<TriageItem>; exit: { link?: string; resync?: true } | null }[] = [
    { code: "too_new", item: {}, exit: null },
    { code: "result_unknown_days", item: { reason_code: "result_unknown_days" }, exit: { resync: true } },
    { code: "needs_resync", item: { reason_code: "needs_resync" }, exit: { resync: true } },
    { code: "mixed_currency", item: { reason_code: "mixed_currency" }, exit: null },
    // A graded ad whose previous window is incomplete: judged, but no trend (change_pct null).
    { code: "no_previous_window", item: { reason_code: "no_previous_window", grade: "over", grade_label: "太貴" }, exit: null },
    { code: "result_kind_unknown", item: { class: "no_target", reason_code: "result_kind_unknown", grade: "no_target", grade_label: "未判斷" }, exit: { link: "/brands/brd_1/ads/campaigns/cmp_1?tab=strategy" } },
    { code: "target_unresolved", item: { class: "no_target", reason_code: "target_unresolved", grade: "no_target", grade_label: "未判斷" }, exit: { link: "/brands/brd_1/ads/campaigns/cmp_1?tab=strategy" } },
  ];
  for (const c of cases) {
    it(`${c.code}：印served的標題與句子，出口照 fix`, async () => {
      mockGetTriage.mockResolvedValue(triage({ items: [triageItem(c.item)] }));
      renderPage();
      const reason = reasons[c.code];
      expect(await screen.findByText(reason.title)).toBeTruthy();
      const r = row(reason.title);
      expect(within(r).getByText(reason.text)).toBeTruthy();
      if (c.exit?.link) {
        expect(within(r).getByRole("link").getAttribute("href")).toBe(c.exit.link);
      } else if (c.exit?.resync) {
        expect(within(r).getByRole("button", { name: "重新檢查 →" })).toBeTruthy();
      } else {
        expect(within(r).queryByRole("button")).toBeNull();
        expect(within(r).queryByRole("link")).toBeNull();
      }
    });
  }

  it("fix＝connections 時出口是資料連線頁", async () => {
    seedAdsRules({ ...RULES_FIXTURE, reasons: { ...reasons, needs_resync: { ...reasons.needs_resync, fix: "connections" } } });
    try {
      mockGetTriage.mockResolvedValue(triage({ items: [triageItem({ reason_code: "needs_resync" })] }));
      renderPage();
      await screen.findByText(reasons.needs_resync.title);
      expect(within(row(reasons.needs_resync.title)).getByRole("link", { name: "去資料連線 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/connections");
    } finally {
      seedAdsRules(RULES_FIXTURE);
    }
  });

  it("每個原因只列一次，照後端給的順序；已判讀出趨勢或沒賣出的廣告不列", async () => {
    mockGetTriage.mockResolvedValue(triage({
      items: [
        triageItem({ entity_id: "ad_1", reason_code: "needs_resync" }),
        triageItem({ entity_id: "ad_2", reason_code: "too_new" }),
        triageItem({ entity_id: "ad_3", reason_code: "needs_resync" }),
        judged({ entity_id: "ad_4" }),
        triageItem({ entity_id: "ad_5", class: "stop_loss", reason_code: "spend_over_target_no_result", grade: "wasted", grade_label: "沒賣出" }),
      ],
    }));
    renderPage();
    await screen.findByText(reasons.needs_resync.title);
    const titles = screen.getAllByText((_, el) => el?.tagName === "B").map((el) => el.textContent);
    expect(titles).toEqual([reasons.needs_resync.title, reasons.too_new.title]);
    expect(screen.queryByText(reasons.cost_per_result_flat.title)).toBeNull();
    expect(screen.queryByText(reasons.spend_over_target_no_result.text)).toBeNull();
  });

  it("規則還沒讀到時，列存在但不印字（沒有備用文字）", async () => {
    mockGetAdsRules.mockReturnValue(new Promise(() => {}));
    seedAdsRules(null);
    try {
      mockGetTriage.mockResolvedValue(triage({ items: [triageItem({ reason_code: "mixed_currency" })] }));
      renderPage();
      await screen.findByText("資料不足，這個活動先不判斷");
      expect(document.querySelectorAll("[data-slot='todo-row']")).toHaveLength(1);
      expect(screen.queryByText(reasons.mixed_currency.title)).toBeNull();
    } finally {
      seedAdsRules(RULES_FIXTURE);
    }
  });
});

describe("WaitPage 讀取結果（F49 Contract O）", () => {
  it("讀取失敗時頭部印 status.label 與 sync.error，不說資料齊了", async () => {
    mockGetTriage.mockResolvedValue(triage({
      items: [judged()],
      data: data({
        sync: { state: "failed", error: "平台回應逾時", last_success_at: "2026-09-19T14:40:00+00:00" },
        status: { state: "failed", label: "上次讀取平台資料失敗。", missing_days: [], last_success_at: "2026-09-19T14:40:00+00:00" },
      }),
    }));
    renderPage();
    const hero = await screen.findByRole("status");
    expect(within(hero).getByText("上次讀取平台資料失敗。")).toBeTruthy();
    expect(within(hero).getByText(/平台回應逾時/)).toBeTruthy();
    expect(screen.queryByText("資料齊了，可以回活動看判讀")).toBeNull();
  });

  it("資料都讀過、已有廣告判讀時才說資料齊了，附上後端的日期範圍", async () => {
    mockGetTriage.mockResolvedValue(triage({ items: [judged()] }));
    renderPage();
    expect(await screen.findByText("資料齊了，可以回活動看判讀")).toBeTruthy();
    expect(screen.getByText(/9\/13～9\/19 每天都讀過/)).toBeTruthy();
  });

  it("重新檢查：送出同步、跟著 useSyncOutcome 讀到結束，印結果句、重新讀這頁", async () => {
    const user = userEvent.setup();
    mockGetTriage.mockResolvedValue(triage());
    mockSyncCampaign.mockResolvedValue({ job: { id: "job_1", status: "pending", last_success_at: null } });
    mockSyncOutcome.mockResolvedValue(outcome({ state: "empty", code: "no_rows", text: "讀完了，這段期間平台沒有數字。" }));
    renderPage();
    await user.click(await screen.findByRole("button", { name: "重新檢查 →" }));
    expect(mockSyncCampaign).toHaveBeenCalledWith("brd_1", "cmp_1");
    expect(await screen.findByText("讀完了，這段期間平台沒有數字。")).toBeTruthy();
    expect(mockSyncOutcome).toHaveBeenCalledWith("brd_1", "cmp_1", expect.anything());
    await waitFor(() => expect(mockGetTriage).toHaveBeenCalledTimes(2));
    await waitFor(() => expect((screen.getByRole("button", { name: "重新檢查 →" }) as HTMLButtonElement).disabled).toBe(false));
  });

  it("重新讀取只讀到一部分時印它的原因", async () => {
    const user = userEvent.setup();
    mockGetTriage.mockResolvedValue(triage());
    mockSyncCampaign.mockResolvedValue({ job: { id: "job_1", status: "pending", last_success_at: null } });
    mockSyncOutcome.mockResolvedValue(outcome({ state: "partial", code: "permission_denied", text: "只讀到一部分：廣告帳號沒有給讀取權限。" }));
    renderPage();
    await user.click(await screen.findByRole("button", { name: "重新檢查 →" }));
    expect((await screen.findByRole("alert")).textContent).toBe("只讀到一部分：廣告帳號沒有給讀取權限。");
  });

  it("讀取中會等到結束才印結果（每 3 秒問一次）", async () => {
    const user = userEvent.setup();
    mockGetTriage.mockResolvedValue(triage());
    mockSyncCampaign.mockResolvedValue({ job: { id: "job_1", status: "pending", last_success_at: null } });
    mockSyncOutcome
      .mockResolvedValueOnce(outcome({ state: "running", text: "正在讀取平台資料…" }))
      .mockResolvedValue(outcome({ state: "failed", code: "disconnected", text: "沒讀到：廣告帳號已中斷連線。" }));
    renderPage();
    await user.click(await screen.findByRole("button", { name: "重新檢查 →" }));
    expect(await screen.findByText("正在讀取平台資料…")).toBeTruthy();
    expect((screen.getByRole("button", { name: "檢查中…" }) as HTMLButtonElement).disabled).toBe(true);
    expect(mockGetTriage).toHaveBeenCalledTimes(1);
    expect((await screen.findByRole("alert", {}, { timeout: 5000 })).textContent).toBe("沒讀到：廣告帳號已中斷連線。");
    await waitFor(() => expect(mockGetTriage).toHaveBeenCalledTimes(2));
  }, 10000);

  it("送出同步失敗時顯示錯誤、按鈕恢復可按", async () => {
    const user = userEvent.setup();
    mockGetTriage.mockResolvedValue(triage());
    mockSyncCampaign.mockRejectedValue(new Error("同步失敗，請稍後再試。"));
    renderPage();
    await user.click(await screen.findByRole("button", { name: "重新檢查 →" }));
    expect(await screen.findByText("同步失敗，請稍後再試。")).toBeTruthy();
    expect((screen.getByRole("button", { name: "重新檢查 →" }) as HTMLButtonElement).disabled).toBe(false);
    expect(mockSyncOutcome).not.toHaveBeenCalled();
  });
});

describe("WaitPage 日子格（F49 Contract V）", () => {
  it("照後端的 days 畫：有資料、讀過沒花費、缺，三種不同；標題是後端視窗的日期", async () => {
    mockGetTriage.mockResolvedValue(triage({
      data: data({
        missing_days: ["2026-09-19"],
        days: days({ "2026-09-15": "empty", "2026-09-16": "empty", "2026-09-19": "missing" }),
      }),
    }));
    renderPage();
    expect(await screen.findByRole("heading", { name: "9/13～9/19" })).toBeTruthy();
    const tiles = screen.getByLabelText("每日資料");
    expect(within(tiles).getAllByLabelText(/^2026-/)).toHaveLength(7);
    const data13 = within(tiles).getByLabelText("2026-09-13 有資料");
    const empty15 = within(tiles).getByLabelText("2026-09-15 讀過・沒花費");
    const missing19 = within(tiles).getByLabelText("2026-09-19 缺");
    expect(data13.className).not.toBe(empty15.className);
    expect(empty15.className).not.toBe(missing19.className);
    expect(data13.className).not.toBe(missing19.className);
  });

  it("沒有 days 時不畫格子、也不自己算日子", async () => {
    mockGetTriage.mockResolvedValue({ window_days: 7, items: [], closed: EMPTY_CLOSED });
    renderPage();
    await screen.findByText("還沒同步過，先不判斷");
    expect(screen.queryByLabelText("每日資料")).toBeNull();
    expect(screen.getByText("尚未同步")).toBeTruthy();
  });
});

describe("WaitPage 活動一生（F49 Contract L）", () => {
  it("草稿：說還沒上架、出口回活動，沒有重新檢查、沒有平台晶片", async () => {
    mockListCampaigns.mockResolvedValue([campaignCard({ status: "ready", lifecycle: { state: "draft", label: "草稿", can_close: false } })]);
    mockGetTriage.mockResolvedValue(triage({ items: [], data: data({ sync: { state: "never", error: null, last_success_at: null }, days: days({}) }) }));
    renderPage();
    expect(await screen.findByText("這個活動還沒上架，沒有平台資料可讀")).toBeTruthy();
    expect(screen.getByRole("link", { name: "回活動繼續準備 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1");
    expect(screen.queryByRole("button", { name: /重新檢查/ })).toBeNull();
    expect(screen.queryByText("平台照常投放，不受影響")).toBeNull();
    expect(screen.queryByLabelText("每日資料")).toBeNull();
  });

  it("投放中才印平台晶片", async () => {
    mockGetTriage.mockResolvedValue(triage());
    renderPage();
    expect(await screen.findByText("平台照常投放，不受影響")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "結案這一期 →" })).toBeNull();
  });

  it("已結束：往前的出口「結案這一期 →」到結案連結，沒有平台晶片", async () => {
    mockListCampaigns.mockResolvedValue([campaignCard({ status: "ended", end_date: "2026-09-19", lifecycle: { state: "ended", label: "已結束・待結案", can_close: true } })]);
    mockGetTriage.mockResolvedValue(triage());
    renderPage();
    expect((await screen.findByRole("link", { name: "結案這一期 →" })).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1?tab=perf&close=1");
    expect(screen.queryByText("平台照常投放，不受影響")).toBeNull();
  });

  it("匯入的已結束活動沒有結案（can_close false）", async () => {
    mockListCampaigns.mockResolvedValue([campaignCard({ lifecycle: { state: "ended", label: "已結束", can_close: false } })]);
    mockGetTriage.mockResolvedValue(triage());
    renderPage();
    await screen.findByText("剛開始、數字還不夠");
    expect(screen.queryByRole("link", { name: "結案這一期 →" })).toBeNull();
  });
});

describe("WaitPage 頭部提示與讀取失敗", () => {
  it("有最近成功同步時顯示時間", async () => {
    mockGetTriage.mockResolvedValue(triage());
    renderPage();
    expect(await screen.findByText("最近同步 09/19 22:40")).toBeTruthy();
  });

  it("讀取失敗時可重新讀取", async () => {
    mockGetTriage.mockRejectedValue(new Error("讀取失敗，請稍後再試。"));
    renderPage();
    expect(await screen.findByText("讀取失敗，請稍後再試。")).toBeTruthy();
  });

  it("找不到這個 Campaign", async () => {
    mockListCampaigns.mockResolvedValue([]);
    mockGetTriage.mockResolvedValue(triage());
    renderPage();
    expect(await screen.findByText("找不到這個 Campaign。")).toBeTruthy();
  });
});
