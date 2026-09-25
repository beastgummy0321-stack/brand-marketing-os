/** frontend/src/components/ads/month/MonthReviewPage.test.tsx — F27-I19: the page moved off
 * `listCampaigns`/`getTriage`/`fetchOrders` for its money sections and now reads Contract G's
 * `getMonthSummary` + `getMonthlyBudget` (both refetched together on the month Segmented) for
 * 全品牌花費／商城訂單／各活動／這個月關掉／下月建議; `listCampaigns`+`getTriage` stay only for
 * 素材 (F26 rule, month-independent); `getAdsLearnings` (Contract D) drives 記入品牌學習.
 * `vi.mock`s every one of those, never hits a real API.
 *
 * F27-I27: every `CampaignChip` family comes straight from the backend's own
 * `campaign_objective` field (`app/ads/repository.py::campaign_objective_family`, same rule as
 * campaign cards/triage items) — never a frontend keyword guess off the raw `objective` string,
 * and 記入品牌學習 no longer needs its own `listCampaigns` lookup for it. */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { listCampaigns } from "@/lib/adsApi";
import type { CampaignTriage, TriageClosedBlock, TriageClosedItem, TriageItem } from "@/lib/adsTriageApi";
import { getTriage } from "@/lib/adsTriageApi";
import { getMonthlyBudget, type MonthlyBudget } from "@/lib/adsChangeApi";
import {
  dismissSuggestion, getMonthSummary,
  type MonthCampaignRow, type MonthSuggestion, type MonthSummary,
} from "@/lib/adsMonthApi";
import { getAdsLearnings, type AdsLearning } from "@/lib/adsLearningsApi";
import { MonthReviewPage } from "./MonthReviewPage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, listCampaigns: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, getTriage: vi.fn() };
});
vi.mock("@/lib/adsChangeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsChangeApi")>("@/lib/adsChangeApi");
  return { ...actual, getMonthlyBudget: vi.fn() };
});
vi.mock("@/lib/adsMonthApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsMonthApi")>("@/lib/adsMonthApi");
  return { ...actual, getMonthSummary: vi.fn(), dismissSuggestion: vi.fn() };
});
vi.mock("@/lib/adsLearningsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsLearningsApi")>("@/lib/adsLearningsApi");
  return { ...actual, getAdsLearnings: vi.fn() };
});

const mockListCampaigns = vi.mocked(listCampaigns);
const mockGetTriage = vi.mocked(getTriage);
const mockGetMonthlyBudget = vi.mocked(getMonthlyBudget);
const mockGetMonthSummary = vi.mocked(getMonthSummary);
const mockDismissSuggestion = vi.mocked(dismissSuggestion);
const mockGetAdsLearnings = vi.mocked(getAdsLearnings);

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
    grade: "on_target", grade_label: "划算", previous_grade: null, grade_move: null,
    window: { start: "2026-09-15", end: "2026-09-21", days: 7, previous_start: "2026-09-08", previous_end: "2026-09-14", extended_from: null },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 1000, result_count: 5, cost_per_result: 200, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    previous: { spend: 900, result_count: 4, cost_per_result: 225, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: -0.11, sample: { gate: true, spend_multiple: 2.2, days_with_events: 5 },
    ...overrides,
  };
}

const EMPTY_CLOSED: TriageClosedBlock = {
  paused: 0, archived: 0, other: 0, total: 0, items: [], truncated: false,
};

function closedItem(overrides: Partial<TriageClosedItem> = {}): TriageClosedItem {
  return {
    entity_id: "closed_1", name: "1150706 已下架單圖", native_status: "PAUSED",
    thumbnail_url: null, spend: 300, cost_per_result: 150, result_label: "購買",
    ...overrides,
  };
}

