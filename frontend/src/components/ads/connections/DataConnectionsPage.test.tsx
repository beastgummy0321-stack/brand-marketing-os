/** frontend/src/components/ads/connections/DataConnectionsPage.test.tsx — F30-I15: the v10 connections page
 * (prototype `connections()`), fed by the one `GET …/connections` read (Feature F30 Contract H). The fixture has
 * the real shape the server writes: an ok account, an auth-expired account with a two-day gap, a never-read
 * account, orders missing after a date, a product without cost, and the four platforms without a reader. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdsConnections, CalendarDayState, ConnectionSource } from "@/lib/adsConnectionsApi";
import { getConnections } from "@/lib/adsConnectionsApi";
import { formatSyncTime } from "@/lib/format";
import { DataConnectionsPage, sourceChip, sourceNote } from "./DataConnectionsPage";

vi.mock("@/lib/adsConnectionsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsConnectionsApi")>("@/lib/adsConnectionsApi");
  return { ...actual, getConnections: vi.fn() };
});

const iso = (d: number) => `2026-09-${String(d).padStart(2, "0")}`;
const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, i) => iso(from + i));
const TODAY = 23;

function source(overrides: Partial<ConnectionSource> & Pick<ConnectionSource, "key" | "kind" | "name" | "state" | "note">): ConnectionSource {
  return { platform: null, last_success_at: null, missing_days: [], affected_campaigns: [], action: null, ...overrides };
}

function days(state: (d: number) => CalendarDayState) {
  return range(1, 30).map((date, i) => ({ date, state: state(i + 1) }));
}

function fixture(): AdsConnections {
  const unsupported = [["google_ads", "Google Ads"], ["tiktok", "TikTok"], ["shopee", "蝦皮"], ["momo", "momo"]].map(([key, label]) =>
    source({ key: `platform:${key}`, kind: "platform", platform: key, name: label, state: "unsupported", note: "尚未支援，接上後開放" }));
  return {
    attention_count: 4,
    sources: [
      source({ key: "meta:act_1", kind: "ad_account", platform: "meta", name: "Meta 廣告帳戶・示例品牌主帳戶", state: "ok",
        note: "每天的資料都有讀到", last_success_at: "2026-09-23T00:40:00Z" }),
      source({ key: "meta:act_2", kind: "ad_account", platform: "meta", name: "Meta 廣告帳戶・中秋活動帳戶", state: "auth_expired",
        note: "09/17、09/18 讀不到・中秋限定活動先不判斷", last_success_at: "2026-09-16T01:00:00Z", missing_days: [iso(17), iso(18)],
        affected_campaigns: [{ id: "cmp_mid", name: "中秋限定活動" }], action: { label: "重新授權", href: "/settings?tab=meta" } }),
      source({ key: "meta:act_3", kind: "ad_account", platform: "meta", name: "Meta 廣告帳戶・新品測試帳戶", state: "never",
        note: "還沒讀取過", missing_days: ["2026-08-26", ...range(1, 22)] }),
      source({ key: "orders", kind: "orders", name: "商城訂單報表", state: "missing_days", note: "最新到 09/12，缺 09/13 之後",
        missing_days: range(13, 22), action: { label: "補報表", href: "/brands/brd_1/orders" } }),
      source({ key: "product_costs", kind: "product_costs", name: "商品成本", state: "missing_cost", note: "3 個商品，2 個有成本；秋季新色缺成本",
        action: { label: "去填成本", href: "/brands/brd_1/products" } }),
      ...unsupported,
    ],
    calendar: {
      month: "2026-09",
      today: iso(TODAY),
      rows: [
        { source_key: "meta:act_1", label: "示例品牌主帳戶", days: days((d) => (d > TODAY ? "future" : "ok")) },
        { source_key: "meta:act_2", label: "中秋活動帳戶", days: days((d) => (d > TODAY ? "future" : d < 10 ? "none" : d === 17 || d === 18 ? "missing" : "ok")) },
        { source_key: "meta:act_3", label: "新品測試帳戶", days: days((d) => (d >= TODAY ? "future" : "missing")) },
        { source_key: "orders", label: "商城訂單報表", days: days((d) => (d >= TODAY ? "future" : d > 12 ? "missing" : "ok")) },
      ],
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getConnections).mockResolvedValue(fixture());
});

function renderPage() {
  return render(
    <MemoryRouter>
      <DataConnectionsPage brandId="brd_1" />
    </MemoryRouter>,
  );
}

const row = (name: string) =>
  within(screen.getByRole("list", { name: "資料來源" })).getByText(name, { selector: "b" }).closest("[data-slot=source-row]") as HTMLElement;

describe("sourceChip / sourceNote (state → chip words; the server note shown as is)", () => {
  const [ok, expired, never, orders, costs, google] = fixture().sources;

  it("maps every state to one chip; problems are warn, a platform without a reader is neutral", () => {
    expect(sourceChip(ok)).toEqual({ tone: "ok", label: "正常" });
    expect(sourceChip(expired)).toEqual({ tone: "warn", label: "權限失效" });
    expect(sourceChip({ ...expired, state: "failed" })).toEqual({ tone: "warn", label: "讀取失敗" });
    expect(sourceChip(never)).toEqual({ tone: "warn", label: "還沒讀取" });
    expect(sourceChip(orders)).toEqual({ tone: "warn", label: "缺 09/13 之後" });
    expect(sourceChip({ ...ok, state: "missing_days", missing_days: [iso(17), iso(18)] })).toEqual({ tone: "warn", label: "缺 2 天" });
    expect(sourceChip({ ...ok, state: "missing_days", missing_days: [] })).toEqual({ tone: "warn", label: "缺資料" });
    expect(sourceChip(costs)).toEqual({ tone: "warn", label: "缺成本" });
    expect(sourceChip(google)).toEqual({ tone: "neutral", label: "尚未支援" });
  });

  it("「never」 says what is missing per kind: no account bound, no orders imported, no products", () => {
    expect(sourceChip({ ...google, state: "never" }).label).toBe("尚未連接");
    expect(sourceChip({ ...orders, state: "never" }).label).toBe("尚未匯入");
    expect(sourceChip({ ...costs, state: "never" }).label).toBe("還沒有商品");
  });

  it("an ok account adds its last read time; every other row prints the server note unchanged", () => {
    expect(sourceNote(ok)).toBe(`每天的資料都有讀到・最近讀取 ${formatSyncTime("2026-09-23T00:40:00Z")}`);
    expect(sourceNote(expired)).toBe("09/17、09/18 讀不到・中秋限定活動先不判斷");
    expect(sourceNote({ ...ok, last_success_at: null })).toBe("每天的資料都有讀到");
    expect(sourceNote(orders)).toBe("最新到 09/12，缺 09/13 之後");
  });
});

describe("DataConnectionsPage (F30-I15, v10 connections())", () => {
  it("header prints the server's attention count and the read-only chip", async () => {
    renderPage();
    expect(await screen.findByText("4 項需要處理")).toBeTruthy();
    expect(screen.getByText("只讀取，不會修改你的廣告").getAttribute("data-tone")).toBe("ok");
  });

  it("one row per source in server order; the four platforms without a reader come last, greyed", async () => {
    renderPage();
    await screen.findByText("Meta 廣告帳戶・示例品牌主帳戶");
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector("b")?.textContent)).toEqual([
      "Meta 廣告帳戶・示例品牌主帳戶", "Meta 廣告帳戶・中秋活動帳戶", "Meta 廣告帳戶・新品測試帳戶", "商城訂單報表", "商品成本",
      "Google Ads", "TikTok", "蝦皮", "momo",
    ]);
    for (const name of ["Google Ads", "TikTok", "蝦皮", "momo"]) {
      expect(row(name).className).toMatch(/opacity-60/);
      expect(within(row(name)).getByText("尚未支援")).toBeTruthy();
      expect(within(row(name)).queryByRole("link")).toBeNull();
    }
    expect(row("商品成本").className).not.toMatch(/opacity-60/);
  });

  it("actions only on problem rows, linking to the page that fixes them; ok and action-less rows have none", async () => {
    renderPage();
    await screen.findByText("Meta 廣告帳戶・示例品牌主帳戶");
    expect(within(row("Meta 廣告帳戶・中秋活動帳戶")).getByRole("link", { name: "重新授權 →" }).getAttribute("href")).toBe("/settings?tab=meta");
    expect(within(row("商城訂單報表")).getByRole("link", { name: "補報表 →" }).getAttribute("href")).toBe("/brands/brd_1/orders");
    expect(within(row("商品成本")).getByRole("link", { name: "去填成本 →" }).getAttribute("href")).toBe("/brands/brd_1/products");
    expect(within(row("Meta 廣告帳戶・示例品牌主帳戶")).queryByRole("link")).toBeNull();
    expect(within(row("Meta 廣告帳戶・新品測試帳戶")).queryByRole("link")).toBeNull();
    expect(within(row("Meta 廣告帳戶・示例品牌主帳戶")).getByText("✓ 正常")).toBeTruthy();
    expect(within(row("Meta 廣告帳戶・新品測試帳戶")).getByText("還沒讀取過")).toBeTruthy();
  });

  it("the removed v7 cards are gone: no budget, no past-ads history, no 影響 chips, no 查看 on ok rows", async () => {
    renderPage();
    await screen.findByText("Meta 廣告帳戶・示例品牌主帳戶");
    expect(screen.queryByText(/Meta 預算金額/)).toBeNull();
    expect(screen.queryByText(/過去的廣告紀錄/)).toBeNull();
    expect(screen.queryByText("影響")).toBeNull();
    expect(screen.queryByRole("link", { name: /查看/ })).toBeNull();
  });

  it("「9 月每天的資料」: a day grid row per calendar row, today ringed, missing days titled, with its legend", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "9 月每天的資料" })).toBeTruthy();
    const grid = screen.getByRole("group", { name: "9 月每天的資料" });
    expect(within(grid).getAllByRole("img")).toHaveLength(4 * 30);
    expect(grid.querySelectorAll("[data-today]")).toHaveLength(4);
    expect(within(grid).getByRole("img", { name: "中秋活動帳戶 9/17 缺資料" }).getAttribute("data-state")).toBe("missing");
    expect(within(grid).getByRole("img", { name: "商城訂單報表 9/12 有資料" })).toBeTruthy();
    const legend = document.querySelector("[data-slot=legend]") as HTMLElement;
    for (const word of ["有資料", "缺資料", "不需要／還沒到", "今天"]) expect(within(legend).getByText(word)).toBeTruthy();
  });

  it("loading shows the skeleton, not an empty list or a zero count", async () => {
    let resolve: (value: AdsConnections) => void = () => {};
    vi.mocked(getConnections).mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    renderPage();
    expect(screen.getByTestId("connections-loading")).toBeTruthy();
    expect(screen.queryByText(/項需要處理/)).toBeNull();
    resolve(fixture());
    expect(await screen.findByText("4 項需要處理")).toBeTruthy();
    expect(screen.queryByTestId("connections-loading")).toBeNull();
  });

  it("a failed read shows ReadFailed with 重試 (never empty data); 重試 reads again", async () => {
    vi.mocked(getConnections).mockRejectedValueOnce(new Error("讀取資料連線失敗。"));
    renderPage();
    const failed = await screen.findByRole("alert");
    expect(within(failed).getByText(/讀取資料連線失敗/)).toBeTruthy();
    expect(screen.queryByRole("listitem")).toBeNull();
    expect(screen.queryByText(/項需要處理/)).toBeNull();

    await userEvent.click(within(failed).getByRole("button", { name: "重試" }));
    expect(await screen.findByText("4 項需要處理")).toBeTruthy();
    expect(getConnections).toHaveBeenCalledTimes(2);
  });

  it("layout: prototype `.page` max-width 1260, breadcrumb and back bar to the ads home", async () => {
    const { container } = renderPage();
    await screen.findByText("4 項需要處理");
    expect(container.querySelector(".max-w-\\[1260px\\]")).toBeTruthy();
    expect(screen.getByRole("link", { name: "投放中心" }).getAttribute("href")).toBe("/brands/brd_1/ads");
    expect(screen.getByRole("link", { name: "← 投放中心" }).getAttribute("href")).toBe("/brands/brd_1/ads");
  });
});
