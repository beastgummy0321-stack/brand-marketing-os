/** frontend/src/components/ads/home/HomeBoard.test.tsx — the v10 home blocks (F28-I08 board D, F29-I11), rendered on
 * their own with realistic shapes (longest names, imported campaign, no-cap draft, decimal costs, unknown values).
 * Unknown numbers print the prototype's unknown words, never 0; money goes through the kit formatter; glossary words
 * are `Term`s, so their sentences are stripped before comparing text (`plain`). */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { HomeCampaign, HomeOverview } from "@/lib/adsHomeApi";
import type { CloseoutQueueRow, QueueItem, SettleQueueRow, TriageItem } from "@/lib/adsTriageApi";
import { CampaignRows } from "./CampaignRows";
import { MonthMoney } from "./MonthMoney";
import { NextDates } from "./NextDates";
import { QualityBand } from "./QualityBand";
import { TodayDecisions } from "./TodayDecisions";

/** An element's text without the glossary sentences its `Term`s carry. */
function plain(el: Element): string {
  const copy = el.cloneNode(true) as Element;
  copy.querySelectorAll('[role="tooltip"]').forEach((n) => n.remove());
  return (copy.textContent ?? "").replace(/\s+/g, " ").trim();
}
/** Matches the innermost element whose plain text is exactly `text`. */
function byPlain(text: string) {
  return (_: string, el: Element | null) => !!el && plain(el) === text && ![...el.children].some((c) => plain(c) === text);
}

const LONG = "中秋限定活動・送禮受眾 2026｜Advantage+ 購物活動 - 複本";

function campaign(overrides: Partial<HomeCampaign> = {}): HomeCampaign {
  return {
    campaign_id: "cmp_daily", name: "日常商品推廣・轉換", origin: "internal", status: "live", month_spend: 15767.4, purchases: 121,
    cost_per_purchase: 130.31, cap: { value: 450, basis: "own", break_even: 520 }, active_ads: 8, daily_budget: 1200, missing_days: [], sync_state: "ok",
    data_status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: "2026-09-23T00:40:00Z" }, handoff: null, draft: null,
    ...overrides,
  };
}

function home(overrides: Partial<HomeOverview> = {}): HomeOverview {
  return {
    month: "2026-09", day_of_month: 23, days_in_month: 30, currency: "TWD", spent: 22000,
    money: {
      purchases: 158, cost_per_purchase: 139.24, cap: { value: 450, basis: "own", break_even: 520 }, earn: 60163.5, earn_missing: [], excluded: [],
      previous_same_period: { days: 22, purchases: 118, cost_per_purchase: 221.37 },
    },
    pace: { budget_amount: 60000, available: 23600, daily: [{ day: "2026-09-22", cumulative: 22000 }], projected_month_end: 28695.65 },
    quality: { buckets: [{ grade: "on_target", amount: 22000, count: 3, ads: [] }] },
    timeline: [
      { date: "2026-09-23", kind: "today", campaign_id: null, name: null, ready: null },
      { date: "2026-09-30", kind: "month_review", campaign_id: null, name: null, ready: null },
      { date: "2026-10-01", kind: "campaign_start", campaign_id: "cmp_fall", name: "秋季新色預購", ready: false },
      { date: "2026-10-08", kind: "campaign_end", campaign_id: "cmp_daily", name: "日常商品推廣・轉換", ready: null },
    ],
    campaigns: [campaign()],
    sync: { last_success_at: "2026-09-23T00:40:00Z", next_at: null },
    ...overrides,
  };
}

const ready = (h: HomeOverview) => ({ status: "ready" as const, home: h });
const wrap = (node: React.ReactNode) => render(<MemoryRouter>{node}</MemoryRouter>);

