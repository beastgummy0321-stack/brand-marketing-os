/** F28-I10: campaign detail graded against the cap (prototype v9 `tabPerf()`). Covers the header cap chip, the ruler
 * card (title, window chip, missing-days chip, 去改上限, 打平 mark, empty ruler without a cap), default folds, the
 * rows' actions and ruler-dot navigation, `?ad=` deep links, and the three reads failing independently. Realistic
 * fixtures: the longest real names, decimal costs, 0 results, no cap, gap days, an imported campaign. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { listCampaigns } from "@/lib/adsApi";
import type { CampaignTriage, QueueCleanup, QueueItem, QueuePayload, TriageClosedBlock, TriageItem } from "@/lib/adsTriageApi";
import { getQueue, getTriage } from "@/lib/adsTriageApi";
import { CampaignDetailPage, missingDaysLabel, windowLabel } from "./CampaignDetailPage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, listCampaigns: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, getTriage: vi.fn(), getQueue: vi.fn() };
});

const CAMPAIGN_NAME = "【銷售】1150706 Beast Prime 最高數量";
const WS = "/brands/brd_1/ads/campaigns/cmp_1";

function campaignCard(overrides: Partial<CampaignCardData> = {}): CampaignCardData {
  return {
    id: "cmp_1", name: CAMPAIGN_NAME, status: "live", start_date: "2026-09-08", end_date: "2026-10-08", objective: "轉換",
    created_at: "2026-09-01T00:00:00Z", created_by: null, budget_planned: null, budget_total: null,
    budget_progress: { spent: 22000, total: 60000, pct: 36.7 },
    judgment: { tone: "neutral", text: "投放中", detail: "" }, outcome: { spend: 0, purchases: 0, revenue: 0 },
    ...overrides,
  };
}

type Cap = { value: number | null; basis: "own" | "break_even" | null; break_even?: number | null };
const OWN_450: Cap = { value: 450, basis: "own", break_even: 520 };

function ad(id: string, name: string, grade: TriageItem["grade"], spend: number | null, results: number | null, cap: Cap = OWN_450, extra: Partial<TriageItem> = {}): TriageItem {
  const labels = { on_target: "划算", watch: "偏貴", over: "太貴", wasted: "沒賣出", insufficient: "剛開始、數字還不夠", no_target: "未判斷" };
  const cost = spend !== null && results ? Math.round((spend / results) * 100) / 100 : null;
  const metrics = { spend, result_count: results, cost_per_result: cost, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null };
  return {
    entity_id: id, native_id: `n_${id}`, name, campaign_id: "cmp_1", campaign_name: CAMPAIGN_NAME, thumbnail_url: null,
    class: "flat", label: "持平", reason_code: "", grade, grade_label: labels[grade], previous_grade: null, grade_move: null,
    window: { start: "2026-09-10", end: "2026-09-23", days: 14, previous_start: "2026-08-27", previous_end: "2026-09-09", extended_from: null },
    target: { value: cap.value, basis: cap.basis, result_kind: "purchase", result_label: "購買", missing: [], break_even: cap.break_even ?? null },
    current: metrics, previous: { ...metrics, spend: null, result_count: null, cost_per_result: null }, change_pct: null,
    sample: { gate: grade !== "insufficient", spend_multiple: null, days_with_events: 10 },
    ...extra,
  };
}

/** The prototype's `daily` campaign: 5 划算, 1 偏貴, 1 太貴, 1 沒賣出 against 上限 450. */
function dailyAds(cap: Cap = OWN_450): TriageItem[] {
  return [
    ad("a1", "晨光隨行杯・日常出發", "on_target", 1440, 30, cap),
    ad("a2", "晨光隨行杯・隨時有你｜好攜帶，走到哪都適合（通勤情境單圖・最多數量 1150706）", "on_target", 1407, 28, cap),
    ad("a3", "辦公室一角・質感桌面", "on_target", 1300, 25, cap),
    ad("a4", "開箱 15 秒・單手開蓋", "on_target", 1100, 20, cap),
    ad("a5", "健身情境・保冷 12 小時", "on_target", 3450, 8, cap),
    ad("a6", "再行銷・兩入組 NT$1,580 免運 - 複本 2", "watch", 3120, 6, cap, { change_pct: 0.1818 }),
    ad("a7", "提問式貼文・早晨第一口是什麼？", "over", 2470, 4, cap, { change_pct: 0.1002 }),
    ad("a8", "秋季新色預告・直式 9:16 短影音", "wasted", 1480, 0, cap),
  ];
}

const EMPTY_CLOSED: TriageClosedBlock = { paused: 0, archived: 0, other: 0, total: 0, items: [], truncated: false };