function triage(items: TriageItem[], closed: TriageClosedBlock = EMPTY_CLOSED): CampaignTriage {
  return { window_days: 7, items, closed };
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

function monthCampaignRow(overrides: Partial<MonthCampaignRow> = {}): MonthCampaignRow {
  return {
    campaign_id: "cmp_1", name: "日常商品推廣", objective: "轉換", campaign_objective: "sales",
    spend: 18400, result_count: 40, result_label: "購買",
    cost_per_result: 412, target: 450, verdict: "met",
    ...overrides,
  };
}

function monthSuggestion(overrides: Partial<MonthSuggestion> = {}): MonthSuggestion {
  return {
    key: "refresh:cmp_1", kind: "refresh", campaign_id: "cmp_1", campaign_name: "日常商品推廣",
    objective: "轉換", campaign_objective: "sales", title: "補 3 則新素材",
    why: "有效的方向只剩 1 則在投",
    action_url: "/brands/brd_1/ads/campaigns/cmp_1/detail",
    ...overrides,
  };
}

function monthSummary(overrides: Partial<MonthSummary> = {}): MonthSummary {
  return {
    month: "2026-09", currency: "TWD", total_spend: 22000,
    campaigns: [monthCampaignRow()],
    orders: { this_net: 43470, this_count: 51, previous_net: 61200, previous_count: 60, change_pct: -0.29 },
    closed_this_month: 2, closed_tracking_since: "2026-09-22",
    suggestions: [monthSuggestion()],
    days_covered: 30, days_elapsed: 21,
    // F29-I01 Contract C: the month's spend split by the one ruler; one remembered "no" got worse.
    grades: {
      spent: 22000,
      buckets: [
        { grade: "on_target", amount: 15400, count: 1, ads: [{ entity_id: "ad_1", name: "1150706 健身情境單圖", thumbnail_url: null, spend: 15400 }] },
        { grade: "watch", amount: 0, count: 0, ads: [] },
        { grade: "over", amount: 3000, count: 1, ads: [{ entity_id: "ad_2", name: "提問式貼文", thumbnail_url: null, spend: 3000 }] },
        { grade: "wasted", amount: 1480, count: 1, ads: [{ entity_id: "ad_3", name: "秋季新色預告", thumbnail_url: null, spend: 1480 }] },
        { grade: "insufficient", amount: 2120, count: 2, ads: [] },
        { grade: "no_target", amount: 0, count: 0, ads: [] },
      ],
      rows: [],
      missing: [{ campaign_id: "cmp_1", name: "日常商品推廣", missing_days: ["2026-09-17", "2026-09-18"] }],
    },
    rejected: {
      worse: [{
        change_set_id: "acs_1", campaign_id: "cmp_1", campaign_name: "日常商品推廣", title: "清理：日常商品推廣",
        at: "2026-09-12T02:00:00+00:00", reason: "季節性", ads: [{ entity_id: "ad_2", name: "提問式貼文", thumbnail_url: null, was: "watch", now: "over" }],
      }],
      same_count: 1,
    },
    ...overrides,
  };
}

function adsLearning(overrides: Partial<AdsLearning> = {}): AdsLearning {
  return {
    id: "lrn_1", text: "「日常出發」生活情境對廣泛受眾有效", confidence: "likely", count: 2,
    campaign_id: "cmp_1", campaign_name: "日常商品推廣", campaign_objective: "sales",
    learned_at: "2026-09-10T00:00:00Z",
    ...overrides,
  };
}

function LocationDisplay() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/brands/brd_1/ads/month"]}>
      <MonthReviewPage brandId="brd_1" />
      <LocationDisplay />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockListCampaigns.mockResolvedValue([campaignCard()]);
  mockGetTriage.mockResolvedValue(triage([triageItem()]));
  mockGetMonthlyBudget.mockResolvedValue(monthlyBudget());
  mockGetMonthSummary.mockResolvedValue(monthSummary());
  mockDismissSuggestion.mockResolvedValue({ ok: true });
  mockGetAdsLearnings.mockResolvedValue([adsLearning()]);
});

