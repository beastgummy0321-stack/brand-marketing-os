/** F29-I15: the month review rebuilt to v10 (prototype `month()`, `#/month` and `#/month/8`). Two reads, each
 * mocked and each failing on its own: `getMonthSummary` (Contract C `grades` / `rejected`, suggestions, closed
 * count) and `getHomeOverview` (weekly pace, same-days-last-month trend). Fixtures use real-shaped rows. */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getHomeOverview, type HomeOverview } from "@/lib/adsHomeApi";
import {
  dismissSuggestion, getMonthSummary,
  type MonthGrades, type MonthRejectedCard, type MonthSuggestion, type MonthSummary, type PeriodGradeBucket, type PeriodGradeRow,
} from "@/lib/adsMonthApi";
import type { TriageGrade } from "@/lib/adsTriageApi";
import { downloadCsv, toCsv } from "../patterns";
import { currentBudgetMonth } from "../MonthlyBudgetPanel";
import { MonthReviewPage } from "./MonthReviewPage";
import { seedAdsRules, watchTenths } from "../patterns/rules";
import { RULES_FIXTURE } from "../patterns/rulesFixture";
import { monthCsvName, monthCsvRows, weekBars } from "./monthCsv";
import { shiftMonth } from "@/lib/orgClock";

// F37-I05 (ruling 4c): the page reads the budget month from the org clock (`useWorkspace().identity.org`);
// the timezone is mutable so one case can move the org to UTC+14 without re-mocking the module.
let orgTimezone = "Asia/Taipei";
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "u:o", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: orgTimezone, today: "2026-09-28" }, orgs: [] } }) }));
vi.mock("@/lib/adsMonthApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsMonthApi")>("@/lib/adsMonthApi");
  return { ...actual, getMonthSummary: vi.fn(), dismissSuggestion: vi.fn() };
});
vi.mock("@/lib/adsHomeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsHomeApi")>("@/lib/adsHomeApi");
  return { ...actual, getHomeOverview: vi.fn() };
});
vi.mock("../patterns", async () => {
  const actual = await vi.importActual<typeof import("../patterns")>("../patterns");
  return { ...actual, downloadCsv: vi.fn() };
});

const mockSummary = vi.mocked(getMonthSummary);
const mockHome = vi.mocked(getHomeOverview);
const mockDismiss = vi.mocked(dismissSuggestion);
const mockDownload = vi.mocked(downloadCsv);

const THIS = currentBudgetMonth();
const LAST = shiftMonth(THIS, -1);
const N = Number(THIS.slice(5));
const NEXT = Number(shiftMonth(THIS, 1).slice(5));
const PREV = Number(LAST.slice(5));

function row(overrides: Partial<PeriodGradeRow> = {}): PeriodGradeRow {
  return {
    campaign_id: "cmp_daily", campaign_name: "日常商品推廣", origin: "internal",
    entity_id: "ad_1", name: "1150706 健身情境單圖", group_name: "廣泛受眾",
    thumbnail_url: null, spend: 2400, results: 6, cost_per_result: 400,
    cap: 450, break_even: 520, grade: "on_target", grade_label: "划算", currency: "TWD",
    ...overrides,
  };
}

const ORDER: TriageGrade[] = ["on_target", "watch", "over", "wasted", "insufficient", "no_target"];

/** Buckets the way `period_grades.summarize` builds them: every grade listed, amount null when a spend is unknown. */
function gradesOf(rows: PeriodGradeRow[], overrides: Partial<MonthGrades> = {}): MonthGrades {
  const sum = (list: PeriodGradeRow[]) => (list.some((r) => r.spend === null) ? null : list.reduce((s, r) => s + (r.spend as number), 0));
  const buckets: PeriodGradeBucket[] = ORDER.map((grade) => {
    const members = rows.filter((r) => r.grade === grade);
    return {
      grade, amount: members.length ? sum(members) : 0, count: members.length,
      ads: members.map((r) => ({ entity_id: r.entity_id, name: r.name, thumbnail_url: r.thumbnail_url, spend: r.spend })),
    };
  });
  return { spent: sum(rows), buckets, rows, missing: [], ...overrides };
}