function triage(items: TriageItem[], extra: Partial<CampaignTriage> = {}): CampaignTriage {
  return {
    window_days: 28, items, closed: EMPTY_CLOSED,
    data: {
      sync: { state: "ok", error: null, last_success_at: null }, coverage: { start: "2026-08-27", end: "2026-09-23" }, missing_days: [],
      status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: null },
    },
    ...extra,
  };
}

function queueRow(o: Partial<QueueItem> & { triage: TriageItem }): QueueItem {
  return {
    id: "q", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: "k", category: "triage", kind: "worse",
    severity: "rule_warning", message: "", action_url: null, visible_from: null, status: "open",
    created_at: "2026-09-23T00:00:00Z", resolved_at: null, kind_key: "worse", proposal: null, ...o,
  };
}
function cleanup(ids: string[]): QueueCleanup {
  return {
    campaign_id: "cmp_1", campaign_name: CAMPAIGN_NAME, can_support: 6, active_ads: 8,
    ads: ids.map((id) => ({ entity_id: id, name: id, thumbnail_url: null, spend_7d: 700, grade: "wasted", cost_per_result: null, spend: 1480, result_count: 0, daily_spend: 100, rejected_before: null })),
    keep: [], short: 0, daily_saving: 260, scale_owner_id: null,
  };
}
function queue(items: QueueItem[]): QueuePayload {
  return { items, counts: { stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 }, total_ads: 0, kinds_available: [], kinds_pending: [] };
}
function dailyQueue(items: TriageItem[]) {
  return queue([
    queueRow({ kind_key: "cleanup", triage: items[0], cleanup: cleanup(["a8", "a7"]), action_url: `${WS}/propose/cleanup/cmp_1` }),
    queueRow({ kind_key: "worse", triage: items[5] }),
  ]);
}

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}
function renderPage(path = `${WS}/detail`) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/detail" element={<CampaignDetailPage brandId="brd_1" campaignId="cmp_1" />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}
const detailsOf = (title: string) => screen.getByText(title, { selector: "summary b" }).closest("details")!;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listCampaigns).mockResolvedValue([campaignCard()]);
  vi.mocked(getQueue).mockResolvedValue(queue([]));
  Element.prototype.scrollIntoView = vi.fn(); // jsdom has none
});