describe("MonthReviewPage（F27-I19）全品牌花費卡", () => {
  it("正常狀態：`total_spend`／`budget.amount` 都有值時畫量尺", async () => {
    renderPage();
    expect(await screen.findByText("TWD 22,000")).toBeTruthy();
    expect(screen.getByText("月總額 TWD 60,000")).toBeTruthy();
  });

  it("`budget.amount===null`：印「月總額 尚未設定」", async () => {
    mockGetMonthlyBudget.mockResolvedValue(monthlyBudget({ amount: null }));
    renderPage();
    expect(await screen.findByText("月總額 尚未設定")).toBeTruthy();
    expect(screen.getByText("TWD 22,000")).toBeTruthy();
  });

  it("`total_spend===null`：印「花費未核實」，沒有量尺", async () => {
    mockGetMonthSummary.mockResolvedValue(monthSummary({ total_spend: null }));
    renderPage();
    expect(await screen.findByText("花費未核實")).toBeTruthy();
  });

  it("月選單一起重打月摘要＋月預算，不重打素材／品牌學習", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("TWD 22,000");
    expect(mockGetMonthSummary).toHaveBeenCalledTimes(1);
    expect(mockGetMonthlyBudget).toHaveBeenCalledTimes(1);
    const thisMonth = mockGetMonthSummary.mock.calls[0][1];

    mockGetMonthSummary.mockResolvedValue(monthSummary({ total_spend: 5000 }));
    mockGetMonthlyBudget.mockResolvedValue(monthlyBudget({ amount: null }));
    await user.click(screen.getByRole("button", { name: /月/, pressed: false }));

    await waitFor(() => expect(mockGetMonthSummary).toHaveBeenCalledTimes(2));
    expect(mockGetMonthlyBudget).toHaveBeenCalledTimes(2);
    const lastMonth = mockGetMonthSummary.mock.calls[1][1];
    expect(lastMonth).not.toBe(thisMonth);
    expect(mockListCampaigns).toHaveBeenCalledTimes(1);
    expect(mockGetAdsLearnings).toHaveBeenCalledTimes(1);
  });
});

describe("MonthReviewPage（F27-I19）商城訂單卡", () => {
  it("印本月至今天數、上月淨額、▼ 變化", async () => {
    renderPage();
    expect(await screen.findByText("43,470")).toBeTruthy();
    expect(screen.getByText("▼29%")).toBeTruthy();
    expect(screen.getByText("上月 61,200")).toBeTruthy();
    expect(screen.getByText("本月至今（21 天）")).toBeTruthy();
  });

  it("`orders===null`：整張卡省略", async () => {
    mockGetMonthSummary.mockResolvedValue(monthSummary({ orders: null }));
    renderPage();
    await screen.findByText("TWD 22,000");
    expect(screen.queryByText("商城訂單淨額・品牌整體")).toBeNull();
  });
});

describe("MonthReviewPage（F27-I19／F27-I27）各活動", () => {
  it("`verdict=\"met\"`：達標 chip，量尺畫出來", async () => {
    renderPage();
    expect(await screen.findByText("達標")).toBeTruthy();
    expect(screen.getByText("每次購買成本 412")).toBeTruthy();
    expect(screen.getByText("目標 450")).toBeTruthy();
  });

  it("活動 chip 的家族直接讀 `campaign_objective`，不猜關鍵字", async () => {
    mockGetMonthSummary.mockResolvedValue(monthSummary({
      campaigns: [monthCampaignRow({ campaign_objective: "engagement" })],
    }));
    renderPage();
    const heading = await screen.findByText("各活動");
    const chip = heading.parentElement?.querySelector('[data-slot="campaign-chip"]');
    expect(chip?.getAttribute("data-variant")).toBe("engagement");
  });

  it("`campaign_objective` 缺值時退回 `other`，不猜關鍵字", async () => {
    mockGetMonthSummary.mockResolvedValue(monthSummary({
      campaigns: [monthCampaignRow({ campaign_objective: null })],
    }));
    renderPage();
    const heading = await screen.findByText("各活動");
    const chip = heading.parentElement?.querySelector('[data-slot="campaign-chip"]');
    expect(chip?.getAttribute("data-variant")).toBe("other");
  });

  it("`verdict=\"missed\"`：未達標", async () => {
    mockGetMonthSummary.mockResolvedValue(monthSummary({ campaigns: [monthCampaignRow({ verdict: "missed", cost_per_result: 600 })] }));
    renderPage();
    expect(await screen.findByText("未達標")).toBeTruthy();
  });

  it("`verdict=\"unjudged\"`／`target===null`：未判斷，量尺打斜紋、印「尚未設定目標」", async () => {
    mockGetMonthSummary.mockResolvedValue(monthSummary({
      campaigns: [monthCampaignRow({ verdict: "unjudged", target: null, cost_per_result: null })],
    }));
    renderPage();
    expect(await screen.findByText("未判斷")).toBeTruthy();
    expect(screen.getByText("尚未設定目標")).toBeTruthy();
  });

  it("沒有活動時顯示空狀態", async () => {
    mockGetMonthSummary.mockResolvedValue(monthSummary({ campaigns: [] }));
    renderPage();
    expect(await screen.findByText("沒有可回顧的活動")).toBeTruthy();
  });
});

