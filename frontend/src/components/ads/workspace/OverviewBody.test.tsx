/** F30-I07: the workspace overview in its three states (prototype v10 `tabOverview()`, `kvNumbers()`): draft checklist
 * with k／4 and the ruler preview; the data gap (per-ad distance to a judgeable sample, missing days, the reason chip);
 * live (the next open decision or 「沒有要決定的事」, the four 14-day numbers, the in-flight ruler). Every extra read
 * fails on its own; unknown numbers stay unknown. Realistic fixtures: prototype names, decimal costs, a closing ad. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CampaignDetail } from "@/lib/adsApi";
import { getQueue, getTriage, type CloseoutQueueRow, type QueueItem, type QueuePayload } from "@/lib/adsTriageApi";
import { getCampaignStructure, type CampaignStructure, type CampaignWorkspace, type StructureAd } from "@/lib/adsWorkspaceApi";
import { RULES_FIXTURE, seedAdsRules } from "../patterns/rulesFixture";
import { OverviewBody, dayRange } from "./OverviewBody";
// F50 Contract K: the org clock reads the workspace org zone; dates assert Asia/Taipei output, never the runner's.
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-10-01" }, orgs: [] } }) }));

vi.mock("@/lib/adsWorkspaceApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsWorkspaceApi")>("@/lib/adsWorkspaceApi");
  return { ...actual, getCampaignStructure: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, getQueue: vi.fn(), getTriage: vi.fn() };
});

const CAP = { value: 450, basis: "own", own_value: 450, break_even: 520, price: 1580, product_id: "prd_cup", result_kind: "purchase", result_label: "購買", missing: [], revision: 1 };
const NO_CAP = { ...CAP, value: null, basis: null, own_value: null, break_even: null, product_id: "prd_fall", knowledge_product_id: "kp_fall" };
function detail(o: Partial<CampaignDetail> = {}): CampaignDetail {
  return { id: "cmp_daily", name: "日常商品推廣・轉換", objective: "購買", origin: "internal", status: "live", lifecycle: LIVE, cap: CAP,
    budget_planned: 30000, labels: { conversion: "購買", count: "購買數", cpa: "每次購買成本" }, groups: [], ...o } as unknown as CampaignDetail;
}
const DRAFT = { cap_set: false, budget_set: false, slots_ready: 7, slots_total: 8, launch_checked: 0, launch_total: 0 };
function ws(o: Partial<CampaignWorkspace> = {}): CampaignWorkspace {
  return { stage: { key: "decide", done: ["plan", "assets", "launch", "read"] }, pending_count: 2, delivery: "live", daily_budget: 1200, active_ads: 8, can_support: 6,
    next_sync_at: "2026-09-23T04:40:00Z", missing_days: [],
    totals: { start: "2026-09-10", end: "2026-09-23", currency: "TWD", spend: 15767, results: 121, cost_per_result: 130.31 }, draft: null, ...o };
}
/** `GET …/structure` serves `reason_code` and `sample` beside each grade (F48 Contract R). */
function ad(id: string, name: string, spend: number, results: number, grade: StructureAd["grade"], o: Partial<StructureAd> = {}): StructureAd {
  return { ad_id: `pad_${id}`, entity_id: id, name, thumbnail_url: null, spend, results, grade,
    grade_label: grade === "insufficient" ? "剛開始、數字還不夠" : null,
    reason_code: grade === "insufficient" ? "too_new" : grade === "wasted" ? "spend_over_target_no_result" : null, sample: null,
    cost_per_result: results ? Math.round((spend / results) * 100) / 100 : null,
    closing: false, missing_material: false, ...o };
}
const DAILY: CampaignStructure = { groups: [
  { group_id: "g_a", name: "A・廣泛受眾", daily_budget: 400, ads: [
    ad("a1", "晨光隨行杯・日常出發", 1440, 30, "on_target"),
    ad("a2", "晨光隨行杯・隨時有你｜好攜帶，走到哪都適合（通勤情境單圖・最多數量 1150706）", 1407, 28, "on_target"),
  ] },
  { group_id: "g_b", name: "B・再行銷 30 天", daily_budget: 800, ads: [
    ad("a6", "再行銷・兩入組 NT$1,580 免運 - 複本 2", 3120, 6, "watch"),
    ad("a7", "提問式貼文・早晨第一口是什麼？", 2470, 4, "over"),
    ad("a8", "秋季新色預告・直式 9:16 短影音", 1480, 0, "wasted"),
    ad("a9", "舊版主視覺 0715", 900, 1, "insufficient", { closing: true }),
    ad("x1", "還沒上架的一則", 0, 0, null, { entity_id: null }),
  ] },
] };
function triageOf(id: string, o: Record<string, unknown> = {}) {
  return { entity_id: id, name: id, campaign_id: "cmp_daily", thumbnail_url: null, grade_move: null,
    current: { spend: 3120, result_count: 6, cost_per_result: 520 }, ...o };
}
/** F49 Contract Q: every row as `queue_done.stamp` serves it — `decision`, `done`, `position` (1-based over the brand's
 * open decision rows in board order, null on a done row or a notice) and its `campaign_id`. */
