/** frontend/src/components/ads/connections/DataConnectionsPage.test.tsx — F21-I02：資料連線頁
 * （v7 `connections()`）。覆蓋 issue Done／§1.7 自查：五張卡各自的狀態（ok／warn／
 * neutral）、「影響」chip 只在 warn 才印、按鈕文案與目的地、header「N 項需要處理」（warn＋
 * 失敗）、§1.7 item 9 獨立讀取失敗（一張卡失敗不拖累其餘卡，附重試）、0 個綁定帳戶時
 * 過去的廣告紀錄卡不打 `fetchMetaBackfillStatus`（lead 修正 2026-09-22：逐條對照後端程式
 * 重新核過資料 → 狀態規則，這批測試專門補舊版測不出來的坑）。`vi.mock` 掉四支 lib，
 * 不打真的 API。 */
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
function orderItem(overrides: Partial<OrdersPageData["orders"]["items"][number]> = {}) {
  return { id: "ord_1", order_number: "#1", order_date: "2026-09-21", total_amount: 100, order_status: "Open", voucher_code: null, ...overrides };
}
function orders(items: OrdersPageData["orders"]["items"] = [orderItem()], total = items.length): OrdersPageData {
  return {
    brand: { id: "brd_1", name: "品牌" },
    summary: { since: "2026-08-01", until: "2026-09-22", has_history: true, order_count: total, net_revenue: 100, average_order_value: 100, new_customers: 1, existing_customers: 0, repurchase_rate: null, repurchase_sample_size: 0, sku_margins: [] },
    orders: { items, page: 1, page_size: 12, total },
    policy_changes: [], channel_entries: [],
  };
}
function product(overrides: Partial<ProductListItem> = {}): ProductListItem {
  return { id: "prd_0", name: "商品", status: "active", parent_id: null, fact_count: 0, pending_fact_count: 0, economics_status: "confirmed", ...overrides };
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
  vi.mocked(fetchProductList).mockResolvedValue([product()]);
  vi.mocked(fetchMetaBackfillStatus).mockResolvedValue(backfill());
});

function renderPage() {
  return render(
    <MemoryRouter>
      <DataConnectionsPage brandId="brd_1" />
    </MemoryRouter>,
  );
}

