/** frontend/src/components/ads/home/HomeBoard.test.tsx — F28-I08 board D blocks, rendered on their own with realistic
 * shapes (longest names, imported campaign, no-cap draft, decimal costs, unknown values). Unknown numbers print the
 * prototype's unknown words, never 0; money goes through the kit formatter. */
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { HomeCampaign, HomeOverview } from "@/lib/adsHomeApi";
import type { QueueItem, TriageItem } from "@/lib/adsTriageApi";
import { CampaignRows } from "./CampaignRows";
import { MonthMoney } from "./MonthMoney";
import { NextDates } from "./NextDates";
import { QualityBand } from "./QualityBand";
import { TodayDecisions } from "./TodayDecisions";

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
    expect(screen.getByText("你的上限 450")).toBeTruthy();
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
    expect(screen.getByText("暫用打平 520")).toBeTruthy();
    expect(screen.getAllByText("8 月同期沒有可比資料")).toHaveLength(2);
    expect(screen.getByText("還沒設這個月的預算")).toBeTruthy();
    expect(screen.queryByText(/NT\$0/)).toBeNull();
  });

  it("no shared cap: says the campaigns differ, or that none has a cap", () => {
    const differ = home({ money: { ...home().money!, cap: null }, campaigns: [campaign(), campaign({ campaign_id: "c2", cap: { value: 300, basis: "own", break_even: 520 } })] });
    const { unmount } = wrap(<MonthMoney brandId="b" state={ready(differ)} onRetry={vi.fn()} scaleHref={null} onBudgetClosed={vi.fn()} />);
    expect(screen.getByText("各活動上限不同")).toBeTruthy();
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

describe("QualityBand", () => {
  it("an unknown month spend grades nothing and says why", () => {
    wrap(<QualityBand state={ready(home({ spent: null, quality: null }))} onRetry={vi.fn()} />);
    expect(screen.getByText("9 月已花還不完整（有一天的花費沒讀到），先不分級")).toBeTruthy();
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
        missing_days: ["2026-09-17", "2026-09-18"], daily_budget: null }),
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

  it("a failed platform read turns the action into 重新連線 with a chip", () => {
    wrap(<CampaignRows brandId="b" state={ready(home({ campaigns: [campaign({ sync_state: "auth_expired" })] }))} onRetry={vi.fn()} />);
    expect(screen.getByText("讀取失敗")).toBeTruthy();
    expect(screen.getByRole("link", { name: "重新連線 →" })).toBeTruthy();
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
    change_pct: 18.2, sample: { gate: true, spend_multiple: 6.9, days_with_events: 7 },
    ...overrides,
  };
}
function row(id: string, kind: QueueItem["kind_key"], extra: Partial<QueueItem> = {}, t: Partial<TriageItem> = {}): QueueItem {
  return {
    id, org_id: "o", brand_id: "b", campaign_period_id: null, dedupe_key: id, category: "ads", kind: null, severity: "rule_warning", message: "",
    action_url: null, visible_from: null, status: "open", created_at: "2026-09-23T00:00:00Z", resolved_at: null, kind_key: kind,
    triage: triage(t), proposal: null, ...extra,
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
    expect(screen.getByText("每筆 617 元")).toBeTruthy();
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

  it("worse card: previous struck through, current whole yuan, compared with the cap (or 打平 when break-even)", () => {
    const { unmount } = wrap(<TodayDecisions brandId="b" state={payload([row("w1", "worse")])} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(screen.getByText("比上週變貴")).toBeTruthy();
    expect(screen.getByText("440")).toBeTruthy();
    expect(screen.getByText("→ 520 元")).toBeTruthy();
    expect(screen.getByText("比上限貴 16%")).toBeTruthy();
    unmount();
    wrap(<TodayDecisions brandId="b" state={payload([row("w1", "worse", {}, { target: { value: 520, basis: "break_even", result_kind: "purchase", result_label: "購買", missing: [] }, window: { ...triage().window, days: 14 } })])} syncing={false} recovering={false} sync={null} onRetry={vi.fn()} />);
    expect(screen.getByText("還在打平內")).toBeTruthy();
    expect(screen.getByText("比前 14 天變貴")).toBeTruthy();
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