function cleanupRow(position: number | null = 1): QueueItem {
  return { id: "q1", brand_id: "brd_1", kind_key: "cleanup", proposal: null, action_url: "/brands/brd_1/ads/campaigns/cmp_daily/propose/cleanup/cmp_daily",
    campaign_id: "cmp_daily", decision: true, done: position === null, position,
    triage: triageOf("a8"), cleanup: { campaign_id: "cmp_daily", campaign_name: "日常商品推廣・轉換", can_support: 6, active_ads: 8,
      ads: [{ entity_id: "a8" }, { entity_id: "a7" }], keep: [{}, {}, {}, {}, {}, {}], short: 0, daily_saving: 260, scale_owner_id: null } } as unknown as QueueItem;
}
function worseRow(campaign = "cmp_daily", position: number | null = 2): QueueItem {
  return { id: `q2_${campaign}`, brand_id: "brd_1", kind_key: "worse", proposal: null, action_url: null,
    campaign_id: campaign, decision: true, done: position === null, position,
    triage: triageOf("a6", { campaign_id: campaign, name: "再行銷・兩入組 NT$1,580 免運 - 複本 2", grade_move: { from: "on_target", to: "watch" } }) } as unknown as QueueItem;
}
/** A notice row (Contract Q: `scale_budget` is shown on the money card, never a decision). */
function scaleNotice(): QueueItem {
  return { id: "q9", brand_id: "brd_1", kind_key: "scale_budget", proposal: null, action_url: null, campaign_id: "cmp_daily",
    decision: false, done: false, position: null, triage: triageOf("a1") } as unknown as QueueItem;
}
/** The ended campaign's closeout row as served (`kind_key: "closeout"`, split into `closeouts`). */
function closeoutRow(position = 1, running: { count: number; read_at: string | null } = { count: 2, read_at: "2026-10-11T04:30:00Z" }): CloseoutQueueRow {
  return { id: "q_close", dedupe_key: "ads-closeout:cmp_daily", category: "ads_triage_closeout", severity: "warning",
    message: "「日常商品推廣・轉換」已結束，待結案", action_url: "/brands/brd_1/ads/campaigns/cmp_daily?tab=perf&close=1",
    visible_from: null, status: "open", created_at: "2026-10-10T00:00:00Z", campaign_id: "cmp_daily", decision: true, position, done: false,
    closeout: { campaign_id: "cmp_daily", campaign_name: "日常商品推廣・轉換", end_date: "2026-10-09", running } } as unknown as CloseoutQueueRow;
}
const queue = (items: QueueItem[], closeouts: CloseoutQueueRow[] = []) => ({
  items, closeouts, counts: {}, total_ads: 0, kinds_available: [], kinds_pending: [],
  decisions: { kinds: ["cleanup", "worse", "closeout", "settle", "refresh_creative"], open: [...items, ...closeouts].filter((r) => typeof r.position === "number").length },
}) as unknown as QueuePayload;
const LIVE = { state: "live", label: "投放中", can_close: true } as const;
const ENDED = { state: "ended", label: "已結束・待結案", can_close: true } as const;
const CLOSED = { state: "closed", label: "已結案", can_close: false } as const;

