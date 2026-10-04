/** F28-I10: the detail page's grade groups — grouping, order, hints, per-row numbers, and each row's one action
 * (在清理提議 → cleanup, 去處理 → its own open row, else 看紀錄). Realistic fixtures: the longest real ad names, decimal
 * costs, 0 results, no cap. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { listCampaigns } from "@/lib/adsApi";
import type { QueueCleanup, QueueItem, QueueSettle, TriageClosedBlock, TriageItem, WireQueuePayload } from "@/lib/adsTriageApi";
import { getTriage, splitQueue } from "@/lib/adsTriageApi";
import { apiFetch } from "@/lib/http";
import { formatAmount } from "../patterns";
import { RULES_FIXTURE, seedAdsRules } from "../patterns/rulesFixture";
import { CampaignDetailPage } from "./CampaignDetailPage";
import {
  ClosedGroup, GradeGroups, OPEN_BY_DEFAULT, adActions, groupOf, trendNote, type GroupKey, type RowAction, type RowExtras,
} from "./GradeGroups";

// F29-I03: the detail-page test below runs the REAL `getQueue` (and its `splitQueue`) over a backend payload;
// only the transport and the two other reads are stubbed.
vi.mock("@/lib/http", async () => {
  const actual = await vi.importActual<typeof import("@/lib/http")>("@/lib/http");
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, listCampaigns: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, getTriage: vi.fn() };
});

const WS = "/brands/brd_1/ads/campaigns/cmp_1";
const LONG_NAME = "晨光隨行杯・隨時有你｜好攜帶，走到哪都適合（通勤情境單圖・最多數量 1150706）";

function item(o: Partial<TriageItem> & { spend?: number | null; results?: number | null; cost?: number | null } = {}): TriageItem {
  const { spend = 1440, results = 30, cost = 48, ...rest } = o;
  return {
    entity_id: "a1", native_id: "n_a1", name: "晨光隨行杯・日常出發", campaign_id: "cmp_1", campaign_name: "日常商品推廣・轉換",
    thumbnail_url: null, class: "better", label: "變好", reason_code: "cost_per_result_down",
    grade: "on_target", grade_label: "划算", previous_grade: null, grade_move: null,
    window: { start: "2026-09-10", end: "2026-09-23", days: 14, previous_start: "2026-08-27", previous_end: "2026-09-09", extended_from: null },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend, result_count: results, cost_per_result: cost, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    previous: { spend: 1500, result_count: 29, cost_per_result: 52.1, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: -0.0787, sample: { sales: results ?? null, few: false, too_new: false, spend_multiple: 3.2, days_with_events: 12 },
    ...rest,
  };
}

function queueRow(o: Partial<QueueItem> & { triage: TriageItem }): QueueItem {
  return {
    id: "q", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: "k", category: "triage",
    kind: "worse", severity: "rule_warning", message: "", action_url: null, visible_from: null, status: "open",
    created_at: "2026-09-23T00:00:00Z", resolved_at: null, kind_key: "worse", proposal: null, done: false, ...o,
  };
}

function cleanupPayload(ids: string[]): QueueCleanup {
  return {
    campaign_id: "cmp_1", campaign_name: "日常商品推廣・轉換", can_support: 6, active_ads: 8,
    ads: ids.map((id) => ({ entity_id: id, name: id, thumbnail_url: null, spend_7d: 700, grade: "wasted", cost_per_result: null, spend: 1480, result_count: 0, daily_spend: 100, rejected_before: null })),
    keep: [], short: 0, daily_saving: 260, scale_owner_id: null,
  };
}

const wasted = item({ entity_id: "a8", name: "秋季新色預告・直式 9:16 短影音", grade: "wasted", grade_label: "沒賣出", reason_code: "spend_over_target_no_result", spend: 1480, results: 0, cost: null, change_pct: null });
const over = item({ entity_id: "a7", name: "提問式貼文・早晨第一口是什麼？", grade: "over", grade_label: "太貴", spend: 2470, results: 4, cost: 617.5, change_pct: 0.1002 });
const watch = item({ entity_id: "a6", name: "再行銷・兩入組 NT$1,580 免運 - 複本 2", grade: "watch", grade_label: "偏貴", spend: 3120, results: 6, cost: 520, change_pct: 0.1818 });
const ok = item({ entity_id: "a2", name: LONG_NAME, spend: 1407, results: 28, cost: 50.25 });
const thin = item({ entity_id: "m2", name: "中秋限定・月光藍開箱", grade: "insufficient", grade_label: "剛開始、數字還不夠", reason_code: "too_new", spend: 120, results: 0, cost: null, change_pct: null });
const noData = item({ entity_id: "m9", name: "同步缺口那一則", grade: "insufficient", grade_label: "資料不足", reason_code: "result_unknown_days", spend: null, results: null, cost: null, change_pct: null });
/** The served ruler lines for the 450 cap the fixtures use (F48 Contract R-API: hints come from the rules). */
const CAP = 450;
const WATCH = formatAmount(CAP * RULES_FIXTURE.grade.watch_band);
const UNSOLD = formatAmount(CAP * RULES_FIXTURE.grade.unsold_spend_multiple);

