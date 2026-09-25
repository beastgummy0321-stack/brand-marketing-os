/** frontend/src/components/ads/wait/WaitPage.test.tsx — F24-I03：`vi.mock` 掉 `@/lib/adsApi`／
 * `@/lib/adsTriageApi`／`@/lib/ordersApi`／`@/lib/adsExternalApi`，不打真的 API。覆蓋 Feature
 * Decisions「Wait page」：三個事實列（未連接／缺天／訂單缺口）、沒有缺天時改列 `reason_code`
 * （缺天存在就不重複列）、「重新檢查」＝`syncCampaign`＋poll 直到不是 pending／running 才
 * 重新讀取、忙碌時停用、訂單讀取失敗不拖累整頁、頭部提示（最近同步／尚未同步）、找不到
 * Campaign。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { listCampaigns } from "@/lib/adsApi";
import type { CampaignTriage, TriageClosedBlock, TriageItem } from "@/lib/adsTriageApi";
import { getTriage } from "@/lib/adsTriageApi";
import type { OrdersPageData } from "@/lib/ordersApi";
import { fetchOrders } from "@/lib/ordersApi";
import { syncCampaign, syncJob } from "@/lib/adsExternalApi";
import { WaitPage } from "./WaitPage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, listCampaigns: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, getTriage: vi.fn() };
});
vi.mock("@/lib/ordersApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/ordersApi")>("@/lib/ordersApi");
  return { ...actual, fetchOrders: vi.fn() };
});
vi.mock("@/lib/adsExternalApi", () => ({ syncCampaign: vi.fn(), syncJob: vi.fn() }));

const mockListCampaigns = vi.mocked(listCampaigns);
const mockGetTriage = vi.mocked(getTriage);
const mockFetchOrders = vi.mocked(fetchOrders);
const mockSyncCampaign = vi.mocked(syncCampaign);
const mockSyncJob = vi.mocked(syncJob);

function campaignCard(overrides: Partial<CampaignCardData> = {}): CampaignCardData {
  return {
    id: "cmp_1", name: "【銷售】1150706 Beast Prime 最高數量", status: "live",
    start_date: "2026-08-01", end_date: null, objective: "轉換",
    created_at: "2026-08-01T00:00:00Z", created_by: null,
    budget_planned: null, budget_total: null,
    budget_progress: { spent: null, total: null, pct: null },
    judgment: { tone: "neutral", text: "投放中", detail: "" },
    outcome: { spend: null, purchases: null, revenue: null },
    ...overrides,
  };
}

function triageItem(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "ad_1", native_id: "native_1", name: "1150706 健身情境單圖",
    campaign_id: "cmp_1", campaign_name: "【銷售】1150706 Beast Prime 最高數量", thumbnail_url: null,
    class: "insufficient", label: "資料不足", reason_code: "below_sample_gate",
    grade: "insufficient", grade_label: "剛開始、數字還不夠", previous_grade: null, grade_move: null,
    window: { start: "2026-08-25", end: "2026-09-21", days: 28, previous_start: "2026-07-28", previous_end: "2026-08-24", extended_from: 14 },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: null, result_count: null, cost_per_result: null, result_kind: null, result_label: "成果", derived_zero_days: 0, reason: "result_unknown_days" },
    previous: { spend: null, result_count: null, cost_per_result: null, result_kind: null, result_label: "成果", derived_zero_days: 0, reason: "result_unknown_days" },
    change_pct: null, sample: { gate: false, spend_multiple: null, days_with_events: 0 },
    ...overrides,
  };
}

// F26-I01: `closed` is always sent by the real backend -- an empty block here (this page's own
// closed-ad handling is out of this issue's scope).
const EMPTY_CLOSED: TriageClosedBlock = {
  paused: 0, archived: 0, other: 0, total: 0, items: [], truncated: false,
};

function triage(overrides: Partial<CampaignTriage> = {}): CampaignTriage {
  return {
    window_days: 28,
    items: [triageItem()],
    closed: EMPTY_CLOSED,
    data: {
      sync: { state: "ok", error: null, last_success_at: "2026-09-19T14:40:00+00:00" },
      coverage: { start: "2026-08-25", end: "2026-09-19" },
      missing_days: [],
      status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: "2026-09-19T14:40:00+00:00" },
    },
    ...overrides,
  };
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

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/brands/brd_1/ads/campaigns/cmp_1/wait"]}>
      <Routes>
        <Route
          path="/brands/:brandId/ads/campaigns/:campaignId/wait"
          element={<WaitPage brandId="brd_1" campaignId="cmp_1" />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockListCampaigns.mockResolvedValue([campaignCard()]);
  mockFetchOrders.mockResolvedValue(orders());
});

describe("WaitPage（F24-I03）事實列", () => {
  it("帳戶未連接＋缺天＋訂單缺口三列，缺天存在時不列 reason_code", async () => {
    mockGetTriage.mockResolvedValue(triage({
      items: [triageItem(), triageItem({ entity_id: "ad_2", reason_code: "no_previous_window" })],
      data: {
        sync: { state: "disconnected", error: null, last_success_at: "2026-09-19T14:40:00+00:00" },
        coverage: { start: "2026-08-25", end: "2026-09-19" },
        missing_days: ["2026-09-17", "2026-09-18"],
        status: { state: "disconnected", label: "廣告帳號已中斷連線，讀不到新資料。", missing_days: ["2026-09-17", "2026-09-18"], last_success_at: "2026-09-19T14:40:00+00:00" },
      },
    }));
    renderPage();
    expect(await screen.findByText("廣告帳戶未連接")).toBeTruthy();
    expect(screen.getByText("重新連接後會自動補資料")).toBeTruthy();
    expect(screen.getByRole("link", { name: "去連接 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/connections");
    expect(screen.getByText("缺 9/17、9/18（2 天）")).toBeTruthy();
    expect(screen.getByText("同步恢復後自動補")).toBeTruthy();
    expect(screen.getByText("商城報表只到 9/14")).toBeTruthy();
    expect(screen.getByText("補到 9/19 才能對照訂單")).toBeTruthy();
    expect(screen.getByRole("link", { name: "補報表 →" }).getAttribute("href")).toBe("/brands/brd_1/orders");
    // 缺天已經存在，不重複列 reason_code。
    expect(screen.queryByText("樣本還不夠")).toBeNull();
    expect(screen.queryByText("缺前一期可比資料")).toBeNull();
  });

  it("授權失效時列「Meta 讀取權限失效」，按鈕連到 /settings?tab=meta（F27-I21）", async () => {
    mockGetTriage.mockResolvedValue(triage({
      data: {
        sync: { state: "auth_expired", error: "拒絕存取", last_success_at: "2026-09-19T14:40:00+00:00" },
        coverage: { start: "2026-08-25", end: "2026-09-19" },
        missing_days: ["2026-09-17", "2026-09-18"],
        status: { state: "auth_expired", label: "平台授權已過期，重新連線後才能讀資料。", missing_days: ["2026-09-17", "2026-09-18"], last_success_at: "2026-09-19T14:40:00+00:00" },
      },
    }));
    renderPage();
    expect(await screen.findByText("Meta 讀取權限失效")).toBeTruthy();
    expect(screen.getByText("重新授權後會自動補資料")).toBeTruthy();
    expect(screen.getByRole("link", { name: "重新授權 →" }).getAttribute("href")).toBe("/settings?tab=meta");
    // 缺天列仍然並存（授權失效不擋掉其他事實列）。
    expect(screen.getByText("缺 9/17、9/18（2 天）")).toBeTruthy();
    // 授權失效跟未連接互斥，不會同時出現「廣告帳戶未連接」。
    expect(screen.queryByText("廣告帳戶未連接")).toBeNull();
  });

  it("沒有缺天、全部資料不足時，依 reason_code 各列一則（固定順序）", async () => {
    mockGetTriage.mockResolvedValue(triage({
      items: [
        triageItem({ entity_id: "ad_1", reason_code: "result_unknown_days" }),
        triageItem({ entity_id: "ad_2", reason_code: "below_sample_gate" }),
        triageItem({ entity_id: "ad_3", reason_code: "below_sample_gate" }),
      ],
      data: {
        sync: { state: "ok", error: null, last_success_at: "2026-09-19T14:40:00+00:00" },
        coverage: { start: "2026-08-25", end: "2026-09-19" },
        missing_days: [],
        status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: "2026-09-19T14:40:00+00:00" },
      },
    }));
    renderPage();
    expect(await screen.findByText("樣本還不夠")).toBeTruthy();
    expect(screen.getByText("每則廣告的花費或成果數還沒過門檻，累積中")).toBeTruthy();
    expect(screen.getAllByText("樣本還不夠")).toHaveLength(1);
    expect(screen.getByText("成果數未知")).toBeTruthy();
    expect(screen.getByText("平台沒回報這幾天的成果")).toBeTruthy();
    // 沒有帳戶未連接／訂單缺口的事實時不列。
    expect(screen.queryByText("廣告帳戶未連接")).toBeNull();
  });

  it("不是全部資料不足時不列 reason_code", async () => {
    mockGetTriage.mockResolvedValue(triage({
      items: [triageItem({ class: "flat", grade: "on_target", grade_label: "划算" })],
      data: {
        sync: { state: "ok", error: null, last_success_at: "2026-09-19T14:40:00+00:00" },
        coverage: { start: "2026-08-25", end: "2026-09-19" },
        missing_days: [],
        status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: "2026-09-19T14:40:00+00:00" },
      },
    }));
    renderPage();
    await screen.findByText("資料不足，這個活動先不判斷");
    expect(screen.queryByText("樣本還不夠")).toBeNull();
  });

  it("F29-I01 一把尺：趨勢 class 是資料不足、但已對上限分級的廣告不算在等（不列 reason_code）", async () => {
    mockGetTriage.mockResolvedValue(triage({
      items: [
        triageItem({ entity_id: "ad_1", reason_code: "below_sample_gate" }),
        triageItem({ entity_id: "ad_2", class: "insufficient", reason_code: "no_previous_window", grade: "over", grade_label: "太貴" }),
      ],
      data: {
        sync: { state: "ok", error: null, last_success_at: "2026-09-19T14:40:00+00:00" },
        coverage: { start: "2026-08-25", end: "2026-09-19" },
        missing_days: [],
        status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: "2026-09-19T14:40:00+00:00" },
      },
    }));
    renderPage();
    await screen.findByText("資料不足，這個活動先不判斷");
    expect(screen.queryByText("樣本還不夠")).toBeNull();
    expect(screen.queryByText("缺前一期可比資料")).toBeNull();
  });

  it("訂單讀取失敗不拖累整頁，只是不列訂單缺口那一列", async () => {
    mockFetchOrders.mockRejectedValue(new Error("讀取失敗"));
    mockGetTriage.mockResolvedValue(triage({
      data: {
        sync: { state: "ok", error: null, last_success_at: "2026-09-19T14:40:00+00:00" },
        coverage: { start: "2026-08-25", end: "2026-09-19" },
        missing_days: [],
        status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: "2026-09-19T14:40:00+00:00" },
      },
    }));
    renderPage();
    await screen.findByText("樣本還不夠");
    expect(screen.queryByText(/商城報表只到/)).toBeNull();
  });

  it("`data` 缺漏時視為從沒同步過、沒有覆蓋範圍", async () => {
    mockGetTriage.mockResolvedValue({ window_days: 28, items: [], closed: EMPTY_CLOSED });
    renderPage();
    await screen.findByText("資料不足，這個活動先不判斷");
    expect(screen.getByText("尚未同步")).toBeTruthy();
    expect(screen.queryByText("廣告帳戶未連接")).toBeNull();
  });
});

describe("WaitPage（F24-I03）頭部提示", () => {
  it("有最近成功同步時顯示時間", async () => {
    mockGetTriage.mockResolvedValue(triage());
    renderPage();
    expect(await screen.findByText("最近同步 09/19 22:40")).toBeTruthy();
  });

  it("never 顯示「尚未同步」，按鈕仍可按", async () => {
    mockGetTriage.mockResolvedValue(triage({
      data: {
        sync: { state: "never", error: null, last_success_at: null }, coverage: null, missing_days: [],
        status: { state: "never", label: "還沒讀過平台資料。", missing_days: [], last_success_at: null },
      },
    }));
    renderPage();
    await screen.findByText("資料不足，這個活動先不判斷");
    expect(screen.getByText("尚未同步")).toBeTruthy();
    expect((screen.getByRole("button", { name: "重新檢查 →" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("WaitPage（F24-I03）重新檢查", () => {
  it("送出同步、poll 到非 pending／running 後重新讀取並恢復按鈕", async () => {
    const user = userEvent.setup();
    mockGetTriage.mockResolvedValue(triage());
    mockSyncCampaign.mockResolvedValue({ job: { id: "job_1", status: "pending", last_success_at: null } });
    mockSyncJob.mockResolvedValue({ job: { id: "job_1", status: "succeeded", last_success_at: "2026-09-22T01:00:00+00:00" }, connected: true });
    renderPage();
    const button = await screen.findByRole("button", { name: "重新檢查 →" });
    await user.click(button);
    expect(mockSyncCampaign).toHaveBeenCalledWith("brd_1", "cmp_1");
    await waitFor(() => expect(mockSyncJob).toHaveBeenCalled());
    await waitFor(() => expect(mockGetTriage).toHaveBeenCalledTimes(2));
    await waitFor(() => expect((screen.getByRole("button", { name: "重新檢查 →" }) as HTMLButtonElement).disabled).toBe(false));
  });

  it("重新檢查失敗時顯示錯誤、按鈕恢復可按", async () => {
    const user = userEvent.setup();
    mockGetTriage.mockResolvedValue(triage());
    mockSyncCampaign.mockRejectedValue(new Error("同步失敗，請稍後再試。"));
    renderPage();
    const button = await screen.findByRole("button", { name: "重新檢查 →" });
    await user.click(button);
    expect(await screen.findByText("同步失敗，請稍後再試。")).toBeTruthy();
    expect((screen.getByRole("button", { name: "重新檢查 →" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("WaitPage（F24-I03）讀取失敗與找不到", () => {
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