function renderBody(c: CampaignDetail, w: CampaignWorkspace, canPublish = true) {
  const onGo = vi.fn();
  const view = render(<MemoryRouter><OverviewBody brandId="brd_1" campaign={c} workspace={w} canPublish={canPublish} onGo={onGo} advanced={<p>舊總覽內容</p>} /></MemoryRouter>);
  return { onGo, ...view };
}
const bar = () => document.querySelector("[data-slot=action-bar]") as HTMLElement;
const plain = (el: Element) => { const c = el.cloneNode(true) as HTMLElement; c.querySelectorAll("[role=tooltip]").forEach((t) => t.remove()); return c.textContent; };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getCampaignStructure).mockResolvedValue(DAILY);
  vi.mocked(getQueue).mockResolvedValue(queue([worseRow(), cleanupRow(), worseRow("cmp_other", 3)]));
});

describe("draft (v10 camp/fall/overview)", () => {
  it("nothing set: 0／4, each row's 去處理 goes where it is done, 去設上限 in the bar, the empty ruler and 去填商品成本; nothing else is read", async () => {
    const { onGo } = renderBody(detail({ status: "draft", name: "秋季新色預購", cap: NO_CAP as never, budget_planned: null }),
      ws({ stage: { key: "plan", done: [] }, pending_count: 0, draft: DRAFT, totals: null }));
    expect(screen.getByText("0／4 完成")).toBeTruthy();
    const rows = [...document.querySelectorAll("[data-slot=todo-row]")];
    expect(rows.map((r) => r.textContent)).toEqual(["1上限還沒設定去處理 →", "2預算還沒選去處理 →", "3素材7／8 格去處理 →", "4上架還沒開始去處理 →"]);
    for (const [i, target] of [[0, "strategy"], [1, "strategy"], [2, "assets"], [3, "publish"]] as const) {
      fireEvent.click(within(rows[i] as HTMLElement).getByRole("button"));
      expect(onGo).toHaveBeenLastCalledWith(target);
    }
    fireEvent.click(within(bar()).getByRole("button", { name: "去設上限 →" }));
    expect(onGo).toHaveBeenLastCalledWith("strategy");
    expect(document.querySelector('[data-slot=target-ruler][data-variant="empty"]')).toBeTruthy();
    // F43-I16: cost lives on the sell-way's knowledge product, step 4 (賣法與價格) of product onboarding.
    expect(screen.getByRole("link", { name: "去填商品成本" }).getAttribute("href")).toBe("/brands/brd_1/products/kp_fall/onboarding?step=4");
    expect(getCampaignStructure).not.toHaveBeenCalled();
    expect(getQueue).not.toHaveBeenCalled();
  });

  it("去填商品成本 without a knowledge product (no product yet, or an older payload) opens the products page", () => {
    for (const cap of [{ ...NO_CAP, product_id: null, knowledge_product_id: null }, { ...NO_CAP, knowledge_product_id: undefined }]) {
      const { unmount } = renderBody(detail({ status: "draft", cap: cap as never, budget_planned: null }),
        ws({ stage: { key: "plan", done: [] }, pending_count: 0, draft: DRAFT, totals: null }));
      expect(screen.getByRole("link", { name: "去填商品成本" }).getAttribute("href")).toBe("/brands/brd_1/products");
      unmount();
    }
  });

  it("cap, budget and slots done, launch not approved: 3／4 with 查看, bar 確認上架清單; without the publish page it goes to assets", () => {
    const w = ws({ stage: { key: "assets", done: ["plan"] }, draft: { ...DRAFT, cap_set: true, budget_set: true, slots_ready: 8 } });
    const { onGo } = renderBody(detail({ status: "draft" }), w, false);
    expect(screen.getByText("3／4 完成")).toBeTruthy();
    expect(screen.getByText("每賣一筆最多 450 元")).toBeTruthy();
    expect(screen.getByText("NT$30,000")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "查看 →" })).toHaveLength(3);
    fireEvent.click(within(bar()).getByRole("button", { name: "確認上架清單 →" }));
    expect(onGo).toHaveBeenLastCalledWith("assets");
  });

  it("launch approved: n／N 已核對 and 繼續：到平台完成", () => {
    const { onGo } = renderBody(detail({ status: "draft" }), ws({ stage: { key: "launch", done: ["plan", "assets"] },
      draft: { ...DRAFT, cap_set: true, budget_set: true, slots_ready: 8, launch_checked: 2, launch_total: 5 } }));
    expect(screen.getByText("2／5 已核對")).toBeTruthy();
    fireEvent.click(within(bar()).getByRole("button", { name: "繼續：到平台完成 →" }));
    expect(onGo).toHaveBeenLastCalledWith("publish");
  });
});