const MIXED_ROWS: PeriodGradeRow[] = [
  row({ entity_id: "ad_ok1", name: "通勤情境單圖", spend: 8000, results: 20, cost_per_result: 400 }),
  row({ entity_id: "ad_ok2", name: "早晨第一口影片", spend: 6300, results: 15, cost_per_result: 420 }),
  row({ entity_id: "ad_watch", name: "提問式貼文", spend: 3120, results: 6, cost_per_result: 520, grade: "watch", grade_label: "偏貴" }),
  row({ entity_id: "ad_over", name: "開箱輪播", spend: 2470, results: 4, cost_per_result: 617.5, grade: "over", grade_label: "太貴" }),
  row({ entity_id: "ad_stop", name: "節慶限定圖", spend: 1480, results: 0, cost_per_result: null, grade: "wasted", grade_label: "沒賣出" }),
  row({ entity_id: "ad_thin", name: "新上的短影音", spend: 630, results: 1, cost_per_result: 630, grade: "insufficient", grade_label: "剛開始、數字還不夠" }),
];

function suggestion(overrides: Partial<MonthSuggestion> = {}): MonthSuggestion {
  return {
    key: "refresh:cmp_daily", kind: "refresh", campaign_id: "cmp_daily", campaign_name: "日常商品推廣",
    objective: "轉換", campaign_objective: "sales", title: "補 2 則新素材", why: "有效的方向只剩 2 則在投",
    action_url: "/brands/brd_bughunt/ads/campaigns/cmp_daily/materials", ...overrides,
  };
}

function rejectedCard(overrides: Partial<MonthRejectedCard> = {}): MonthRejectedCard {
  return {
    change_set_id: "chg_1", campaign_id: "cmp_daily", campaign_name: "日常商品推廣",
    title: "關掉：提問式貼文・早晨第一口是什麼？", at: `${THIS}-05T02:00:00Z`, reason: "想再多看幾天",
    ads: [{ entity_id: "ad_watch", name: "提問式貼文", thumbnail_url: null, was: "watch", now: "over" }],
    ...overrides,
  };
}

function summary(overrides: Partial<MonthSummary> = {}): MonthSummary {
  return {
    month: THIS, currency: "TWD", total_spend: 22000,
    campaigns: [{
      campaign_id: "cmp_daily", name: "日常商品推廣", objective: "轉換", campaign_objective: "sales",
      spend: 22000, result_count: 46, result_label: "購買", cost_per_result: 478, target: 450, verdict: "missed",
    }],
    orders: null, closed_this_month: 6, closed_tracking_since: "2026-06-01",
    suggestions: [suggestion()], days_covered: 30, days_elapsed: 23,
    grades: gradesOf(MIXED_ROWS),
    rejected: { worse: [rejectedCard()], same_count: 2 },
    ...overrides,
  };
}

function days(month: string, daily: number[]): { day: string; cumulative: number | null }[] {
  let total = 0;
  return daily.map((spend, i) => {
    total += spend;
    return { day: `${month}-${String(i + 1).padStart(2, "0")}`, cumulative: total };
  });
}

function home(overrides: Partial<HomeOverview> = {}): HomeOverview {
  return {
    month: THIS, day_of_month: 24, days_in_month: 30, currency: "TWD", spent: 22000,
    money: {
      purchases: 158, cost_per_purchase: 139, cap: null, earn: null, earn_missing: [], excluded: [],
      previous_same_period: { days: 23, purchases: 118, cost_per_purchase: 221 },
    },
    pace: {
      budget_amount: 60000, available: 38000, projected_month_end: 28700,
      // 23 complete days: weeks 1–3 full, week 4 through day 23.
      daily: days(THIS, [...Array(7).fill(600), ...Array(7).fill(900), ...Array(7).fill(1000), 1500, 1700]),
    },
    quality: null, timeline: null, campaigns: null, sync: null,
    ...overrides,
  };
}

function renderPage(url = "/brands/brd_bughunt/ads/month") {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <MonthReviewPage brandId="brd_bughunt" />
    </MemoryRouter>,
  );
}

function bucket(label: string) {
  return screen.getByRole("region", { name: label });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockSummary.mockResolvedValue(summary());
  mockHome.mockResolvedValue(home());
  mockDismiss.mockResolvedValue({ ok: true });
});

