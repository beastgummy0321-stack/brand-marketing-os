/** frontend/src/components/ads/home/CampaignCards.test.tsx — F19-I04：v7 活動卡（`CampaignCard`）
 * 的三態（正常／尚未設定目標／讀取失敗）、五分類長條圖例只列非零分類、重試、連結目標。
 * `CampaignCards` 自己打 `listCampaigns`，每張卡再各自打 `getTriage`／必要時 `getTarget`
 * （見 `CampaignCard.tsx` 的 ponytail 註解：最多兩支請求）。 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { listCampaigns } from "@/lib/adsApi";
import type { CampaignTarget, CampaignTriage, TriageItem } from "@/lib/adsTriageApi";
import { getTarget, getTriage } from "@/lib/adsTriageApi";
import { CampaignCards } from "./CampaignCards";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, listCampaigns: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, getTriage: vi.fn(), getTarget: vi.fn() };
});

function campaignCardData(overrides: Partial<CampaignCardData> = {}): CampaignCardData {
  return {
    id: "cmp_1", name: "測試 Campaign", status: "live",
    start_date: "2026-01-01", end_date: "2026-01-31", objective: "轉換",
    created_at: "2026-01-01T00:00:00Z", created_by: null,
    budget_planned: null, budget_total: null,
    budget_progress: { spent: null, total: null, pct: null },
    judgment: { tone: "neutral", text: "投放中", detail: "還沒有花費資料" },
    outcome: { spend: 0, purchases: 0, revenue: 0 },
    ...overrides,
  };
}

function triageItem(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "ad_1", native_id: "native_1", name: "廣告 A", campaign_id: "cmp_1",
    class: "stop_loss", label: "停損", reason_code: "spend_over_stop_loss",
    window: { start: "2026-09-01", end: "2026-09-07", days: 7, previous_start: "2026-08-25", previous_end: "2026-08-31", extended_from: null },
    target: { value: 450, basis: "break_even", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 5200, result_count: 0, cost_per_result: null, result_kind: "purchase", result_label: "購買", derived_zero_days: 7, reason: null },
    previous: { spend: 4900, result_count: 15, cost_per_result: 326.7, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: null, sample: { gate: true, spend_multiple: 3.2, days_with_events: 7 },
    ...overrides,
  };
}

function triage(items: TriageItem[]): CampaignTriage {
  return { window_days: 7, items };
}

function campaignTarget(overrides: Partial<CampaignTarget> = {}): CampaignTarget {
  return {
    campaign_id: "cmp_1", product_ids: [], own_value: null, revision: 1,
    value: 450, basis: "break_even", result_kind: "purchase", result_label: "購買",
    result_kinds: [], missing: [],
    ...overrides,
  };
}

function renderCards() {
  return render(
    <MemoryRouter>
      <CampaignCards brandId="brd_1" />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listCampaigns).mockResolvedValue([campaignCardData()]);
});

describe("CampaignCards（F19-I04，v7 活動卡）", () => {
  it("正常態：目標大數字、依據 chip、調整連結到設定目標頁；圖例只列非零分類", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([
      triageItem({ entity_id: "ad_1", class: "stop_loss", label: "停損" }),
      triageItem({ entity_id: "ad_2", class: "better", label: "變好" }),
      triageItem({ entity_id: "ad_3", class: "better", label: "變好" }),
      triageItem({ entity_id: "ad_4", class: "flat", label: "持平" }),
      triageItem({ entity_id: "ad_5", class: "flat", label: "持平" }),
    ]));

    renderCards();

    expect(await screen.findByText("目標每次購買成本")).toBeTruthy();
    expect(screen.getByText("NT$ 450")).toBeTruthy();
    expect(screen.getByText("損益兩平")).toBeTruthy();
    expect(screen.getByText("轉換・5 則")).toBeTruthy();

    const adjust = screen.getByRole("link", { name: "調整" });
    expect(adjust.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/target");

    expect(screen.getByText(/停損 1/)).toBeTruthy();
    expect(screen.getByText(/變好 2/)).toBeTruthy();
    expect(screen.getByText(/持平 2/)).toBeTruthy();
    expect(screen.queryByText(/變差/)).toBeNull();
    expect(screen.queryByText(/資料不足/)).toBeNull();
  });

  it("活動名稱連到 Campaign 工作區", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));

    renderCards();

    const heading = await screen.findByRole("heading", { name: "測試 Campaign" });
    const link = within(heading).getByRole("link", { name: "測試 Campaign" });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1");
  });

  it("尚未設定目標：印「尚未設定」，按鈕連到設定目標頁，missing 印成 chip", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([]));
    vi.mocked(getTarget).mockResolvedValue(campaignTarget({ value: null, basis: null, missing: ["缺廣告花費資料"] }));

    renderCards();

    expect(await screen.findByText("尚未設定")).toBeTruthy();
    expect(screen.getByText("缺廣告花費資料")).toBeTruthy();

    const setup = screen.getByRole("link", { name: "設定目標，才開始判斷" });
    expect(setup.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/target");
    expect(vi.mocked(getTarget).mock.calls.length).toBe(1);
  });

  it("目標已設定但沒有廣告：不畫長條，改印「沒有廣告資料」", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([]));
    vi.mocked(getTarget).mockResolvedValue(campaignTarget({ value: 300, basis: "own", missing: [] }));

    const { container } = renderCards();

    expect(await screen.findByText("沒有廣告資料")).toBeTruthy();
    expect(screen.getByText("自訂")).toBeTruthy();
    expect(container.querySelectorAll(".bg-danger, .bg-warning, .bg-success").length).toBe(0);
  });

  it("讀取失敗：印暫時讀取不到與重新讀取，按下後恢復（只重試這張卡）", async () => {
    vi.mocked(getTriage).mockRejectedValueOnce(new Error("網路錯誤"));

    renderCards();

    expect(await screen.findByText("暫時讀取不到")).toBeTruthy();
    const retry = screen.getByRole("button", { name: "重新讀取「測試 Campaign」" });
    expect(retry.textContent).toBe("重新讀取");

    vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));
    await userEvent.click(retry);

    expect(await screen.findByText("NT$ 450")).toBeTruthy();
    expect(vi.mocked(getTriage).mock.calls.length).toBe(2);
  });

  it("預算 chip：已知印金額，未知印警示 chip「預算待核實」", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCardData({ id: "cmp_known", name: "已知預算", budget_progress: { spent: 1000, total: 5000, pct: 20 } }),
    ]);
    vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));

    renderCards();

    expect(await screen.findByText("NT$ 5,000")).toBeTruthy();
    expect(screen.queryByText("預算待核實")).toBeNull();
  });

  it("預算未知：印警示 chip「預算待核實」", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));

    renderCards();

    expect(await screen.findByText("預算待核實")).toBeTruthy();
  });
});