describe("純函式：每張卡的資料 → 畫面狀態（lead 修正 2026-09-22 的規則）", () => {
  it("accounts：0 個綁定帳戶→warn「尚未連接」；≥1→ok「已連接」，只算綁這個品牌的帳戶", () => {
    const zero = accountsCardState(accounts({ accounts: [{ id: "mad_1", account_id: "1", name: "帳戶一", currency: "TWD", connected_at: "2026-09-01T00:00:00Z", bound_brand_ids: ["brd_other"] }] }), spend(), "brd_1");
    expect(zero.tone).toBe("warn");
    expect(zero.badge).toBe("尚未連接");
    expect(zero.fact).toBe("還沒有連接廣告帳戶");
    expect(zero.buttonLabel).toBe("去連接");

    const some = accountsCardState(accounts(), spend(), "brd_1");
    expect(some.tone).toBe("ok");
    expect(some.fact).toBe("1 個帳戶・最近讀取 09/21 11:03");
  });

  it("budget：amount===null→warn「尚未設定」（不論 currency）；currency===null 但有 amount→warn「預算待核實」；uncertainties 非空不算 warn", () => {
    const noAmount = budgetCardState(budget({ amount: null, currency: null }), "brd_1");
    expect(noAmount.tone).toBe("warn");
    expect(noAmount.badge).toBe("尚未設定");

    const noCurrency = budgetCardState(budget({ amount: 1000, currency: null }), "brd_1");
    expect(noCurrency.tone).toBe("warn");
    expect(noCurrency.badge).toBe("預算待核實");

    const withUncertainties = budgetCardState(budget({ amount: 60000, currency: "TWD", uncertainties: ["還有未核對的花費"] }), "brd_1");
    expect(withUncertainties.tone).toBe("ok");
    expect(withUncertainties.impacts).toEqual([]);
  });

  it("orders：total===0→warn「尚未匯入」；第一頁全部 order_date 為 null→warn「日期不明」；跳過 null 找到第一筆有日期的訂單", () => {
    const empty = ordersCardState(orders([], 0), "brd_1", "2026-09-22");
    expect(empty.tone).toBe("warn");
    expect(empty.badge).toBe("尚未匯入");

    const allNull = ordersCardState(orders([orderItem({ order_date: null }), orderItem({ order_date: null })]), "brd_1", "2026-09-22");
    expect(allNull.tone).toBe("warn");
    expect(allNull.badge).toBe("日期不明");

    // `ORDER BY order_date DESC` 把 NULL 排最前——前兩筆沒日期，第三筆才有。
    const skipsNulls = ordersCardState(
      orders([orderItem({ order_date: null }), orderItem({ order_date: null }), orderItem({ order_date: "2026-09-20" })]),
      "brd_1",
      "2026-09-21",
    );
    expect(skipsNulls.tone).toBe("ok");
    expect(skipsNulls.fact).toBe("最新到 9/20");
  });

  it("orders：「今天／昨天」比本機日曆日字串，不解析成 Date、不用 UTC getter——灌本機日期字串就能算對", () => {
    // 今天 9/22，昨天 9/21：最新 9/21（等於昨天）→ ok。
    const fresh = ordersCardState(orders([orderItem({ order_date: "2026-09-21" })]), "brd_1", "2026-09-22");
    expect(fresh.tone).toBe("ok");
    expect(fresh.badge).toBe("已更新");

    // 最新 9/20，早於昨天 9/21→warn，缺的日期＝9/21（最新＋1 天）。
    const stale = ordersCardState(orders([orderItem({ order_date: "2026-09-20" })]), "brd_1", "2026-09-22");
    expect(stale.tone).toBe("warn");
    expect(stale.badge).toBe("缺 9/21 之後");

    // 跨月：最新 8/31，今天 9/2（昨天 9/1）→ 早於昨天，缺的日期要正確跨月成 9/1，不是 8/32。
    const crossMonth = ordersCardState(orders([orderItem({ order_date: "2026-08-31" })]), "brd_1", "2026-09-02");
    expect(crossMonth.badge).toBe("缺 9/1 之後");
  });

  it("products：只算上架中且不是別列母產品的列；母產品與下架列不計入分母，也不計入分子", () => {
    const withParentAndArchived = productsCardState(
      [
        product({ id: "parent", status: "active", parent_id: null, economics_status: "none" }),
        product({ id: "c1", status: "active", parent_id: "parent", economics_status: "confirmed" }),
        product({ id: "c2", status: "active", parent_id: "parent", economics_status: "confirmed" }),
        product({ id: "c3", status: "active", parent_id: "parent", economics_status: "confirmed" }),
        product({ id: "c4", status: "active", parent_id: "parent", economics_status: "confirmed" }),
        product({ id: "c5", status: "active", parent_id: "parent", economics_status: "confirmed" }),
        product({ id: "archived", status: "archived", parent_id: null, economics_status: "confirmed" }),
      ],
      "brd_1",
    );
    expect(withParentAndArchived.fact).toBe("5 個商品，5 個有成本");
    expect(withParentAndArchived.tone).toBe("ok");

    const noSellable = productsCardState([product({ id: "gone", status: "archived", parent_id: null })], "brd_1");
    expect(noSellable.tone).toBe("warn");
    expect(noSellable.badge).toBe("尚未建立商品");

    const noneConfirmed = productsCardState([product({ economics_status: "none" }), product({ economics_status: "pending" })], "brd_1");
    expect(noneConfirmed.tone).toBe("warn");
    expect(noneConfirmed.badge).toBe("缺成本");
  });

  it("history：running→neutral「帶入中」；沒有 earliest_spend_date→warn「尚未帶入」；否則 ok 並算月數；0 個帳戶→warn「先連接帳戶」", () => {
    expect(historyCardState(backfill({ running: true }), "brd_1").tone).toBe("neutral");
    const none = historyCardState(backfill({ earliest_spend_date: null }), "brd_1");
    expect(none.tone).toBe("warn");
    expect(none.badge).toBe("尚未帶入");
    const done = historyCardState(backfill({ earliest_spend_date: "2025-04-25", latest_spend_date: "2026-09-21" }), "brd_1");
    expect(done.tone).toBe("ok");
    expect(done.fact).toBe("已帶入 18 個月");

    const noAccounts = historyCardState("no-accounts", "brd_1");
    expect(noAccounts.tone).toBe("warn");
    expect(noAccounts.badge).toBe("先連接帳戶");
  });
});

