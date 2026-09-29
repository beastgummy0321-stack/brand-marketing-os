/** F28-I10: campaign detail graded against the cap (prototype v9 `tabPerf()`). Covers the header cap chip, the ruler
 * card (title, window chip, missing-days chip, 去改上限, 打平 mark, empty ruler without a cap), default folds, the
 * rows' actions and ruler-dot navigation, `?ad=` deep links, and the three reads failing independently. Realistic
 * fixtures: the longest real names, decimal costs, 0 results, no cap, gap days, an imported campaign.
 * F40-I06 (prototype `#/perf`, `#/detail`): the 「這期狀態列」 on top of `CampaignPerfBody` (five cells, the backend's
 * period grade, the data-status chips, 重新讀取平台／結案這一期 opening the shared close dialog, closed／imported states)
 * and the two program lines under the ruler title (local ads never built, platform ads not built here). */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AbPair, AbPairsView, AbSide } from "@/lib/adsAbApi";
import { getAbPairs, pauseAbLoser } from "@/lib/adsAbApi";
import type { AdRow, CampaignCard as CampaignCardData, CampaignDetail, CampaignPerformance } from "@/lib/adsApi";
import { closeCampaign, getPerformance, listCampaigns } from "@/lib/adsApi";
import type { ChangeSet } from "@/lib/adsChangeApi";
import type { MaterialTask } from "@/lib/adsMaterialApi";
import { MaterialRequestError, cancelMaterialTask, createReplaceRequest, listMaterialTasks } from "@/lib/adsMaterialApi";
import type { CampaignDataStatus, CampaignTriage, QueueCleanup, QueueItem, QueuePayload, TriageClosedBlock, TriageItem } from "@/lib/adsTriageApi";
import { getQueue, getTriage } from "@/lib/adsTriageApi";
import { CampaignDetailPage, CampaignPerfBody, dataStatusChip, missingDaysLabel, programLines, windowLabel } from "./CampaignDetailPage";
import { missingDaysChip, periodDays } from "./PeriodStatusRow";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, listCampaigns: vi.fn(), getPerformance: vi.fn(), closeCampaign: vi.fn() };
});
// F40-I06: the status row reads the org clock (`useOrgClock` → `useWorkspace().identity.org`) for 「今天」 and the
// period's day count; the timezone is fixed to Taipei and `Date` is faked per case (timers stay real).
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({
    scope: "user:org", brands: [], brandsLoading: false, brandsError: null, refreshBrands: () => {},
    identity: {
      user: { id: "usr_1", email: "a@example.com" },
      org: { id: "org_test", name: "測試組織", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2020-01-01" },
      orgs: [],
    },
  }),
}));
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, getTriage: vi.fn(), getQueue: vi.fn() };
});
vi.mock("@/lib/adsAbApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsAbApi")>("@/lib/adsAbApi");
  return { ...actual, getAbPairs: vi.fn(), pauseAbLoser: vi.fn() };
});
vi.mock("@/lib/adsMaterialApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsMaterialApi")>("@/lib/adsMaterialApi");
  return { ...actual, listMaterialTasks: vi.fn(), createReplaceRequest: vi.fn(), cancelMaterialTask: vi.fn() };
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

/** The ruler card's title as a reader sees it: the glossary terms' hidden sentences are not part of it. */
async function rulerTitle(): Promise<string> {
  const h2 = (await screen.findByRole("region", { name: "對照上限" })).querySelector("h2")!.cloneNode(true) as HTMLElement;
  h2.querySelectorAll("[role=tooltip]").forEach((t) => t.remove());
  return h2.textContent ?? "";
}

// ---- A/B pairs (Contract F) and material requests (Contract H), real shapes ----
function side(o: Partial<AbSide> & { ad_id: string; name: string; value_label: string }): AbSide {
  return { entity_id: `e_${o.ad_id}`, thumbnail_url: null, spend: null, results: null, cost_per_result: null, ...o };
}
const RULES = { min_days: 7, min_conversions_each: 10, relative_difference: 0.1 };
function judgedPair(o: Partial<AbPair> = {}): AbPair {
  return {
    pair_id: "ad_a1:ad_a4", group_id: "g_a", group_name: "廣告組 A", dimension: "hook", dimension_label: "開場",
    a: side({ ad_id: "ad_a4", name: "開箱 15 秒・單手開蓋", value_label: "開箱畫面", spend: 560, results: 10, cost_per_result: 56 }),
    b: side({ ad_id: "ad_a1", name: "晨光隨行杯・日常出發", value_label: "出門情境", spend: 720, results: 16, cost_per_result: 45 }),
    window: { start: "2026-09-16", end: "2026-09-22" }, days: 7, rules: RULES, state: "judged",
    missing: { days: 0, a_results: 0, b_results: 0 }, winner: "b", difference_pct: 19.6,
    reason: "「開場」用「出門情境」比「開箱畫面」每次轉換成本低 19.6%", decision: null, ...o,
  };
}
function collectingPair(): AbPair {
  return {
    pair_id: "ad_a2:ad_a3", group_id: "g_a", group_name: "廣告組 A", dimension: "scene", dimension_label: "場景",
    a: side({ ad_id: "ad_a3", name: "辦公室一角・質感桌面", value_label: "辦公桌", spend: 330, results: 6, cost_per_result: 55 }),
    b: side({ ad_id: "ad_a2", name: "通勤情境單圖", value_label: "通勤路上", spend: 410, results: 11, cost_per_result: 37.27 }),
    window: { start: "2026-09-20", end: "2026-09-23" }, days: 4, rules: RULES, state: "collecting",
    missing: { days: 3, a_results: 4, b_results: 0 }, winner: null, difference_pct: null, reason: null, decision: null,
  };
}
const abView = (pairs: AbPair[]): AbPairsView => ({ pairs, unavailable: null });
function task(entityId: string, o: Partial<MaterialTask> = {}): MaterialTask {
  return {
    id: `mt_${entityId}`, campaign_id: "cmp_1", revision: 1, title: `換掉：${entityId}`, mode: "workbench_image", instruction: "",
    copy_fields: {} as MaterialTask["copy_fields"], prompt: { source: "none" }, reference_asset_ids: [], review_id: null,
    recommendation_id: null, review_context: null, content_hash: "h", candidates: [], selected_candidate_id: null,
    placement_id: null, placement_revision: null, placement_current: null, pack_id: null, dispatch_status: "not_requested",
    history: [], limitations: [], created_at: "2026-09-24T02:00:00Z",
    replaces: { entity_id: entityId, name: entityId, thumbnail_url: null }, cancelled_at: null, ...o,
  };
}
async function openMenu(rowId: string) {
  const row = screen.getByTestId(`ad-row-${rowId}`);
  await userEvent.click(within(row).getByText("⋯"));
  return row;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listCampaigns).mockResolvedValue([campaignCard()]);
  vi.mocked(getQueue).mockResolvedValue(queue([]));
  vi.mocked(getAbPairs).mockResolvedValue(abView([]));
  vi.mocked(listMaterialTasks).mockResolvedValue({ tasks: [] });
  Element.prototype.scrollIntoView = vi.fn(); // jsdom has none
});

