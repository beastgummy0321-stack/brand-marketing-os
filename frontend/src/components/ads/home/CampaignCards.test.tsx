/** frontend/src/components/ads/home/CampaignCards.test.tsx — F19-I04：v7 活動卡（`CampaignCard`）
 * 的狀態（正常／有廣告但未設定目標／沒有廣告／讀取失敗）、狀態 pill、預算 chip 標籤、五分類
 * 長條的分母與寬度、`no_target` 另開一顆 chip、重試只影響那一張卡。`CampaignCards` 自己打
 * `listCampaigns`，每張卡再各自打 `getTriage`（見 `CampaignCard.tsx` 的 ponytail 註解）。 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { listCampaigns } from "@/lib/adsApi";
import type { CampaignTriage, TriageItem } from "@/lib/adsTriageApi";
import { getTriage } from "@/lib/adsTriageApi";
import { CampaignCards } from "./CampaignCards";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, listCampaigns: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, getTriage: vi.fn() };
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

function renderCards() {
  return render(
    <MemoryRouter>
      <CampaignCards brandId="brd_1" />
    </MemoryRouter>,
  );
}

/** 每次呼叫 `getTriage` 打的是哪個 campaign（第二個參數）；重試只影響那一張卡的斷言用這個。 */
function callsFor(campaignId: string): number {
  return vi.mocked(getTriage).mock.calls.filter(([, id]) => id === campaignId).length;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listCampaigns).mockResolvedValue([campaignCardData()]);
});