describe("MonthMoney", () => {
  it("prints the rounded earn, whole-yuan cost per purchase, the shared cap and last month's same days", () => {
    wrap(<MonthMoney brandId="b" state={ready(home())} onRetry={vi.fn()} scaleHref={null} onBudgetClosed={vi.fn()} />);
    expect(screen.getByText("扣掉廣告費，這個月估計多賺")).toBeTruthy();
    expect(screen.getByText("約 NT$60,000")).toBeTruthy();
    expect(screen.getByText("NT$139 元")).toBeTruthy();
    expect(screen.getByText(byPlain("每個活動各有上限，目前都是 450"))).toBeTruthy();
    expect(screen.getByText(byPlain("・有賺（打平 520）"))).toBeTruthy();
    expect(screen.getByText("各活動上限 450")).toBeTruthy();
    expect(screen.getByText("比 8 月同期多 40 筆")).toBeTruthy();
    expect(screen.getByText("便宜 37%")).toBeTruthy();
    expect(screen.getByText("8 月同期 221 元")).toBeTruthy();
    expect(screen.getByText("23,600 元")).toBeTruthy();
    expect(screen.getByText(/照現在速度月底會用不完/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "看加預算建議 →" })).toBeNull();
  });

  it("unknowns: earn names what is missing, no purchase yet, no comparison, break-even cap wording", () => {
    const h = home({
      money: { purchases: 0, cost_per_purchase: null, cap: { value: 520, basis: "break_even", break_even: 520 }, earn: null, earn_missing: ["product_cost"], excluded: [], previous_same_period: null },
      pace: { budget_amount: null, available: null, daily: [], projected_month_end: null },
    });
    wrap(<MonthMoney brandId="b" state={ready(h)} onRetry={vi.fn()} scaleHref={null} onBudgetClosed={vi.fn()} />);
    expect(screen.getByText("算不出來・缺商品成本")).toBeTruthy();
    expect(screen.getByText("還沒有購買")).toBeTruthy();
    expect(screen.getByText(byPlain("每個活動各自算，目前都暫用打平線 520"))).toBeTruthy();
    expect(document.querySelector('[data-slot="money-tag"]')).toBeNull();
    expect(screen.getAllByText("8 月同期沒有可比資料")).toHaveLength(2);
    expect(screen.getByText("還沒設這個月的預算")).toBeTruthy();
    expect(screen.queryByText(/NT\$0/)).toBeNull();
  });

  it("no shared cap: says the campaigns differ, or that none has a cap", () => {
    const differ = home({ money: { ...home().money!, cap: null }, campaigns: [campaign(), campaign({ campaign_id: "c2", cap: { value: 300, basis: "own", break_even: 520 } })] });
    const { unmount } = wrap(<MonthMoney brandId="b" state={ready(differ)} onRetry={vi.fn()} scaleHref={null} onBudgetClosed={vi.fn()} />);
    expect(screen.getByText(byPlain("每個活動的上限不一樣"))).toBeTruthy();
    unmount();
    const none = home({ money: { ...home().money!, cap: null }, campaigns: [campaign({ cap: null })] });
    wrap(<MonthMoney brandId="b" state={ready(none)} onRetry={vi.fn()} scaleHref={null} onBudgetClosed={vi.fn()} />);
    expect(screen.getByText("還沒設上限")).toBeTruthy();
  });

  it("a loss prints 少賺 with the absolute amount; another currency keeps its code", () => {
    wrap(<MonthMoney brandId="b" state={ready(home({ currency: "USD", money: { ...home().money!, earn: -1499.5 } }))} onRetry={vi.fn()} scaleHref={null} onBudgetClosed={vi.fn()} />);
    expect(screen.getByText("扣掉廣告費，這個月估計少賺")).toBeTruthy();
    expect(screen.getByText("約 USD 1,000")).toBeTruthy();
  });

  it("the pace block failing alone says so once; the money column stays", () => {
    wrap(<MonthMoney brandId="b" state={ready(home({ pace: null }))} onRetry={vi.fn()} scaleHref={null} onBudgetClosed={vi.fn()} />);
    expect(screen.getByText("預算進度暫時讀取不到")).toBeTruthy();
    expect(screen.getByText("約 NT$60,000")).toBeTruthy();
  });
});

/** The band reads the brand from the home route (`/brands/:brandId/ads`) for its 重新讀取平台 link. */
const wrapOnHome = (node: React.ReactNode) => render(
  <MemoryRouter initialEntries={["/brands/b/ads"]}><Routes><Route path="/brands/:brandId/ads" element={node} /></Routes></MemoryRouter>,
);