function renderGroups(items: TriageItem[], opts: {
  cap?: number | null; breakEven?: number | null; dataReason?: string | null; open?: GroupKey[];
  actions?: Map<string, RowAction>; extras?: (item: TriageItem) => RowExtras; pauseHref?: (item: TriageItem) => string;
} = {}) {
  const actions = opts.actions ?? adActions("brd_1", "cmp_1", WS, items, []);
  const onToggle = vi.fn();
  const view = render(
    <MemoryRouter>
      <GradeGroups
        items={items} cap={opts.cap === undefined ? 450 : opts.cap} actions={actions}
        breakEven={opts.breakEven === undefined ? 520 : opts.breakEven} dataReason={opts.dataReason ?? null} extras={opts.extras} pauseHref={opts.pauseHref}
        openGroups={new Set(opts.open ?? OPEN_BY_DEFAULT)} onToggle={onToggle} highlightId={null} registerRow={() => {}}
      />
    </MemoryRouter>,
  );
  return { ...view, onToggle };
}

const detailsOf = (title: string) => screen.getByText(title, { selector: "b" }).closest("details")!;

describe("groupOf / trendNote", () => {
  it("splits insufficient by the backend's own reason_code (too_new = 剛開始, else 資料不足), never by its label", () => {
    expect(groupOf(thin)).toBe("thin");
    expect(groupOf(noData)).toBe("no_data");
    expect(groupOf(wasted)).toBe("wasted");
    // A relabelled payload still groups by its code.
    expect(groupOf({ ...thin, grade_label: "還在累積" })).toBe("thin");
    expect(groupOf({ ...noData, grade_label: "剛開始、數字還不夠" })).toBe("no_data");
    expect(groupOf({ ...thin, reason_code: "mixed_currency" })).toBe("no_data");
  });

  it("prints the prototype trend note from change_pct and the window length", () => {
    expect(trendNote(over)).toBe("比前 14 天 ▲10%");
    expect(trendNote(ok)).toBe("比前 14 天 ▼8%");
    expect(trendNote(item({ change_pct: 0.001 }))).toBe("比前 14 天 ±0%");
    expect(trendNote(wasted)).toBe("比前 14 天：沒有可比資料");
  });
});

