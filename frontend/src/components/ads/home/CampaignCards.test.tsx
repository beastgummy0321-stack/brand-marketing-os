/** frontend/src/components/ads/home/CampaignCards.test.tsx — F19-I04：v7 活動卡（`CampaignCard`）
 * 的狀態（正常／有廣告但未設定目標／沒有廣告／讀取失敗）、狀態 pill、預算 chip 標籤、五分類
 * 長條的分母與寬度、`no_target` 另開一顆 chip、重試只影響那一張卡。`CampaignCards` 自己打
 * `listCampaigns`，每張卡再各自打 `getTriage`（見 `CampaignCard.tsx` 的 ponytail 註解）。 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { listCampaigns } from "@/lib/adsApi";
import type { CampaignTriage, TriageClosedBlock, TriageData, TriageItem } from "@/lib/adsTriageApi";
import { getTriage } from "@/lib/adsTriageApi";
import { syncCampaign, syncJob } from "@/lib/adsExternalApi";
import { CampaignCards } from "./CampaignCards";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, listCampaigns: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, getTriage: vi.fn() };
});
vi.mock("@/lib/adsExternalApi", () => ({ syncCampaign: vi.fn(), syncJob: vi.fn() }));

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
    entity_id: "ad_1", native_id: "native_1", name: "廣告 A", campaign_id: "cmp_1", campaign_name: "活動一", thumbnail_url: null,
    class: "stop_loss", label: "停損", reason_code: "spend_over_stop_loss",
    window: { start: "2026-09-01", end: "2026-09-07", days: 7, previous_start: "2026-08-25", previous_end: "2026-08-31", extended_from: null },
    target: { value: 450, basis: "break_even", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 5200, result_count: 0, cost_per_result: null, result_kind: "purchase", result_label: "購買", derived_zero_days: 7, reason: null },
    previous: { spend: 4900, result_count: 15, cost_per_result: 326.7, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: null, sample: { gate: true, spend_multiple: 3.2, days_with_events: 7 },
    ...overrides,
  };
}

// F26-I01: `closed` is always sent by the real backend -- an empty block for every test here
// unless a scenario overrides it directly (F26-I02's own 「另有 N 則已關閉」 line describe block
// below passes a real one).
const EMPTY_CLOSED: TriageClosedBlock = {
  paused: 0, archived: 0, other: 0, total: 0, items: [], truncated: false,
};

function triage(items: TriageItem[], data?: TriageData, closed: TriageClosedBlock = EMPTY_CLOSED): CampaignTriage {
  return { window_days: 7, items, closed, data };
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

/** RTL 的 `getByText` 預設只比對一個節點「自己的」文字節點（`getNodeText`：只收直接子文字
 * 節點，略過子元素），不是整個 `textContent`——這頁有幾處把一段文字的一部分包進巢狀
 * `<span>`/`<b>` 加粗（例如「・<b>投放中 N 則</b>」），要用完整 `textContent` 比對才找得到。 */