describe("QualityBand", () => {
  // F40-I07 (drill-7 #8, prototype `#/home`): three honest empty states — the day is named, a failed block is a
  // failure, and a month with nothing spent says so; none prints 0 or blames 「有一天的花費沒讀到」 for every null.
  it("(i) unread day: names it and 重新讀取平台 opens that campaign's 成效 tab", () => {
    const h = home({ spent: null, quality: null, campaigns: [campaign(), campaign({ campaign_id: "cmp_gap", missing_days: ["2026-09-03"] })] });
    wrapOnHome(<QualityBand state={ready(h)} onRetry={vi.fn()} />);
    expect(screen.getByText("9 月已花還不完整（09/03 沒讀到），先不分級")).toBeTruthy();
    expect(screen.getByRole("link", { name: "重新讀取平台" }).getAttribute("href")).toBe("/brands/b/ads/campaigns/cmp_gap?tab=performance");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("(ii) spend known but no grades: 分級讀取失敗 in danger tone with 重試 reloading the board", () => {
    const onRetry = vi.fn();
    wrapOnHome(<QualityBand state={ready(home({ spent: 10081, quality: null }))} onRetry={onRetry} />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toBe("分級讀取失敗");
    expect(alert.className).toContain("text-danger");
    fireEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/還不完整|沒讀到/)).toBeNull();
  });

  it("(iii) nothing spent this month: one sentence, no button, no band", () => {
    wrapOnHome(<QualityBand state={ready(home({ spent: 0, quality: { buckets: [] } }))} onRetry={vi.fn()} />);
    expect(screen.getByText("9 月還沒有花費資料，先不分級")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText(/0 元|NT\$0/)).toBeNull();
  });

  it("buckets render through the kit band with the month label", () => {
    wrap(<QualityBand state={ready(home())} onRetry={vi.fn()} />);
    expect(screen.getByText("100%")).toBeTruthy();
    expect(screen.getByText("9 月已花 22,000 元")).toBeTruthy();
  });
});

describe("CampaignRows", () => {
  it("live, imported-with-gap and draft rows: names open the workspace; each row has its one next step", () => {
    const h = home({ campaigns: [
      campaign(),
      campaign({ campaign_id: "cmp_mid", name: LONG, origin: "imported", status: "draft", month_spend: 6233.5, purchases: 37, cost_per_purchase: 168.46,
        missing_days: ["2026-09-17", "2026-09-18"], daily_budget: null,
        data_status: { state: "partial", label: "有幾天的資料還沒讀到，數字可能偏少。", missing_days: ["2026-09-17", "2026-09-18"], last_success_at: "2026-09-23T00:40:00Z" } }),
      campaign({ campaign_id: "cmp_fall", name: "秋季新色預購", status: "draft", month_spend: null, purchases: null, cost_per_purchase: null, cap: null,
        active_ads: 0, draft: { start_date: "2026-10-01", cap_missing: true, ads_total: 8, ads_ready: 7, approved: false } }),
    ] });
    wrap(<CampaignRows brandId="b" state={ready(h)} onRetry={vi.fn()} />);
    const grid = screen.getByTestId("campaign-grid");
    expect(within(grid).getByText(LONG, { exact: true }).closest("a")?.getAttribute("href")).toBe("/brands/b/ads/campaigns/cmp_mid");
    expect(within(grid).getByText("15,767 元")).toBeTruthy();
    expect(within(grid).getByText("130 元")).toBeTruthy();
    expect(within(grid).getByText("9/17、9/18 沒抓到資料")).toBeTruthy();
    expect(within(grid).getByText("在投 8 則・每日 未知")).toBeTruthy();
    expect(within(grid).getByRole("link", { name: "重新連線 →" }).getAttribute("href")).toBe("/brands/b/ads/connections");
    expect(within(grid).getByRole("link", { name: "打開 →" }).getAttribute("href")).toBe("/brands/b/ads/campaigns/cmp_daily");
    expect(within(grid).getByText("10/01 開始・還要設上限、補 1 張圖")).toBeTruthy();
    expect(within(grid).getByText("還沒上架")).toBeTruthy();
    expect(within(grid).getByText("還沒設上限")).toBeTruthy();
    expect(within(grid).getByRole("link", { name: "繼續準備 →" }).getAttribute("href")).toBe("/brands/b/ads/campaigns/cmp_fall?tab=strategy");
    expect(within(grid).getByRole("link", { name: "全部活動 →" }).getAttribute("href")).toBe("/brands/b/ads/campaigns");
  });

  it("no purchase yet and no spend rows say so, not 0", () => {
    wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: [campaign({ month_spend: null, purchases: 0, cost_per_purchase: null, cap: { value: 520, basis: "break_even", break_even: 520 } })] }))} onRetry={vi.fn()} />);
    expect(screen.getByText("沒有花費紀錄")).toBeTruthy();
    expect(screen.getByText("還沒有購買")).toBeTruthy();
    expect(screen.queryByText("0 元")).toBeNull();
  });

  it("a failed platform read turns the action into 重新連線; the reason is the row's own data_status sentence", () => {
    wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: [campaign({ sync_state: "auth_expired",
      data_status: { state: "auth_expired", label: "平台授權已過期，重新連線後才能讀資料。", missing_days: [], last_success_at: null } })] }))} onRetry={vi.fn()} />);
    expect(screen.getByText("平台授權已過期，重新連線後才能讀資料")).toBeTruthy();
    expect(screen.getByRole("link", { name: "重新連線 →" })).toBeTruthy();
  });

  it("the reason comes from data_status only: a stale sync_state or missing_days never adds a second one", () => {
    wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: [campaign({ sync_state: "failed", missing_days: ["2026-09-17"] })] }))} onRetry={vi.fn()} />);
    expect(screen.queryByText(/讀取失敗|沒抓到資料|還沒讀到/)).toBeNull();
    expect(screen.getByRole("link", { name: "打開 →" })).toBeTruthy();
  });

  it("every day read and nothing spent: the sentence stands where the spend would be", () => {
    wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: [campaign({ month_spend: null, purchases: null, cost_per_purchase: null,
      data_status: { state: "no_rows", label: "已讀過平台資料，這段期間沒有花費紀錄。", missing_days: [], last_success_at: null } })] }))} onRetry={vi.fn()} />);
    expect(screen.getByText("已讀過平台資料，這段期間沒有花費紀錄")).toBeTruthy();
    expect(screen.queryByText("沒有花費紀錄")).toBeNull();
  });

  it("handoff: 等你到 Meta 完成 (platform) and 等核對 (check) link to the 變更與核對 tab; none shows no chip", () => {
    const h = home({ campaigns: [
      campaign({ campaign_id: "cmp_mid", name: "中秋限定活動", handoff: { state: "platform", change_set_id: "cs_1" } }),
      campaign({ campaign_id: "cmp_x", name: "夏季清倉・舊帳戶", origin: "imported", handoff: { state: "check", change_set_id: "cs_2" } }),
      campaign({ campaign_id: "cmp_fall", name: "秋季新色預購", status: "draft", month_spend: null, purchases: null, cost_per_purchase: null, cap: null,
        active_ads: 0, handoff: { state: "platform", change_set_id: "launch_1" }, draft: { start_date: "2026-10-01", cap_missing: false, ads_total: 8, ads_ready: 8, approved: true } }),
      campaign(),
    ] });
    wrap(<CampaignRows brandId="b" state={ready(h)} onRetry={vi.fn()} />);
    const platform = screen.getAllByRole("link", { name: "等你到 Meta 完成 →" });
    expect(platform.map((a) => a.getAttribute("href"))).toEqual([
      "/brands/b/ads/campaigns/cmp_mid?tab=changes", "/brands/b/ads/campaigns/cmp_fall?tab=changes",
    ]);
    expect(platform[0].querySelector('[data-slot="chip"]')?.getAttribute("data-tone")).toBe("accent");
    const check = screen.getByRole("link", { name: "等核對 →" });
    expect(check.getAttribute("href")).toBe("/brands/b/ads/campaigns/cmp_x?tab=changes");
    expect(check.querySelector('[data-slot="chip"]')?.getAttribute("data-tone")).toBe("warn");
    expect(screen.getAllByRole("link", { name: /等你到 Meta 完成|等核對/ })).toHaveLength(3);
  });

  it("money tag beside the cost: 有賺 against break-even; hidden when break-even is unknown (never guessed)", () => {
    const { unmount } = wrap(<CampaignRows brandId="b" state={ready(home())} onRetry={vi.fn()} />);
    expect(screen.getByText(byPlain("・有賺（打平 520）"))).toBeTruthy();
    unmount();
    wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: [campaign({ cap: { value: 450, basis: "own", break_even: null } })] }))} onRetry={vi.fn()} />);
    expect(screen.getByText("130 元")).toBeTruthy();
    expect(document.querySelector('[data-slot="money-tag"]')).toBeNull();
  });

  it("longest real names wrap inside their cell instead of being cut (the 1024 layout itself is in the side-by-side evidence)", () => {
    wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: [campaign({ name: LONG, handoff: { state: "check", change_set_id: "cs_1" },
      data_status: { state: "partial", label: "有幾天的資料還沒讀到，數字可能偏少。", missing_days: ["2026-09-01", "2026-09-02", "2026-09-17", "2026-09-18"], last_success_at: null } })] }))} onRetry={vi.fn()} />);
    expect(screen.getByText("4 天沒抓到資料")).toBeTruthy();
    const name = screen.getByRole("link", { name: LONG });
    expect(name.textContent).toBe(LONG);
    expect(name.className).toContain("[overflow-wrap:anywhere]");
    expect(name.className).toContain("whitespace-normal");
    expect(name.parentElement?.className).toContain("flex-wrap");
  });

  // F49 Contract L: the word is the served lifecycle; 「在投」 is the served running count and only while live.
  it("an ended campaign reads 已結束・待結案 with its closeout step and no 在投; ads still running are said apart", () => {
    wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: [
      campaign({ campaign_id: "cmp_end", name: "秋季檔期・第三期", status: "ended", lifecycle: { state: "ended", label: "已結束・待結案", can_close: true },
        running: { count: 2, unknown: 0, read_at: "2026-10-10T02:00:00Z", stale: false } }),
      campaign({ campaign_id: "cmp_imp", name: "夏季清倉・舊帳戶", origin: "imported", status: "ended", lifecycle: { state: "ended", label: "已結束", can_close: false },
        running: { count: 0, unknown: 0, read_at: null, stale: false } }),
    ] }))} onRetry={vi.fn()} />);
    const grid = screen.getByTestId("campaign-grid");
    expect(within(grid).getByText("已結束・待結案").getAttribute("data-state")).toBe("ended");
    expect(within(grid).getByText("已結束")).toBeTruthy();
    expect(grid.textContent).not.toMatch(/在投/);
    expect(within(grid).getByText("平台上還開著 2 則")).toBeTruthy();
    expect(within(grid).getByRole("link", { name: "結案這一期 →" }).getAttribute("href")).toBe("/brands/b/ads/campaigns/cmp_end?tab=perf&close=1");
    // An imported campaign has no closeout here: it opens as before.
    expect(within(grid).getByRole("link", { name: "打開 →" }).getAttribute("href")).toBe("/brands/b/ads/campaigns/cmp_imp");
  });

  it("a live row prints 投放中 and the served running count; a count read before the last report says when it was read", () => {
    const readAt = "2026-10-03T06:20:00Z";
    const d = new Date(readAt);
    const at = `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: [
      campaign({ lifecycle: { state: "live", label: "投放中", can_close: true }, active_ads: 0, daily_budget: null,
        running: { count: 0, unknown: 1, read_at: readAt, stale: true } }),
      campaign({ campaign_id: "cmp_2", name: "第二個活動", lifecycle: { state: "live", label: "投放中", can_close: true }, active_ads: 3,
        running: { count: 3, unknown: 0, read_at: readAt, stale: false } }),
    ] }))} onRetry={vi.fn()} />);
    expect(screen.getByText(`在投 0 則・另有 1 則狀態不明・上次讀取 ${at}・每日 未知`)).toBeTruthy();
    expect(screen.getByText("在投 3 則・每日 1,200")).toBeTruthy();
    expect(screen.getAllByText("投放中")).toHaveLength(2);
  });

  it("a stale count never read yet says so instead of a time", () => {
    wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: [
      campaign({ lifecycle: { state: "live", label: "投放中", can_close: true }, active_ads: 0, running: { count: 0, unknown: 0, read_at: null, stale: true } }),
    ] }))} onRetry={vi.fn()} />);
    expect(screen.getByText("在投 0 則・還沒讀到平台上的廣告・每日 1,200")).toBeTruthy();
  });

  it("a draft row's chip is the served label", () => {
    wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: [
      campaign({ campaign_id: "cmp_fall", name: "秋季新色預購", status: "ready", lifecycle: { state: "draft", label: "草稿", can_close: false }, month_spend: null, purchases: null, cost_per_purchase: null, cap: null,
        active_ads: 0, draft: { start_date: "2026-10-01", cap_missing: false, ads_total: 8, ads_ready: 8, approved: true } }),
    ] }))} onRetry={vi.fn()} />);
    expect(screen.getByText("草稿").getAttribute("data-state")).toBe("draft");
  });

  it("no campaign in progress: names the ones closed this month and links to all campaigns; none closed says 還沒有活動", () => {
    const { unmount } = wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: [], closed_this_month: 3 }))} onRetry={vi.fn()} />);
    expect(screen.getByTestId("campaign-grid").textContent).toContain("這個月沒有進行中的活動・已結案 3 個");
    expect(screen.getByRole("link", { name: "已結案 3 個" }).getAttribute("href")).toBe("/brands/b/ads/campaigns");
    expect(screen.queryByText("還沒有活動")).toBeNull();
    unmount();
    wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: [], closed_this_month: 0 }))} onRetry={vi.fn()} />);
    expect(screen.getByText("還沒有活動")).toBeTruthy();
  });

  it("the campaigns block failing alone shows its own retry", () => {
    wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: null }))} onRetry={vi.fn()} />);
    expect(screen.getByText("活動暫時讀取不到")).toBeTruthy();
  });
});

describe("NextDates", () => {
  it("four stops: today with its note, month review, a start that is not ready, an end (short names)", () => {
    wrap(<NextDates home={home()} note={{ kind: "open", count: 2 }} onJump={vi.fn()} />);
    expect(screen.getByText("9/23 今天")).toBeTruthy();
    expect(screen.getByRole("button", { name: "2 件要你決定 ↓" })).toBeTruthy();
    expect(screen.getByText("9 月回顧")).toBeTruthy();
    expect(screen.getByText("10/01")).toBeTruthy();
    expect(screen.getByText("・還沒準備好")).toBeTruthy();
    expect(screen.getByText("日常商品推廣這一期結束")).toBeTruthy();
  });
});

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
/** The brand's open period-settle row (Contract E), August settled on 9/2. */
function settleRow(overrides: Partial<SettleQueueRow> = {}): SettleQueueRow {
  return {
    id: "itr_s", dedupe_key: "settle", category: "ads_triage_settle", severity: "rule_warning", message: "結算上一期（8 月），待寫進筆記本",
    action_url: "/brands/b/ads/settle/2026-08/result", visible_from: null, status: "open", created_at: "2026-09-02T00:00:00Z",
    settle: { month: "2026-08", start: "2026-08-01", end: "2026-08-31", campaign_count: 2, imported_count: 1, learnable_count: 5, buckets: [
      { grade: "on_target", amount: 15300, count: 2, ads: [] }, { grade: "watch", amount: 3900, count: 1, ads: [] },
      { grade: "over", amount: 9340, count: 2, ads: [] }, { grade: "wasted", amount: 1600, count: 1, ads: [] },
      { grade: "insufficient", amount: 1600, count: 2, ads: [] }, { grade: "no_target", amount: 0, count: 0, ads: [] },
    ] },
    ...overrides,
  };
}
function row(id: string, kind: QueueItem["kind_key"], extra: Partial<QueueItem> = {}, t: Partial<TriageItem> = {}): QueueItem {
  return {
    id, org_id: "o", brand_id: "b", campaign_period_id: null, dedupe_key: id, category: "ads", kind: null, severity: "rule_warning", message: "",
    action_url: null, visible_from: null, status: "open", created_at: "2026-09-23T00:00:00Z", resolved_at: null, kind_key: kind,
    triage: triage(t), proposal: null, done: false, ...extra,
  };
}
const payload = (items: QueueItem[]) => ({ status: "ready" as const, queue: { items, counts: { stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 }, total_ads: 0, kinds_available: [], kinds_pending: [] } });

describe("TodayDecisions", () => {
  it("cleanup card: red-only cut title with the saving rounded to 10; 沒賣出 rows show spend, others whole-yuan cost", () => {
    const cleanup = row("c1", "cleanup", {
      action_url: "/brands/b/ads/campaigns/cmp_daily/propose/cleanup/cmp_daily",
      cleanup: { campaign_id: "cmp_daily", campaign_name: "日常商品推廣・轉換", can_support: 6, active_ads: 8, short: 0, daily_saving: 257, scale_owner_id: null, keep: [],
        ads: [
          { entity_id: "a9", name: "秋季新色預告・直式 9:16 短影音", thumbnail_url: null, spend_7d: 770, grade: "wasted", cost_per_result: null, spend: 1480, result_count: 0, daily_spend: 110, rejected_before: null },
          { entity_id: "a8", name: "提問式貼文・早晨第一口是什麼？", thumbnail_url: null, spend_7d: 1050, grade: "over", cost_per_result: 617.5, spend: 2470, result_count: 4, daily_spend: 150, rejected_before: null },
        ] },
    });
    wrap(<TodayDecisions brandId="b" state={payload([cleanup])} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(screen.getByText("關掉色帶裡紅色的 2 則，每天省約 260 元")).toBeTruthy();
    expect(screen.getByText("花 1,480・0 筆")).toBeTruthy();
    expect(screen.getByText("每筆 618 元")).toBeTruthy(); // F47-I06: 617.5 rounds like the performance page, never floors
    expect(screen.getByText("沒賣出")).toBeTruthy();
    expect(screen.getByText("太貴")).toBeTruthy();
    expect(screen.getByRole("link", { name: "決定要不要關 →" }).getAttribute("data-variant")).toBe("default");
  });

  it("cleanup with unknown saving and a 偏貴 ad: plain cut title, no saving", () => {
    const cleanup = row("c1", "cleanup", {
      action_url: "/x",
      cleanup: { campaign_id: "cmp_daily", campaign_name: "日常商品推廣・轉換", can_support: 6, active_ads: 8, short: 0, daily_saving: null, scale_owner_id: null, keep: [],
        ads: [{ entity_id: "a8", name: "提問式貼文", thumbnail_url: null, spend_7d: null, grade: "watch", cost_per_result: 500, spend: 2470, result_count: 4, daily_spend: null, rejected_before: null }] },
    });
    wrap(<TodayDecisions brandId="b" state={payload([cleanup])} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(screen.getByText("關掉 1 則")).toBeTruthy();
  });

  it("worse card: the label is the backend's grade move; costs compared with this campaign's cap; trend only as a footnote", () => {
    const { unmount } = wrap(<TodayDecisions brandId="b" state={payload([row("w1", "worse", {}, { target: { ...triage().target, break_even: 520 } })])} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(screen.getByText("從划算變太貴")).toBeTruthy();
    expect(screen.getByText(byPlain("每筆 440 → 520，超過日常商品推廣的上限 450"))).toBeTruthy();
    expect(screen.getByText(byPlain("・剛好打平（打平 520）"))).toBeTruthy();
    expect(screen.getByText("比前 7 天 ▲18%（只當參考）")).toBeTruthy();
    expect(screen.getByRole("link", { name: "查原因 →" }).getAttribute("data-variant")).toBe("outline");
    unmount();
    wrap(<TodayDecisions brandId="b" state={payload([row("w1", "worse", {}, {
      grade_move: { from: "on_target", to: "watch" }, change_pct: null, window: { ...triage().window, days: 14 },
      target: { value: 520, basis: "break_even", result_kind: "purchase", result_label: "購買", missing: [], break_even: 520 },
      current: { ...triage().current, cost_per_result: 505.5 },
    })])} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(screen.getByText("從划算變偏貴")).toBeTruthy();
    expect(screen.getByText(byPlain("每筆 440 → 506，還在日常商品推廣暫用打平線 520 內"))).toBeTruthy(); // 505.5 rounds (F47-I06)
    expect(screen.getByText("比前 14 天：沒有可比資料（只當參考）")).toBeTruthy();
  });

  it("a worse row without a grade move: no move is guessed from previous_grade or the trend; no break-even, no money tag", () => {
    wrap(<TodayDecisions brandId="b" state={payload([row("w1", "worse", {}, { grade_move: null, previous_grade: "on_target", grade: "over" })])} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(screen.getByText("每筆變多了")).toBeTruthy();
    expect(screen.queryByText(/^從.+變/)).toBeNull();
    expect(document.querySelector('[data-slot="money-tag"]')).toBeNull();
  });

  it("cleanup rows: grade chips are glossary terms and a cost carries its money tag when break-even is known", () => {
    const cleanup = row("c1", "cleanup", {
      action_url: "/x",
      cleanup: { campaign_id: "cmp_daily", campaign_name: "日常商品推廣・轉換", can_support: 6, active_ads: 8, short: 0, daily_saving: null, scale_owner_id: null, keep: [],
        ads: [{ entity_id: "a8", name: "提問式貼文・早晨第一口是什麼？", thumbnail_url: null, spend_7d: null, grade: "over", cost_per_result: 617.5, spend: 2470, result_count: 4, daily_spend: null, rejected_before: null }] },
    }, { target: { ...triage().target, break_even: 520 } });
    wrap(<TodayDecisions brandId="b" state={payload([cleanup])} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(document.querySelector('[data-grade="over"] [data-slot="term"]')).toBeTruthy();
    expect(screen.getByText(byPlain("・在虧（打平 520）"))).toBeTruthy();
  });

  it("settle card: the row's range, campaigns (imported counted), learnable ads, the grade bar and 開始結算; it spans the row", () => {
    wrap(<TodayDecisions brandId="b" state={{ status: "ready", queue: { ...payload([]).queue, settle: settleRow() } }} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    const card = screen.getByRole("article", { name: "結算上一期" });
    expect(card.className).toContain("col-span-full");
    expect(within(card).getByText("08/01–08/31・2 個活動（1 個從 Meta 帶進來）")).toBeTruthy();
    expect(within(card).getByText(byPlain("5 則的成績可以寫進筆記本"))).toBeTruthy();
    expect(card.querySelector('[data-slot="grade-bar"]')).toBeTruthy();
    expect(card.querySelector('[data-slot="grade-rules"]')).toBeNull();
    expect(within(card).getByText("沒賣出 1 則")).toBeTruthy();
    expect(within(card).getByRole("link", { name: "開始結算 →" }).getAttribute("href")).toBe("/brands/b/ads/settle/2026-08/result");
    expect(screen.getByText("1 件")).toBeTruthy();
  });

  it("settle with no imported campaign drops the Meta note", () => {
    const row = settleRow({ settle: { ...settleRow().settle, imported_count: 0, campaign_count: 1 } });
    wrap(<TodayDecisions brandId="b" state={{ status: "ready", queue: { ...payload([]).queue, settle: row } }} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(screen.getByText("08/01–08/31・1 個活動")).toBeTruthy();
  });

  it("a written settle leaves the cards and the count, and sits in 今天處理過 with its range", () => {
    const row = settleRow({ status: "resolved" });
    wrap(<TodayDecisions brandId="b" state={{ status: "ready", queue: { ...payload([]).queue, settle: row } }} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(screen.queryByRole("article", { name: "結算上一期" })).toBeNull();
    expect(screen.getByText("今天沒有要決定的事")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "今天處理過 1 件" }));
    expect(screen.getByText("結算上一期 08/01–08/31")).toBeTruthy();
    expect(screen.getByText("✓ 已寫進筆記本").getAttribute("data-tone")).toBe("ok");
  });

  // F47-I07 (drill-10 Q2): a deferred decision is done by the row's own `done`, shows 「M/D 再看」 and links back to its set.
  it("a deferred cleanup sits in 今天處理過 with 「M/D 再看」 linking to its change set; the count ignores it", () => {
    const deferred = row("c1", "cleanup", {
      action_url: "/brands/b/ads/campaigns/cmp_daily/propose/cleanup/cmp_daily", done: true,
      proposal: { kind: "cleanup", change_set_id: "acs_9", campaign_id: "cmp_daily", status: "deferred", verification_state: "pending", reason: "想再觀察幾天", revisit_at: "2026-11-05T12:00:00Z", multi: true },
      cleanup: { campaign_id: "cmp_daily", campaign_name: "日常商品推廣・轉換", can_support: 6, active_ads: 8, short: 0, daily_saving: null, scale_owner_id: null, keep: [],
        ads: [{ entity_id: "a8", name: "提問式貼文", thumbnail_url: null, spend_7d: null, grade: "wasted", cost_per_result: null, spend: 2470, result_count: 0, daily_spend: null, rejected_before: null }] },
    });
    wrap(<TodayDecisions brandId="b" state={payload([deferred, row("w1", "worse")])} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(screen.getByText("1 件")).toBeTruthy();
    expect(screen.queryByRole("article", { name: "關 1 則、留 0 則" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "今天處理過 1 件" }));
    const back = screen.getByRole("link", { name: "11/5 再看" });
    expect(back.getAttribute("href")).toBe("/brands/b/ads/campaigns/cmp_daily/changes/acs_9/confirm");
  });

  it("a row the backend marks open stays open even if its proposal looks decided (one owner of done-ness)", () => {
    const stale = row("w1", "worse", { done: false, proposal: { kind: "review", review_id: "r1", status: "deferred", decision: "deferred", reason: null, revisit_at: null, recommendation_id: null, change_set_id: null, change_set_status: null, verification_state: null, multi: false } });
    wrap(<TodayDecisions brandId="b" state={payload([stale])} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(screen.getByText("1 件")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /今天處理過/ })).toBeNull();
  });

  it("a closeout beyond the first three folds into its own row with 結案這一期; the fold count and chip use the served count", () => {
    const close: CloseoutQueueRow = {
      id: "itr_c", dedupe_key: "c", category: "ads_triage_closeout", severity: "rule_warning", message: "「秋季檔期・第三期」已結束，待結案",
      action_url: "/brands/b/ads/campaigns/cmp_fall?tab=perf&close=1", visible_from: null, status: "open", created_at: "2026-10-10T00:00:00Z",
      campaign_id: "cmp_fall", decision: true, position: 4, done: false,
      closeout: { campaign_id: "cmp_fall", campaign_name: "秋季檔期・第三期", end_date: null, running: { count: 0, read_at: null } },
    };
    const rows = [1, 2, 3].map((n) => row(`w${n}`, "worse", { decision: true, position: n }, { entity_id: `ad_${n}`, name: `廣告 ${n}` }));
    wrap(<TodayDecisions brandId="b" state={{ status: "ready", queue: { ...payload(rows).queue, closeouts: [close], decisions: { kinds: [], open: 4 } } }} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(screen.getAllByRole("article")).toHaveLength(3);
    expect(screen.getByText("4 件")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "還有 1 件要決定" }));
    expect(screen.getByText("「秋季檔期・第三期」已結束，待結案")).toBeTruthy();
    expect(screen.getByRole("link", { name: "結案這一期 →" }).getAttribute("href")).toBe("/brands/b/ads/campaigns/cmp_fall?tab=perf&close=1");
  });

  it("an approved decision's button prints the served verification word", () => {
    const approved = row("c1", "cleanup", {
      action_url: "/x",
      proposal: { kind: "cleanup", change_set_id: "acs_1", campaign_id: "cmp_daily", status: "approved", verification_state: "reported", verification_label: "已回報，待讀回", reason: null, revisit_at: null, multi: true },
      cleanup: { campaign_id: "cmp_daily", campaign_name: "日常商品推廣・轉換", can_support: 6, active_ads: 8, short: 0, daily_saving: null, scale_owner_id: null, keep: [],
        ads: [{ entity_id: "a8", name: "提問式貼文", thumbnail_url: null, spend_7d: null, grade: "wasted", cost_per_result: null, spend: 2470, result_count: 0, daily_spend: null, rejected_before: null }] },
    });
    wrap(<TodayDecisions brandId="b" state={payload([approved])} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(screen.getByRole("link", { name: "已回報，待讀回 →" }).getAttribute("href")).toBe("/brands/b/ads/campaigns/cmp_daily/changes/acs_1/verify");
  });

  it("read failure: hero with the last successful sync time and a retry", () => {
    const d = new Date("2026-09-22T14:40:00Z");
    const p = (n: number) => String(n).padStart(2, "0");
    wrap(<TodayDecisions brandId="b" state={{ status: "error", message: "x" }} syncing={false} recovering={false} sync={{ last_success_at: d.toISOString(), next_at: null }} onRetry={vi.fn()} />);
    expect(screen.getByText("今天的判斷讀取失敗")).toBeTruthy();
    expect(screen.getByText(`上次成功 ${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}・已保存的決定都還在`)).toBeTruthy();
    expect(screen.getByRole("button", { name: "重新讀取" })).toBeTruthy();
  });
});