describe("GradeGroups", () => {
  it("orders groups 沒賣出 → 太貴 → 偏貴 → 划算 → 剛開始 → 資料不足, with the cap hints and counts", () => {
    const { container } = renderGroups([ok, thin, watch, noData, over, wasted]);
    const titles = [...container.querySelectorAll("summary b")].map((b) => b.textContent);
    expect(titles).toEqual(["沒賣出", "太貴", "偏貴", "划算", "剛開始、數字還不夠", "資料不足"]);
    expect(within(detailsOf("沒賣出").querySelector("summary")!).getByText(`花到 ${UNSOLD} 元還沒賣出`)).toBeTruthy();
    expect(screen.getByText(`每筆超過 ${WATCH} 元`)).toBeTruthy();
    expect(screen.getByText(`每筆 450–${WATCH} 元`)).toBeTruthy();
    expect(screen.getByText("每筆不到 450 元")).toBeTruthy();
    expect(screen.getByText(`還沒花到 ${UNSOLD} 元`)).toBeTruthy();
    // 資料不足 is not about the spend line: no invented hint.
    expect(detailsOf("資料不足").querySelector("summary")!.textContent).toBe("資料不足1 則");
  });

  it("the hints follow the served rules, and print nothing while the rules are not loaded (no literal fallback)", () => {
    seedAdsRules({ ...RULES_FIXTURE, grade: { ...RULES_FIXTURE.grade, watch_band: 1.5, unsold_spend_multiple: 4 } });
    try {
      const { unmount } = renderGroups([over, wasted]);
      expect(screen.getByText("每筆超過 675 元")).toBeTruthy();
      expect(screen.getByText("花到 1,800 元還沒賣出")).toBeTruthy();
      unmount();
      seedAdsRules(null);
      const { container } = renderGroups([over, wasted, thin]);
      expect(container.textContent).not.toMatch(/每筆超過|還沒賣出|還沒花到/);
      // The titles are the payload's own words.
      expect([...container.querySelectorAll("summary b")].map((b) => b.textContent)).toEqual(["沒賣出", "太貴", "剛開始、數字還不夠"]);
    } finally {
      seedAdsRules(RULES_FIXTURE);
    }
  });

  it("a graded row with a small sample shows 樣本少 beside its trend note — the only sample chip (no 還太新, even when too_new); 剛開始 rows show none", () => {
    const few = item({ entity_id: "f1", name: "小樣本・三筆", cost: 210, results: 3, sample: { sales: 3, few: true, too_new: false, spend_multiple: 1.4, days_with_events: 3 } });
    const fresh = item({ entity_id: "f2", name: "剛上兩天", grade: "over", grade_label: "太貴", cost: 900, results: 1, sample: { sales: 1, few: true, too_new: true, spend_multiple: 2, days_with_events: 1 } });
    const thinFresh = { ...thin, sample: { sales: 0, few: false, too_new: true, spend_multiple: 0.3, days_with_events: 0 } };
    renderGroups([few, fresh, ok, thinFresh], { open: ["on_target", "over", "thin"] });
    const chips = (id: string) => [...screen.getByTestId(`ad-row-${id}`).querySelectorAll("[data-part=sample]")].map((c) => c.textContent);
    expect(chips("f1")).toEqual([RULES_FIXTURE.labels.flags.few]);
    expect(chips("f2")).toEqual([RULES_FIXTURE.labels.flags.few]);
    expect(document.body.textContent).not.toContain("還太新");
    expect(chips("a2")).toEqual([]);
    expect(chips("m2")).toEqual([]);
  });

  it("opens only the groups it is told to (default 沒賣出／太貴／偏貴) and reports toggles", () => {
    const { onToggle } = renderGroups([ok, thin, watch, over, wasted]);
    expect(detailsOf("沒賣出").open).toBe(true);
    expect(detailsOf("太貴").open).toBe(true);
    expect(detailsOf("偏貴").open).toBe(true);
    expect(detailsOf("划算").open).toBe(false);
    expect(detailsOf("剛開始、數字還不夠").open).toBe(false);
    const okDetails = detailsOf("划算");
    okDetails.open = true;
    fireEvent(okDetails, new Event("toggle"));
    expect(onToggle).toHaveBeenCalledWith("on_target", true);
  });

  it("rows: long name wraps (never truncated), spend and per-purchase cost in whole yuan, 沒賣出 prints 購買 0 筆, 剛開始 prints the word", () => {
    renderGroups([ok, over, wasted, thin], { open: ["wasted", "over", "on_target", "thin"] });
    const okRow = screen.getByTestId("ad-row-a2");
    const name = within(okRow).getByText(LONG_NAME);
    expect(name.className).not.toMatch(/truncate/);
    expect(within(okRow).getByText("1,407 元")).toBeTruthy();
    expect(within(okRow).getByText("50 元")).toBeTruthy();

    const overRow = screen.getByTestId("ad-row-a7");
    expect(within(overRow).getByText("每賣一筆")).toBeTruthy();
    expect(within(overRow).getByText("618 元")).toBeTruthy();
    expect(within(overRow).getByText("比前 14 天 ▲10%")).toBeTruthy();

    const wastedRow = screen.getByTestId("ad-row-a8");
    expect(within(wastedRow).getByText("購買")).toBeTruthy();
    expect(within(wastedRow).getByText("0 筆")).toBeTruthy();

    const thinRow = screen.getByTestId("ad-row-m2");
    // The too-new word is the glossary term (its sentence states the ruled gate).
    expect(within(thinRow).getByText("剛開始、數字還不夠").getAttribute("data-slot")).toBe("term");
    expect(within(thinRow).getByText("120 元")).toBeTruthy();
  });

  it("money tags against break-even beside every cost per purchase: 有賺／剛好打平／在虧; none on 沒賣出 and 剛開始", () => {
    renderGroups([ok, watch, over, wasted, thin], { open: ["wasted", "over", "watch", "on_target", "thin"] });
    const tag = (id: string) => screen.getByTestId(`ad-row-${id}`).querySelector("[data-slot=money-tag]");
    expect(tag("a2")?.getAttribute("data-variant")).toBe("gain");
    expect(tag("a2")?.textContent).toMatch(/有賺.*（打平 520）$/);
    expect(tag("a6")?.getAttribute("data-variant")).toBe("even");
    expect(tag("a7")?.getAttribute("data-variant")).toBe("loss");
    expect(tag("a8")).toBeNull();
    expect(tag("m2")).toBeNull();
  });

  it("no break-even (no product cost) or a non-purchase result: no money tag, never a guess", () => {
    const clicks = item({
      entity_id: "c1", cost: 3.456,
      current: { spend: 34.56, result_count: 10, cost_per_result: 3.456, result_kind: "link_click", result_label: "連結點擊", derived_zero_days: 0, reason: null },
    });
    const { unmount } = renderGroups([ok], { breakEven: null, open: ["on_target"] });
    expect(screen.getByText("50 元")).toBeTruthy();
    expect(document.querySelector("[data-slot=money-tag]")).toBeNull();
    unmount();
    renderGroups([clicks], { open: ["on_target"] });
    expect(screen.getByText("每次連結點擊成本")).toBeTruthy();
    expect(document.querySelector("[data-slot=money-tag]")).toBeNull();
  });

  it("資料不足 carries the campaign's one data_status sentence as its hint", () => {
    renderGroups([noData], { dataReason: "有幾天的資料還沒讀到，數字可能偏少。", open: [] });
    expect(within(detailsOf("資料不足").querySelector("summary")!).getByText("有幾天的資料還沒讀到，數字可能偏少。")).toBeTruthy();
  });

  it("row extras: the page's menu sits after the decision button, an open request shows its chip, a failure its line", () => {
    const queue = [queueRow({ kind_key: "worse", triage: watch })];
    renderGroups([watch, ok], {
      actions: adActions("brd_1", "cmp_1", WS, [watch, ok], queue), open: ["watch", "on_target"],
      extras: (i) => ({
        menu: <button type="button">⋯ {i.entity_id}</button>,
        requestOpen: i.entity_id === "a2",
        error: i.entity_id === "a6" ? "換掉這一則沒送出：網路錯誤" : null,
      }),
    });
    const watchRow = screen.getByTestId("ad-row-a6");
    const buttons = within(watchRow).getAllByRole("link").concat(within(watchRow).getAllByRole("button"));
    expect(buttons.map((b) => b.textContent)).toEqual(["去處理", "⋯ a6"]);
    expect(within(watchRow).getByRole("alert").textContent).toBe("換掉這一則沒送出：網路錯誤");
    expect(within(watchRow).queryByText("換掉這一則・需求已開")).toBeNull();
    const okRow = screen.getByTestId("ad-row-a2");
    expect(within(okRow).getByText("換掉這一則・需求已開").getAttribute("data-tone")).toBe("accent");
    expect(within(okRow).queryByRole("link")).toBeNull();
  });

  it("unknown spend reads 未知 (never 0); a non-purchase result kind names its own result", () => {
    const clicks = item({
      entity_id: "c1", grade: "no_target", grade_label: "未判斷", spend: null, cost: 3.456,
      current: { spend: null, result_count: 10, cost_per_result: 3.456, result_kind: "link_click", result_label: "連結點擊", derived_zero_days: 0, reason: null },
      target: { value: null, basis: null, result_kind: "link_click", result_label: "連結點擊", missing: [] },
    });
    renderGroups([clicks], { cap: null, open: ["no_target"] });
    const row = screen.getByTestId("ad-row-c1");
    expect(within(row).getByText("未知")).toBeTruthy();
    expect(within(row).getByText("每次連結點擊成本")).toBeTruthy();
    expect(within(row).getByText("3 元")).toBeTruthy();
    // No cap: the group is 未判斷 and carries no hint.
    expect(detailsOf("未判斷").querySelector("summary")!.textContent).toBe("未判斷1 則");
  });

  it("F45-I06: every active row carries 「暫停」 to the pause page (from=perf), beside its decision and before its menu", () => {
    const queue = [queueRow({ kind_key: "worse", triage: watch })];
    renderGroups([watch, ok, wasted], {
      actions: adActions("brd_1", "cmp_1", WS, [watch, ok, wasted], queue), open: ["wasted", "watch", "on_target"],
      extras: (i) => ({ menu: <button type="button">⋯ {i.entity_id}</button>, requestOpen: false, error: null }),
      pauseHref: (i) => `${WS}/propose/pause/${i.entity_id}?from=perf`,
    });
    const watchRow = screen.getByTestId("ad-row-a6");
    expect(within(watchRow).getAllByRole("link").map((l) => l.textContent)).toEqual(["去處理", "暫停"]);
    for (const id of ["a6", "a2", "a8"]) {
      const pause = within(screen.getByTestId(`ad-row-${id}`)).getByRole("link", { name: "暫停" });
      expect(pause.getAttribute("href")).toBe(`${WS}/propose/pause/${id}?from=perf`);
      expect(pause.getAttribute("data-variant")).toBe("outline");
    }
  });

  it("sorts rows most expensive per result first, unknown cost last", () => {
    const cheap = item({ entity_id: "x1", cost: 40.1 });
    const dear = item({ entity_id: "x2", cost: 420.75 });
    const unknown = item({ entity_id: "x3", cost: null });
    const { container } = renderGroups([cheap, unknown, dear], { open: ["on_target"] });
    const ids = [...container.querySelectorAll("[data-testid^=ad-row-]")].map((e) => e.getAttribute("data-testid"));
    expect(ids).toEqual(["ad-row-x2", "ad-row-x1", "ad-row-x3"]);
  });
});