function textOf(expected: string) {
  return (_content: string, node: Element | null) => node?.textContent === expected;
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
    expect(screen.getByText("暫用打平")).toBeTruthy();
    // F26-I02: the count chip now reads 「・投放中 N 則」 (`state.items` is active-only since
    // F26-I01) instead of the old bare 「・N 則」.
    expect(screen.getByText(textOf("・投放中 5 則"))).toBeTruthy();
    expect(screen.getByText("投放中", { exact: true })).toBeTruthy(); // STATUS_LABEL.live (exact, not the count chip's 「投放中 5 則」)

    const adjust = screen.getByRole("link", { name: "調整" });
    expect(adjust.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/target");

    expect(screen.getByText(/停損 1/)).toBeTruthy();
    expect(screen.getByText(/變好 2/)).toBeTruthy();
    expect(screen.getByText(/持平 2/)).toBeTruthy();
    expect(screen.queryByText(/變差/)).toBeNull();
    expect(screen.queryByText(/資料不足/)).toBeNull();
  });

  it("目標數字可能是算出來的小數（打平＝售價減成本）：最多兩位小數，不用 Math.round", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([
      triageItem({ target: { value: 5200 / 15, basis: "break_even", result_kind: "purchase", result_label: "購買", missing: [] } }),
    ]));

    renderCards();

    expect(await screen.findByText("346.67", { exact: true })).toBeTruthy();
    expect(screen.queryByText("347")).toBeNull();
    expect(screen.getByText("暫用打平")).toBeTruthy();
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
    expect(screen.getByText(textOf("・投放中 4 則"))).toBeTruthy(); // header 的「N 則」仍是總則數
    const width = (cls: string) => (container.querySelector(`[data-segment="${cls}"]`) as HTMLElement).style.width;
    expect(width("better")).toBe("50%"); // 分母排除 no_target：2 則已判斷，各占一半
    expect(width("flat")).toBe("50%");
  });

  it("活動名稱連到 Campaign 工作區，帶著可點擊的「›」但可及名稱與 e2e 文字比對仍是純名稱", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));

    renderCards();

    const heading = await screen.findByRole("heading", { name: "測試 Campaign" });
    const link = within(heading).getByRole("link", { name: "測試 Campaign" });
    // F20-I02：名稱連結現在落在活動詳情頁（v7 campPage()），不是五分頁工作區。
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/detail");
    expect(screen.getByText("測試 Campaign", { exact: true })).toBeTruthy();
  });

  it("超長活動名稱：「›」不被 truncate 擠掉，連結可及名稱仍是完整名稱", async () => {
    const longName = "2026 秋季新品啟動・晨光隨行杯 X 在地烘豆師聯名限定款・全通路整合行銷總覽計畫(電商站內+社群廣告+聯盟導流三線並行)";
    vi.mocked(listCampaigns).mockResolvedValue([campaignCardData({ name: longName })]);
    vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));

    renderCards();

    const heading = await screen.findByRole("heading", { name: longName });
    const link = within(heading).getByRole("link", { name: longName });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/detail");
    // 「›」永遠在（shrink-0），只有名稱那格 truncate；title 存在 <Link> 本身（F27-I17：名稱換成
    // `CampaignChip`，這顆共用元件沒有 title 插槽）。
    expect(within(link).getByText("›", { exact: true })).toBeTruthy();
    expect(link.getAttribute("title")).toBe(longName);
  });

  it("F27-I17：標題用共用 CampaignChip，family 從 campaign_objective 讀", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([campaignCardData({ campaign_objective: "sales" })]);
    vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));

    const { container } = renderCards();
    await screen.findByText("測試 Campaign", { exact: true });

    const chip = container.querySelector('[data-slot="campaign-chip"]');
    expect(chip?.getAttribute("data-variant")).toBe("sales");
  });

  it("F27-I17：campaign_objective 沒帶（手寫 fixture 沒補）時 CampaignChip 退回 other，不是掛掉", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));

    const { container } = renderCards();
    await screen.findByText("測試 Campaign", { exact: true });

    const chip = container.querySelector('[data-slot="campaign-chip"]');
    expect(chip?.getAttribute("data-variant")).toBe("other");
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

  // F27-I17 Contract F: capacity 是 `CampaignCard.data.capacity`（`listCampaigns`
  // ／`repository.py::list_campaigns` 直接帶的，`adsApi.ts` 上的欄位），跟同名但另一支 API
  // （`getTriage`／`triage.py::_data_view`）的 `TriageData.capacity` 是兩個各自獨立的讀——這裡
  // 用 `campaignCardData` 掛，不是 `triage()` 的 `data`。
  describe("F27-I17 Contract F：容量 chip「每日 X」／「約撐得起 N 則」", () => {
    it("兩個數字都在，且同時在投超過撐得起的則數：兩顆 chip 都印，撐得起那顆轉 warn", async () => {
      vi.mocked(listCampaigns).mockResolvedValue([campaignCardData({
        data: {
          sync: { state: "ok", error: null, last_success_at: "2026-09-21T00:00:00Z" },
          capacity: { daily_budget: 900, currency: "TWD", target: 450, can_support: 2, active_ads: 3 },
        },
      })]);
      vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));

      renderCards();

      expect(await screen.findByText("每日 900 TWD")).toBeTruthy();
      const supportChip = screen.getByText(textOf("約撐得起 2 則"));
      expect(supportChip.getAttribute("data-tone")).toBe("warn");
    });

    it("撐得起的則數還夠用（active_ads ≤ can_support）：chip 是 neutral，不是 warn", async () => {
      vi.mocked(listCampaigns).mockResolvedValue([campaignCardData({
        data: {
          sync: { state: "ok", error: null, last_success_at: "2026-09-21T00:00:00Z" },
          capacity: { daily_budget: 900, currency: "TWD", target: 450, can_support: 4, active_ads: 3 },
        },
      })]);
      vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));

      renderCards();

      const supportChip = await screen.findByText(textOf("約撐得起 4 則"));
      expect(supportChip.getAttribute("data-tone")).toBe("neutral");
    });

    it("daily_budget／can_support 都是 null：不印容量 chip，只留原本的預算 chip", async () => {
      vi.mocked(listCampaigns).mockResolvedValue([campaignCardData({
        data: {
          sync: { state: "ok", error: null, last_success_at: "2026-09-21T00:00:00Z" },
          capacity: { daily_budget: null, currency: null, target: null, can_support: null, active_ads: 3 },
        },
      })]);
      vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));

      renderCards();

      await screen.findByText("450", { exact: true });
      expect(screen.queryByText(/^每日 /)).toBeNull();
      expect(screen.queryByText(/^約撐得起 /)).toBeNull();
    });
  });
  describe("F24-I02：sync 異常態與「資料不足，先不判斷」", () => {
    it("sync 失敗：灰卡「暫時讀取不到」＋已保存的紀錄都還在；重新讀取＝真同步（syncCampaign→輪詢→重讀這張卡）", async () => {
      vi.mocked(getTriage).mockResolvedValue(triage([triageItem()], {
        sync: { state: "failed", error: "(#190) token expired", last_success_at: "2026-09-19T14:40:00Z" },
        coverage: { start: "2026-09-01", end: "2026-09-07" }, missing_days: [],
      }));
      vi.mocked(syncCampaign).mockResolvedValue({ job: { id: "job_1", status: "pending", last_success_at: null } });
      vi.mocked(syncJob).mockResolvedValue({
        job: { id: "job_1", status: "success", last_success_at: "2026-09-22T00:00:00Z" }, connected: true,
      });

      renderCards();

      expect(await screen.findByText("暫時讀取不到")).toBeTruthy();
      expect(screen.getByText("已保存的紀錄都還在")).toBeTruthy();
      expect(screen.queryByText("預算待核實")).toBeNull();

      const retry = screen.getByRole("button", { name: "重新讀取「測試 Campaign」" });
      await userEvent.click(retry);

      await waitFor(() => expect(syncCampaign).toHaveBeenCalledWith("brd_1", "cmp_1"));
      await waitFor(() => expect(syncJob).toHaveBeenCalledWith("brd_1", "job_1"));
      await waitFor(() => expect(callsFor("cmp_1")).toBe(2));
    });

    it("sync 進行中：chip「讀取中」，重新讀取按鈕停用", async () => {
      vi.mocked(getTriage).mockResolvedValue(triage([triageItem()], {
        sync: { state: "syncing", error: null, last_success_at: "2026-09-19T14:40:00Z" },
        coverage: { start: "2026-09-01", end: "2026-09-07" }, missing_days: [],
      }));

      renderCards();

      expect(await screen.findByText("讀取中")).toBeTruthy();
      const retry = screen.getByRole("button", { name: "重新讀取「測試 Campaign」" });
      expect(retry.hasAttribute("disabled")).toBe(true);
    });

    it("廣告帳戶未連接：chip「廣告帳戶未連接」，按鈕「去連接」連到資料連線頁（不是重新讀取）", async () => {
      vi.mocked(getTriage).mockResolvedValue(triage([triageItem()], {
        sync: { state: "disconnected", error: null, last_success_at: null },
        coverage: null, missing_days: [],
      }));

      renderCards();

      expect(await screen.findByText("廣告帳戶未連接")).toBeTruthy();
      const link = screen.getByRole("link", { name: "去連接" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/connections");
      expect(screen.queryByRole("button", { name: /重新讀取/ })).toBeNull();
    });

    it("資料不足（缺同步天數）：warn 卡＋「缺 N 天資料」＋「去處理」連到等待頁", async () => {
      vi.mocked(getTriage).mockResolvedValue(triage(
        [triageItem({ entity_id: "ad_1", class: "insufficient", reason_code: "below_sample_gate" })],
        {
          sync: { state: "ok", error: null, last_success_at: "2026-09-21T00:00:00Z" },
          coverage: { start: "2026-09-01", end: "2026-09-14" },
          missing_days: ["2026-09-17", "2026-09-18"],
        },
      ));

      renderCards();

      expect(await screen.findByText("資料不足，先不判斷")).toBeTruthy();
      expect(screen.getByText("缺 2 天資料")).toBeTruthy();
      const link = screen.getByRole("link", { name: "去處理" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/wait");
    });

    it("資料不足（從沒同步過成效）：coverage null 印「尚未同步成效」，不是缺天數", async () => {
      vi.mocked(getTriage).mockResolvedValue(triage(
        [triageItem({ entity_id: "ad_1", class: "insufficient", reason_code: "below_sample_gate" })],
        { sync: { state: "ok", error: null, last_success_at: "2026-09-21T00:00:00Z" }, coverage: null, missing_days: [] },
      ));

      renderCards();

      expect(await screen.findByText("資料不足，先不判斷")).toBeTruthy();
      expect(screen.getByText("尚未同步成效")).toBeTruthy();
    });

    it("資料不足（已同步，樣本還不夠）：依這批 insufficient 廣告裡多數的 reason_code 印 chip", async () => {
      vi.mocked(getTriage).mockResolvedValue(triage(
        [
          triageItem({ entity_id: "ad_1", class: "insufficient", reason_code: "below_sample_gate" }),
          triageItem({ entity_id: "ad_2", class: "insufficient", reason_code: "below_sample_gate" }),
          triageItem({ entity_id: "ad_3", class: "insufficient", reason_code: "no_previous_window" }),
        ],
        {
          sync: { state: "ok", error: null, last_success_at: "2026-09-21T00:00:00Z" },
          coverage: { start: "2026-09-01", end: "2026-09-14" },
          missing_days: [],
        },
      ));

      renderCards();

      expect(await screen.findByText("資料不足，先不判斷")).toBeTruthy();
      expect(screen.getByText("樣本還不夠")).toBeTruthy();
    });

    it("no_target 不是「資料不足」：全部 no_target 仍走既有「尚未設定」卡，不誤判成警示卡", async () => {
      vi.mocked(getTriage).mockResolvedValue(triage(
        [triageItem({
          entity_id: "ad_1", class: "no_target",
          target: { value: null, basis: null, result_kind: null, result_label: "購買", missing: [] },
        })],
        {
          sync: { state: "ok", error: null, last_success_at: "2026-09-21T00:00:00Z" },
          coverage: { start: "2026-09-01", end: "2026-09-14" },
          missing_days: [],
        },
      ));

      renderCards();

      expect(await screen.findByText("尚未設定")).toBeTruthy();
      expect(screen.queryByText("資料不足，先不判斷")).toBeNull();
    });

    it("沒有 data（手寫 fixture 沒補，視同 never）：跟今天原本的卡一樣，不套新的異常／警示態", async () => {
      vi.mocked(getTriage).mockResolvedValue(triage([triageItem()]));
      renderCards();
      expect(await screen.findByText("450", { exact: true })).toBeTruthy();
      expect(screen.queryByText("暫時讀取不到")).toBeNull();
      expect(screen.queryByText("資料不足，先不判斷")).toBeNull();
    });

    it("onSync：listCampaigns 讀成功後把整批清單回報給上層（F24-I02 頁首同步晶片用）", async () => {
      const campaigns = [campaignCardData({ id: "cmp_x" })];
      vi.mocked(listCampaigns).mockResolvedValue(campaigns);
      vi.mocked(getTriage).mockResolvedValue(triage([]));
      const onSync = vi.fn();

      render(
        <MemoryRouter>
          <CampaignCards brandId="brd_1" onSync={onSync} />
        </MemoryRouter>,
      );

      await waitFor(() => expect(onSync).toHaveBeenCalledWith(campaigns));
    });
  });

  describe("F26-I02：另有 N 則已關閉", () => {
    it("closed.total > 0：印「另有 N 則已關閉（暫停 X・已封存 Y），不列入判斷」＋「查看 →」連到詳情頁", async () => {
      vi.mocked(getTriage).mockResolvedValue(triage(
        [triageItem()], undefined, { paused: 11, archived: 4, other: 0, total: 15, items: [], truncated: false },
      ));

      renderCards();

      expect(await screen.findByText(textOf("另有 15 則已關閉（暫停 11・已封存 4），不列入判斷"))).toBeTruthy();
      const link = screen.getByRole("link", { name: "查看 →" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/detail");
    });

    it("closed.total === 0：整行省略，不印「另有」", async () => {
      vi.mocked(getTriage).mockResolvedValue(triage([triageItem()])); // EMPTY_CLOSED 預設

      renderCards();

      await screen.findByText("450", { exact: true });
      expect(screen.queryByText(/另有/)).toBeNull();
      expect(screen.queryByRole("link", { name: "查看 →" })).toBeNull();
    });

    it("other 桶不單獨列出，只併進粗體總數（跟 prototype 一樣不拆 DELETED／ADSET_PAUSED／CAMPAIGN_PAUSED）", async () => {
      vi.mocked(getTriage).mockResolvedValue(triage(
        [triageItem()], undefined, { paused: 1, archived: 0, other: 2, total: 3, items: [], truncated: false },
      ));

      renderCards();

      expect(await screen.findByText(textOf("另有 3 則已關閉（暫停 1・已封存 0），不列入判斷"))).toBeTruthy();
    });
  });
});