describe("MonthReviewPage（F26-I03）素材", () => {
  it("有效只算划算、還看不出＝還沒分級（F29-I01 一把尺，不看趨勢 class）；無效・已停讀 closed 區塊", async () => {
    mockGetTriage.mockResolvedValue(triage(
      [
        // 趨勢變差但仍在上限內：划算，算有效。
        triageItem({ entity_id: "ad_1", class: "worse", label: "變差", grade: "on_target", grade_label: "划算" }),
        triageItem({ entity_id: "ad_2", class: "stop_loss", label: "停損", grade: "wasted", grade_label: "沒賣出" }),
        triageItem({ entity_id: "ad_3", class: "insufficient", label: "資料不足", reason_code: "below_sample_gate", grade: "insufficient", grade_label: "剛開始、數字還不夠" }),
        triageItem({ entity_id: "ad_4", class: "insufficient", label: "資料不足", reason_code: "result_unknown_days", grade: "insufficient", grade_label: "資料不足" }),
        // 趨勢變好但超過上限：太貴，不算有效。
        triageItem({ entity_id: "ad_5", class: "better", label: "變好", grade: "over", grade_label: "太貴" }),
        triageItem({ entity_id: "ad_6", class: "flat", label: "持平", grade: "watch", grade_label: "偏貴" }),
      ],
      { paused: 2, archived: 1, other: 0, total: 3, truncated: false, items: [
        closedItem({ entity_id: "closed_1", native_status: "PAUSED" }),
        closedItem({ entity_id: "closed_2", native_status: "PAUSED" }),
        closedItem({ entity_id: "closed_3", native_status: "ARCHIVED" }),
      ] },
    ));
    renderPage();
    await screen.findByText("素材");
    expect(screen.getByText("有效")).toBeTruthy();
    expect(screen.getByText("無效・已停")).toBeTruthy();
    expect(screen.getByText("還看不出")).toBeTruthy();
    expect(screen.getByText("1 則")).toBeTruthy();
    expect(screen.getByText("3 則")).toBeTruthy();
    expect(screen.getByText("2 則")).toBeTruthy();
  });

  it("同一組超過 12 則時最多畫 12 張縮圖，其餘摺成「＋N 則」", async () => {
    mockGetTriage.mockResolvedValue(triage(
      Array.from({ length: 13 }, (_, i) => triageItem({ entity_id: `ad_${i}`, class: "better" })),
    ));
    renderPage();
    await screen.findByText("素材");
    expect(screen.getByText("13 則")).toBeTruthy();
    expect(screen.getAllByTestId("material-thumb").length).toBe(12);
    expect(screen.getByText("＋1 則")).toBeTruthy();
  });

  it("讀取失敗時可重新讀取，不拖累已經畫好的月摘要區塊", async () => {
    mockListCampaigns.mockRejectedValue(new Error("讀取失敗，請稍後再試。"));
    renderPage();
    await screen.findByText("TWD 22,000");
    expect(await screen.findByText("讀取失敗，請稍後再試。")).toBeTruthy();
  });
});

describe("MonthReviewPage（F27-I19）這個月關掉", () => {
  it("`closed_this_month !== null`：LearnCard 印「這個月關掉 N 則」", async () => {
    renderPage();
    expect(await screen.findByText("這個月關掉 2 則")).toBeTruthy();
  });

  it("`closed_this_month === null`：灰字印「關閉時間從 <since> 起記錄」", async () => {
    mockGetMonthSummary.mockResolvedValue(monthSummary({ closed_this_month: null, closed_tracking_since: "2026-09-22" }));
    renderPage();
    expect(await screen.findByText("關閉時間從 2026/9/22 起記錄")).toBeTruthy();
  });
});