describe("MonthReviewPage — current month", () => {
  it("splits the spend by grade and counts only 划算 as 有效", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: `${N} 月回顧` })).toBeTruthy();
    expect(await screen.findByText(`${N} 月已花 22,000 元，分到這幾格`)).toBeTruthy();
    expect(mockSummary).toHaveBeenCalledWith("brd_bughunt", THIS, expect.anything());
    expect(mockHome).toHaveBeenCalledWith("brd_bughunt", THIS, expect.anything());

    const good = bucket("有效（只算划算）");
    expect(within(good).getByText("2 則")).toBeTruthy();
    expect(within(good).getByText("每筆在上限內・花 14,300 元")).toBeTruthy();
    expect(within(bucket("偏貴")).getByText("1 則")).toBeTruthy();
    const bad = bucket("太貴・沒賣出");
    expect(within(bad).getByText("2 則")).toBeTruthy();
    expect(within(bad).getByText(/花 3,950 元/)).toBeTruthy();
    expect(within(bucket("剛開始、數字還不夠")).getByText("1 則")).toBeTruthy();

    expect(screen.getByText("這個月關掉 6 則")).toBeTruthy();
  });

  it("draws the weekly spend against the budget pace, with the unfinished weeks marked", async () => {
    renderPage();
    const weekly = await screen.findByRole("region", { name: "每週花費 vs 預算步調" });
    expect(within(weekly).getByText("月預算 60,000 的步調")).toBeTruthy();
    expect(within(weekly).getByText("已花 22,000")).toBeTruthy();
    expect(within(weekly).getByText("4,200")).toBeTruthy(); // 7 × 600
    expect(within(weekly).getByText("3,200")).toBeTruthy(); // week 4 through day 23
    expect(within(weekly).getByText(`到 ${THIS.slice(5)}/23`)).toBeTruthy();
    expect(within(weekly).getByText("還沒到")).toBeTruthy();
  });

  it("says where the missing days are and that they do not count", async () => {
    mockSummary.mockResolvedValue(summary({
      grades: gradesOf(MIXED_ROWS, { missing: [{ campaign_id: "cmp_mid", name: "中秋限定活動", missing_days: [`${THIS}-17`, `${THIS}-18`] }] }),
    }));
    renderPage();
    const m = THIS.slice(5);
    expect(await screen.findByText(`中秋限定活動缺 ${m}/17、${m}/18 兩天資料，這兩天不計；其他天照常算`)).toBeTruthy();
  });

  it("uses the flow verbs on suggestions, and 先不要 dismisses one for the month", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByRole("heading", { name: `${NEXT} 月建議` })).toBeTruthy();
    const card = screen.getByRole("region", { name: "補 2 則新素材" });
    expect(within(card).getByRole("link", { name: "看提議（核准或拒絕）→" }).getAttribute("href")).toBe("/brands/brd_bughunt/ads/campaigns/cmp_daily/materials");
    await user.click(within(card).getByRole("button", { name: "先不要" }));
    expect(mockDismiss).toHaveBeenCalledWith("brd_bughunt", THIS, "refresh:cmp_daily");
    await waitFor(() => expect(screen.queryByRole("region", { name: "補 2 則新素材" })).toBeNull());
  });

  it("F46 next_plan: the card's button reads 用這些學習排下一期 → to the create page; other kinds keep 看提議; 先不要 works the same", async () => {
    const user = userEvent.setup();
    const next = suggestion({
      key: "next_plan:adc_B", kind: "next_plan", campaign_id: "adc_B", campaign_name: "三盒組・09/19～10/01",
      objective: "購買", title: "用「三盒組・09/19～10/01」學到的排下一期",
      why: "留下 2 則（最好的「考前一週・書包一盒」每筆 555）、換掉 1 則", action_url: "/brands/brd_bughunt/ads/new?sell_way=prd_box",
    });
    mockSummary.mockResolvedValue(summary({ suggestions: [suggestion(), next] }));
    renderPage();
    const card = await screen.findByRole("region", { name: "用「三盒組・09/19～10/01」學到的排下一期" });
    expect(within(card).getByText("留下 2 則（最好的「考前一週・書包一盒」每筆 555）、換掉 1 則")).toBeTruthy();
    expect(within(card).getByRole("link", { name: "用這些學習排下一期 →" }).getAttribute("href")).toBe("/brands/brd_bughunt/ads/new?sell_way=prd_box");
    expect(within(card).queryByText("看提議（核准或拒絕）→")).toBeNull();
    expect(within(screen.getByRole("region", { name: "補 2 則新素材" })).getByRole("link", { name: "看提議（核准或拒絕）→" })).toBeTruthy();
    await user.click(within(card).getByRole("button", { name: "先不要" }));
    expect(mockDismiss).toHaveBeenCalledWith("brd_bughunt", THIS, "next_plan:adc_B");
    await waitFor(() => expect(screen.queryByRole("region", { name: "用「三盒組・09/19～10/01」學到的排下一期" })).toBeNull());
  });

  it("brings a rejected cleanup back only when it got worse, and counts the rest in the footnote", async () => {
    const user = userEvent.setup();
    renderPage();
    const card = await screen.findByRole("region", { name: "關掉：提問式貼文・早晨第一口是什麼？" });
    expect(within(card).getByText("上次你拒絕時是偏貴，現在變太貴")).toBeTruthy();
    expect(within(card).getByText(`${THIS.slice(5)}/05 拒絕・原因：想再多看幾天`)).toBeTruthy();
    expect(within(card).getByRole("link", { name: "看提議（核准或拒絕）→" }).getAttribute("href"))
      .toBe("/brands/brd_bughunt/ads/campaigns/cmp_daily/propose/cleanup/cmp_daily");
    expect(screen.getByText("你拒絕過的另外 2 件沒有變差，這裡不再提。")).toBeTruthy();
    expect(screen.getByText(`比 ${PREV} 月同期（只當參考，不影響判斷）：購買多 40 筆・每筆便宜 37%`)).toBeTruthy();

    await user.click(within(card).getByRole("button", { name: "先不要" }));
    expect(mockDismiss).toHaveBeenCalledWith("brd_bughunt", THIS, "cleanup:cmp_daily");
    await waitFor(() => expect(screen.queryByRole("region", { name: "關掉：提問式貼文・早晨第一口是什麼？" })).toBeNull());
  });

  it("a failed 先不要 on a rejected card keeps the card and says so", async () => {
    const user = userEvent.setup();
    mockDismiss.mockRejectedValueOnce(new Error("沒有存到"));
    renderPage();
    const card = await screen.findByRole("region", { name: "關掉：提問式貼文・早晨第一口是什麼？" });
    await user.click(within(card).getByRole("button", { name: "先不要" }));
    expect(await within(card).findByText("沒有存到")).toBeTruthy();
    expect(screen.getByRole("region", { name: "關掉：提問式貼文・早晨第一口是什麼？" })).toBeTruthy();
  });

  it("shows no rejected card or footnote line when every remembered no stayed the same", async () => {
    mockSummary.mockResolvedValue(summary({ rejected: { worse: [], same_count: 0 }, suggestions: [] }));
    mockHome.mockResolvedValue(home({ money: null }));
    renderPage();
    expect(await screen.findByText("這個月沒有要給下個月的建議。")).toBeTruthy();
    expect(screen.queryByText(/上次你拒絕時/)).toBeNull();
    expect(screen.queryByText(/這裡不再提/)).toBeNull();
  });

  it("a month with only thin ads has nothing 有效", async () => {
    const thin = [
      row({ entity_id: "t1", spend: 300, results: 1, grade: "insufficient", grade_label: "剛開始、數字還不夠" }),
      row({ entity_id: "t2", spend: 120, results: 0, cost_per_result: null, grade: "insufficient", grade_label: "剛開始、數字還不夠" }),
    ];
    mockSummary.mockResolvedValue(summary({ grades: gradesOf(thin), rejected: { worse: [], same_count: 0 } }));
    renderPage();
    const good = await screen.findByRole("region", { name: "有效（只算划算）" });
    expect(within(good).getByText("0 則", { selector: "[data-slot=chip]" })).toBeTruthy();
    expect(within(bucket("剛開始、數字還不夠")).getByText("2 則")).toBeTruthy();
    expect(within(bucket("剛開始、數字還不夠")).getByText("還沒花到上限 × 3・花 420 元")).toBeTruthy();
  });

  it("bucket titles and captions are the served grade words and bands (F48 Contract R-API), none written down", async () => {
    renderPage();
    const tenths = watchTenths(RULES_FIXTURE);
    const caption = (title: string) => within(bucket(title)).getByText((_, el) => el?.getAttribute("data-part") === "caption").textContent;
    await screen.findByRole("region", { name: `有效（只算${RULES_FIXTURE.labels.grade.on_target}）` });
    expect(caption(RULES_FIXTURE.labels.grade.watch)).toMatch(new RegExp(`^超過上限 ${tenths} 成內・`));
    expect(caption(`${RULES_FIXTURE.labels.grade.over}・${RULES_FIXTURE.labels.grade.wasted}`)).toMatch(new RegExp(`^超過 ${tenths} 成，或花了錢沒賣出・`));
    expect(caption(RULES_FIXTURE.labels.grade.too_new)).toMatch(new RegExp(`^還沒花到上限 × ${RULES_FIXTURE.grade.unsold_spend_multiple}・`));
  });

  it("a different served ruler changes the captions with no frontend edit", async () => {
    seedAdsRules({ ...RULES_FIXTURE, grade: { ...RULES_FIXTURE.grade, watch_band: 1.3, unsold_spend_multiple: 4 } });
    try {
      renderPage();
      await screen.findByRole("region", { name: "偏貴" });
      expect(within(bucket("偏貴")).getByText(/^超過上限 3 成內/)).toBeTruthy();
      expect(within(bucket("太貴・沒賣出")).getByText(/^超過 3 成，或花了錢沒賣出/)).toBeTruthy();
      expect(within(bucket("剛開始、數字還不夠")).getByText(/^還沒花到上限 × 4/)).toBeTruthy();
    } finally {
      seedAdsRules(RULES_FIXTURE);
    }
  });

  it("mixed currencies: unknown spend reads as unknown, never 0", async () => {
    const mixed = [row({ entity_id: "a", spend: null, currency: null }), row({ entity_id: "b", grade: "watch", grade_label: "偏貴", spend: 900 })];
    mockSummary.mockResolvedValue(summary({ currency: null, total_spend: null, grades: gradesOf(mixed) }));
    mockHome.mockResolvedValue(home({ spent: null, pace: { budget_amount: null, available: null, projected_month_end: null, daily: days(THIS, [1, 1]).map((d) => ({ ...d, cumulative: null })) } }));
    renderPage();
    expect(await screen.findByText(`${N} 月的花費分到這幾格`)).toBeTruthy();
    expect(screen.getByText(/總額未知/)).toBeTruthy();
    expect(within(bucket("有效（只算划算）")).getByText("每筆在上限內・花費未知")).toBeTruthy();
    expect(screen.getByText("已花 未知")).toBeTruthy();
    expect(screen.getByText("沒設月預算，不畫步調")).toBeTruthy();
    expect(screen.getAllByText("未知").length).toBeGreaterThan(0);
    // Only a genuinely empty bucket may read 0; the unknown total and the bucket holding the unknown ad never do.
    expect(screen.queryByText(/已花 0/)).toBeNull();
    expect(within(bucket("有效（只算划算）")).queryByText(/花 0 元/)).toBeNull();
  });
});

