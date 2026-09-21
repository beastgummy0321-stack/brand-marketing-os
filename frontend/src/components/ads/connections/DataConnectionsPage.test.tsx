/** frontend/src/components/ads/connections/DataConnectionsPage.test.tsx — F21-I02：資料連線頁
 * （v7 `connections()`）。覆蓋 issue Done／§1.7 自查：五張卡各自的狀態（ok／warn）、
 * 「影響」chip 只在 warn 才印、按鈕文案與目的地、header「N 項需要處理」、§1.7 item 9
 * 獨立讀取失敗（一張卡失敗不拖累其餘卡，附重試）。`vi.mock` 掉四支 lib，不打真的 API。 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MetaAccountsData, MetaBackfillStatus, MetaSpendSummary } from "@/lib/metaApi";
import { fetchMetaAccounts, fetchMetaBackfillStatus, fetchMetaSpend } from "@/lib/metaApi";
import type { MonthlyBudget } from "@/lib/adsChangeApi";
import { getMonthlyBudget } from "@/lib/adsChangeApi";
import type { OrdersPageData } from "@/lib/ordersApi";
import { fetchOrders } from "@/lib/ordersApi";
import type { ProductListItem } from "@/lib/productsApi";
import { fetchProductList } from "@/lib/productsApi";
import {
  accountsCardState,
  budgetCardState,
  DataConnectionsPage,
  historyCardState,
  ordersCardState,
  productsCardState,
} from "./DataConnectionsPage";

vi.mock("@/lib/metaApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/metaApi")>("@/lib/metaApi");
  return { ...actual, fetchMetaAccounts: vi.fn(), fetchMetaSpend: vi.fn(), fetchMetaBackfillStatus: vi.fn() };
});
vi.mock("@/lib/adsChangeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsChangeApi")>("@/lib/adsChangeApi");
  return { ...actual, getMonthlyBudget: vi.fn() };
});
vi.mock("@/lib/ordersApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/ordersApi")>("@/lib/ordersApi");
  return { ...actual, fetchOrders: vi.fn() };
});
vi.mock("@/lib/productsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/productsApi")>("@/lib/productsApi");
  return { ...actual, fetchProductList: vi.fn() };
});

function accounts(overrides: Partial<MetaAccountsData> = {}): MetaAccountsData {
  return {
    token_tail: "abcd",
    accounts: [
      { id: "mad_1", account_id: "1", name: "帳戶一", currency: "TWD", connected_at: "2026-09-01T00:00:00Z", bound_brand_ids: ["brd_1"] },
      { id: "mad_2", account_id: "2", name: "帳戶二（別的品牌）", currency: "TWD", connected_at: "2026-09-01T00:00:00Z", bound_brand_ids: ["brd_other"] },
    ],
    ...overrides,
  };
}
function spend(overrides: Partial<MetaSpendSummary> = {}): MetaSpendSummary {
  return { last_pull_at: "2026-09-21T03:03:25.000Z", campaigns: [], total: { campaign_id: "total", campaign_name: "總計", spend: 0, impressions: 0, clicks: 0, roas: null }, ...overrides };
}
function budget(overrides: Partial<MonthlyBudget> = {}): MonthlyBudget {
  return {
    month: "2026-09", currency: "TWD", amount: 60000, revision: 1, known_spend: 1000, ongoing_estimate: 500,
    reserved_increases: 0, available: 5000, uncertainties: [], can_increase: true, period_end: "2026-09-30",
    confirmed_at: "2026-09-19T00:00:00Z", notice: "",
    ...overrides,
  };
}
function orders(overrides: Partial<OrdersPageData> = {}): OrdersPageData {
  return {
    brand: { id: "brd_1", name: "品牌" },
    summary: { since: "2026-08-01", until: "2026-09-22", has_history: true, order_count: 1, net_revenue: 100, average_order_value: 100, new_customers: 1, existing_customers: 0, repurchase_rate: null, repurchase_sample_size: 0, sku_margins: [] },
    orders: { items: [{ id: "ord_1", order_number: "#1", order_date: "2026-09-21", total_amount: 100, order_status: "Open", voucher_code: null }], page: 1, page_size: 12, total: 1 },
    policy_changes: [], channel_entries: [],
    ...overrides,
  };
}
function products(overrides: Partial<ProductListItem>[] = [{ economics_status: "confirmed" }]): ProductListItem[] {
  return overrides.map((o, i) => ({ id: `prd_${i}`, name: `商品 ${i}`, status: "active", parent_id: null, fact_count: 0, pending_fact_count: 0, economics_status: "confirmed", ...o }));
}
function backfill(overrides: Partial<MetaBackfillStatus> = {}): MetaBackfillStatus {
  return { running: false, earliest_spend_date: "2025-04-25", latest_spend_date: "2026-09-21", ad_rows: 100, ...overrides };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchMetaAccounts).mockResolvedValue(accounts());
  vi.mocked(fetchMetaSpend).mockResolvedValue(spend());
  vi.mocked(getMonthlyBudget).mockResolvedValue(budget());
  vi.mocked(fetchOrders).mockResolvedValue(orders());
  vi.mocked(fetchProductList).mockResolvedValue(products());
  vi.mocked(fetchMetaBackfillStatus).mockResolvedValue(backfill());
});

function renderPage() {
  return render(
    <MemoryRouter>
      <DataConnectionsPage brandId="brd_1" />
    </MemoryRouter>,
  );
}

describe("純函式：每張卡的資料 → 畫面狀態", () => {
  it("accounts：只算綁這個品牌的帳戶，固定 ok（沒有欄位可判斷權限失效，不做、不假）", () => {
    const state = accountsCardState(accounts(), spend(), "brd_1");
    expect(state.tone).toBe("ok");
    expect(state.fact).toBe("1 個帳戶・最近讀取 09/21 11:03");
    expect(state.impacts).toEqual([]);
    expect(state.buttonLabel).toBe("查看");
    expect(state.buttonHref).toBe("/settings?tab=meta");
  });

  it("budget：currency 為 null 或有 uncertainties 都算 warn，影響 chip 沿用原型固定文案", () => {
    const warnByCurrency = budgetCardState(budget({ currency: null, amount: null }), "brd_1");
    expect(warnByCurrency.tone).toBe("warn");
    expect(warnByCurrency.fact).toBe("幣別與金額尚未設定");
    expect(warnByCurrency.impacts).toEqual(["加預算提議", "約撐得起幾則"]);

    const warnByUncertainty = budgetCardState(budget({ uncertainties: ["還有未核對的花費"] }), "brd_1");
    expect(warnByUncertainty.tone).toBe("warn");

    const ok = budgetCardState(budget(), "brd_1");
    expect(ok.tone).toBe("ok");
    expect(ok.impacts).toEqual([]);
    expect(ok.buttonLabel).toBe("查看");
  });

  it("orders：沒有訂單→warn「尚未匯入」；最新到昨天以前→warn 並印缺的日期；否則 ok", () => {
    const empty = ordersCardState(orders({ orders: { items: [], page: 1, page_size: 12, total: 0 } }), "brd_1", new Date("2026-09-22T00:00:00Z"));
    expect(empty.tone).toBe("warn");
    expect(empty.badge).toBe("尚未匯入");

    const stale = ordersCardState(orders(), "brd_1", new Date("2026-09-25T00:00:00Z"));
    expect(stale.tone).toBe("warn");
    expect(stale.badge).toBe("缺 9/22 之後");
    expect(stale.fact).toBe("最新到 9/21");

    const fresh = ordersCardState(orders(), "brd_1", new Date("2026-09-22T00:00:00Z"));
    expect(fresh.tone).toBe("ok");
  });

  it("products：至少一個有成本才 ok；事實一律印總數與有成本數", () => {
    const ok = productsCardState(products([{ economics_status: "confirmed" }, { economics_status: "none" }]), "brd_1");
    expect(ok.tone).toBe("ok");
    expect(ok.fact).toBe("2 個商品，1 個有成本");

    const warn = productsCardState(products([{ economics_status: "none" }, { economics_status: "pending" }]), "brd_1");
    expect(warn.tone).toBe("warn");
    expect(warn.fact).toBe("2 個商品，0 個有成本");
    expect(warn.buttonLabel).toBe("補成本");
  });

  it("history：running→neutral「帶入中」；沒有日期→warn；否則 ok 並算月數", () => {
    expect(historyCardState(backfill({ running: true }), "brd_1").tone).toBe("neutral");
    const none = historyCardState(backfill({ earliest_spend_date: null, latest_spend_date: null }), "brd_1");
    expect(none.tone).toBe("warn");
    const done = historyCardState(backfill({ earliest_spend_date: "2025-04-25", latest_spend_date: "2026-09-21" }), "brd_1");
    expect(done.tone).toBe("ok");
    expect(done.fact).toBe("已帶入 18 個月");
  });
});

describe("DataConnectionsPage（F21-I02，v7 connections()）", () => {
  it("五張卡都讀到：header 印「N 項需要處理」（只算 warn），未支援平台灰卡固定顯示", async () => {
    vi.mocked(getMonthlyBudget).mockResolvedValue(budget({ uncertainties: ["還有未核對的花費"] }));
    vi.mocked(fetchOrders).mockResolvedValue(orders({ orders: { items: [{ id: "o", order_number: "#1", order_date: "2026-01-01", total_amount: 1, order_status: "Open", voucher_code: null }], page: 1, page_size: 12, total: 1 } }));

    renderPage();

    expect(await screen.findByText("2 項需要處理")).toBeTruthy();
    expect(screen.getByText("Meta 廣告帳戶")).toBeTruthy();
    expect(screen.getByText("Google Ads")).toBeTruthy();
    expect(screen.getByText("尚未支援")).toBeTruthy();
  });

  it("warn 卡：印「影響」chip 與原型固定文案，按鈕連去既有設定入口", async () => {
    vi.mocked(getMonthlyBudget).mockResolvedValue(budget({ uncertainties: ["還有未核對的花費"] }));

    renderPage();
    await screen.findByText("Meta 預算金額");

    const budgetCard = screen.getByTestId("connection-card-Meta 預算金額");
    expect(within(budgetCard).getByText("影響")).toBeTruthy();
    expect(within(budgetCard).getByText("加預算提議")).toBeTruthy();
    expect(within(budgetCard).getByText("約撐得起幾則")).toBeTruthy();
    const link = within(budgetCard).getByRole("link", { name: "去核實 →" });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads");
  });

  it("ok 卡：不印「影響」；帳戶卡固定查看，指到 Meta 帳戶設定入口", async () => {
    renderPage();
    await screen.findByText("Meta 廣告帳戶");

    const accountsCard = screen.getByTestId("connection-card-Meta 廣告帳戶");
    expect(within(accountsCard).queryByText("影響")).toBeNull();
    const link = within(accountsCard).getByRole("link", { name: "查看 →" });
    expect(link.getAttribute("href")).toBe("/settings?tab=meta");
  });

  it("§1.7 item 9：一張卡讀取失敗不拖累其餘卡；印「讀取失敗」與「重試」，按下去重打那一張", async () => {
    vi.mocked(fetchOrders).mockRejectedValueOnce(new Error("訂單讀取失敗"));

    renderPage();

    const ordersCard = await screen.findByTestId("connection-card-商城訂單報表");
    expect(within(ordersCard).getByText("讀取失敗")).toBeTruthy();
    expect(within(ordersCard).getByText("訂單讀取失敗")).toBeTruthy();

    // 其餘卡照常顯示，沒有被這張卡的失敗拖累。
    expect(await screen.findByText("Meta 廣告帳戶")).toBeTruthy();
    expect(screen.getByTestId("connection-card-過去的廣告紀錄")).toBeTruthy();

    vi.mocked(fetchOrders).mockResolvedValue(orders());
    await userEvent.click(within(ordersCard).getByRole("button", { name: "重試" }));
    expect(await within(ordersCard).findByText("最新到 9/21")).toBeTruthy();
  });

  it("版面寬度照 v7 `.page{max-width:1180px}`：外層容器帶同一個上限", async () => {
    const { container } = renderPage();
    await screen.findByText("Meta 廣告帳戶");
    expect(container.querySelector(".max-w-\\[1180px\\]")).toBeTruthy();
  });
});
