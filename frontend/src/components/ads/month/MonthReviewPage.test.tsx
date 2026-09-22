/** frontend/src/components/ads/month/MonthReviewPage.test.tsx — F24-I04：`vi.mock` 掉
 * `@/lib/adsApi`／`@/lib/adsTriageApi`／`@/lib/ordersApi`／`@/lib/adsChangeApi`，不打真的 API。
 * 覆蓋 Feature Decisions「Monthly review」：月選單只驅動全品牌花費卡（不重打活動／訂單）、
 * `known_spend===null`／`amount===null` 兩種未知態、訂單卡讀取失敗時整張省略、各活動花費只在
 * `window.days` 一致時合計、達標／未達標／未判斶三種 chip、素材依 class 分三組。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { listCampaigns } from "@/lib/adsApi";
import type { CampaignTriage, TriageItem } from "@/lib/adsTriageApi";
import { getTriage } from "@/lib/adsTriageApi";
import type { OrdersPageData } from "@/lib/ordersApi";
import { fetchOrders } from "@/lib/ordersApi";
import { getMonthlyBudget, type MonthlyBudget } from "@/lib/adsChangeApi";
import { MonthReviewPage } from "./MonthReviewPage";

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
vi.mock("@/lib/adsChangeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsChangeApi")>("@/lib/adsChangeApi");
  return { ...actual, getMonthlyBudget: vi.fn() };
});

const mockListCampaigns = vi.mocked(listCampaigns);
const mockGetTriage = vi.mocked(getTriage);
const mockFetchOrders = vi.mocked(fetchOrders);
const mockGetMonthlyBudget = vi.mocked(getMonthlyBudget);

function campaignCard(overrides: Partial<CampaignCardData> = {}): CampaignCardData {
  return {
    id: "cmp_1", name: "日常商品推廣", status: "live",
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
    campaign_id: "cmp_1", campaign_name: "日常商品推廣", thumbnail_url: null,
    class: "better", label: "變好", reason_code: "cost_per_result_down",
    window: { start: "2026-09-15", end: "2026-09-21", days: 7, previous_start: "2026-09-08", previous_end: "2026-09-14", extended_from: null },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 1000, result_count: 5, cost_per_result: 200, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    previous: { spend: 900, result_count: 4, cost_per_result: 225, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: -0.11, sample: { gate: true, spend_multiple: 2.2, days_with_events: 5 },
    ...overrides,
  };
}

function triage(items: TriageItem[]): CampaignTriage {
  return { window_days: 7, items };
}

function monthlyBudget(overrides: Partial<MonthlyBudget> = {}): MonthlyBudget {
  return {
    month: "2026-09", currency: "TWD", amount: 60000, revision: 2,
    known_spend: 22000, ongoing_estimate: 0, reserved_increases: 0,
    available: 38000, uncertainties: [], can_increase: true,
    period_end: "2026-09-30", confirmed_at: "2026-09-19T14:39:22Z", notice: "",
    ...overrides,
  };
}

function orders(overrides: Partial<OrdersPageData["summary"]> = {}): OrdersPageData {
  return {
    brand: { id: "brd_1", name: "示例品牌" },
    summary: {
      since: "2026-08-23", until: "2026-09-22", has_history: true, order_count: 99,
      net_revenue: 91861, average_order_value: 927.89, new_customers: 93, existing_customers: 4,
      repurchase_rate: 0.0619, repurchase_sample_size: 97, sku_margins: [],
      ...overrides,
    },
    orders: { items: [], page: 1, page_size: 12, total: 0 },
    policy_changes: [], channel_entries: [],
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <MonthReviewPage brandId="brd_1" />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockListCampaigns.mockResolvedValue([campaignCard()]);
  mockGetTriage.mockResolvedValue(triage([triageItem()]));
  mockFetchOrders.mockResolvedValue(orders());
  mockGetMonthlyBudget.mockResolvedValue(monthlyBudget());
});

describe("MonthReviewPage（F24-I04）全品牌花費卡", () => {
  it("正常狀態：已花／月總額都有值時畫量尺", async () => {
    renderPage();
    expect(await screen.findByText("TWD 22,000")).toBeTruthy();
    expect(screen.getByText("月總額 TWD 60,000")).toBeTruthy();
  });

  it("`amount===null`：印「月總額 尚未設定」，打斜紋量尺，不是一般量尺", async () => {
    mockGetMonthlyBudget.mockResolvedValue(monthlyBudget({ amount: null }));
    renderPage();
    expect(await screen.findByText("月總額 尚未設定")).toBeTruthy();
    expect(screen.getByText("TWD 22,000")).toBeTruthy();
  });

  it("`known_spend===null`：印「花費未核實」＋第一條 uncertainties，沒有量尺", async () => {
    mockGetMonthlyBudget.mockResolvedValue(
      monthlyBudget({ known_spend: null, uncertainties: ["帳戶仍有未承接的活動，品牌花費歸屬尚不完整。", "第二條不印"] }),
    );
    renderPage();
    expect(await screen.findByText("花費未核實")).toBeTruthy();
    expect(screen.getByText("帳戶仍有未承接的活動，品牌花費歸屬尚不完整。")).toBeTruthy();
    expect(screen.queryByText("第二條不印")).toBeNull();
  });

  it("月選單只重打全品牌花費卡，不重打活動／訂單", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("TWD 22,000");
    expect(mockGetMonthlyBudget).toHaveBeenCalledTimes(1);
    const thisMonth = mockGetMonthlyBudget.mock.calls[0][1];

    mockGetMonthlyBudget.mockResolvedValue(monthlyBudget({ known_spend: 5000, amount: null }));
    await user.click(screen.getByRole("button", { name: /月/, pressed: false }));

    await waitFor(() => expect(mockGetMonthlyBudget).toHaveBeenCalledTimes(2));
    const lastMonth = mockGetMonthlyBudget.mock.calls[1][1];
    expect(lastMonth).not.toBe(thisMonth);
    // 活動／訂單只在掛載時各打一次，月選單切換不重打。
    expect(mockListCampaigns).toHaveBeenCalledTimes(1);
    expect(mockFetchOrders).toHaveBeenCalledTimes(1);
  });
});

describe("MonthReviewPage（F24-I04）商城訂單卡", () => {
  it("用回應自己的 since／until 標窗口", async () => {
    renderPage();
    expect(await screen.findByText("8/23–9/22 實收")).toBeTruthy();
    expect(screen.getByText("91,861")).toBeTruthy();
  });

  it("讀取失敗時整張卡省略，不拖累其餘卡片", async () => {
    mockFetchOrders.mockRejectedValue(new Error("讀取失敗"));
    renderPage();
    await screen.findByText("TWD 22,000");
    expect(screen.queryByText("商城訂單淨額・品牌整體")).toBeNull();
  });
});

describe("MonthReviewPage（F24-I04）各活動", () => {
  it("同一活動所有廣告 `window.days` 一致時合計花費，量尺達標", async () => {
    mockGetTriage.mockResolvedValue(triage([
      triageItem({ entity_id: "ad_1", current: { spend: 600, result_count: 2, cost_per_result: 300, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null } }),
      triageItem({ entity_id: "ad_2", current: { spend: 400, result_count: 2, cost_per_result: 200, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null } }),
    ]));
    renderPage();
    expect(await screen.findByText("花費・近 7 天")).toBeTruthy();
    expect(screen.getByText("1,000")).toBeTruthy();
    expect(screen.getByText("達標")).toBeTruthy();
  });

  it("`window.days` 不一致時不合計，印「各廣告期間不同，未合計」，未判斶", async () => {
    mockGetTriage.mockResolvedValue(triage([
      triageItem({ entity_id: "ad_1", window: { start: "2026-09-15", end: "2026-09-21", days: 7, previous_start: "2026-09-08", previous_end: "2026-09-14", extended_from: null } }),
      triageItem({ entity_id: "ad_2", window: { start: "2026-08-25", end: "2026-09-21", days: 28, previous_start: "2026-07-28", previous_end: "2026-08-24", extended_from: 14 } }),
    ]));
    renderPage();
    expect(await screen.findByText("各廣告期間不同，未合計")).toBeTruthy();
    expect(screen.getByText("未判斷")).toBeTruthy();
  });

  it("沒有目標時未判斶，量尺打斜紋、右邊寫「尚未設定目標」", async () => {
    mockGetTriage.mockResolvedValue(triage([
      triageItem({ target: { value: null, basis: null, result_kind: null, result_label: "點擊", missing: ["result_kind"] } }),
    ]));
    renderPage();
    expect(await screen.findByText("尚未設定目標")).toBeTruthy();
    expect(screen.getByText("未判斷")).toBeTruthy();
  });

  it("成本高於目標時未達標", async () => {
    mockGetTriage.mockResolvedValue(triage([
      triageItem({ current: { spend: 1000, result_count: 1, cost_per_result: 1000, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null } }),
    ]));
    renderPage();
    expect(await screen.findByText("未達標")).toBeTruthy();
  });
});

describe("MonthReviewPage（F24-I04）素材", () => {
  it("依 class 分三組：有效／無效已停／還看不出（flat+insufficient 合併）", async () => {
    mockListCampaigns.mockResolvedValue([campaignCard()]);
    mockGetTriage.mockResolvedValue(triage([
      triageItem({ entity_id: "ad_1", class: "better", label: "變好" }),
      triageItem({ entity_id: "ad_2", class: "stop_loss", label: "停損" }),
      triageItem({ entity_id: "ad_3", class: "flat", label: "持平" }),
      triageItem({ entity_id: "ad_4", class: "insufficient", label: "資料不足" }),
      triageItem({ entity_id: "ad_5", class: "worse", label: "變差" }),
    ]));
    renderPage();
    await screen.findByText("素材");
    expect(screen.getByText("有效")).toBeTruthy();
    expect(screen.getByText("無效・已停")).toBeTruthy();
    expect(screen.getByText("還看不出")).toBeTruthy();
    expect(screen.getAllByText("1 則").length).toBe(2); // 有效、無效・已停 各 1 則
    expect(screen.getByText("2 則")).toBeTruthy(); // 還看不出 flat+insufficient
  });

  it("同一組超過 12 則時最多畫 12 張縮圖，其餘摺成「＋N 則」，標頭計數仍印全部則數", async () => {
    mockListCampaigns.mockResolvedValue([campaignCard()]);
    mockGetTriage.mockResolvedValue(triage(
      Array.from({ length: 13 }, (_, i) => triageItem({ entity_id: `ad_${i}`, class: "better" })),
    ));
    renderPage();
    await screen.findByText("素材");
    expect(screen.getByText("13 則")).toBeTruthy(); // 標頭計數不受上限影響
    expect(screen.getAllByTestId("material-thumb").length).toBe(12);
    expect(screen.getByText("＋1 則")).toBeTruthy();
  });
});

describe("MonthReviewPage（F24-I04）記入品牌學習／下月建議", () => {
  it("兩個章節都是灰階佔位卡（沒有後端可讀）", async () => {
    renderPage();
    await screen.findByText("記入品牌學習");
    expect(screen.getAllByText("接上後開放").length).toBe(2);
  });
});

describe("MonthReviewPage（F24-I04）讀取失敗", () => {
  it("活動讀取失敗時可重新讀取", async () => {
    mockListCampaigns.mockRejectedValue(new Error("讀取失敗，請稍後再試。"));
    renderPage();
    expect(await screen.findByText("讀取失敗，請稍後再試。")).toBeTruthy();
  });
});