describe("adActions", () => {
  const items = [wasted, over, watch, ok];

  it("ads inside this campaign's open cleanup row → 在清理提議 (its action_url); own worse row → 去處理; else 看紀錄", () => {
    const queue = [
      queueRow({ id: "q_clean", kind_key: "cleanup", triage: ok, cleanup: cleanupPayload(["a8", "a7"]), action_url: `${WS}/propose/cleanup/cmp_1` }),
      queueRow({ id: "q_worse", kind_key: "worse", triage: watch }),
    ];
    const actions = adActions("brd_1", "cmp_1", WS, items, queue);
    expect(actions.get("a8")).toEqual({ label: "在清理提議", href: `${WS}/propose/cleanup/cmp_1` });
    expect(actions.get("a7")).toEqual({ label: "在清理提議", href: `${WS}/propose/cleanup/cmp_1` });
    expect(actions.get("a6")).toEqual({ label: "去處理", href: `${WS}/review/a6` });
    // The cleanup row's carrier ad (`triage`) is not its own row.
    expect(actions.get("a2")).toEqual({ label: "看紀錄", href: `${WS}?tab=performance&ad=a2` });
  });

  it("an ad in the cleanup AND with its own worse row points at the cleanup first", () => {
    const queue = [
      queueRow({ kind_key: "cleanup", triage: ok, cleanup: cleanupPayload(["a7"]), action_url: `${WS}/propose/cleanup/cmp_1` }),
      queueRow({ kind_key: "worse", triage: over }),
    ];
    expect(adActions("brd_1", "cmp_1", WS, items, queue).get("a7")!.label).toBe("在清理提議");
  });

  it("a cleanup row of another campaign, or a done cleanup, never marks this campaign's ads", () => {
    const other = { ...cleanupPayload(["a8"]), campaign_id: "cmp_other" };
    const done = queueRow({
      kind_key: "cleanup", triage: ok, cleanup: cleanupPayload(["a8"]),
      proposal: { kind: "cleanup", change_set_id: "s", campaign_id: "cmp_1", status: "approved", verification_state: "confirmed", reason: null, revisit_at: null, multi: true },
    });
    expect(adActions("brd_1", "cmp_1", WS, items, [queueRow({ kind_key: "cleanup", triage: ok, cleanup: other, action_url: "/x" })]).get("a8")!.label).toBe("看紀錄");
    expect(adActions("brd_1", "cmp_1", WS, items, [done]).get("a8")!.label).toBe("看紀錄");
  });

  it("an own row whose proposal is done falls back to 看紀錄; an open one routes to its current step", () => {
    const pause = (status: "approved" | "rejected") => queueRow({
      kind_key: "stop_loss", triage: wasted,
      proposal: { kind: "pause", change_set_id: "set_1", campaign_id: "cmp_1", status, verification_state: "pending", reason: null, revisit_at: null, multi: false },
    });
    expect(adActions("brd_1", "cmp_1", WS, items, [pause("approved")]).get("a8")).toEqual({ label: "去處理", href: `${WS}/changes/set_1/handoff` });
    expect(adActions("brd_1", "cmp_1", WS, items, [pause("rejected")]).get("a8")!.label).toBe("看紀錄");
  });

  it("campaign-level rows (refresh_creative, scale_budget) never become an ad's own action", () => {
    const queue = [queueRow({ kind_key: "refresh_creative", triage: ok }), queueRow({ kind_key: "scale_budget", triage: ok })];
    expect(adActions("brd_1", "cmp_1", WS, items, queue).get("a2")!.label).toBe("看紀錄");
  });

  it("renders 在清理提議／去處理 as outline buttons; a 看紀錄 row has no row button (看紀錄 is in its menu)", () => {
    const queue = [
      queueRow({ kind_key: "cleanup", triage: ok, cleanup: cleanupPayload(["a8"]), action_url: `${WS}/propose/cleanup/cmp_1` }),
      queueRow({ kind_key: "worse", triage: watch }),
    ];
    renderGroups(items, { actions: adActions("brd_1", "cmp_1", WS, items, queue), open: ["wasted", "watch", "on_target"] });
    const clean = within(screen.getByTestId("ad-row-a8")).getByRole("link", { name: "在清理提議" });
    expect(clean.getAttribute("data-variant")).toBe("outline");
    expect(within(screen.getByTestId("ad-row-a6")).getByRole("link", { name: "去處理" }).getAttribute("data-variant")).toBe("outline");
    expect(within(screen.getByTestId("ad-row-a2")).queryByRole("link")).toBeNull();
  });
});