describe("CampaignDetailPage (F28-I10, v10 tabPerf F29-I13)", () => {
  it("own cap: header chip 上限 450, ruler card title, window chip, 去改上限 → strategy tab, 打平 mark, legend once", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    const { container } = renderPage();

    expect(await rulerTitle()).toBe("在投 8 則對照上限 450");
    expect(screen.getByRole("heading", { level: 1, name: CAMPAIGN_NAME })).toBeTruthy();
    // The legend and the money rule print once per screen; the dashed 打平 mark is named under the ruler.
    expect(container.querySelectorAll("[data-slot=grade-rules]").length).toBe(1);
    expect(container.querySelectorAll("[data-slot=money-rule]").length).toBe(1);
    expect(screen.getByText(/^橘色虛線：/)).toBeTruthy();
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

  it("default folds: 沒賣出／太貴／偏貴 open, 划算 folded; rows carry 在清理提議／去處理, 看紀錄 in the ⋯ menu; bar 看清理提議", async () => {
    const items = dailyAds();
    vi.mocked(getTriage).mockResolvedValue(triage(items));
    vi.mocked(getQueue).mockResolvedValue(dailyQueue(items));
    renderPage();

    await rulerTitle();
    expect(detailsOf("沒賣出").open).toBe(true);
    expect(detailsOf("太貴").open).toBe(true);
    expect(detailsOf("偏貴").open).toBe(true);
    expect(detailsOf("划算").open).toBe(false);

    const wasted = screen.getByTestId("ad-row-a8");
    expect((await within(wasted).findByRole("link", { name: "在清理提議" })).getAttribute("href")).toBe(`${WS}/propose/cleanup/cmp_1`);
    expect(within(screen.getByTestId("ad-row-a7")).getByRole("link", { name: "在清理提議" })).toBeTruthy();
    expect(within(screen.getByTestId("ad-row-a6")).getByRole("link", { name: "去處理" }).getAttribute("href")).toBe(`${WS}/review/a6`);
    expect(within(wasted).getByText("0 筆")).toBeTruthy();
    expect(within(screen.getByTestId("ad-row-a7")).getByText("617.5 元")).toBeTruthy();
    expect(screen.getByRole("link", { name: "看清理提議 →" }).getAttribute("href")).toBe(`${WS}/propose/cleanup/cmp_1`);
    expect(screen.getByRole("link", { name: "← 總覽" }).getAttribute("href")).toBe(WS);

    const okRow = screen.getByTestId("ad-row-a1");
    expect(within(okRow).queryByRole("link")).toBeNull();
    await openMenu("a1");
    await userEvent.click(within(okRow).getByRole("button", { name: "看紀錄" }));
    expect(screen.getByTestId("where").textContent).toBe(`${WS}?tab=performance&ad=a1`);
  });

  it("no open cleanup: the bar has only ← 總覽", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    renderPage();
    await rulerTitle();
    expect(screen.queryByRole("link", { name: "看清理提議 →" })).toBeNull();
    expect(screen.getByRole("link", { name: "← 總覽" })).toBeTruthy();
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

  it("break-even cap (tgt:none): chip 暫用打平 520 in warn, title 暫用打平線, no separate 打平 mark or dashed-line note", async () => {
    const be: Cap = { value: 520, basis: "break_even", break_even: 520 };
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds(be)));
    renderPage();

    expect(await rulerTitle()).toBe("在投 8 則對照暫用打平線 520");
    expect(screen.getByText("暫用打平 520", { selector: "[data-slot=chip]" }).getAttribute("data-tone")).toBe("warn");
    expect(screen.queryByText("打平 520")).toBeNull();
    expect(screen.queryByText(/^橘色虛線：/)).toBeNull();
  });

  it("gap days (mid): the missing-days chip comes from data.status only; with only 划算／剛開始 every group stays folded", async () => {
    const items = [
      ad("m1", "中秋禮盒・隨行杯對杯組（家庭團圓情境）", "on_target", 5603, 35),
      ad("m2", "中秋限定・月光藍開箱", "insufficient", 120, 0),
      ad("m3", "送禮提案・長輩也會用的保溫杯", "insufficient", 180, 1),
    ];
    vi.mocked(getTriage).mockResolvedValue(triage(items, {
      data: {
        sync: { state: "ok", error: null, last_success_at: null }, coverage: null, missing_days: [],
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

  it("a broken read (auth_expired) is the ruler card's one chip, and the 資料不足 group's hint — the backend's sentence", async () => {
    const status: CampaignDataStatus = { state: "auth_expired", label: "平台授權已過期，重新連線後才能讀資料。", missing_days: [], last_success_at: null };
    const noData = ad("n1", "同步缺口那一則", "insufficient", null, null, OWN_450, { grade_label: "資料不足" });
    vi.mocked(getTriage).mockResolvedValue(triage([...dailyAds(), noData], {
      data: { sync: { state: "auth_expired", error: null, last_success_at: null }, coverage: null, missing_days: [], status },
    }));
    renderPage();

    const chip = await screen.findByText("平台授權已過期，重新連線後才能讀資料", { selector: "[data-slot=chip]" });
    expect(chip.getAttribute("data-state")).toBe("auth_expired");
    expect(within(detailsOf("資料不足").querySelector("summary")!).getByText("平台授權已過期，重新連線後才能讀資料。")).toBeTruthy();
    expect(within(screen.getByTestId("ad-row-n1")).getByText("未知")).toBeTruthy();
  });

  it("no cap and no product cost: 沒設上限 chip, the empty ruler, 去設上限, no legend, no money tags; every ad under 未判斷", async () => {
    const none: Cap = { value: null, basis: null, break_even: null };
    vi.mocked(getTriage).mockResolvedValue(triage([
      ad("a1", "晨光隨行杯・日常出發", "no_target", 1440, 30, none),
      ad("a2", "零成果的那一則", "no_target", 830.5, 0, none),
    ]));
    const { container } = renderPage();

    expect(await rulerTitle()).toBe("在投 2 則，沒設上限");
    expect(screen.getByText("沒設上限", { selector: "[data-slot=chip]" }).getAttribute("data-tone")).toBe("warn");
    expect(container.querySelector('[data-slot=target-ruler][data-variant="empty"]')).toBeTruthy();
    expect(screen.getByText("沒設上限，先不分等級", { selector: "div" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "去設上限" }).getAttribute("href")).toBe(`${WS}?tab=strategy`);
    expect(container.querySelector("[data-slot=grade-rules]")).toBeNull();
    expect(detailsOf("未判斷").open).toBe(false);
    expect(within(screen.getByTestId("ad-row-a2")).getByText("830.5 元")).toBeTruthy();
    expect(container.querySelector("[data-slot=money-tag]")).toBeNull();
  });

  it("own cap but no break-even (product cost unknown): no money tag anywhere, no dashed-line note", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds({ value: 450, basis: "own", break_even: null })));
    vi.mocked(getAbPairs).mockResolvedValue(abView([judgedPair()]));
    const { container } = renderPage();

    await screen.findByText("B 比較划算");
    expect(container.querySelector("[data-slot=money-tag]")).toBeNull();
    expect(screen.queryByText(/^橘色虛線：/)).toBeNull();
    expect(container.querySelectorAll("[data-slot=grade-rules]").length).toBe(1);
  });

  it("imported campaign with a long objective: 平台預算 chip, only the objective truncates; no A/B card, never read", async () => {
    const objective = "提高 Beast Prime 的購買數量，以購買次數為主要成效，這是一整句很長的匯入活動目標敘述用來測試截斷";
    vi.mocked(listCampaigns).mockResolvedValue([campaignCard({ origin: "imported", objective })]);
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    renderPage();

    expect(await screen.findByText("・8 則")).toBeTruthy();
    expect(screen.getByText("平台預算")).toBeTruthy();
    expect(screen.getByText(objective).className).toMatch(/truncate/);
    expect(screen.getByText("・8 則").className).not.toMatch(/truncate/);
    await rulerTitle();
    expect(screen.queryByTestId("ab-block")).toBeNull();
    expect(getAbPairs).not.toHaveBeenCalled();
  });

  it("queue fails: the ruler and groups stay, the queue shows its own failure and retries alone", async () => {
    const items = dailyAds();
    vi.mocked(getTriage).mockResolvedValue(triage(items));
    vi.mocked(getQueue).mockRejectedValueOnce(new Error("佇列讀取失敗"));
    renderPage();

    expect(await screen.findByText(/^決策進度讀不到（佇列讀取失敗）/)).toBeTruthy();
    expect(await rulerTitle()).toBe("在投 8 則對照上限 450");
    expect(within(screen.getByTestId("ad-row-a8")).queryByRole("link")).toBeNull();

    vi.mocked(getQueue).mockResolvedValue(dailyQueue(items));
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await within(screen.getByTestId("ad-row-a8")).findByRole("link", { name: "在清理提議" })).toBeTruthy();
    expect(screen.queryByText(/決策進度讀不到/)).toBeNull();
    expect(getTriage).toHaveBeenCalledTimes(1);
  });

  it("triage fails: the header stays, the body shows its own failure, retry reloads triage only", async () => {
    vi.mocked(getTriage).mockRejectedValueOnce(new Error("網路錯誤"));
    const { container } = renderPage();

    expect(await screen.findByText("成效讀不到：網路錯誤")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1, name: CAMPAIGN_NAME })).toBeTruthy();
    expect(container.querySelector("[data-slot=read-failed]")).toBeTruthy();
    expect(screen.queryByText("沒有廣告資料，這個活動還沒有可以判斷的內容。")).toBeNull();

    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await rulerTitle()).toBe("在投 8 則對照上限 450");
    expect(listCampaigns).toHaveBeenCalledTimes(1);
  });

  it("campaign list fails or lacks this campaign: page-level failure with retry", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    vi.mocked(listCampaigns).mockRejectedValueOnce(new Error("清單讀取失敗"));
    renderPage();
    expect(await screen.findByText("活動清單讀不到：清單讀取失敗")).toBeTruthy();

    vi.mocked(listCampaigns).mockResolvedValue([campaignCard({ id: "cmp_other" })]);
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText("找不到這個 Campaign。")).toBeTruthy();
  });

  it("no ads at all: says why from data.status; all ads closed: only 不在投的 and its fold", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([]));
    const { unmount } = renderPage();
    expect(await screen.findByText("沒有廣告資料，這個活動還沒有可以判斷的內容。")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /上限/ })).toBeNull();
    unmount();

    vi.mocked(getTriage).mockResolvedValue(triage([], {
      data: {
        sync: { state: "never", error: null, last_success_at: null }, coverage: null, missing_days: [],
        status: { state: "never", label: "還沒讀過平台資料。", missing_days: [], last_success_at: null },
      },
    }));
    const second = renderPage();
    expect(await screen.findByText("還沒讀過平台資料。")).toBeTruthy();
    second.unmount();

    vi.mocked(getTriage).mockResolvedValue(triage([], {
      closed: { paused: 11, archived: 4, other: 0, total: 15, truncated: false, items: [{ entity_id: "c1", name: "舊版主視覺 0715", native_status: "PAUSED", thumbnail_url: null, spend: 321, cost_per_result: 45.5, result_label: "購買" }] },
    }));
    renderPage();
    expect(await screen.findByText("暫停 11・已封存 4・不算在上面的在投數量裡")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 2, name: "不在投的" })).toBeTruthy();
    expect(detailsOf("已關閉的 15 則").open).toBe(false);
    expect(screen.queryByText("沒有廣告資料，這個活動還沒有可以判斷的內容。")).toBeNull();
    expect(screen.queryByRole("region", { name: "對照上限" })).toBeNull();
  });

  it("?ad=: opens that ad's group, highlights its row and scrolls once; folding others never scrolls again", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    renderPage(`${WS}/detail?ad=a3`);

    await rulerTitle();
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
    await rulerTitle();
    expect(detailsOf("沒賣出").open).toBe(true);
    expect(detailsOf("划算").open).toBe(false);
  });

  it("chip labels: one missing day, many missing days as a range; mixed window lengths as a range; data status", () => {
    expect(missingDaysLabel([])).toBeNull();
    expect(missingDaysLabel(["2026-09-17"])).toBe("缺 09/17，這天不計");
    expect(missingDaysLabel(["2026-09-24", "2026-08-28", "2026-09-01", "2026-09-02"])).toBe("缺 08/28–09/24 間 4 天，這些天不計");
    const a = ad("a1", "甲", "on_target", 100, 1);
    const b = ad("b1", "乙", "insufficient", 50, 0, OWN_450, { window: { start: "2026-08-27", end: "2026-09-23", days: 28, previous_start: "2026-07-30", previous_end: "2026-08-26", extended_from: 14 } });
    expect(windowLabel([a])).toBe("近 14 天 09/10–09/23");
    expect(windowLabel([a, b])).toBe("近 14–28 天 08/27–09/23");
    expect(dataStatusChip(null)).toBeNull();
    expect(dataStatusChip({ state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: null })).toBeNull();
    expect(dataStatusChip({ state: "syncing", label: "正在讀取平台的最新資料。", missing_days: [], last_success_at: null })).toBe("正在讀取平台的最新資料");
  });
});

