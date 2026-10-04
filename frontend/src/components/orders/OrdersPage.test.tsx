import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createChannelEntry, fetchOrders, type OrdersPageData } from "@/lib/ordersApi";
import { OrdersPage } from "./OrdersPage";

vi.mock("@/lib/ordersApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/ordersApi")>("@/lib/ordersApi");
  return { ...actual, fetchOrders: vi.fn(), createChannelEntry: vi.fn() };
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

describe("OrdersPage channel revenue sends what was typed (F47-I03, drill-10 甲 訂單 #5)", () => {
  async function openChannelEntry() {
    render(<MemoryRouter initialEntries={["/?tab=channels"]}><OrdersPage brandId="b1" /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "新增通路營收" }));
    return screen.findByRole("dialog", { name: "新增通路營收" });
  }

  it("a refused amount shows the server's sentence under the amount, keeps it, and clears on edit", async () => {
    vi.mocked(createChannelEntry).mockRejectedValue(new Error("營收不能是負數。"));
    const panel = await openChannelEntry();
    const date = panel.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(date, { target: { value: "2026-09-16" } });
    const amount = screen.getByText("金額（選填）").closest("label")!.querySelector("input")!;
    await userEvent.type(amount, "-5");
    await userEvent.click(screen.getByRole("button", { name: "記下這筆" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("營收不能是負數。");
    expect(amount.closest("label")?.contains(alert)).toBe(true);
    expect(vi.mocked(createChannelEntry).mock.calls[0][1]).toMatchObject({ revenue: "-5", entry_date: "2026-09-16" });
    expect(amount.value).toBe("-5");

    await userEvent.clear(amount);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("F50-I02 (controls a-59): quantity −2 is sent as typed and the server's count sentence shows under 數量", async () => {
    vi.mocked(createChannelEntry).mockRejectedValue(new Error("數量要是 0 以上的整數。"));
    const panel = await openChannelEntry();
    const date = panel.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(date, { target: { value: "2026-09-16" } });
    const quantity = screen.getByText("數量（選填）").closest("label")!.querySelector("input")!;
    await userEvent.type(quantity, "-2");
    await userEvent.click(screen.getByRole("button", { name: "記下這筆" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("數量要是 0 以上的整數。");
    expect(quantity.closest("label")?.contains(alert)).toBe(true);
    expect(vi.mocked(createChannelEntry).mock.lastCall?.[1]).toMatchObject({ quantity: "-2" });
  });
});