describe("MonthReviewPage（F27-I19／F27-I27）記入品牌學習", () => {
  it("印 📒 文字、N 次同方向、信心 chip；活動 chip 的家族直接讀 `campaign_objective`", async () => {
    renderPage();
    expect(await screen.findByText("「日常出發」生活情境對廣泛受眾有效")).toBeTruthy();
    expect(screen.getByText("2 次同方向")).toBeTruthy();
    expect(screen.getByText("可能成立")).toBeTruthy();
    // F27-I27: no `listCampaigns` lookup involved -- the chip's family comes straight off
    // `learning.campaign_objective` ("sales" from the fixture), never a keyword guess, and (with
    // no raw objective text in Contract D's own response) never a `・<objective>` suffix either.
    const row = screen.getByText("2 次同方向").closest("div");
    const chip = row?.querySelector('[data-slot="campaign-chip"][data-variant="sales"]');
    expect(chip).toBeTruthy();
    expect(chip?.textContent).toContain("日常商品推廣");
    expect(chip?.textContent).not.toContain("・");
  });

  it("`confidence` 三種都印對應中文", async () => {
    mockGetAdsLearnings.mockResolvedValue([
      adsLearning({ id: "l1", confidence: "observed" }),
      adsLearning({ id: "l2", confidence: "validated", text: "第二筆" }),
    ]);
    renderPage();
    expect(await screen.findByText("觀察到")).toBeTruthy();
    expect(screen.getByText("成立")).toBeTruthy();
  });

  it("`campaign_objective` 是 `null`（活動本身查不到）時退回純文字，不硬造家族", async () => {
    mockGetAdsLearnings.mockResolvedValue([
      adsLearning({ campaign_id: "cmp_unknown", campaign_name: "未知活動", campaign_objective: null }),
    ]);
    renderPage();
    expect(await screen.findByText("未知活動")).toBeTruthy();
  });

  it("沒有紀錄時印「還沒有記錄。」", async () => {
    mockGetAdsLearnings.mockResolvedValue([]);
    renderPage();
    expect(await screen.findByText("還沒有記錄。")).toBeTruthy();
  });

  it("讀取失敗時可重新讀取", async () => {
    mockGetAdsLearnings.mockRejectedValue(new Error("讀取失敗，請稍後再試。"));
    renderPage();
    await screen.findByText("記入品牌學習");
    expect(await screen.findByText("讀取失敗，請稍後再試。")).toBeTruthy();
  });
});

describe("MonthReviewPage（F27-I19）✦ 下月建議", () => {
  it("採用導去 action_url", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "採用" }));
    await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/detail"));
  });

  it("`action_url===null` 時採用按鈕停用", async () => {
    mockGetMonthSummary.mockResolvedValue(monthSummary({ suggestions: [monthSuggestion({ action_url: null })] }));
    renderPage();
    const adopt = await screen.findByRole("button", { name: "採用" }) as HTMLButtonElement;
    expect(adopt.disabled).toBe(true);
  });

  it("略過呼叫 dismissSuggestion 成功後從清單移掉這張卡", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("🖼 補 3 則新素材");
    await user.click(screen.getByRole("button", { name: "略過" }));
    await waitFor(() => expect(mockDismissSuggestion).toHaveBeenCalledWith("brd_1", "2026-09", "refresh:cmp_1"));
    await waitFor(() => expect(screen.queryByText("🖼 補 3 則新素材")).toBeNull());
  });

  it("沒有建議時印一行說明", async () => {
    mockGetMonthSummary.mockResolvedValue(monthSummary({ suggestions: [] }));
    renderPage();
    expect(await screen.findByText("這個月沒有下月建議。")).toBeTruthy();
  });
});

describe("MonthReviewPage（F27-I19）讀取失敗", () => {
  it("月摘要讀取失敗時可重新讀取", async () => {
    mockGetMonthSummary.mockRejectedValue(new Error("讀取失敗，請稍後再試。"));
    renderPage();
    expect(await screen.findByText("讀取失敗，請稍後再試。")).toBeTruthy();
  });
});