describe("A/B block (F29-I13, v10 abBlock)", () => {
  it("judged + collecting pairs: one card between the ruler and the groups, 2 組, the kit pieces, 怎麼比的 folded", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    vi.mocked(getAbPairs).mockResolvedValue(abView([judgedPair(), collectingPair()]));
    const { container } = renderPage();

    const block = await screen.findByTestId("ab-block");
    expect(within(block).getByRole("heading", { name: "兩則只差一處的比較" })).toBeTruthy();
    expect(within(block).getByText("2 組")).toBeTruthy();
    expect(block.querySelector('[data-slot=ab-pair][data-variant="judged"]')).toBeTruthy();
    expect(block.querySelector('[data-slot=ab-pair][data-variant="collecting"]')).toBeTruthy();
    expect(within(block).getByText("B 比較划算")).toBeTruthy();
    expect(within(block).getByText("還差 3 天／A 還差 4 筆購買")).toBeTruthy();
    expect(within(block).getByRole("button", { name: "關掉輸家（A）→" })).toBeTruthy();
    expect(within(block).getByRole("button", { name: "怎麼比的" }).getAttribute("aria-expanded")).toBe("false");
    // Money tags inside the tiles use the campaign's break-even.
    expect(block.querySelectorAll("[data-slot=money-tag]").length).toBe(2);
    // Order: ruler card, A/B card, then the first grade group.
    const ruler = screen.getByRole("region", { name: "對照上限" });
    const firstGroup = container.querySelector("details.group")!;
    expect(ruler.compareDocumentPosition(block) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(block.compareDocumentPosition(firstGroup) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("關掉輸家 creates the ab pause set and opens its confirm step", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    vi.mocked(getAbPairs).mockResolvedValue(abView([judgedPair()]));
    vi.mocked(pauseAbLoser).mockResolvedValue({ id: "set_ab" } as ChangeSet);
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "關掉輸家（A）→" }));
    expect(pauseAbLoser).toHaveBeenCalledWith("brd_1", "cmp_1", "ad_a1:ad_a4", expect.any(String));
    expect((await screen.findByTestId("where")).textContent).toBe(`${WS}/changes/set_ab/confirm`);
  });

  it("pause-loser refused (409): the page stays and says why; a retry replays the same operation", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    vi.mocked(getAbPairs).mockResolvedValue(abView([judgedPair()]));
    vi.mocked(pauseAbLoser).mockRejectedValueOnce(new Error("輸家那則還沒對應到平台上的廣告，先完成上架核對。"));
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: "關掉輸家（A）→" }));
    expect(await screen.findByText("關掉輸家沒建立成：輸家那則還沒對應到平台上的廣告，先完成上架核對。")).toBeTruthy();
    expect(screen.queryByTestId("where")).toBeNull();
    expect(await rulerTitle()).toBe("在投 8 則對照上限 450");

    vi.mocked(pauseAbLoser).mockResolvedValue({ id: "set_ab" } as ChangeSet);
    await userEvent.click(screen.getByRole("button", { name: "關掉輸家（A）→" }));
    const ops = vi.mocked(pauseAbLoser).mock.calls.map((c) => c[3]);
    expect(ops[0]).toBe(ops[1]);
  });

  it("decided pairs show their state: draft → confirm, approved → 等你到 Meta 完成 + 繼續, readback → 繼續 to verify, confirmed, rejected", async () => {
    type Decision = NonNullable<AbPair["decision"]>;
    const decision = (status: Decision["status"], verification_state: Decision["verification_state"]): Decision =>
      ({ change_set_id: `set_${status}_${verification_state}`, status, verification_state });
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    vi.mocked(getAbPairs).mockResolvedValue(abView([
      judgedPair({ pair_id: "p1", decision: decision("draft", null) }),
      judgedPair({ pair_id: "p2", decision: decision("approved", "pending") }),
      judgedPair({ pair_id: "p3", decision: decision("approved", "reported") }),
      judgedPair({ pair_id: "p4", decision: decision("approved", "confirmed") }),
      judgedPair({ pair_id: "p5", decision: decision("rejected", null) }),
    ]));
    renderPage();

    const block = await screen.findByTestId("ab-block");
    expect(within(block).getByRole("link", { name: "關掉輸家（A）→" }).getAttribute("href")).toBe(`${WS}/changes/set_draft_null/confirm`);
    expect(within(block).getByText("已核准・等你到 Meta 完成")).toBeTruthy();
    const next = within(block).getAllByRole("link", { name: "繼續 →" }).map((l) => l.getAttribute("href"));
    expect(next).toEqual([`${WS}/changes/set_approved_pending/handoff`, `${WS}/changes/set_approved_reported/verify`]);
    expect(within(block).getByText("已核准・核對中")).toBeTruthy();
    expect(within(block).getByText(/^✓ 已關掉 A・寫進/)).toBeTruthy();
    expect(within(block).getByText("你決定兩則都留")).toBeTruthy();
    expect(within(block).queryByRole("button", { name: /關掉輸家/ })).toBeNull();
  });

  it("an unreadable pair names why; no pairs → no card at all", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    vi.mocked(getAbPairs).mockResolvedValue(abView([{
      ...judgedPair(), state: "unreadable", winner: null, difference_pct: null,
      reason: "缺 2026-09-17、2026-09-18 的資料；缺資料不當成零。",
    }]));
    const { unmount } = renderPage();
    const block = await screen.findByTestId("ab-block");
    expect(block.querySelector('[data-slot=ab-pair][data-variant="unreadable"]')).toBeTruthy();
    expect(within(block).getByText("缺 2026-09-17、2026-09-18 的資料；缺資料不當成零。")).toBeTruthy();
    expect(within(block).queryByRole("button", { name: /關掉輸家/ })).toBeNull();
    unmount();

    vi.mocked(getAbPairs).mockResolvedValue(abView([]));
    renderPage();
    await rulerTitle();
    await vi.waitFor(() => expect(getAbPairs).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId("ab-block")).toBeNull();
    expect(screen.queryByText("兩則只差一處的比較")).toBeNull();
  });

  it("the A/B read fails: its own failure with retry, never an empty or hidden block", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    vi.mocked(getAbPairs).mockRejectedValueOnce(new Error("讀取 A/B 比較失敗。"));
    renderPage();

    expect(await screen.findByText(/^兩則比較讀不到（讀取 A\/B 比較失敗。）/)).toBeTruthy();
    vi.mocked(getAbPairs).mockResolvedValue(abView([judgedPair()]));
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByTestId("ab-block")).toBeTruthy();
  });
});