describe("CampaignDetailPage (F28-I10, v9 tabPerf)", () => {
  it("own cap: header chip 上限 450, ruler card title, window chip, 去改上限 → strategy tab, 打平 mark", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    const { container } = renderPage();

    expect(await screen.findByRole("heading", { name: "在投 8 則對照上限 450" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: CAMPAIGN_NAME })).toBeTruthy();
    const capChip = screen.getByText("上限 450", { selector: "[data-slot=chip]" });
    expect(capChip.getAttribute("data-tone")).toBe("accent");
    expect(screen.getByText("近 14 天 09/10–09/23")).toBeTruthy();
    expect(screen.getByRole("link", { name: "去改上限" }).getAttribute("href")).toBe(`${WS}?tab=strategy`);
    expect(screen.queryByRole("link", { name: /目標/ })).toBeNull();
    expect(screen.getByRole("link", { name: "全部資料 ›" }).getAttribute("href")).toBe(WS);
    expect(container.querySelector('[data-slot=target-ruler][data-variant="full"]')).toBeTruthy();
    expect(screen.getByText("打平 520")).toBeTruthy();
    expect(container.querySelector(".max-w-\\[1260px\\]")).toBeTruthy();
  });

  it("default folds: 沒賣出／太貴／偏貴 open, 划算 folded; rows carry 在清理提議／去處理／看紀錄", async () => {
    const items = dailyAds();
    vi.mocked(getTriage).mockResolvedValue(triage(items));
    vi.mocked(getQueue).mockResolvedValue(dailyQueue(items));
    renderPage();

    await screen.findByRole("heading", { name: "在投 8 則對照上限 450" });
    expect(detailsOf("沒賣出").open).toBe(true);
    expect(detailsOf("太貴").open).toBe(true);
    expect(detailsOf("偏貴").open).toBe(true);
    expect(detailsOf("划算").open).toBe(false);

    const wasted = screen.getByTestId("ad-row-a8");
    expect((await within(wasted).findByRole("link", { name: "在清理提議" })).getAttribute("href")).toBe(`${WS}/propose/cleanup/cmp_1`);
    expect(within(screen.getByTestId("ad-row-a7")).getByRole("link", { name: "在清理提議" })).toBeTruthy();
    expect(within(screen.getByTestId("ad-row-a6")).getByRole("link", { name: "去處理" }).getAttribute("href")).toBe(`${WS}/review/a6`);
    expect(within(screen.getByTestId("ad-row-a1")).getByRole("link", { name: "看紀錄" }).getAttribute("href")).toBe(`${WS}?tab=performance&ad=a1`);
    expect(within(wasted).getByText("0 筆")).toBeTruthy();
    expect(within(screen.getByTestId("ad-row-a7")).getByText("617.5 元")).toBeTruthy();
  });

  it("clicking a ruler dot goes where that ad's row button goes", async () => {
    const items = dailyAds();
    vi.mocked(getTriage).mockResolvedValue(triage(items));
    vi.mocked(getQueue).mockResolvedValue(dailyQueue(items));
    renderPage();

    await within(await screen.findByTestId("ad-row-a8")).findByRole("link", { name: "在清理提議" });
    await userEvent.click(screen.getByRole("button", { name: /^秋季新色預告・直式 9:16 短影音｜/ }));
    expect(screen.getByTestId("where").textContent).toBe(`${WS}/propose/cleanup/cmp_1`);
  });

  it("break-even cap (tgt:none): chip 暫用打平 520 in warn, no separate 打平 mark", async () => {
    const be: Cap = { value: 520, basis: "break_even", break_even: 520 };
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds(be)));
    renderPage();

    expect(await screen.findByRole("heading", { name: "在投 8 則對照暫用打平 520" })).toBeTruthy();
    expect(screen.getByText("暫用打平 520", { selector: "[data-slot=chip]" }).getAttribute("data-tone")).toBe("warn");
    expect(screen.queryByText("打平 520")).toBeNull();
  });

  it("gap days (mid): missing-days chip; with only 划算／剛開始 every group stays folded", async () => {
    const items = [
      ad("m1", "中秋禮盒・隨行杯對杯組（家庭團圓情境）", "on_target", 5603, 35),
      ad("m2", "中秋限定・月光藍開箱", "insufficient", 120, 0),
      ad("m3", "送禮提案・長輩也會用的保溫杯", "insufficient", 180, 1),
    ];
    vi.mocked(getTriage).mockResolvedValue(triage(items, {
      data: {
        sync: { state: "ok", error: null, last_success_at: null }, coverage: null, missing_days: ["2026-09-18", "2026-09-17"],
        status: { state: "partial", label: "有幾天的資料還沒讀到，數字可能偏少。", missing_days: ["2026-09-18", "2026-09-17"], last_success_at: null },
      },
    }));
    renderPage();

    expect(await screen.findByText("缺 09/17、09/18，這兩天不計")).toBeTruthy();
    expect(detailsOf("划算").open).toBe(false);
    expect(detailsOf("剛開始、數字還不夠").open).toBe(false);
    // The ruler's own tray lists the too-new ads against the 3 × cap spend line.
    expect(screen.getByText("剛開始、數字還不夠 2 則")).toBeTruthy();
  });

  it("no cap and no product cost: 沒設上限 chip, the empty ruler, 去設上限; every ad folded under 未判斷", async () => {
    const none: Cap = { value: null, basis: null, break_even: null };
    vi.mocked(getTriage).mockResolvedValue(triage([
      ad("a1", "晨光隨行杯・日常出發", "no_target", 1440, 30, none),
      ad("a2", "零成果的那一則", "no_target", 830.5, 0, none),
    ]));
    const { container } = renderPage();

    expect(await screen.findByRole("heading", { name: "在投 2 則，沒設上限" })).toBeTruthy();
    expect(screen.getByText("沒設上限", { selector: "[data-slot=chip]" }).getAttribute("data-tone")).toBe("warn");
    expect(container.querySelector('[data-slot=target-ruler][data-variant="empty"]')).toBeTruthy();
    expect(screen.getByText("沒設上限，先不分等級", { selector: "div" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "去設上限" }).getAttribute("href")).toBe(`${WS}?tab=strategy`);
    expect(detailsOf("未判斷").open).toBe(false);
    expect(within(screen.getByTestId("ad-row-a2")).getByText("830.5 元")).toBeTruthy();
  });

  it("imported campaign with a long objective: 平台預算 chip, only the objective truncates", async () => {
    const objective = "提高 Beast Prime 的購買數量，以購買次數為主要成效，這是一整句很長的匯入活動目標敘述用來測試截斷";
    vi.mocked(listCampaigns).mockResolvedValue([campaignCard({ origin: "imported", objective })]);
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    renderPage();

    expect(await screen.findByText("・8 則")).toBeTruthy();
    expect(screen.getByText("平台預算")).toBeTruthy();
    expect(screen.getByText(objective).className).toMatch(/truncate/);
    expect(screen.getByText("・8 則").className).not.toMatch(/truncate/);
  });

  it("queue fails: the ruler and groups stay, the queue shows its own error and retries alone", async () => {
    const items = dailyAds();
    vi.mocked(getTriage).mockResolvedValue(triage(items));
    vi.mocked(getQueue).mockRejectedValueOnce(new Error("佇列讀取失敗"));
    renderPage();

    expect(await screen.findByText("決策進度讀取失敗：佇列讀取失敗")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "在投 8 則對照上限 450" })).toBeTruthy();
    expect(within(screen.getByTestId("ad-row-a8")).getByRole("link", { name: "看紀錄" })).toBeTruthy();

    vi.mocked(getQueue).mockResolvedValue(dailyQueue(items));
    await userEvent.click(screen.getByRole("button", { name: "重新讀取" }));
    expect(await within(screen.getByTestId("ad-row-a8")).findByRole("link", { name: "在清理提議" })).toBeTruthy();
    expect(screen.queryByText(/決策進度讀取失敗/)).toBeNull();
    expect(getTriage).toHaveBeenCalledTimes(1);
  });

  it("triage fails: the header stays, the body shows its own error, retry reloads triage only", async () => {
    vi.mocked(getTriage).mockRejectedValueOnce(new Error("網路錯誤"));
    renderPage();

    expect(await screen.findByText("網路錯誤")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: CAMPAIGN_NAME })).toBeTruthy();
    expect(screen.getByText("讀取失敗")).toBeTruthy();

    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    await userEvent.click(screen.getByRole("button", { name: "重新讀取" }));
    expect(await screen.findByRole("heading", { name: "在投 8 則對照上限 450" })).toBeTruthy();
    expect(listCampaigns).toHaveBeenCalledTimes(1);
  });

  it("campaign list fails or lacks this campaign: page-level error with retry", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    vi.mocked(listCampaigns).mockRejectedValueOnce(new Error("清單讀取失敗"));
    renderPage();
    expect(await screen.findByText("清單讀取失敗")).toBeTruthy();

    vi.mocked(listCampaigns).mockResolvedValue([campaignCard({ id: "cmp_other" })]);
    await userEvent.click(screen.getByRole("button", { name: "重新讀取" }));
    expect(await screen.findByText("找不到這個 Campaign。")).toBeTruthy();
  });

  it("no ads at all: says so, no ruler; all ads closed: only the closed fold", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([]));
    const { unmount } = renderPage();
    expect(await screen.findByText("沒有廣告資料，這個活動還沒有可以判斷的內容。")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /上限/ })).toBeNull();
    unmount();

    vi.mocked(getTriage).mockResolvedValue(triage([], {
      closed: { paused: 11, archived: 4, other: 0, total: 15, truncated: false, items: [{ entity_id: "c1", name: "舊版主視覺 0715", native_status: "PAUSED", thumbnail_url: null, spend: 321, cost_per_result: 45.5, result_label: "購買" }] },
    }));
    renderPage();
    expect(await screen.findByText("暫停 11・已封存 4・不列入判斷")).toBeTruthy();
    expect(detailsOf("已關閉").open).toBe(false);
    expect(screen.queryByText("沒有廣告資料，這個活動還沒有可以判斷的內容。")).toBeNull();
    expect(screen.queryByRole("region", { name: "對照上限" })).toBeNull();
  });

  it("?ad=: opens that ad's group, highlights its row and scrolls once; folding others never scrolls again", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    renderPage(`${WS}/detail?ad=a3`);

    await screen.findByRole("heading", { name: "在投 8 則對照上限 450" });
    expect(detailsOf("划算").open).toBe(true);
    expect(screen.getByTestId("ad-row-a3").className).toMatch(/ring-primary/);
    expect(scroll).toHaveBeenCalledTimes(1);

    const over = detailsOf("太貴");
    over.open = false;
    fireEvent(over, new Event("toggle"));
    expect(scroll).toHaveBeenCalledTimes(1);
  });

  it("an unknown ?ad= id is ignored", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    renderPage(`${WS}/detail?ad=nope`);
    await screen.findByRole("heading", { name: "在投 8 則對照上限 450" });
    expect(detailsOf("沒賣出").open).toBe(true);
    expect(detailsOf("划算").open).toBe(false);
  });

  it("chip labels: one missing day, many missing days as a range; mixed window lengths as a range", () => {
    expect(missingDaysLabel([])).toBeNull();
    expect(missingDaysLabel(["2026-09-17"])).toBe("缺 09/17，這天不計");
    expect(missingDaysLabel(["2026-09-24", "2026-08-28", "2026-09-01", "2026-09-02"])).toBe("缺 08/28–09/24 間 4 天，這些天不計");
    const a = ad("a1", "甲", "on_target", 100, 1);
    const b = ad("b1", "乙", "insufficient", 50, 0, OWN_450, { window: { start: "2026-08-27", end: "2026-09-23", days: 28, previous_start: "2026-07-30", previous_end: "2026-08-26", extended_from: 14 } });
    expect(windowLabel([a])).toBe("近 14 天 09/10–09/23");
    expect(windowLabel([a, b])).toBe("近 14–28 天 08/27–09/23");
  });
});