describe("DataConnectionsPage（F21-I02，v7 connections()）", () => {
  it("五張卡都讀到：header 印「N 項需要處理」（warn＋失敗都算），未支援平台灰卡固定顯示且帶原型 .cn.off 的灰底", async () => {
    vi.mocked(getMonthlyBudget).mockResolvedValue(budget({ amount: null, currency: null }));

    renderPage();

    expect(await screen.findByText("1 項需要處理")).toBeTruthy();
    const unsupported = screen.getByTestId("connection-card-unsupported-Google Ads");
    expect(unsupported.className).toMatch(/bg-muted/);
  });

  it("0 個綁定帳戶：帳戶卡 warn「尚未連接」，過去的廣告紀錄卡 warn「先連接帳戶」，且不打 fetchMetaBackfillStatus", async () => {
    vi.mocked(fetchMetaAccounts).mockResolvedValue(accounts({ accounts: [] }));

    renderPage();

    const accountsCard = await screen.findByTestId("connection-card-Meta 廣告帳戶");
    expect(within(accountsCard).getByText("尚未連接")).toBeTruthy();
    const historyCard = await screen.findByTestId("connection-card-過去的廣告紀錄");
    expect(within(historyCard).getByText("先連接帳戶")).toBeTruthy();
    expect(fetchMetaBackfillStatus).not.toHaveBeenCalled();
  });

  it("warn 卡：印「影響」chip 與原型固定文案，按鈕連去既有設定入口", async () => {
    vi.mocked(getMonthlyBudget).mockResolvedValue(budget({ amount: null, currency: null }));

    renderPage();
    await screen.findByText("Meta 預算金額");

    const budgetCard = screen.getByTestId("connection-card-Meta 預算金額");
    expect(within(budgetCard).getByText("影響")).toBeTruthy();
    expect(within(budgetCard).getByText("加預算提議")).toBeTruthy();
    expect(within(budgetCard).getByText("約撐得起幾則")).toBeTruthy();
    const link = within(budgetCard).getByRole("link", { name: "去設定 →" });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads");
  });

  it("ok 卡：不印「影響」；帳戶卡指到 Meta 帳戶設定入口", async () => {
    renderPage();
    await screen.findByText("Meta 廣告帳戶");

    const accountsCard = screen.getByTestId("connection-card-Meta 廣告帳戶");
    expect(within(accountsCard).queryByText("影響")).toBeNull();
    const link = within(accountsCard).getByRole("link", { name: "查看 →" });
    expect(link.getAttribute("href")).toBe("/settings?tab=meta");
  });

  it("§1.7 item 9：一張卡讀取失敗不拖累其餘卡；印「讀取失敗」與「重試」，按下去重打那一張；失敗也算進 header 的「需要處理」", async () => {
    vi.mocked(fetchOrders).mockRejectedValueOnce(new Error("訂單讀取失敗"));

    renderPage();

    const ordersCard = await screen.findByTestId("connection-card-商城訂單報表");
    expect(within(ordersCard).getByText("讀取失敗")).toBeTruthy();
    expect(within(ordersCard).getByText("訂單讀取失敗")).toBeTruthy();
    expect(await screen.findByText("1 項需要處理")).toBeTruthy();

    // 其餘卡照常顯示，沒有被這張卡的失敗拖累。
    expect(await screen.findByText("Meta 廣告帳戶")).toBeTruthy();
    expect(screen.getByTestId("connection-card-過去的廣告紀錄")).toBeTruthy();

    vi.mocked(fetchOrders).mockResolvedValue(orders());
    await userEvent.click(within(ordersCard).getByRole("button", { name: "重試" }));
    expect(await within(ordersCard).findByText(/最新到/)).toBeTruthy();
  });

  it("版面寬度照 v7 `.page{max-width:1180px}`：外層容器帶同一個上限", async () => {
    const { container } = renderPage();
    await screen.findByText("Meta 廣告帳戶");
    expect(container.querySelector(".max-w-\\[1180px\\]")).toBeTruthy();
  });
});