describe("換掉這一則 (F29-I13, v10 row menu)", () => {
  it("opens a request from the ⋯ menu: the row says 需求已開 and the menu offers 取消換掉這一則", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    vi.mocked(createReplaceRequest).mockResolvedValue({ task: task("a7") });
    renderPage();

    await rulerTitle();
    const row = await openMenu("a7");
    expect(within(row).getByText("⋯").closest("summary")!.getAttribute("aria-label")).toBe("更多：提問式貼文・早晨第一口是什麼？");
    await userEvent.click(within(row).getByRole("button", { name: "換掉這一則" }));
    expect(createReplaceRequest).toHaveBeenCalledWith("brd_1", "cmp_1", "a7");
    expect(await within(row).findByText("換掉這一則・需求已開")).toBeTruthy();
    expect(within(row).getByRole("button", { name: "取消換掉這一則" })).toBeTruthy();
    expect(within(row).queryByRole("button", { name: "換掉這一則" })).toBeNull();
  });

  it("a request already in the material list shows on its row; cancelling withdraws it", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    vi.mocked(listMaterialTasks).mockResolvedValue({ tasks: [task("a6"), task("a1", { replaces: null })] });
    vi.mocked(cancelMaterialTask).mockResolvedValue({ task: task("a6", { cancelled_at: "2026-09-25T01:00:00Z" }) });
    renderPage();

    const row = await screen.findByTestId("ad-row-a6");
    expect(await within(row).findByText("換掉這一則・需求已開")).toBeTruthy();
    expect(within(screen.getByTestId("ad-row-a1")).queryByText("換掉這一則・需求已開")).toBeNull();
    await openMenu("a6");
    await userEvent.click(within(row).getByRole("button", { name: "取消換掉這一則" }));
    expect(cancelMaterialTask).toHaveBeenCalledWith("brd_1", "cmp_1", "mt_a6");
    await vi.waitFor(() => expect(within(row).queryByText("換掉這一則・需求已開")).toBeNull());
    expect(within(row).getByRole("button", { name: "換掉這一則" })).toBeTruthy();
  });

  it("a failed create or cancel keeps the page, says why on the row and keeps the old state", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(dailyAds()));
    vi.mocked(listMaterialTasks).mockResolvedValue({ tasks: [task("a6")] });
    vi.mocked(createReplaceRequest).mockRejectedValue(new MaterialRequestError("網路中斷，請再試一次。", 503));
    vi.mocked(cancelMaterialTask).mockRejectedValue(new MaterialRequestError("此素材需求已被核准的變更清單採用，不能取消。", 409));
    renderPage();

    const created = await screen.findByTestId("ad-row-a7");
    await openMenu("a7");
    await userEvent.click(within(created).getByRole("button", { name: "換掉這一則" }));
    expect((await within(created).findByRole("alert")).textContent).toBe("換掉這一則沒送出：網路中斷，請再試一次。");
    expect(within(created).queryByText("換掉這一則・需求已開")).toBeNull();

    const inUse = screen.getByTestId("ad-row-a6");
    await within(inUse).findByText("換掉這一則・需求已開");
    await openMenu("a6");
    await userEvent.click(within(inUse).getByRole("button", { name: "取消換掉這一則" }));
    expect((await within(inUse).findByRole("alert")).textContent).toBe("取消換掉這一則沒成功：此素材需求已被核准的變更清單採用，不能取消。");
    expect(within(inUse).getByText("換掉這一則・需求已開")).toBeTruthy();
    expect(await rulerTitle()).toBe("在投 8 則對照上限 450");
  });

  it("the material list fails: its own failure with retry; the rows and their decisions stay", async () => {
    const items = dailyAds();
    vi.mocked(getTriage).mockResolvedValue(triage(items));
    vi.mocked(getQueue).mockResolvedValue(dailyQueue(items));
    vi.mocked(listMaterialTasks).mockRejectedValueOnce(new MaterialRequestError("素材任務讀取失敗", 500));
    renderPage();

    expect(await screen.findByText(/^素材需求讀不到（素材任務讀取失敗）/)).toBeTruthy();
    expect(await within(screen.getByTestId("ad-row-a8")).findByRole("link", { name: "在清理提議" })).toBeTruthy();
    vi.mocked(listMaterialTasks).mockResolvedValue({ tasks: [task("a8")] });
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await within(screen.getByTestId("ad-row-a8")).findByText("換掉這一則・需求已開")).toBeTruthy();
    expect(screen.queryByText(/素材需求讀不到/)).toBeNull();
  });
});