describe("MonthReviewPage — past month", () => {
  it("reads the previous month from ?month= and shows its books without next-month suggestions", async () => {
    mockSummary.mockResolvedValue(summary({ month: LAST }));
    mockHome.mockResolvedValue(home({ month: LAST, days_in_month: 31, pace: { budget_amount: 60000, available: 0, projected_month_end: 48500, daily: days(LAST, Array(31).fill(1500)) } }));
    renderPage(`/brands/brd_bughunt/ads/month?month=${LAST}`);
    expect(await screen.findByRole("heading", { level: 1, name: `${PREV} 月回顧` })).toBeTruthy();
    expect(mockSummary).toHaveBeenCalledWith("brd_bughunt", LAST, expect.anything());
    expect(await screen.findByRole("region", { name: "有效（只算划算）" })).toBeTruthy();
    expect(screen.getByText("每筆在上限內")).toBeTruthy();
    expect(screen.queryByText(/分到這幾格/)).toBeNull();
    expect(screen.queryByText(/月建議/)).toBeNull();
    expect(screen.queryByText(/上次你拒絕時/)).toBeNull();
    expect(screen.queryByText("還沒到")).toBeNull();
    expect(screen.getByRole("button", { name: `${PREV} 月` }).getAttribute("aria-pressed")).toBe("true");
  });

  it("the month buttons switch the month", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { level: 1, name: `${N} 月回顧` });
    await user.click(screen.getByRole("button", { name: `${PREV} 月` }));
    expect(await screen.findByRole("heading", { level: 1, name: `${PREV} 月回顧` })).toBeTruthy();
    await waitFor(() => expect(mockSummary).toHaveBeenLastCalledWith("brd_bughunt", LAST, expect.anything()));
  });
});