describe("ClosedGroup", () => {
  const off = (label: string) => ({ state: "off" as const, label });
  it("under 不在投的, folded by default, 共 N 則; rows are thumb, name and the served delivery word only; truncated prints the rest", () => {
    render(
      <MemoryRouter>
        <ClosedGroup
          open={false} onToggle={() => {}}
          closed={{
            groups: [{ ...off("已暫停"), count: 40 }, { ...off("已封存"), count: 16 }, { ...off("已刪除"), count: 1 }],
            total: 57, truncated: true,
            items: [
              { entity_id: "c1", name: "舊版主視覺 0715", delivery: off("已暫停"), delivery_label: "已暫停", thumbnail_url: null, spend: 321, cost_per_result: 45.5, result_label: "購買" },
              { entity_id: "c2", name: "開箱長版 0605", delivery: off("已封存"), delivery_label: "已封存", thumbnail_url: null, spend: null, cost_per_result: null, result_label: "購買" },
              { entity_id: "c3", name: null, delivery: off("已刪除"), delivery_label: "已刪除", thumbnail_url: null, spend: 0, cost_per_result: null, result_label: "購買" },
            ],
          } as unknown as TriageClosedBlock}
        />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 2, name: "不在投的" })).toBeTruthy();
    const details = detailsOf("共 57 則");
    expect(details.open).toBe(false);
    expect(within(details.querySelector("summary")!).queryByText("57 則")).toBeNull();
    expect(screen.getByText("已暫停 40・已封存 16・已刪除 1・不算在上面的在投數量裡")).toBeTruthy();
    const paused = screen.getByTestId("closed-ad-row-c1");
    expect(within(paused).getByText("舊版主視覺 0715")).toBeTruthy();
    expect(within(paused).getByText("已暫停")).toBeTruthy();
    expect(within(paused).queryByText("321 元")).toBeNull();
    expect(within(paused).queryByRole("link")).toBeNull();
    expect(within(screen.getByTestId("closed-ad-row-c2")).getByText("已封存")).toBeTruthy();
    const deleted = screen.getByTestId("closed-ad-row-c3");
    expect(within(deleted).getByText("（未命名廣告）")).toBeTruthy();
    expect(within(deleted).getByText("已刪除")).toBeTruthy();
    expect(screen.getByText("…其餘 54 則")).toBeTruthy();
  });

  it("F49 Contract L: an ad on the platform but not delivering (被拒登) prints its served word, and the hint counts every served group", () => {
    render(
      <MemoryRouter>
        <ClosedGroup open={false} onToggle={() => {}} closed={{
          groups: [{ state: "not_running", label: "被拒登", count: 1 }, { ...off("所屬廣告組已暫停"), count: 2 }],
          total: 3, truncated: false,
          items: [{ entity_id: "r1", name: "被拒的廣告", delivery: { state: "not_running", label: "被拒登" }, delivery_label: "被拒登", thumbnail_url: null, spend: null, cost_per_result: null, result_label: "購買" }],
        } as unknown as TriageClosedBlock} />
      </MemoryRouter>,
    );
    expect(screen.getByText("被拒登 1・所屬廣告組已暫停 2・不算在上面的在投數量裡")).toBeTruthy();
    expect(within(screen.getByTestId("closed-ad-row-r1")).getByText("被拒登")).toBeTruthy();
  });
});

