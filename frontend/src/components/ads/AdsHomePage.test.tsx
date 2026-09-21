/** frontend/src/components/ads/AdsHomePage.test.tsx — F19-I02：v7 首頁版面重寫，取代 F04-I09
 * 的舊版判斷帶／時間軸／建檔檢查表斷言（issue 授權）。首頁只負責讀 `refreshQueue`／
 * `listCampaigns` 並把資料原樣交給 `DecisionQueue`／`CampaignCards`／`BudgetCard`，
 * 這裡驗證版面骨架：header 件數、灰階佔位、月預算未知態、兩個插槽都有掛、錯誤＋重試。 */
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
    class: "stop_loss", label: "停損", reason_code: "spend_over_stop_loss",
    window: { start: "2026-09-01", end: "2026-09-07", days: 7, previous_start: "2026-08-25", previous_end: "2026-08-31", extended_from: null },
    target: { value: 450, basis: "break_even", result_kind: "purchase", missing: [] },
    current: { spend: 5200, result_count: 0, cost_per_result: null, result_kind: "purchase", derived_zero_days: 7, reason: null },
    previous: { spend: 4900, result_count: 15, cost_per_result: 326.7, result_kind: "purchase", derived_zero_days: 0, reason: null },
    change_pct: null, sample: { gate: true, spend_multiple: 3.2, days_with_events: 7 },
    ...overrides,
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
  vi.mocked(getChangeControlSummary).mockResolvedValue({ pending_count: 0, items: [], truncated: false });
  vi.mocked(getMonthlyBudget).mockResolvedValue(unknownBudget());
});

describe("AdsHomePage（F19-I02，v7 首頁版面）", () => {
  it("header 件數：有待決定的件數時印出「N 件」，處理完時印「都處理完了」", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(
      queue({ items: [{ id: "q1", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: "k1", category: "ads_triage_stop_loss", kind: null, severity: "rule_warning", message: "廣告「晨光隨行杯・日常出發」停損，待決定", action_url: "/brands/brd_1/ads/campaigns/cmp_1?tab=performance", visible_from: null, status: "open", created_at: "2026-09-19T00:00:00Z", resolved_at: null, triage: triageItem() }] }),
    );
    vi.mocked(listCampaigns).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText("1 件・由上往下處理就好")).toBeTruthy();
  });

  it("空佇列：header 印「都處理完了」，佇列卡印誠實空狀態句", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());
    vi.mocked(listCampaigns).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText("都處理完了")).toBeTruthy();
    expect(await screen.findByText("目前沒有需要你決定的廣告。")).toBeTruthy();
  });

  it("每月回顧是灰階不可點佔位，帶「接上後開放」標記", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());
    vi.mocked(listCampaigns).mockResolvedValue([]);

    renderPage();

    const button = await screen.findByRole("button", { name: "每月回顧，接上後開放" });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText("接上後開放")).toBeTruthy();
  });

  it("月預算未知：金額顯示「尚待確認」，不印假 0", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());
    vi.mocked(listCampaigns).mockResolvedValue([]);
    vi.mocked(getMonthlyBudget).mockResolvedValue(unknownBudget());

    renderPage();

    const region = await screen.findByRole("region", { name: "本月可新增承諾" });
    await waitFor(() => expect(region.textContent).toContain("尚待確認"));
    expect(region.textContent).not.toMatch(/[^0-9]0(?![0-9])/);
  });

  it("兩個插槽都掛上：佇列列與活動卡同時出現", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(
      queue({ items: [{ id: "q1", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: "k1", category: "ads_triage_stop_loss", kind: null, severity: "rule_warning", message: "廣告「晨光隨行杯・日常出發」停損，待決定", action_url: "/brands/brd_1/ads/campaigns/cmp_1?tab=performance", visible_from: null, status: "open", created_at: "2026-09-19T00:00:00Z", resolved_at: null, triage: triageItem() }] }),
    );
    vi.mocked(listCampaigns).mockResolvedValue([campaignCard()]);

    renderPage();

    expect(await screen.findByText("晨光隨行杯・日常出發")).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "測試 Campaign" })).toBeTruthy();
    expect(screen.getByTestId("campaign-grid")).toBeTruthy();
  });

  it("讀取失敗：顯示錯誤與重新載入，按下後恢復正常內容", async () => {
    vi.mocked(refreshQueue).mockRejectedValueOnce(new Error("讀取失敗，請稍後再試。"));
    vi.mocked(listCampaigns).mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText("讀取失敗")).toBeTruthy();
    const retry = screen.getByRole("button", { name: "重新載入" });
    vi.mocked(refreshQueue).mockResolvedValue(queue());
    await userEvent.click(retry);

    expect(await screen.findByText("都處理完了")).toBeTruthy();
  });
});