// ---- F40-I06: the 這期狀態列 and the program lines (prototype `#/perf` with its 「還有 2 天沒讀到」 toggle, `#/detail`) ----
const CAP_450 = { value: 450, basis: "own" as const, own_value: 450, break_even: 520, price: 998, product_id: "prd_1", result_kind: "purchase", result_label: "購買", missing: [], revision: 1 };
function localAd(id: string, name: string, local_state: AdRow["local_state"]): AdRow {
  return {
    id, campaign_id: "cmp_1", group_id: "grp_1", name, audience_key: null, pain_key: null, angle_key: null, hook_key: null,
    proof_key: null, offer_key: null, format_key: null, coordinates_snapshot_json: {}, product_id: null,
    asset_ready_source: null, asset_ready_by: null, asset_ready_at: null,
    external_id: local_state === "bound" ? `ext_${id}` : null, external_name: null, external_status: null, local_state, bound_at: null,
  } as unknown as AdRow;
}
/** The drill-7 period-2 shape: 4 built ads, 2 never built (缺圖). */
function campaignDetail(o: Partial<CampaignDetail> = {}, ads?: AdRow[]): CampaignDetail {
  return {
    id: "cmp_1", name: "10 月第一期・讀書與運動", objective: "購買", origin: "internal", status: "live", cap: CAP_450,
    start_date: "2026-09-26", end_date: "2026-10-02", context_json: {}, constraints_json: {}, verdict: null, verdict_json: {},
    capabilities: { allowed: [], unavailable: {} }, external_view: null,
    groups: [{
      id: "grp_1", campaign_id: "cmp_1", channel_key: "meta", name: "新客", role: "new", daily_budget: 1500, start_date: null, end_date: null,
      external_id: "ext_g", external_name: null, external_status: null, local_state: "bound", bound_at: null,
      ads: ads ?? [
        localAd("l1", "運動後與忙碌日常", "bound"), localAd("l2", "早晨通勤", "bound"), localAd("l3", "深夜讀書", "bound"),
        localAd("l4", "上班日午休", "bound"), localAd("l5", "週末補眠", "unbound"), localAd("l6", "考前衝刺", "unbound"),
      ],
    }],
    ...o,
  } as unknown as CampaignDetail;
}
type BodyProps = Partial<Parameters<typeof CampaignPerfBody>[0]>;
function renderBody(c: CampaignDetail, extra: BodyProps = {}) {
  const onCampaignChange = vi.fn();
  const onSync = vi.fn();
  const view = (p: BodyProps) => (
    <MemoryRouter initialEntries={[`${WS}?tab=perf`]}>
      <CampaignPerfBody brandId="brd_1" campaignId="cmp_1" origin={c.origin} campaign={c} onCampaignChange={onCampaignChange} onSync={onSync} {...extra} {...p} />
    </MemoryRouter>
  );
  const utils = render(view({}));
  return { onCampaignChange, onSync, rerender: (p: BodyProps) => utils.rerender(view(p)) };
}

