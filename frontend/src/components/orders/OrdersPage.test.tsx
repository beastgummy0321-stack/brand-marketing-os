import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchOrders, type OrdersPageData } from "@/lib/ordersApi";
import { OrdersPage } from "./OrdersPage";

vi.mock("@/lib/ordersApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/ordersApi")>("@/lib/ordersApi");
  return { ...actual, fetchOrders: vi.fn() };
});

// Shape of GET /api/brands/{b}/orders for a brand that has never imported anything.
const empty: OrdersPageData = {
  brand: { id: "b1", name: "虛構北風羊毛" },
  summary: {
    since: "2026-08-27", until: "2026-09-25", has_history: false, order_count: 0,
    net_revenue: null, average_order_value: null, new_customers: 0, existing_customers: 0,
    repurchase_rate: null, repurchase_sample_size: 0, sku_margins: [],
  },
  orders: { items: [], page: 1, page_size: 20, total: 0 },
  policy_changes: [],
  channel_entries: [],
};

beforeEach(() => {
  vi.mocked(fetchOrders).mockResolvedValue(empty);
});

describe("OrdersPage empty state names every accepted format (drill item 7d)", () => {
  it("the overview empty state names EasyStore and 蝦皮, same as the import panel", async () => {
    render(<MemoryRouter><OrdersPage brandId="b1" /></MemoryRouter>);
    const title = await screen.findByText("還沒有訂單資料");
    const emptyText = title.parentElement?.textContent ?? "";
    expect(emptyText).toContain("EasyStore 訂單匯出");
    expect(emptyText).toContain("蝦皮賣家中心報表");

    await userEvent.click(screen.getAllByRole("button", { name: "匯入訂單檔" })[0]);
    const panel = await screen.findByRole("dialog", { name: "匯入訂單檔" });
    expect(panel.textContent).toContain("EasyStore 訂單匯出");
    expect(panel.textContent).toContain("蝦皮賣家中心報表");
    // The importer no longer reads Meta ad CSVs; the panel must not promise it.
    expect(panel.textContent).not.toContain("Meta 廣告 CSV");
  });
});