describe("data gap (v10 camp/mid/overview)", () => {
  const MID: CampaignStructure = { groups: [{ group_id: "g", name: "A・送禮受眾", daily_budget: 600, ads: [
    ad("m1", "中秋禮盒・隨行杯對杯組（家庭團圓情境）", 5603, 35, "on_target"),
    ad("m2", "中秋限定・月光藍開箱", 120, 0, "insufficient"),
  ] }] };
  const gapWs = ws({ stage: { key: "read", done: ["plan", "assets", "launch"] }, pending_count: 0, missing_days: ["2026-09-18", "2026-09-17"],
    totals: { start: "2026-09-10", end: "2026-09-23", currency: "TWD", spend: null, results: null, cost_per_result: null } });

  it("each ad's distance to a judgeable sample, the missing days dashed, the reason chip, 去資料連線補授權", async () => {
    vi.mocked(getCampaignStructure).mockResolvedValue(MID);
    vi.mocked(getTriage).mockResolvedValue({ data: { status: { state: "auth_expired", label: "中秋活動帳戶讀取權限失效。", missing_days: [], last_success_at: null } } } as never);
    renderBody(detail({ name: "中秋限定活動" }), gapWs);
    expect(screen.getByText("門檻：花到 1,350 元（上限 × 3）")).toBeTruthy();
    expect(await screen.findByText("已花 120 元")).toBeTruthy();
    expect(screen.getByText("9%")).toBeTruthy();
    expect(screen.getByText(/每筆 160 元/)).toBeTruthy();
    expect(document.querySelectorAll("[data-slot=grade-rules]")).toHaveLength(1);
    expect(await screen.findByText("中秋活動帳戶讀取權限失效")).toBeTruthy();
    const tiles = [...document.querySelectorAll("[data-slot=day-tiles] i")];
    expect(tiles).toHaveLength(14);
    expect(tiles.filter((t) => t.className.includes("border-dashed")).map((t) => t.textContent)).toEqual(["17", "18"]);
    expect(screen.getByText("缺資料，這兩天不計")).toBeTruthy();
    expect(within(bar()).getByRole("link", { name: "去資料連線補授權 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/connections");
    expect(getQueue).not.toHaveBeenCalled();
  });

  it("F48: the gate is the served 沒賣出 line; a graded ad with a small sample shows 樣本少 beside its grade; no rules → no gate numbers", async () => {
    vi.mocked(getCampaignStructure).mockResolvedValue({ groups: [{ group_id: "g", name: "A・送禮受眾", daily_budget: 600, ads: [
      ad("m1", "中秋禮盒・隨行杯對杯組（家庭團圓情境）", 1200, 3, "on_target", { sample: { sales: 3, few: true, too_new: false, spend_multiple: 2.7, days_with_events: 3 } }),
      ad("m2", "中秋限定・月光藍開箱", 120, 0, "insufficient", { sample: { sales: 0, few: false, too_new: true, spend_multiple: 0.3, days_with_events: 0 } }),
      ad("m3", "秋季新色預告・直式 9:16 短影音", 1480, 0, "wasted", { sample: { sales: 0, few: false, too_new: true, spend_multiple: 3.3, days_with_events: 0 } }),
    ] }] });
    vi.mocked(getTriage).mockResolvedValue({ data: { status: { state: "partial", label: "", missing_days: [], last_success_at: null } } } as never);
    const line = 450 * RULES_FIXTURE.grade.unsold_spend_multiple;
    const { unmount } = renderBody(detail(), gapWs);
    expect(screen.getByText(`門檻：花到 ${line.toLocaleString("en-US")} 元（上限 × ${RULES_FIXTURE.grade.unsold_spend_multiple}）`)).toBeTruthy();
    const few = (await screen.findByText("中秋禮盒・隨行杯對杯組（家庭團圓情境）")).parentElement as HTMLElement;
    expect([...few.querySelectorAll("[data-part=sample]")].map((c) => c.textContent)).toEqual([RULES_FIXTURE.labels.flags.few]);
    // 剛開始 already says it is new: no sample chip beside it.
    expect(screen.getByText("中秋限定・月光藍開箱").parentElement!.querySelectorAll("[data-part=sample]")).toHaveLength(0);
    expect(screen.getByText(`${Math.round((120 / line) * 100)}%`)).toBeTruthy();
    // 沒賣出 has no cost per sale: the row prints what it spent, 0 筆, on a danger meter against the served line — never
    // 「每筆 未知」, and no 還太新 beside it.
    const wasted = screen.getByText("秋季新色預告・直式 9:16 短影音").parentElement as HTMLElement;
    expect(within(wasted).getByText("花了 1,480 元，0 筆")).toBeTruthy();
    expect(within(wasted).getByText(`門檻 ${line.toLocaleString("en-US")}`)).toBeTruthy();
    expect(wasted.querySelector("[data-slot=meter]")?.getAttribute("data-variant")).toBe("danger");
    expect(wasted.textContent).not.toMatch(/每筆|未知|還太新/);
    expect(wasted.querySelectorAll("[data-part=sample]")).toHaveLength(0);
    unmount();
    seedAdsRules(null);
    try {
      renderBody(detail(), gapWs);
      expect(await screen.findByText("中秋限定・月光藍開箱")).toBeTruthy();
      expect(screen.queryByText(/門檻/)).toBeNull();
      expect(document.querySelectorAll("[data-part=sample]")).toHaveLength(0);
    } finally {
      seedAdsRules(RULES_FIXTURE);
    }
  });

  it("the structure read fails on its own (ReadFailed + 重試); the missing days still show", async () => {
    vi.mocked(getCampaignStructure).mockRejectedValueOnce(new Error("逾時")).mockResolvedValueOnce(MID);
    vi.mocked(getTriage).mockRejectedValue(new Error("讀不到"));
    renderBody(detail(), gapWs);
    expect(await screen.findByText(/每則廣告的花費讀不到：逾時/)).toBeTruthy();
    expect(await screen.findByText(/缺資料的原因讀不到：讀不到/)).toBeTruthy();
    expect(document.querySelectorAll("[data-slot=day-tiles] i")).toHaveLength(14);
    expect(within(bar()).getByRole("link", { name: "去資料連線 →" })).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "重試" })[0]);
    expect(await screen.findByText("已花 120 元")).toBeTruthy();
  });

  it("dayRange spans the missing days and the totals window", () => {
    expect(dayRange(["2026-09-30"], { start: "2026-09-28", end: "2026-10-01" } as never)).toEqual(["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"]);
    expect(dayRange([], null)).toEqual([]);
  });
});