// ---- F29-I03: the brand-level settle row never reaches a screen that scans ad rows ----

const SETTLE: QueueSettle = {
  month: "2026-08", start: "2026-08-01", end: "2026-08-31", campaign_count: 2, imported_count: 1, learnable_count: 6,
  buckets: [{ grade: "on_target", amount: 14240, count: 2, ads: [] }],
};

/** What `GET .../queue` really sends: the settle row (triage null) between two ad rows. */
function wirePayload(): WireQueuePayload {
  const settleRow = {
    id: "q_settle", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null,
    dedupe_key: "ads-triage:settle:brd_1:2026-08-31", category: "ads_triage_settle", kind: null,
    severity: "informational" as const, message: "結算上一期（8 月），待寫進筆記本",
    action_url: "/brands/brd_1/ads/settle/2026-08/result", visible_from: null, status: "open",
    created_at: "2026-09-02T00:00:00Z", resolved_at: null, kind_key: "settle" as const, triage: null,
    proposal: null, settle: SETTLE,
  };
  return {
    items: [
      queueRow({ id: "q_worse", kind_key: "worse", triage: watch }),
      settleRow,
      queueRow({ id: "q_clean", kind_key: "cleanup", triage: ok, cleanup: cleanupPayload(["a8"]), action_url: `${WS}/propose/cleanup/cmp_1` }),
    ],
    counts: { stop_loss: 0, worse: 1, better: 0, flat: 3, insufficient: 0, no_target: 0 }, total_ads: 4,
    kinds_available: ["worse", "scale_budget", "refresh_creative", "insufficient_data", "cleanup", "settle"], kinds_pending: [],
  };
}

