/** frontend/src/components/ads/AdsHomePage.test.tsx — F19-I02：v7 首頁版面重寫，取代 F04-I09
 * 的舊版判斷帶／時間軸／建檔檢查表斷言（issue 授權）。首頁只負責讀 `refreshQueue`（header 件數
 * ＋ `DecisionQueue`），`CampaignCards`／`BudgetCard`／`ChangeAttention` 各自打自己的 API——
 * review repair (b)：一塊讀取失敗不拖累另外兩塊，這裡驗證三塊真的互相獨立。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CampaignCard } from "@/lib/adsApi";
import { listCampaigns } from "@/lib/adsApi";
import type { QueuePayload, TriageItem } from "@/lib/adsTriageApi";
import { refreshQueue } from "@/lib/adsTriageApi";
import { getChangeControlSummary, getMonthlyBudget, type MonthlyBudget } from "@/lib/adsChangeApi";
import { AdsHomePage } from "./AdsHomePage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, listCampaigns: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, refreshQueue: vi.fn() };
});
vi.mock("@/lib/adsChangeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsChangeApi")>("@/lib/adsChangeApi");
  return { ...actual, getChangeControlSummary: vi.fn(), getMonthlyBudget: vi.fn() };
});

function unknownBudget(overrides: Partial<MonthlyBudget> = {}): MonthlyBudget {
  return {
    month: "2026-09", currency: "TWD", amount: null, revision: 0,
    known_spend: null, ongoing_estimate: null, reserved_increases: 0,
    available: null, uncertainties: ["待補資料"], can_increase: false,
    period_end: "2026-09-30", confirmed_at: null, notice: "餘額未知",
    ...overrides,
  };
}

function triageItem(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "ad_1", native_id: "native_1", name: "晨光隨行杯・日常出發", campaign_id: "cmp_1",
    campaign_name: "晨光隨行杯上市",
    class: "stop_loss", label: "停損", reason_code: "spend_over_stop_loss",
    window: { start: "2026-09-01", end: "2026-09-07", days: 7, previous_start: "2026-08-25", previous_end: "2026-08-31", extended_from: null },
    target: { value: 450, basis: "break_even", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 5200, result_count: 0, cost_per_result: null, result_kind: "purchase", result_label: "購買", derived_zero_days: 7, reason: null },
    previous: { spend: 4900, result_count: 15, cost_per_result: 326.7, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: null, sample: { gate: true, spend_multiple: 3.2, days_with_events: 7 },
    ...overrides,
  };
}

function queueItem(id: string, overrides: Partial<TriageItem> = {}) {
  return {
    id, org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: `k_${id}`,
    category: "ads_triage_stop_loss", kind: null, severity: "rule_warning" as const,
    message: `廣告「${overrides.name ?? "晨光隨行杯・日常出發"}」停損，待決定`,
    action_url: `/brands/brd_1/ads/campaigns/cmp_1?tab=performance`, visible_from: null,
    status: "open", created_at: "2026-09-19T00:00:00Z", resolved_at: null,
    triage: triageItem(overrides),
  };
}

function queue(overrides: Partial<QueuePayload> = {}): QueuePayload {
  return {
    items: [], counts: { stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 },
    total_ads: 0, kinds_available: ["stop_loss", "worse"], kinds_pending: ["scale_budget", "refresh_creative"],
    ...overrides,
  };
}

function campaignCard(overrides: Partial<CampaignCard> = {}): CampaignCard {
  return {
    id: "cmp_1", name: "測試 Campaign", status: "live",
    start_date: "2026-01-01", end_date: "2026-01-31", objective: "conversion",
    created_at: "2026-01-01T00:00:00Z", created_by: null,
    budget_planned: null, budget_total: null,
    budget_progress: { spent: null, total: null, pct: null },
    judgment: { tone: "neutral", text: "投放中", detail: "還沒有花費資料" },
    outcome: { spend: 0, purchases: 0, revenue: 0 },
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AdsHomePage brandId="brd_1" />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  // 重置每個 mock 的呼叫紀錄，讓「refreshQueue 每次掛載只呼叫一次」這類斷言不受測試順序影響。
  vi.clearAllMocks();
  vi.mocked(getChangeControlSummary).mockResolvedValue({ pending_count: 0, items: [], truncated: false });
  vi.mocked(getMonthlyBudget).mockResolvedValue(unknownBudget());
  vi.mocked(listCampaigns).mockResolvedValue([]);
});

describe("AdsHomePage（F19-I02，v7 首頁版面）", () => {
  it("header 件數：多件時印出「N 件」（含 refreshQueue 每次掛載只呼叫一次）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(
      queue({ items: [queueItem("q1"), queueItem("q2", { name: "晨光隨行杯・辦公室一角" }), queueItem("q3", { name: "晨光隨行杯・隨時有你" })] }),
    );

    renderPage();

    expect(await screen.findByText("3 件・由上往下處理就好")).toBeTruthy();
    expect(vi.mocked(refreshQueue).mock.calls.length).toBe(1);
  });

  it("空佇列：header 印「都處理完了」（誠實空狀態句由 DecisionQueue 的佔位列自己扛，這支只管頁首）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());

    renderPage();

    expect(await screen.findByText("都處理完了")).toBeTruthy();
  });

  it("佇列列真的照 payload 渲染（分類、名稱、連結）——列的細節斷言在 DecisionQueue.test.tsx，這支只驗頁面接得到資料", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue({ items: [queueItem("q1")] }));

    renderPage();

    expect(await screen.findByText("晨光隨行杯・日常出發")).toBeTruthy();
    expect(screen.getByText("停損")).toBeTruthy();
    expect(screen.getByRole("link", { name: "看證據" })).toBeTruthy();
  });

  it("佇列列沒有 action_url：不給連結（不落回 /brands//ads）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(
      queue({ items: [{ ...queueItem("q1"), action_url: null }] }),
    );

    renderPage();

    expect(await screen.findByText("晨光隨行杯・日常出發")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "看證據" })).toBeNull();
  });

  it("每月回顧是非互動的灰階佔位，不是按鈕", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());

    renderPage();

    expect(await screen.findByText("每月回顧・接上後開放")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /每月回顧/ })).toBeNull();
  });

  it("月預算未知：金額顯示「尚待確認」（逐欄核對，不用籠統的 no-0 regex）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());
    vi.mocked(getMonthlyBudget).mockResolvedValue(unknownBudget());

    renderPage();

    const region = await screen.findByRole("region", { name: "本月可新增承諾" });
    await waitFor(() => expect(region.textContent).toContain("尚待確認"));
    expect(region.textContent).toContain("已花 尚待確認");
    expect(region.textContent).toContain("預留 尚待確認");
    expect(region.textContent).toContain("可用 尚待確認");
  });

  it("月預算已知：分段長條可見（不是灰色佔位條）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());
    vi.mocked(getMonthlyBudget).mockResolvedValue(
      unknownBudget({ amount: 60000, known_spend: 22000, ongoing_estimate: 28000, available: 10000, can_increase: true }),
    );

    renderPage();

    const region = await screen.findByRole("region", { name: "本月可新增承諾" });
    await waitFor(() => expect(region.textContent).toContain("TWD 10,000"));
    expect(region.textContent).toContain("已花 TWD 22,000");
    expect(region.textContent).toContain("預留 TWD 28,000");
  });

  it("兩個插槽都掛上：佇列列與活動卡同時出現", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue({ items: [queueItem("q1")] }));
    vi.mocked(listCampaigns).mockResolvedValue([campaignCard()]);

    renderPage();

    expect(await screen.findByText("晨光隨行杯・日常出發")).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "測試 Campaign" })).toBeTruthy();
    expect(screen.getByTestId("campaign-grid")).toBeTruthy();
  });

  it("活動卡只列未結案的 Campaign，已結案的靠「查看全部活動」連結", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCard({ id: "cmp_live", name: "進行中活動" }),
      campaignCard({ id: "cmp_closed", name: "已結案活動", status: "closed" }),
    ]);

    renderPage();

    expect(await screen.findByRole("heading", { name: "進行中活動" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "已結案活動" })).toBeNull();
    expect(screen.getByRole("link", { name: "查看全部活動 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns");
  });

  it("活動卡讀取失敗不拖累佇列卡（三塊各自獨立）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue({ items: [queueItem("q1")] }));
    vi.mocked(listCampaigns).mockRejectedValue(new Error("活動讀取失敗，請稍後再試。"));

    renderPage();

    expect(await screen.findByText("晨光隨行杯・日常出發")).toBeTruthy();
    expect(await screen.findByText("活動讀取失敗，請稍後再試。")).toBeTruthy();
  });

  it("佇列讀取失敗：顯示錯誤與重試，不拖累月預算卡或活動卡；按下重試後恢復", async () => {
    vi.mocked(refreshQueue).mockRejectedValueOnce(new Error("讀取失敗，請稍後再試。"));
    vi.mocked(getMonthlyBudget).mockResolvedValue(unknownBudget({ amount: 60000, known_spend: 1000, ongoing_estimate: 0, available: 59000 }));
    vi.mocked(listCampaigns).mockResolvedValue([campaignCard()]);

    renderPage();

    expect(await screen.findByText("讀取失敗，請稍後再試。")).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "測試 Campaign" })).toBeTruthy();
    expect(await screen.findByRole("region", { name: "本月可新增承諾" })).toBeTruthy();

    const retry = screen.getByRole("button", { name: "重新讀取" });
    vi.mocked(refreshQueue).mockResolvedValue(queue());
    await userEvent.click(retry);

    expect(await screen.findByText("都處理完了")).toBeTruthy();
  });

  it("移除的舊區塊不再出現（判斷帶／時間軸／建檔檢查表）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());

    renderPage();

    await screen.findByText("都處理完了");
    expect(screen.queryByRole("heading", { name: "進行中的活動" })).toBeNull();
    expect(screen.queryByRole("button", { name: "查看歷史操作紀錄" })).toBeNull();
    expect(screen.queryByRole("button", { name: "查看新活動的建檔準備" })).toBeNull();
  });
});
