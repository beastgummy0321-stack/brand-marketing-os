/** F28-I10: the detail page's grade groups — grouping, order, hints, per-row numbers, and each row's one action
 * (在清理提議 → cleanup, 去處理 → its own open row, else 看紀錄). Realistic fixtures: the longest real ad names, decimal
 * costs, 0 results, no cap. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { QueueCleanup, QueueItem, TriageItem } from "@/lib/adsTriageApi";
import {
  ClosedGroup, GradeGroups, OPEN_BY_DEFAULT, adActions, groupOf, trendNote, type GroupKey, type RowAction,
} from "./GradeGroups";

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
    change_pct: -0.0787, sample: { gate: true, spend_multiple: 3.2, days_with_events: 12 },
    ...rest,
  };
}

function queueRow(o: Partial<QueueItem> & { triage: TriageItem }): QueueItem {
  return {
    id: "q", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: "k", category: "triage",
    kind: "worse", severity: "rule_warning", message: "", action_url: null, visible_from: null, status: "open",
    created_at: "2026-09-23T00:00:00Z", resolved_at: null, kind_key: "worse", proposal: null, ...o,
  };
}

function cleanupPayload(ids: string[]): QueueCleanup {
  return {
    campaign_id: "cmp_1", campaign_name: "日常商品推廣・轉換", can_support: 6, active_ads: 8,
    ads: ids.map((id) => ({ entity_id: id, name: id, thumbnail_url: null, spend_7d: 700, grade: "wasted", cost_per_result: null, spend: 1480, result_count: 0, daily_spend: 100, rejected_before: null })),
    keep: [], short: 0, daily_saving: 260, scale_owner_id: null,
  };
}

const wasted = item({ entity_id: "a8", name: "秋季新色預告・直式 9:16 短影音", grade: "wasted", grade_label: "沒賣出", spend: 1480, results: 0, cost: null, change_pct: null });
const over = item({ entity_id: "a7", name: "提問式貼文・早晨第一口是什麼？", grade: "over", grade_label: "太貴", spend: 2470, results: 4, cost: 617.5, change_pct: 0.1002 });
const watch = item({ entity_id: "a6", name: "再行銷・兩入組 NT$1,580 免運 - 複本 2", grade: "watch", grade_label: "偏貴", spend: 3120, results: 6, cost: 520, change_pct: 0.1818 });
const ok = item({ entity_id: "a2", name: LONG_NAME, spend: 1407, results: 28, cost: 50.25 });
const thin = item({ entity_id: "m2", name: "中秋限定・月光藍開箱", grade: "insufficient", grade_label: "剛開始、數字還不夠", spend: 120, results: 0, cost: null, change_pct: null });
const noData = item({ entity_id: "m9", name: "同步缺口那一則", grade: "insufficient", grade_label: "資料不足", spend: null, results: null, cost: null, change_pct: null });

function renderGroups(items: TriageItem[], opts: { cap?: number | null; open?: GroupKey[]; actions?: Map<string, RowAction> } = {}) {
  const actions = opts.actions ?? adActions("brd_1", "cmp_1", WS, items, []);
  const onToggle = vi.fn();
  const view = render(
    <MemoryRouter>
      <GradeGroups
        items={items} cap={opts.cap === undefined ? 450 : opts.cap} actions={actions}
        openGroups={new Set(opts.open ?? OPEN_BY_DEFAULT)} onToggle={onToggle} highlightId={null} registerRow={() => {}}
      />
    </MemoryRouter>,
  );
  return { ...view, onToggle };
}

const detailsOf = (title: string) => screen.getByText(title, { selector: "b" }).closest("details")!;

describe("groupOf / trendNote", () => {
  it("splits insufficient by the backend's own grade_label", () => {
    expect(groupOf(thin)).toBe("thin");
    expect(groupOf(noData)).toBe("no_data");
    expect(groupOf(wasted)).toBe("wasted");
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
    expect(within(detailsOf("沒賣出").querySelector("summary")!).getByText("花到 1,350 元還沒賣出")).toBeTruthy();
    expect(screen.getByText("每筆超過 540 元")).toBeTruthy();
    expect(screen.getByText("每筆 450–540 元")).toBeTruthy();
    expect(screen.getByText("每筆不到 450 元")).toBeTruthy();
    expect(screen.getByText("還沒花到 1,350 元")).toBeTruthy();
    // 資料不足 is not about the spend line: no invented hint.
    expect(detailsOf("資料不足").querySelector("summary")!.textContent).toBe("資料不足1 則");
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

  it("rows: long name wraps (never truncated), spend and per-purchase cost with decimals, 沒賣出 prints 購買 0 筆, 剛開始 prints the word", () => {
    renderGroups([ok, over, wasted, thin], { open: ["wasted", "over", "on_target", "thin"] });
    const okRow = screen.getByTestId("ad-row-a2");
    const name = within(okRow).getByText(LONG_NAME);
    expect(name.className).not.toMatch(/truncate/);
    expect(within(okRow).getByText("1,407 元")).toBeTruthy();
    expect(within(okRow).getByText("50.25 元")).toBeTruthy();

    const overRow = screen.getByTestId("ad-row-a7");
    expect(within(overRow).getByText("每賣一筆")).toBeTruthy();
    expect(within(overRow).getByText("617.5 元")).toBeTruthy();
    expect(within(overRow).getByText("比前 14 天 ▲10%")).toBeTruthy();

    const wastedRow = screen.getByTestId("ad-row-a8");
    expect(within(wastedRow).getByText("購買")).toBeTruthy();
    expect(within(wastedRow).getByText("0 筆")).toBeTruthy();

    const thinRow = screen.getByTestId("ad-row-m2");
    expect(within(thinRow).getByText("剛開始、數字還不夠")).toBeTruthy();
    expect(within(thinRow).getByText("120 元")).toBeTruthy();
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
    expect(within(row).getByText("3.46 元")).toBeTruthy();
    // No cap: the group is 未判斷 and carries no hint.
    expect(detailsOf("未判斷").querySelector("summary")!.textContent).toBe("未判斷1 則");
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

  it("renders 在清理提議／去處理 as outline buttons and 看紀錄 as a link", () => {
    const queue = [
      queueRow({ kind_key: "cleanup", triage: ok, cleanup: cleanupPayload(["a8"]), action_url: `${WS}/propose/cleanup/cmp_1` }),
      queueRow({ kind_key: "worse", triage: watch }),
    ];
    renderGroups(items, { actions: adActions("brd_1", "cmp_1", WS, items, queue), open: ["wasted", "watch", "on_target"] });
    const clean = within(screen.getByTestId("ad-row-a8")).getByRole("link", { name: "在清理提議" });
    expect(clean.getAttribute("data-variant")).toBe("outline");
    expect(within(screen.getByTestId("ad-row-a6")).getByRole("link", { name: "去處理" }).getAttribute("data-variant")).toBe("outline");
    expect(within(screen.getByTestId("ad-row-a2")).getByRole("link", { name: "看紀錄" }).getAttribute("data-variant")).toBe("link");
  });
});

describe("ClosedGroup", () => {
  it("folded by default with counts; rows keep numbers, status chip and 看紀錄; truncated prints the rest", () => {
    render(
      <MemoryRouter>
        <ClosedGroup
          workspaceHref={WS} open={false} onToggle={() => {}}
          closed={{
            paused: 40, archived: 17, other: 0, total: 57, truncated: true,
            items: [
              { entity_id: "c1", name: "舊版主視覺 0715", native_status: "PAUSED", thumbnail_url: null, spend: 321, cost_per_result: 45.5, result_label: "購買" },
              { entity_id: "c2", name: "開箱長版 0605", native_status: "ARCHIVED", thumbnail_url: null, spend: null, cost_per_result: null, result_label: "購買" },
              { entity_id: "c3", name: null, native_status: "DELETED", thumbnail_url: null, spend: 0, cost_per_result: null, result_label: "購買" },
            ],
          }}
        />
      </MemoryRouter>,
    );
    const details = detailsOf("已關閉");
    expect(details.open).toBe(false);
    expect(within(details.querySelector("summary")!).getByText("57 則")).toBeTruthy();
    expect(screen.getByText("暫停 40・已封存 17・不列入判斷")).toBeTruthy();
    const paused = screen.getByTestId("closed-ad-row-c1");
    expect(within(paused).getByText("321 元")).toBeTruthy();
    expect(within(paused).getByText("45.5 元")).toBeTruthy();
    expect(within(paused).getByText("已暫停")).toBeTruthy();
    expect(within(paused).getByRole("link", { name: "看紀錄" }).getAttribute("href")).toBe(`${WS}?tab=performance&ad=c1`);
    const archived = screen.getByTestId("closed-ad-row-c2");
    expect(within(archived).getByText("已封存")).toBeTruthy();
    expect(within(archived).getAllByText("未知").length).toBe(2);
    const deleted = screen.getByTestId("closed-ad-row-c3");
    expect(within(deleted).getByText("（未命名廣告）")).toBeTruthy();
    expect(within(deleted).getByText("0 元")).toBeTruthy();
    expect(within(deleted).getByText("已關閉")).toBeTruthy();
    expect(screen.getByText("…其餘 54 則")).toBeTruthy();
  });
});