describe("queue settle row (F29-I03)", () => {
  it("splitQueue keeps ad rows in items and exposes the settle row on its own field", () => {
    const queue = splitQueue(wirePayload());
    expect(queue.items.map((q) => q.id)).toEqual(["q_worse", "q_clean"]);
    expect(queue.items.every((q) => q.triage !== null)).toBe(true);
    expect(queue.settle).toEqual({
      id: "q_settle", dedupe_key: "ads-triage:settle:brd_1:2026-08-31", category: "ads_triage_settle",
      severity: "informational", message: "結算上一期（8 月），待寫進筆記本",
      action_url: "/brands/brd_1/ads/settle/2026-08/result", visible_from: null, status: "open",
      created_at: "2026-09-02T00:00:00Z", settle: SETTLE,
    });
    expect(splitQueue({ ...wirePayload(), items: [] }).settle).toBeNull();
  });

  it("the detail page renders its rows' actions with a settle row in the backend queue", async () => {
    Element.prototype.scrollIntoView = vi.fn(); // jsdom has none
    const items = [ok, watch, over, wasted];
    vi.mocked(listCampaigns).mockResolvedValue([{
      id: "cmp_1", name: "日常商品推廣・轉換", status: "live", start_date: "2026-09-08", end_date: "2026-10-08", objective: "轉換",
      created_at: "2026-09-01T00:00:00Z", created_by: null, budget_planned: null, budget_total: null,
      budget_progress: { spent: 22000, total: 60000, pct: 36.7 },
      judgment: { tone: "neutral", text: "投放中", detail: "" }, outcome: { spend: 0, purchases: 0, revenue: 0 },
    }]);
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 28, items, closed: { groups: [], total: 0, items: [], truncated: false } as unknown as TriageClosedBlock,
      data: {
        sync: { state: "ok", error: null, last_success_at: null }, coverage: { start: "2026-08-27", end: "2026-09-23" }, missing_days: [],
        status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: null },
      },
    });
    vi.mocked(apiFetch).mockImplementation(async (input) =>
      String(input).endsWith("/brands/brd_1/queue")
        ? new Response(JSON.stringify({ queue: wirePayload() }), { status: 200, headers: { "Content-Type": "application/json" } })
        : new Response(JSON.stringify({ error: { message: "not stubbed" } }), { status: 404 }),
    );
    render(
      <MemoryRouter initialEntries={[`${WS}/detail`]}>
        <CampaignDetailPage brandId="brd_1" campaignId="cmp_1" />
      </MemoryRouter>,
    );
    const worse = await screen.findByTestId("ad-row-a6");
    expect(await within(worse).findByRole("link", { name: "去處理" })).toBeTruthy();
    expect(within(screen.getByTestId("ad-row-a8")).getByRole("link", { name: "在清理提議" })).toBeTruthy();
    // F45-I06: no decision of its own — the row's only link is its 「暫停」.
    expect(within(screen.getByTestId("ad-row-a2")).getAllByRole("link").map((l) => l.textContent)).toEqual(["暫停"]);
  });
});
