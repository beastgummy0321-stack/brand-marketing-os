/** frontend/src/components/ads/detail/CampaignDetailPage.test.tsx — F20-I02：活動詳情頁
 * （v7 `campPage()`）。覆蓋 Feature Acceptance／Done：頭部（名稱、目標／尚未設定目標、
 * 預算、調整目標、全部資料 ›）、分類分組（停損／變差預設展開，其餘收合）、佇列裡的廣告
 * 才有「去處理」、縮圖 `null`／載入失敗都落到中性佔位、`?ad=` 深連結展開並高亮、沒有廣告、
 * 讀取失敗。`vi.mock` 掉 `@/lib/adsApi`／`@/lib/adsTriageApi`，不打真的 API。 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { listCampaigns } from "@/lib/adsApi";
import type { QueueItem, QueuePayload, TriageClass, TriageItem } from "@/lib/adsTriageApi";
import { getQueue, getTriage } from "@/lib/adsTriageApi";
import { CampaignDetailPage } from "./CampaignDetailPage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, listCampaigns: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, getTriage: vi.fn(), getQueue: vi.fn() };
});

function campaignCardData(overrides: Partial<CampaignCardData> = {}): CampaignCardData {
  return {
    id: "cmp_1", name: "【銷售】1150706 Beast Prime 最高數量", status: "live",
    start_date: "2026-01-01", end_date: "2026-01-31", objective: "轉換",
    created_at: "2026-01-01T00:00:00Z", created_by: null,
    budget_planned: null, budget_total: null,
    budget_progress: { spent: 22000, total: 60000, pct: 36.7 },
    judgment: { tone: "neutral", text: "投放中", detail: "還沒有花費資料" },
    outcome: { spend: 0, purchases: 0, revenue: 0 },
    ...overrides,
  };
}

function triageItem(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "ad_1", native_id: "native_1", name: "1150706 健身情境單圖 最多數量",
    campaign_id: "cmp_1", campaign_name: "【銷售】1150706 Beast Prime 最高數量", thumbnail_url: null,
    class: "insufficient", label: "資料不足", reason_code: "below_sample_gate",
    window: { start: "2026-08-25", end: "2026-09-21", days: 28, previous_start: "2026-07-28", previous_end: "2026-08-24", extended_from: 14 },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: null, result_count: null, cost_per_result: null, result_kind: null, result_label: "成果", derived_zero_days: 0, reason: "result_unknown_days" },
    previous: { spend: null, result_count: null, cost_per_result: null, result_kind: null, result_label: "成果", derived_zero_days: 0, reason: "result_unknown_days" },
    change_pct: null, sample: { gate: false, spend_multiple: null, days_with_events: 0 },
    ...overrides,
  };
}

function queueItem(overrides: Partial<QueueItem> = {}): QueueItem {
  const triage = overrides.triage ?? triageItem({ entity_id: "ad_stop", class: "stop_loss", label: "停損" });
  return {
    id: "q_1", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null,
    dedupe_key: "k_1", category: "triage", kind: "stop_loss", severity: "rule_warning",
    message: "廣告可能該停損了", action_url: `/brands/brd_1/ads/campaigns/cmp_1/detail?ad=${triage.entity_id}`,
    visible_from: null, status: "open", created_at: "2026-09-21T00:00:00Z", resolved_at: null,
    kind_key: "stop_loss", proposal: null, ...overrides, triage,
  };
}

function queue(items: QueueItem[]): QueuePayload {
  const counts = { stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 } as Record<TriageClass, number>;
  return { items, counts, total_ads: items.length, kinds_available: [], kinds_pending: [] };
}

function renderPage(initialPath = "/brands/brd_1/ads/campaigns/cmp_1/detail") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="/brands/:brandId/ads/campaigns/:campaignId/detail"
          element={<CampaignDetailPage brandId="brd_1" campaignId="cmp_1" />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

// jsdom（v30）沒有實作 `Element.prototype.scrollIntoView`（`?ad=` 深連結用它捲到那一列）——
// 補一個 no-op，跟這專案其他用到它的元件一樣，測試環境本來就不驗證真的捲動位置。
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listCampaigns).mockResolvedValue([campaignCardData()]);
  vi.mocked(getQueue).mockResolvedValue(queue([]));
  Element.prototype.scrollIntoView = vi.fn();
});

describe("CampaignDetailPage（F20-I02，v7 campPage()）", () => {
  it("有目標：頭部印目標數字、依據、預算、objective・則數；調整目標／全部資料 › 指對網址", async () => {
    vi.mocked(getTriage).mockResolvedValue({ window_days: 28, items: [triageItem()] });

    renderPage();

    expect(await screen.findByRole("heading", { name: "【銷售】1150706 Beast Prime 最高數量" })).toBeTruthy();
    expect(screen.getByText("轉換")).toBeTruthy();
    expect(screen.getByText("・1 則")).toBeTruthy();
    expect(screen.getByText(/目標每次購買成本 450・自訂/)).toBeTruthy();
    expect(screen.getByText("總預算 NT$ 60,000")).toBeTruthy();
    expect(screen.queryByText("尚未設定目標")).toBeNull();

    const adjust = screen.getByRole("link", { name: "調整目標" });
    expect(adjust.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/target");
    const all = screen.getByRole("link", { name: "全部資料 ›" });
    expect(all.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1");
  });

  it("objective chip：跟 `home/CampaignCard.tsx` 同一種處理——只有 objective 自己截斷，「・N 則」不被擠到換行", async () => {
    const longObjective = "提高 Beast Prime 的購買數量，以購買次數為主要成效，這是一整句很長的匯入活動目標敘述用來測試截斷";
    vi.mocked(listCampaigns).mockResolvedValue([campaignCardData({ objective: longObjective })]);
    vi.mocked(getTriage).mockResolvedValue({ window_days: 28, items: [triageItem()] });

    renderPage();
    await screen.findByText("・1 則");

    const objectiveNode = screen.getByText(longObjective);
    expect(objectiveNode.className).toMatch(/truncate/);
    expect(objectiveNode.getAttribute("title")).toBe(longObjective);
    const chipNode = objectiveNode.parentElement!;
    expect(chipNode.className).toMatch(/max-w-\[14rem\]/);
    // 「・1 則」是不會被截斷的獨立節點，永遠印得出來。
    expect(screen.getByText("・1 則").className).not.toMatch(/truncate/);
  });

  it("沒有目標：每一則都算 no_target，印警告 chip、警告條與「設定目標」（不是「調整目標」）", async () => {
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 28,
      items: [triageItem({ class: "no_target", label: "尚未設定目標", target: { value: null, basis: null, result_kind: null, result_label: "成果", missing: [] } })],
    });

    renderPage();

    await screen.findByText("・1 則");
    expect(screen.getAllByText("尚未設定目標").length).toBeGreaterThan(0); // header chip + 分類名稱
    expect(screen.getByText("沒有目標，這個活動的廣告都還不會被判斷")).toBeTruthy();
    expect(screen.getByRole("link", { name: "設定目標" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "調整目標" })).toBeNull();
    const banner = screen.getByRole("link", { name: "設定目標 →" });
    expect(banner.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/target");
  });

  it("分類分組：停損／變差預設展開，其餘收合；標籤照後端 label，不是自己拼字", async () => {
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 7,
      items: [
        triageItem({ entity_id: "a1", class: "stop_loss", label: "停損" }),
        triageItem({ entity_id: "a2", class: "worse", label: "變差" }),
        triageItem({ entity_id: "a3", class: "better", label: "變好" }),
        triageItem({ entity_id: "a4", class: "flat", label: "持平" }),
      ],
    });

    const { container } = renderPage();
    await screen.findByText("・4 則");

    const detailsOf = (label: string) => {
      const summary = screen.getByText(label).closest("summary")!;
      return summary.closest("details")!;
    };
    expect(detailsOf("停損").open).toBe(true);
    expect(detailsOf("變差").open).toBe(true);
    expect(detailsOf("變好").open).toBe(false);
    expect(detailsOf("持平").open).toBe(false);
    // 收合分類的廣告名稱這時候不在可見文字裡（native <details> 未展開時子節點仍在 DOM，
    // 但這裡只斷言分組數量與展開狀態，不糾結 jsdom 對 hidden 內容的可見性判定）。
    expect(container.querySelectorAll("details").length).toBe(4);
  });

  it("佇列裡的停損廣告：「去處理」走 F22-I05 的提案流程（沒有 proposal 就是提議頁），不連 queue 的 action_url（那會繞回這一頁）", async () => {
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 7,
      items: [
        triageItem({ entity_id: "ad_stop", class: "stop_loss", label: "停損", name: "停損廣告" }),
        triageItem({ entity_id: "ad_flat", class: "flat", label: "持平", name: "持平廣告" }),
      ],
    });
    vi.mocked(getQueue).mockResolvedValue(queue([
      // action_url 故意指回這一頁（F20-I01 之後 queue 的真實形狀）——按鈕不能原樣用它。
      queueItem({ id: "q_stop", triage: triageItem({ entity_id: "ad_stop", class: "stop_loss", label: "停損", name: "停損廣告" }), action_url: "/brands/brd_1/ads/campaigns/cmp_1/detail?ad=ad_stop" }),
    ]));

    renderPage();
    await screen.findByText("・2 則");

    const stopRow = screen.getByTestId("ad-row-ad_stop");
    const goLink = within(stopRow).getByRole("link", { name: "去處理" });
    expect(goLink.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/pause/ad_stop");
    expect(goLink.getAttribute("href")).not.toContain("/detail");
    expect(goLink.getAttribute("href")).not.toContain("tab=performance");

    const flatRow = screen.getByTestId("ad-row-ad_flat");
    expect(within(flatRow).queryByRole("link", { name: "去處理" })).toBeNull();
  });

  it("停損廣告已有提案：按鈕標籤／連結跟著 proposal 狀態走（跟 home/QueueRow 同一支 helper）", async () => {
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 7,
      items: [triageItem({ entity_id: "ad_stop", class: "stop_loss", label: "停損", name: "停損廣告" })],
    });
    vi.mocked(getQueue).mockResolvedValue(queue([
      queueItem({
        id: "q_stop",
        triage: triageItem({ entity_id: "ad_stop", class: "stop_loss", label: "停損", name: "停損廣告" }),
        proposal: {
          change_set_id: "set_1", campaign_id: "cmp_1", kind: "pause",
          status: "approved", verification_state: "pending",
          reason: null, revisit_at: null, multi: false,
        },
      }),
    ]));

    renderPage();
    await screen.findByText("・1 則");

    const stopRow = screen.getByTestId("ad-row-ad_stop");
    const link = within(stopRow).getByRole("link", { name: "到平台完成" });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/set_1/handoff");
  });

  it("`getQueue`失敗：不拖累整頁——目標／分類／列照常顯示，只是沒有「去處理」", async () => {
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 7,
      items: [triageItem({ entity_id: "ad_stop", class: "stop_loss", label: "停損" })],
    });
    vi.mocked(getQueue).mockRejectedValue(new Error("佇列讀取失敗"));

    renderPage();

    expect(await screen.findByText("・1 則")).toBeTruthy();
    expect(screen.getByText("停損").closest("summary")!.closest("details")!.open).toBe(true);
    expect(screen.queryByRole("link", { name: "去處理" })).toBeNull();
    expect(screen.queryByText("讀取失敗")).toBeNull();
  });

  it("縮圖：null 落到中性佔位，有網址先顯示圖片，載入失敗改回佔位", async () => {
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 7,
      items: [
        triageItem({ entity_id: "ad_null", thumbnail_url: null }),
        triageItem({ entity_id: "ad_img", thumbnail_url: "https://cdn.example/thumb.jpg" }),
      ],
    });

    renderPage();
    await screen.findByText("・2 則");

    const nullRow = screen.getByTestId("ad-row-ad_null");
    expect(nullRow.querySelector("img")).toBeNull();

    const imgRow = screen.getByTestId("ad-row-ad_img");
    // 縮圖是裝飾性的（`alt=""`），拿不到 `role="img"`（空 alt 落到 presentation role）——
    // 用標籤本身斷言，跟這顆縮圖本來就不進可及樹一致。
    const img = imgRow.querySelector("img") as HTMLImageElement;
    expect(img.src).toBe("https://cdn.example/thumb.jpg");

    fireEvent.error(img);
    expect(imgRow.querySelector("img")).toBeNull();
  });

  it("`?ad=` 深連結：那一則所在分類展開並高亮那一列；不認得的 id 忽略", async () => {
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 7,
      items: [
        triageItem({ entity_id: "ad_stop", class: "stop_loss", label: "停損" }),
        triageItem({ entity_id: "ad_flat", class: "flat", label: "持平" }),
      ],
    });

    renderPage("/brands/brd_1/ads/campaigns/cmp_1/detail?ad=ad_flat");
    await screen.findByText("・2 則");

    const summary = screen.getByText("持平").closest("summary")!;
    const details = summary.closest("details")!;
    expect(details.open).toBe(true);
    const row = screen.getByTestId("ad-row-ad_flat");
    expect(row.className).toMatch(/ring-primary/);
  });

  it("`?ad=` 深連結只捲動一次：之後摺疊／展開別的分類不會再觸發 scrollIntoView", async () => {
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 7,
      items: [
        triageItem({ entity_id: "ad_stop", class: "stop_loss", label: "停損" }),
        triageItem({ entity_id: "ad_flat", class: "flat", label: "持平" }),
        triageItem({ entity_id: "ad_better", class: "better", label: "變好" }),
      ],
    });
    const scrollSpy = vi.fn();
    Element.prototype.scrollIntoView = scrollSpy;

    renderPage("/brands/brd_1/ads/campaigns/cmp_1/detail?ad=ad_flat");
    await screen.findByText("・3 則");
    expect(screen.getByTestId("ad-row-ad_flat")).toBeTruthy();
    expect(scrollSpy).toHaveBeenCalledTimes(1);

    // 開另一個原本收合的分類（「變好」）——`openGroups` 換了一個新的 `Set`，但高亮的
    // 那一則沒有變，不該再捲一次。
    await userEvent.click(screen.getByText("變好").closest("summary")!);
    expect(scrollSpy).toHaveBeenCalledTimes(1);
  });

  it("不認得的 `?ad=` id：忽略，維持預設展開狀態，不當機", async () => {
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 7,
      items: [
        triageItem({ entity_id: "ad_stop", class: "stop_loss", label: "停損" }),
        triageItem({ entity_id: "ad_flat", class: "flat", label: "持平" }),
      ],
    });

    renderPage("/brands/brd_1/ads/campaigns/cmp_1/detail?ad=unknown_id");
    await screen.findByText("・2 則");

    // 停損有東西所以照 Feature Outcome 預設展開；持平不受這個不存在的 `?ad=` 影響，維持收合。
    expect(screen.getByText("停損").closest("summary")!.closest("details")!.open).toBe(true);
    expect(screen.getByText("持平").closest("summary")!.closest("details")!.open).toBe(false);
  });

  it("分類 summary 右側提示：持平印「照常投放」，資料不足印「還沒花到可判讀的金額」（不帶金額），其餘分類不印", async () => {
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 7,
      items: [
        triageItem({ entity_id: "a1", class: "stop_loss", label: "停損" }),
        triageItem({ entity_id: "a2", class: "flat", label: "持平" }),
        triageItem({ entity_id: "a3", class: "insufficient", label: "資料不足" }),
      ],
    });

    renderPage();
    await screen.findByText("・3 則");

    expect(screen.getByText("照常投放")).toBeTruthy();
    expect(screen.getByText("還沒花到可判讀的金額")).toBeTruthy();
    // 3 倍停損線的金額是後端常數，payload 沒帶——不臆造、不在前端算。
    expect(screen.queryByText(/還沒花到可判讀的金額（/)).toBeNull();
    expect(screen.queryByText(/[×x]\s*3/)).toBeNull();
  });

  it("沒有停損／變差（今天真實 Beast Prime 資料的形狀）：預設展開第一個有廣告的分類，不是整頁收合", async () => {
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 7,
      items: [
        triageItem({ entity_id: "a1", class: "better", label: "變好" }),
        triageItem({ entity_id: "a2", class: "flat", label: "持平" }),
        triageItem({ entity_id: "a3", class: "insufficient", label: "資料不足" }),
      ],
    });

    renderPage();
    await screen.findByText("・3 則");

    // GROUP_ORDER 裡第一個有廣告的是「變好」——不能三個分類全部收合、頁面看起來像空的。
    expect(screen.getByText("變好").closest("summary")!.closest("details")!.open).toBe(true);
    expect(screen.getByText("持平").closest("summary")!.closest("details")!.open).toBe(false);
    expect(screen.getByText("資料不足").closest("summary")!.closest("details")!.open).toBe(false);
  });

  it("尚未設定目標（唯一分類是 no_target）：預設展開那一類，不是整頁只剩一條收合列", async () => {
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 7,
      items: [
        triageItem({ entity_id: "a1", class: "no_target", label: "尚未設定目標", target: { value: null, basis: null, result_kind: null, result_label: "成果", missing: [] } }),
      ],
    });

    renderPage();
    await screen.findByText("・1 則");

    const summaries = screen.getAllByText("尚未設定目標").map((el) => el.closest("summary")).filter((el): el is HTMLElement => el !== null);
    expect(summaries.length).toBe(1);
    expect(summaries[0].closest("details")!.open).toBe(true);
  });

  it("版面寬度照 v7 `.page{max-width:1180px}`：外層容器帶同一個上限，不跟著殼撐到全寬", async () => {
    vi.mocked(getTriage).mockResolvedValue({ window_days: 28, items: [triageItem()] });

    const { container } = renderPage();
    await screen.findByText("・1 則");

    expect(container.querySelector(".max-w-\\[1180px\\]")).toBeTruthy();
  });

  it("沒有廣告資料：不催設定目標，只留全部資料 ›", async () => {
    vi.mocked(getTriage).mockResolvedValue({ window_days: 28, items: [] });

    renderPage();

    expect(await screen.findByText("沒有廣告資料，這個活動還沒有可以判斷的內容。")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "設定目標" })).toBeNull();
    expect(screen.queryByRole("link", { name: "調整目標" })).toBeNull();
    expect(screen.getByRole("link", { name: "全部資料 ›" })).toBeTruthy();
  });

  it("讀取失敗：讀取失敗訊息＋重新讀取，成功後正常顯示", async () => {
    vi.mocked(getTriage).mockRejectedValueOnce(new Error("網路錯誤"));

    renderPage();

    expect(await screen.findByText("讀取失敗")).toBeTruthy();
    expect(screen.getByText("網路錯誤")).toBeTruthy();

    vi.mocked(getTriage).mockResolvedValue({ window_days: 28, items: [triageItem()] });
    await userEvent.click(screen.getByRole("button", { name: "重新讀取" }));

    expect(await screen.findByText("・1 則")).toBeTruthy();
  });

  it("清單裡找不到這個 Campaign：讀取失敗態，訊息是「找不到這個 Campaign。」", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([campaignCardData({ id: "cmp_other" })]);
    vi.mocked(getTriage).mockResolvedValue({ window_days: 28, items: [] });

    renderPage();

    expect(await screen.findByText("找不到這個 Campaign。")).toBeTruthy();
  });
});