describe("CampaignCards（F19-I04，v7 活動卡）", () => {
  it("正常態：目標是不帶幣別符號的純數字、依據 chip、調整連結、圖例只列非零分類、狀態 pill", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([
      triageItem({ entity_id: "ad_1", class: "stop_loss", label: "停損" }),
      triageItem({ entity_id: "ad_2", class: "better", label: "變好" }),
      triageItem({ entity_id: "ad_3", class: "better", label: "變好" }),
      triageItem({ entity_id: "ad_4", class: "flat", label: "持平" }),
      triageItem({ entity_id: "ad_5", class: "flat", label: "持平" }),
    ]));

    renderCards();

    expect(await screen.findByText("目標每次購買成本")).toBeTruthy();
    // 純數字，沒有 NT$（後端不回幣別，formatCurrency 的 NT$ 是錯的標籤）。
    expect(screen.getByText("450", { exact: true })).toBeTruthy();
    expect(screen.queryByText(/NT\$/)).toBeNull();
    expect(screen.getByText("損益兩平")).toBeTruthy();
    expect(screen.getByText("轉換・5 則")).toBeTruthy();
    expect(screen.getByText("投放中")).toBeTruthy(); // STATUS_LABEL.live

    const adjust = screen.getByRole("link", { name: "調整" });
    expect(adjust.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/target");

    expect(screen.getByText(/停損 1/)).toBeTruthy();
    expect(screen.getByText(/變好 2/)).toBeTruthy();
    expect(screen.getByText(/持平 2/)).toBeTruthy();
    expect(screen.queryByText(/變差/)).toBeNull();
    expect(screen.queryByText(/資料不足/)).toBeNull();
  });

  it("目標數字可能是算出來的小數（trailing_30＝spend/result_count）：最多兩位小數，不用 Math.round", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([
      triageItem({ target: { value: 5200 / 15, basis: "trailing_30", result_kind: "purchase", result_label: "購買", missing: [] } }),
    ]));

    renderCards();

    expect(await screen.findByText("346.67", { exact: true })).toBeTruthy();
    expect(screen.queryByText("347")).toBeNull();
    expect(screen.getByText("近 30 天")).toBeTruthy();
  });

  it("五分類長條：寬度＝該分類則數／已判斷則數（1/2/1/1/0 of 5 → 20/40/20/20/0%）", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([
      triageItem({ entity_id: "ad_1", class: "stop_loss" }),
      triageItem({ entity_id: "ad_2", class: "worse" }),
      triageItem({ entity_id: "ad_3", class: "worse" }),
      triageItem({ entity_id: "ad_4", class: "better" }),
      triageItem({ entity_id: "ad_5", class: "flat" }),
    ]));

    const { container } = renderCards();
    await screen.findByText("目標每次購買成本");

    const width = (cls: string) => (container.querySelector(`[data-segment="${cls}"]`) as HTMLElement).style.width;
    expect(width("stop_loss")).toBe("20%");
    expect(width("worse")).toBe("40%");
    expect(width("better")).toBe("20%");
    expect(width("flat")).toBe("20%");
    expect(width("insufficient")).toBe("0%");
  });

  it("有目標但部分則 no_target：長條分母排除它們，另外印「N 則無法判斷」", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([
      triageItem({ entity_id: "ad_1", class: "better" }),
      triageItem({ entity_id: "ad_2", class: "flat" }),
      triageItem({ entity_id: "ad_3", class: "no_target" }),
      triageItem({ entity_id: "ad_4", class: "no_target" }),
    ]));

    const { container } = renderCards();
    await screen.findByText("目標每次購買成本");

    expect(screen.getByText("2 則無法判斷")).toBeTruthy();
    expect(screen.getByText("轉換・4 則")).toBeTruthy(); // header 的「N 則」仍是總則數
    const width = (cls: string) => (container.querySelector(`[data-segment="${cls}"]`) as HTMLElement).style.width;
    expect(width("better")).toBe("50%"); // 分母排除 no_target：2 則已判斷，各占一半
    expect(width("flat")).toBe("50%");
  });

  it("活動名稱連到 Campaign 工作區，帶著可點擊的「›」但可及名稱與 e2e 文字比對仍是純名稱", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));

    renderCards();

    const heading = await screen.findByRole("heading", { name: "測試 Campaign" });
    const link = within(heading).getByRole("link", { name: "測試 Campaign" });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1");
    expect(screen.getByText("測試 Campaign", { exact: true })).toBeTruthy();
  });

  it("超長活動名稱：「›」不被 truncate 擠掉，連結可及名稱仍是完整名稱", async () => {
    const longName = "2026 秋季新品啟動・晨光隨行杯 X 在地烘豆師聯名限定款・全通路整合行銷總覽計畫(電商站內+社群廣告+聯盟導流三線並行)";
    vi.mocked(listCampaigns).mockResolvedValue([campaignCardData({ name: longName })]);
    vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));

    renderCards();

    const heading = await screen.findByRole("heading", { name: longName });
    const link = within(heading).getByRole("link", { name: longName });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1");
    // 「›」永遠在（shrink-0），只有名稱那格 truncate；用 title 存住完整名稱。
    expect(within(link).getByText("›", { exact: true })).toBeTruthy();
    expect(within(link).getByText(longName, { exact: true }).getAttribute("title")).toBe(longName);
  });

  it("有廣告但未設定目標：印「尚未設定」，次要按鈕（outline，非主按鈕）連到設定目標頁，missing 印成 chip", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([
      triageItem({ target: { value: null, basis: null, result_kind: null, result_label: "購買", missing: ["缺廣告花費資料"] } }),
    ]));

    renderCards();

    expect(await screen.findByText("尚未設定")).toBeTruthy();
    expect(screen.getByText("缺廣告花費資料")).toBeTruthy();

    const setup = screen.getByRole("link", { name: "設定目標，才開始判斷" });
    expect(setup.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/target");
    expect(setup.getAttribute("data-variant")).toBe("outline"); // 不是頁面的主按鈕
  });

  it("沒有廣告（草稿／待發布／剛同步）：不催設定目標，只給進入活動的安靜連結", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([]));

    renderCards();

    expect(await screen.findByText("沒有廣告資料")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "設定目標，才開始判斷" })).toBeNull();
    expect(screen.queryByText("尚未設定")).toBeNull();

    const enter = screen.getByRole("link", { name: /進入活動/ });
    expect(enter.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1");
  });

  it("讀取失敗：暫時讀取不到＋「已保存的紀錄都還在」＋預算 chip 仍在；重新讀取只影響這張卡", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCardData({ id: "cmp_a", name: "活動 A", budget_progress: { spent: 1000, total: 5000, pct: 20 } }),
      campaignCardData({ id: "cmp_b", name: "活動 B" }),
    ]);
    vi.mocked(getTriage).mockImplementation((_brand, campaignId) =>
      campaignId === "cmp_a" ? Promise.reject(new Error("網路錯誤")) : Promise.resolve(triage([triageItem({ campaign_id: "cmp_b" })])));

    renderCards();

    expect(await screen.findByText("暫時讀取不到")).toBeTruthy();
    expect(screen.getByText("已保存的紀錄都還在")).toBeTruthy();
    expect(screen.getByText("總預算 NT$ 5,000")).toBeTruthy(); // 預算來自清單，讀取失敗也看得到
    await screen.findByText("450", { exact: true }); // 活動 B 正常顯示，不受 A 失敗拖累

    expect(callsFor("cmp_a")).toBe(1);
    expect(callsFor("cmp_b")).toBe(1);

    const retry = screen.getByRole("button", { name: "重新讀取「活動 A」" });
    vi.mocked(getTriage).mockImplementation((_brand, campaignId) =>
      campaignId === "cmp_a" ? Promise.resolve(triage([triageItem({ campaign_id: "cmp_a" })])) : Promise.resolve(triage([triageItem({ campaign_id: "cmp_b" })])));
    await userEvent.click(retry);

    await screen.findAllByText("450", { exact: true });
    expect(callsFor("cmp_a")).toBe(2); // 這張卡重打了一次
    expect(callsFor("cmp_b")).toBe(1); // 另一張卡完全沒被影響
  });

  it("狀態 pill：一般 Campaign 印狀態文字；匯入的平台活動改印「平台活動」（不論狀態）", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCardData({ id: "cmp_draft", name: "草稿活動", status: "draft" }),
      campaignCardData({ id: "cmp_ext", name: "匯入活動", status: "live", origin: "imported" }),
    ]);
    vi.mocked(getTriage).mockResolvedValue(triage([]));

    renderCards();

    expect(await screen.findByText("草稿")).toBeTruthy(); // STATUS_LABEL.draft
    expect(screen.getByText("平台活動")).toBeTruthy();
    expect(screen.queryByText("投放中")).toBeNull(); // 匯入活動不印它原本的 status（live）
  });

  it("預算 chip：站內已知印「總預算 金額」，未知印警示 chip，匯入的一律印「平台預算」", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCardData({ id: "cmp_known", name: "已知預算", budget_progress: { spent: 1000, total: 5000, pct: 20 } }),
      campaignCardData({ id: "cmp_unknown", name: "未知預算" }),
      campaignCardData({ id: "cmp_ext", name: "匯入活動", origin: "imported", budget_progress: { spent: 1000, total: 9000, pct: 11 } }),
    ]);
    vi.mocked(getTriage).mockResolvedValue(triage([]));

    renderCards();

    expect(await screen.findByText("總預算 NT$ 5,000")).toBeTruthy();
    expect(screen.getByText("預算待核實")).toBeTruthy();
    expect(screen.getByText("平台預算")).toBeTruthy();
    expect(screen.queryByText("總預算 NT$ 9,000")).toBeNull(); // 匯入活動不假裝讀得到站內總預算
  });
});