describe("這期狀態列 (F40-I06, prototype #/perf)", () => {
  /** `getPerformance` as the backend answers for the same period: 10,081 spent, 19 bought, the period graded 偏貴. */
  function perf(o: Partial<CampaignPerformance["coverage"]> = {}, totals: Partial<CampaignPerformance["totals"]> = {}): CampaignPerformance {
    return {
      totals: { spend: 10081, impressions: 90000, clicks: 1200, purchases: 19, revenue: 18962, cpa: 530.58, ctr: 0.0133, roas: 1.88, roas_conservative: 1.88, grade: { grade: "watch", label: "偏貴" }, ...totals },
      daily: [], groups: [], ads: [],
      coverage: { start: "2026-09-26", end: "2026-10-02", expected: 7, missing: 0, missing_days: [], never_synced: false, ...o },
      last_data_at: "2026-10-02T13:00:00Z",
    };
  }
  /** The 4 platform ads: 3 bound to local ads, 1 built elsewhere (`bound_ad_id: null`). */
  function platformAds(): TriageItem[] {
    return [
      ad("a1", "運動後與忙碌日常", "on_target", 3120, 9, OWN_450, { bound_ad_id: "l1" }),
      ad("a2", "早晨通勤", "watch", 2760, 6, OWN_450, { bound_ad_id: "l2" }),
      ad("a3", "深夜讀書", "over", 2601, 4, OWN_450, { bound_ad_id: "l3" }),
      ad("a4", "上班日午休（平台手動建）", "wasted", 1600, 0, OWN_450, { bound_ad_id: null }),
    ];
  }
  const row = () => screen.getByTestId("period-status-row");
  /** Cell text as a reader sees it: one space between elements, the glossary tooltips removed. */
  const readable = (node: Node): string => node.nodeType === Node.TEXT_NODE
    ? node.textContent ?? ""
    : (node as Element).getAttribute?.("role") === "tooltip" ? "" : [...node.childNodes].map(readable).join(" ");
  const cellText = (label: string) => readable(within(row()).getByText(label, { selector: "span" }).parentElement!).replace(/\s+/g, " ").trim();

  beforeEach(() => {
    // Org today = 2026-10-03 (Taipei), the day after the period ends — the prototype's 「今天 10/03」.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-03T04:00:00Z"));
    vi.mocked(getTriage).mockResolvedValue(triage(platformAds(), { data: { sync: { state: "ok", error: null, last_success_at: "2026-10-02T13:00:00Z" }, coverage: null, missing_days: [], status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: null } } }));
    vi.mocked(getPerformance).mockResolvedValue(perf());
  });
  afterEach(() => vi.useRealTimers());

  it("live: five cells from getPerformance totals, the backend's grade chip 對上限 450, 平台已讀到, both buttons and the 整期 caption", async () => {
    renderBody(campaignDetail());
    expect(await within(row()).findByText("10,081 元")).toBeTruthy();
    expect(cellText("期間")).toBe("期間 09/26～10/02 7 天");
    expect(cellText("花費")).toBe("花費 10,081 元 整期合計");
    expect(cellText("購買")).toBe("購買 19 筆 平台回報");
    expect(cellText("每賣一筆")).toBe("每賣一筆 531 元 偏貴 對上限 450");
    expect(cellText("ROAS")).toBe("ROAS 1.88 營收 ÷ 花費");
    const grade = within(row()).getByText("偏貴").closest("[data-slot=chip]")!;
    expect(grade.getAttribute("data-grade")).toBe("watch");
    expect(within(row()).getByText("09/26 開始・10/02 結束・今天 10/03")).toBeTruthy();
    const ready = within(row()).getByText("平台已讀到 09/26～10/02");
    expect(ready.getAttribute("data-tone")).toBe("ok");
    expect(within(row()).getByText("最新 10/02 21:00")).toBeTruthy();
    expect(within(row()).getByRole("button", { name: "重新讀取平台" })).toBeTruthy();
    expect(within(row()).getByRole("button", { name: "結案這一期 →" })).toBeTruthy();
    expect(within(row()).getByText("結案後這期成績寫進筆記本，下一期照它規劃")).toBeTruthy();
    expect(within(row()).getByText("整期＝活動期間的合計；每月回顧只算當月天數，同一則廣告兩邊數字會不同。")).toBeTruthy();
    expect(within(row()).queryByText("已結案")).toBeNull();
    // The row sits above the ruler card.
    const region = await screen.findByRole("region", { name: "對照上限" });
    expect(row().compareDocumentPosition(region) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("missing days: the warning chip names them, 不算 0; the read range and the close caption change; the grade stays the backend's", async () => {
    vi.mocked(getPerformance).mockResolvedValue(perf({ missing: 2, missing_days: ["2026-10-02", "2026-10-01"] }, { grade: { grade: "insufficient", label: "資料不足" } }));
    renderBody(campaignDetail());
    const warn = await within(row()).findByText("10/01、10/02 沒讀到，不算 0");
    expect(warn.getAttribute("data-tone")).toBe("warn");
    expect(within(row()).getByText("平台已讀到 09/26～09/30・最新 10/02 21:00")).toBeTruthy();
    expect(within(row()).queryByText("平台已讀到 09/26～10/02")).toBeNull();
    expect(within(row()).getByText("會先問要不要重新讀取，再結案")).toBeTruthy();
    expect(within(row()).getByText("資料不足").closest("[data-slot=chip]")!.getAttribute("data-grade")).toBe("insufficient");
    expect(within(row()).getByRole("button", { name: "結案這一期 →" })).toBeTruthy();
  });

  it("重新讀取平台 calls the workspace's sync; while it runs the button says 讀取中…; when it ends the row re-reads its numbers", async () => {
    const { onSync, rerender } = renderBody(campaignDetail());
    await within(row()).findByText("10,081 元");
    fireEvent.click(within(row()).getByRole("button", { name: "重新讀取平台" }));
    expect(onSync).toHaveBeenCalledTimes(1);
    rerender({ syncing: true });
    expect((within(row()).getByRole("button", { name: "讀取中…" }) as HTMLButtonElement).disabled).toBe(true);
    vi.mocked(getPerformance).mockResolvedValue(perf({}, { spend: 11581, purchases: 21 }));
    rerender({ syncing: false });
    expect(await within(row()).findByText("11,581 元")).toBeTruthy();
    expect(getPerformance).toHaveBeenCalledTimes(2);
  });

  it("結案這一期 opens the shared close dialog; 確認結案 closes through closeCampaign and hands the campaign back", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const closed = campaignDetail({ status: "closed", verdict: "達成" });
    vi.mocked(closeCampaign).mockResolvedValue(closed);
    const { onCampaignChange } = renderBody(campaignDetail());
    await within(row()).findByText("10,081 元");
    await user.click(within(row()).getByRole("button", { name: "結案這一期 →" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/結案後會對照成功條件寫下判定/)).toBeTruthy();
    expect(within(dialog).getByText(/提前結案會用到目前為止的成效判定/)).toBeTruthy(); // live: the early-close sentence
    await user.click(within(dialog).getByRole("button", { name: "確認結案" }));
    expect(closeCampaign).toHaveBeenCalledWith("brd_1", "cmp_1");
    expect(onCampaignChange).toHaveBeenCalledWith(closed);
  });

  it("closed: the numbers stay, the buttons are gone, the chip says 已結案", async () => {
    renderBody(campaignDetail({ status: "closed", verdict: "達成", closed_at: "2026-10-03T02:00:00Z" }));
    expect(await within(row()).findByText("10,081 元")).toBeTruthy();
    expect(within(row()).getByText("已結案")).toBeTruthy();
    expect(within(row()).queryByRole("button", { name: "結案這一期 →" })).toBeNull();
    expect(within(row()).queryByRole("button", { name: "重新讀取平台" })).toBeNull();
    expect(within(row()).queryByText(/結案後這期成績/)).toBeNull();
  });

  it("imported: no close button, the capability's own sentence; totals come from the native view, never getPerformance", async () => {
    const view = {
      entities: [{ id: "e1", platform: "meta", source_account: "act_1", native_kind: "adset", native_id: "n1", native_label: null, name: "新客", parent_native_id: null, native_status: "ACTIVE", start_date: null, end_date: null, budget_amount: null, budget_type: "daily", budget_raw: {}, currency: "TWD", last_success_at: "2026-10-02T13:00:00Z", sync_error: null, creative: {} }],
      observations: [{ id: "o1", entity_id: "e1", day: "2026-10-01", metric_scope: "adset", attribution_key: "default", currency: "TWD", spend: 500, impressions: 100, clicks: 10, purchases: 2, revenue: 1996, availability: {} }],
      next_entity_cursor: null, next_observation_cursor: null, window: { start: "2026-09-26", end: "2026-10-02" }, connections: [],
      sync: { entities: { status: "ok", last_success_at: "2026-10-02T13:00:00Z" }, observations: { status: "ok", last_success_at: "2026-10-02T13:30:00Z" } }, coverage: {},
    } as unknown as CampaignDetail["external_view"];
    renderBody(campaignDetail({ origin: "imported", capabilities: { allowed: [], unavailable: { close: "既有平台活動不使用內部結案。" } }, external_view: view }), { origin: "imported" });
    expect(await within(row()).findByText("500 元")).toBeTruthy();
    expect(cellText("購買")).toBe("購買 2 筆 平台回報");
    expect(within(row()).queryByRole("button", { name: "結案這一期 →" })).toBeNull();
    expect(within(row()).getByRole("button", { name: "重新讀取平台" })).toBeTruthy();
    expect(within(row()).getByText("既有平台活動不使用內部結案。")).toBeTruthy();
    expect(within(row()).getByText("最新 10/02 21:30")).toBeTruthy(); // the newest external_view.sync section
    expect(within(row()).getByText("未判斷").closest("[data-slot=chip]")!.getAttribute("data-grade")).toBe("no_target");
    expect(getPerformance).not.toHaveBeenCalled();
  });

  it("the totals read fails on its own: the row keeps its buttons and says why with 重試; the ruler card still renders", async () => {
    vi.mocked(getPerformance).mockRejectedValueOnce(new Error("伺服器忙碌"));
    renderBody(campaignDetail());
    expect(await within(row()).findByText(/整期合計讀不到：伺服器忙碌/)).toBeTruthy();
    expect(within(row()).getByRole("button", { name: "結案這一期 →" })).toBeTruthy();
    expect(await screen.findByRole("region", { name: "對照上限" })).toBeTruthy();
    fireEvent.click(within(row()).getByRole("button", { name: "重試" }));
    expect(await within(row()).findByText("10,081 元")).toBeTruthy();
  });

  it("a draft (DraftPerf's case) or no campaign handed in (the standalone page): no row, no totals read", async () => {
    renderBody(campaignDetail({ status: "draft" }));
    expect(await screen.findByRole("region", { name: "對照上限" })).toBeTruthy();
    expect(screen.queryByTestId("period-status-row")).toBeNull();
    expect(getPerformance).not.toHaveBeenCalled();
  });

  it("period helpers: days count through today only; a long gap prints as a range", () => {
    expect(periodDays("2026-09-26", "2026-10-02", "2026-10-03")).toBe(7);
    expect(periodDays("2026-09-26", "2026-10-31", "2026-10-03")).toBe(8); // still running: through today
    expect(periodDays("2026-10-05", "2026-10-31", "2026-10-03")).toBe(0); // not started
    expect(periodDays(null, null, "2026-10-03")).toBeNull();
    expect(missingDaysChip(["2026-10-02"])).toBe("10/02 沒讀到，不算 0");
    expect(missingDaysChip(["2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30"])).toBe("09/27–09/30 間 4 天 沒讀到，不算 0");
  });
});

describe("在投 N 則 counts platform ads only (F40-I06, prototype #/detail)", () => {
  const built = [ad("a1", "運動後與忙碌日常", "on_target", 3120, 9, OWN_450, { bound_ad_id: "l1" }), ad("a2", "早晨通勤", "watch", 2760, 6, OWN_450, { bound_ad_id: "l2" })];
  // A draft campaign: no status row, only the program lines are under test here.
  const withAds = (ads: AdRow[]) => campaignDetail({ status: "draft" }, ads);

  it("unbuilt local ads: the 缺圖 line names them with 到素材補圖 → the assets tab; the title still counts the platform ads", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(built));
    renderBody(withAds([localAd("l1", "運動後與忙碌日常", "bound"), localAd("l5", "週末補眠", "unbound"), localAd("l6", "考前衝刺", "unbound")]));
    expect(await rulerTitle()).toBe("在投 2 則對照上限 450");
    expect(screen.getByTestId("unbuilt-line").textContent).toBe("另有 2 則沒建到平台（缺圖），不算在投：週末補眠、考前衝刺");
    expect(screen.getByRole("link", { name: "到素材補圖 →" }).getAttribute("href")).toBe(`${WS}?tab=assets`);
    expect(screen.queryByTestId("unmatched-line")).toBeNull();
  });

  it("platform ads not built here (bound_ad_id null): their own line; an older item without the field is not counted", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage([...built, ad("a4", "上班日午休（平台手動建）", "wasted", 1600, 0, OWN_450, { bound_ad_id: null }), ad("a5", "舊工廠沒帶欄位", "on_target", 900, 3)]));
    renderBody(withAds([localAd("l1", "運動後與忙碌日常", "bound")]));
    expect(await rulerTitle()).toBe("在投 4 則對照上限 450");
    expect(screen.getByTestId("unmatched-line").textContent).toBe("平台上另有 1 則不是這裡建的：上班日午休（平台手動建）");
    expect(screen.queryByTestId("unbuilt-line")).toBeNull();
  });

  it("every local ad built and every platform ad matched, or no campaign handed in: no program lines", async () => {
    vi.mocked(getTriage).mockResolvedValue(triage(built));
    renderBody(withAds([localAd("l1", "運動後與忙碌日常", "bound"), localAd("l2", "早晨通勤", "bound")]));
    await rulerTitle();
    expect(screen.queryByTestId("program-lines")).toBeNull();
    expect(programLines(built, undefined)).toEqual({ unbuilt: [], unmatched: [] });
  });
});