describe("live (v10 camp/daily/overview)", () => {
  it("the next decision is this campaign's lowest served position (cleanup): 第 1 件（共 3 件）, its title, the bar opens it", async () => {
    renderBody(detail(), ws());
    expect(await screen.findByText("今天要決定的第 1 件（共 3 件）")).toBeTruthy();
    expect(screen.getByText("關 2 則、留 6 則")).toBeTruthy();
    expect(screen.getByText("清理")).toBeTruthy();
    expect(within(bar()).getByRole("link", { name: "看提議 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_daily/propose/cleanup/cmp_daily");
    expect(await screen.findByText("每日 1,200 撐得起 6 則")).toBeTruthy();
  });

  it("four numbers from the 14-day totals, the money tag against break-even, ROAS 參考; the ruler skips closing and unlaunched ads", async () => {
    renderBody(detail(), ws());
    const kv = screen.getByRole("region", { name: "近 14 天數字" });
    expect(within(kv).getByText("15,767 元")).toBeTruthy();
    expect(within(kv).getByText("09/10 – 09/23")).toBeTruthy();
    expect(within(kv).getByText("121 筆")).toBeTruthy();
    expect(within(kv).getByText("130 元")).toBeTruthy();
    expect(plain(kv.querySelector("[data-slot=money-tag]")!)).toBe("・有賺（打平 520）");
    expect(kv.textContent).toContain("ROAS 參考 12.13");
    expect(within(kv).getByText("8／6 則")).toBeTruthy();
    expect(await screen.findByText("在投 5 則對照上限")).toBeTruthy();
    expect(screen.getByRole("link", { name: "看成效 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_daily?tab=perf");
  });

  it("no open decision: 這個活動沒有要決定的事 with the next sync, and the bar has no step", async () => {
    vi.mocked(getQueue).mockResolvedValue(queue([worseRow("cmp_other")]));
    renderBody(detail(), ws({ pending_count: 0 }));
    expect(await screen.findByText("這個活動沒有要決定的事")).toBeTruthy();
    expect(screen.getByText(/^下次同步 \d\d:\d\d 後重新判讀$/)).toBeTruthy();
    expect(bar().textContent).toBe("← 投放中心");
  });

  it("unknown numbers stay unknown (never 0); an unknown capacity shows only 在投", async () => {
    renderBody(detail(), ws({ can_support: null, daily_budget: null,
      totals: { start: "2026-09-10", end: "2026-09-23", currency: "TWD", spend: null, results: null, cost_per_result: null } }));
    const kv = screen.getByRole("region", { name: "近 14 天數字" });
    expect(within(kv).getAllByText("未知")).toHaveLength(3);
    expect(kv.textContent).not.toMatch(/\b0 元|0 筆/);
    expect(within(kv).getByText("8 則")).toBeTruthy();
    expect(within(kv).getByText("每日預算未知")).toBeTruthy();
    expect(kv.querySelector("[data-slot=money-tag]")).toBeNull();
  });

  it("the queue read fails on its own: ReadFailed with 重試; the numbers and the ruler stay", async () => {
    vi.mocked(getQueue).mockRejectedValueOnce(new Error("伺服器忙碌")).mockResolvedValueOnce(queue([cleanupRow()]));
    renderBody(detail(), ws());
    expect(await screen.findByText(/要決定的事讀不到：伺服器忙碌/)).toBeTruthy();
    expect(screen.getByText("15,767 元")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText("關 2 則、留 6 則")).toBeTruthy();
  });

  it("a worse decision names its grade move", async () => {
    vi.mocked(getQueue).mockResolvedValue(queue([worseRow("cmp_daily", 1)]));
    renderBody(detail(), ws({ pending_count: 1 }));
    expect(await screen.findByText("從划算變偏貴")).toBeTruthy();
    expect(within(bar()).getByRole("link", { name: "看證據 →" })).toBeTruthy();
  });

  it("the old overview is folded under 進階：更多活動資訊", () => {
    renderBody(detail(), ws());
    const fold = screen.getByRole("button", { name: "進階：更多活動資訊" });
    expect(fold.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(fold);
    expect(screen.getByText("舊總覽內容")).toBeTruthy();
  });
});

describe("F47-I08 delivery and closed (Contract E, drill-10 S3)", () => {
  const unread = { start: "2026-09-19", end: "2026-10-02", currency: null, spend: null, results: null, cost_per_result: null };

  it("waiting (just launched, nothing spent): the ✓ card says 已上架，等平台開始投放 with the next sync, money cells 還沒開始花", async () => {
    vi.mocked(getQueue).mockResolvedValue(queue([]));
    vi.mocked(getCampaignStructure).mockResolvedValue({ groups: [] });
    renderBody(detail(), ws({ delivery: "waiting", pending_count: 0, active_ads: 0, can_support: null, daily_budget: null,
      stage: { key: "read", done: ["plan", "assets", "launch"] }, totals: unread }));
    expect(await screen.findByText("已上架，等平台開始投放")).toBeTruthy();
    expect(screen.getByText(/^平台開始花錢後，下次同步（\d\d:\d\d）會出現第一筆數字。$/)).toBeTruthy();
    expect(screen.queryByText("這個活動沒有要決定的事")).toBeNull();
    const kv = screen.getByRole("region", { name: "近 14 天數字" });
    expect(within(kv).getAllByText("還沒開始花")).toHaveLength(2);
    expect(within(kv).queryAllByText("未知")).toHaveLength(1); // 購買 is a count, not money
  });

  it("waiting without a known next sync drops the time, never prints a placeholder", async () => {
    vi.mocked(getQueue).mockResolvedValue(queue([]));
    renderBody(detail(), ws({ delivery: "waiting", pending_count: 0, next_sync_at: null, totals: unread }));
    expect(await screen.findByText("平台開始花錢後，下次同步會出現第一筆數字。")).toBeTruthy();
  });

  it("live and unknown (null) keep today's sentences: 沒有要決定的事 and 未知", async () => {
    vi.mocked(getQueue).mockResolvedValue(queue([]));
    for (const delivery of ["live", null] as const) {
      const { unmount } = renderBody(detail(), ws({ delivery, pending_count: 0, totals: unread }));
      expect(await screen.findByText("這個活動沒有要決定的事")).toBeTruthy();
      expect(within(screen.getByRole("region", { name: "近 14 天數字" })).getAllByText("未知")).toHaveLength(3);
      expect(screen.queryByText(/還沒開始花|等平台開始投放/)).toBeNull();
      unmount();
    }
  });

  it("a closed campaign never says 在投: 已結案・平台上還開著 N 則, and the ruler heading drops 在投 (drill-10 c1-ov)", async () => {
    vi.mocked(getQueue).mockResolvedValue(queue([]));
    renderBody(detail({ status: "closed", lifecycle: CLOSED }), ws({ delivery: null, pending_count: 0, active_ads: 6, can_support: 1,
      stage: { key: "review", done: ["plan", "assets", "launch", "read", "decide"] } }));
    const kv = screen.getByRole("region", { name: "近 14 天數字" });
    expect(within(kv).getByText("已結案・平台上還開著 6 則")).toBeTruthy();
    expect(await screen.findByText("廣告對照上限")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/在投/);
  });

  it("a closed campaign with every platform ad closed reads 已結案", () => {
    renderBody(detail({ status: "closed", lifecycle: CLOSED }), ws({ delivery: null, pending_count: 0, active_ads: 0 }));
    expect(within(screen.getByRole("region", { name: "近 14 天數字" })).getByText("已結案")).toBeTruthy();
  });
});

describe("F49 Contract Q／L: the served decision queue and the closeout row", () => {
  it("drill-11 c3-06: an approved and confirmed cleanup (done, no position) is not a decision — 沒有要決定的事, no step in the bar", async () => {
    vi.mocked(getQueue).mockResolvedValue(queue([cleanupRow(null), worseRow("cmp_other", 1)]));
    renderBody(detail(), ws({ pending_count: 0 }));
    expect(await screen.findByText("這個活動沒有要決定的事")).toBeTruthy();
    expect(screen.queryByText(/今天要決定的第/)).toBeNull();
    expect(bar().textContent).toBe("← 投放中心");
  });

  it("a notice (scale_budget, decision false) is never the next decision", async () => {
    vi.mocked(getQueue).mockResolvedValue(queue([scaleNotice()]));
    renderBody(detail(), ws({ pending_count: 0 }));
    expect(await screen.findByText("這個活動沒有要決定的事")).toBeTruthy();
  });

  it("「第 N 件（共 M 件）」 is the row's served position and the brand's open count, never a recount", async () => {
    vi.mocked(getQueue).mockResolvedValue(queue([cleanupRow(null), worseRow("cmp_other", 1), worseRow("cmp_daily", 2)]));
    renderBody(detail(), ws({ pending_count: 1 }));
    expect(await screen.findByText("今天要決定的第 2 件（共 2 件）")).toBeTruthy();
    expect(screen.getByText("從划算變偏貴")).toBeTruthy();
  });

  it("drill-11 p2: an ended campaign's closeout row is its card — the served sentence, the end date, what still runs — and 結案這一期 → opens ?tab=perf&close=1", async () => {
    vi.mocked(getQueue).mockResolvedValue(queue([worseRow("cmp_other", 2)], [closeoutRow(1)]));
    renderBody(detail({ lifecycle: ENDED, end_date: "2026-10-09" }), ws({ pending_count: 1, stage: { key: "review", done: ["plan", "assets", "launch", "read", "decide"] } }));
    expect(await screen.findByText("今天要決定的第 1 件（共 2 件）")).toBeTruthy();
    const card = screen.getByTestId("closeout-decision");
    expect(within(card).getByText("已結束・待結案")).toBeTruthy();
    expect(within(card).getByText("「日常商品推廣・轉換」已結束，待結案")).toBeTruthy();
    expect(within(card).getByText("10/09 結束")).toBeTruthy();
    expect(within(card).getByText(/^平台上還在投 2 則（10\/11 \d\d:30 讀取）$/)).toBeTruthy();
    expect(within(bar()).getByRole("link", { name: "結案這一期 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_daily?tab=perf&close=1");
  });

  it("an ended campaign with unread days still shows its closeout card (the close dialog re-reads first), not the data-gap view", async () => {
    vi.mocked(getQueue).mockResolvedValue(queue([], [closeoutRow(1, { count: 0, read_at: null })]));
    renderBody(detail({ lifecycle: ENDED }), ws({ pending_count: 1, missing_days: ["2026-10-08"] }));
    expect(await screen.findByTestId("closeout-decision")).toBeTruthy();
    expect(screen.getByText("平台上的廣告還沒讀過")).toBeTruthy();
    expect(screen.queryByText("每則廣告離可以判斷還差多少")).toBeNull();
  });

  it("another campaign's closeout row is not this campaign's decision", async () => {
    vi.mocked(getQueue).mockResolvedValue(queue([], [{ ...closeoutRow(1), campaign_id: "cmp_other" }]));
    renderBody(detail(), ws({ pending_count: 0 }));
    expect(await screen.findByText("這個活動沒有要決定的事")).toBeTruthy();
  });
});