describe("MonthReviewPage — org clock", () => {
  // 2026-02-28 10:30Z: Kiritimati (UTC+14) is already 2026-03-01 00:30, while UTC and the test runner zone
  // (Asia/Taipei, 18:30) are still on 2026-02-28. Only `Date` is faked so timers stay real.
  beforeEach(() => { orgTimezone = "Pacific/Kiritimati"; vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-02-28T10:30:00Z")); });
  afterEach(() => { vi.useRealTimers(); orgTimezone = "Asia/Taipei"; });

  it("opens on the organisation's month, not the browser's or Taipei's", async () => {
    mockSummary.mockResolvedValue(summary({ month: "2026-03" }));
    mockHome.mockResolvedValue(home({ month: "2026-03", day_of_month: 1, days_in_month: 31, pace: { budget_amount: 60000, available: 60000, projected_month_end: 0, daily: [] } }));
    renderPage();
    expect(await screen.findByRole("heading", { level: 1, name: "3 月回顧" })).toBeTruthy();
    expect(mockSummary).toHaveBeenCalledWith("brd_bughunt", "2026-03", expect.anything());
    expect(mockHome).toHaveBeenCalledWith("brd_bughunt", "2026-03", expect.anything());
    expect(screen.getByRole("button", { name: "2 月" })).toBeTruthy();
  });
});

describe("MonthReviewPage — read failures", () => {
  it("a failed month summary is its own state, not an empty month; the weekly spend still shows", async () => {
    mockSummary.mockRejectedValueOnce(new Error("伺服器忙碌"));
    renderPage();
    expect(await screen.findByText(/這個月的分級與建議讀不到/)).toBeTruthy();
    expect(screen.queryByText("0 則")).toBeNull();
    expect(await screen.findByRole("region", { name: "每週花費 vs 預算步調" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "下載 CSV" }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.setup().click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText(`${N} 月已花 22,000 元，分到這幾格`)).toBeTruthy();
  });

  it("a failed weekly read fails alone; the grades still show", async () => {
    mockHome.mockRejectedValue(new Error("逾時"));
    renderPage();
    expect(await screen.findByText(/每週花費讀不到/)).toBeTruthy();
    expect(await screen.findByText(`${N} 月已花 22,000 元，分到這幾格`)).toBeTruthy();
    expect(screen.queryByText(/同期/)).toBeNull();
  });
});

describe("month CSV", () => {
  it("writes one line per ad from grades.rows, unknown numbers as empty cells", async () => {
    const rows = [...MIXED_ROWS, row({ entity_id: "u", name: "跨幣別,廣告", spend: null, results: null, cost_per_result: null, cap: null, grade: "no_target", grade_label: "未判斷" })];
    const csv = toCsv(monthCsvRows(rows));
    const lines = csv.trimEnd().split("\r\n");
    expect(lines[0]).toBe("活動,廣告,花費,購買,每賣一筆,上限,等級");
    expect(lines[1]).toBe("日常商品推廣,通勤情境單圖,8000,20,400,450,划算");
    expect(lines[5]).toBe("日常商品推廣,節慶限定圖,1480,0,,450,沒賣出");
    expect(lines[7]).toBe('日常商品推廣,"跨幣別,廣告",,,,,未判斷');
    expect(lines).toHaveLength(8);
    expect(monthCsvName("2026-08")).toBe("2026-08回顧.csv");
  });

  it("the 下載 CSV button saves the month's rows, a past month included", async () => {
    const user = userEvent.setup();
    mockSummary.mockResolvedValue(summary({ month: LAST }));
    renderPage(`/brands/brd_bughunt/ads/month?month=${LAST}`);
    await screen.findByRole("region", { name: "有效（只算划算）" });
    await user.click(screen.getByRole("button", { name: "下載 CSV" }));
    expect(mockDownload).toHaveBeenCalledWith(`${LAST}回顧.csv`, monthCsvRows(MIXED_ROWS));
  });
});

describe("weekBars", () => {
  it("splits cumulative spend into weeks; a null cumulative makes its week unknown", () => {
    const daily = days("2026-09", [100, 100, 100, 100, 100, 100, 100, 50, 50]);
    const bars = weekBars("2026-09", 30, daily, 30000);
    expect(bars.map((b) => b.label)).toEqual(["09/01–07", "09/08–14", "09/15–21", "09/22–28", "09/29–30"]);
    expect(bars[0]).toMatchObject({ state: "known", spend: 700, pace: 7000, through: null });
    expect(bars[1]).toMatchObject({ state: "known", spend: 100, through: "到 09/09" });
    expect(bars[2]).toMatchObject({ state: "future", spend: null });
    expect(bars[4].pace).toBe(2000);
    const unknown = weekBars("2026-09", 30, daily.map((d, i) => (i === 3 ? { ...d, cumulative: null } : d)), null);
    expect(unknown[0]).toMatchObject({ state: "unknown", spend: null, pace: null });
    expect(unknown[1].state).toBe("known");
  });
});
