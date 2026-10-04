/** F30-I07: the workspace head (prototype v10 `wsHead()`) — chips, the stage rail from `GET …/workspace`, the tab bar's
 * open-decision count, and the progress read failing on its own. Realistic values: the longest imported objective, a
 * break-even cap, a draft without a cap, unknown daily budget and pending count. */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { CampaignDetail } from "@/lib/adsApi";
import type { CampaignWorkspace } from "@/lib/adsWorkspaceApi";
import type { ApiRead } from "@/lib/useApiRead";
import { WorkspaceHead, periodText } from "./WorkspaceHead";

/** F49 Contract L: the served lifecycle, as `app/ads/lifecycle.py` labels it. */
const LIFE = {
  draft: { state: "draft", label: "草稿", can_close: false },
  live: { state: "live", label: "投放中", can_close: true },
  ended: { state: "ended", label: "已結束・待結案", can_close: true },
  closed: { state: "closed", label: "已結案", can_close: false },
  importedLive: { state: "live", label: "投放中", can_close: false },
} as const;
const CAP = { value: 450, basis: "own", own_value: 450, break_even: 520, price: 1580, product_id: null, result_kind: "purchase", result_label: "購買", missing: [], revision: 1 };
function detail(o: Partial<CampaignDetail> = {}): CampaignDetail {
  return { id: "cmp_1", name: "日常商品推廣・轉換", objective: "購買", origin: "internal", status: "live", lifecycle: LIFE.live, cap: CAP,
    start_date: "2026-09-08", end_date: "2026-10-08", groups: [], ...o } as unknown as CampaignDetail;
}
function ws(o: Partial<CampaignWorkspace> = {}): CampaignWorkspace {
  return { stage: { key: "decide", done: ["plan", "assets", "launch", "read"] }, pending_count: 2, delivery: "live", daily_budget: 1200, active_ads: 8,
    running: { count: 8, unknown: 0, read_at: "2026-09-23T04:40:00Z", stale: false },
    can_support: 6, next_sync_at: null, missing_days: [], totals: null, draft: null, ...o };
}
const ready = (data: CampaignWorkspace): ApiRead<CampaignWorkspace> => ({ status: "ready", data, error: null, reload: vi.fn() });
function renderHead(c: CampaignDetail | null, read: ApiRead<CampaignWorkspace>, onTab = vi.fn()) {
  render(<MemoryRouter><WorkspaceHead brandId="brd_1" campaign={c} workspace={read} tab="overview" onTab={onTab} /></MemoryRouter>);
  return { onTab };
}
const chips = () => [...document.querySelectorAll("[data-slot=chip]")].map((e) => {
  const clone = e.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("[role=tooltip]").forEach((t) => t.remove());
  return clone.textContent;
});

describe("WorkspaceHead (F30-I07, v10 wsHead)", () => {
  it("live: the served lifecycle word, objective・在投 N 則, 每日, period, the campaign's own cap; the rail marks done stations and the current one", () => {
    renderHead(detail(), ready(ws()));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("日常商品推廣・轉換");
    expect(chips()).toEqual(["投放中", "購買・在投 8 則", "每日 1,200", "09/08 – 10/08", "日常商品推廣的上限 450"]);
    expect(document.querySelector('[data-slot=chip][data-tone="accent"]')).toBeTruthy();
    const rail = screen.getByRole("navigation", { name: "活動進度" });
    const current = within(rail).getByRole("link", { current: "step" });
    expect(current.textContent).toContain("決策");
    expect(current.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1?tab=overview");
    expect(within(rail).getAllByText("已完成：", { exact: false })).toHaveLength(4);
    expect(within(rail).getByRole("link", { name: /計畫/ }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1?tab=strategy");
    expect(within(rail).getByRole("link", { name: /回顧/ }).getAttribute("href")).toBe("/brands/brd_1/ads/month");
    expect(screen.getByRole("button", { name: /^總覽/ }).textContent).toBe("總覽2");
  });

  it("draft without a cap: 草稿 and 沒設上限 (warn); the plan station is current", () => {
    renderHead(detail({ status: "draft", lifecycle: LIFE.draft, name: "秋季新色預購", cap: { ...CAP, value: null, basis: null, own_value: null, break_even: null } as never }),
      ready(ws({ stage: { key: "plan", done: [] }, pending_count: 0, daily_budget: 800, active_ads: 0, can_support: null,
        draft: { cap_set: false, budget_set: false, slots_ready: 7, slots_total: 8, launch_checked: 0, launch_total: 0 } })));
    expect(chips()).toEqual(["草稿", "每日 800", "09/08 – 10/08", "沒設上限"]);
    expect(screen.getByRole("link", { current: "step" }).textContent).toContain("計畫");
    expect(screen.getByRole("button", { name: /^總覽/ }).textContent).toBe("總覽");
  });

  it("F47-I08: a closed campaign never says 在投 — 已結案 and 平台上還開著 N 則, or 已結案 once every platform ad is closed", () => {
    const closed = detail({ status: "closed", lifecycle: LIFE.closed });
    const stage = { key: "review" as const, done: ["plan", "assets", "launch", "read", "decide"] as never };
    const { unmount } = render(<MemoryRouter><WorkspaceHead brandId="brd_1" campaign={closed}
      workspace={ready(ws({ stage, delivery: null, pending_count: 0, active_ads: 6, running: { count: 6, unknown: 0, read_at: null, stale: false } }))} tab="overview" onTab={vi.fn()} /></MemoryRouter>);
    expect(chips().slice(0, 2)).toEqual(["已結案", "購買・平台上還開著 6 則"]);
    unmount();
    renderHead(closed, ready(ws({ stage, delivery: null, pending_count: 0, active_ads: 0, running: { count: 0, unknown: 0, read_at: null, stale: false } })));
    expect(chips().slice(0, 2)).toEqual(["已結案", "購買"]);
    expect(document.body.textContent).not.toContain("在投");
  });

  it("a break-even cap reads 暫用打平線 in warn; an unknown daily budget and pending count print nothing", () => {
    renderHead(detail({ cap: { ...CAP, value: 520, basis: "break_even", own_value: null } as never }), ready(ws({ daily_budget: null, pending_count: null })));
    expect(chips()).toEqual(["投放中", "購買・在投 8 則", "09/08 – 10/08", "日常商品推廣暫用打平線 520"]);
    expect(document.querySelector('[data-slot=chip][data-tone="warn"]')?.textContent).toContain("打平線");
    expect(screen.getByRole("button", { name: /^總覽/ }).textContent).toBe("總覽");
  });

  it("imported: a whole-sentence objective truncates alone, 在投 N 則 stays; the period comes from the platform root", () => {
    const objective = "【銷售】1150706 Beast Prime 最高數量・轉換最大化（含再行銷與類似受眾）";
    const c = detail({ origin: "imported", lifecycle: LIFE.importedLive, objective, start_date: null, end_date: null, external_view: {
      entities: [{ id: "e", native_kind: "campaign", parent_native_id: null, start_date: "2026-08-01", end_date: null }],
    } as never });
    renderHead(c, ready(ws()));
    const chip = screen.getByTitle(objective);
    expect(chip.className).toContain("truncate");
    expect(chip.parentElement!.textContent).toBe(`${objective}・在投 8 則`);
    expect(periodText(c)).toBe("08/01 – 結束日未知");
  });

  it("the progress read fails on its own: ReadFailed with 重試 where the rail was; the tabs still switch", () => {
    const reload = vi.fn();
    const { onTab } = renderHead(detail(), { status: "error", data: null, error: "伺服器忙碌", reload });
    expect(screen.getByRole("alert").textContent).toContain("活動進度讀不到：伺服器忙碌");
    expect(screen.queryByRole("navigation", { name: "活動進度" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(reload).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "成效" }));
    expect(onTab).toHaveBeenCalledWith("perf");
    expect(chips()).toEqual(["投放中", "購買", "09/08 – 10/08", "日常商品推廣的上限 450"]);
  });

  it("F49 Contract L (drill-11 p2): an ended campaign reads 已結束・待結案 (warn), never 投放中, even while its stored status is live", () => {
    renderHead(detail({ status: "live", lifecycle: LIFE.ended, end_date: "2026-10-09" }),
      ready(ws({ stage: { key: "review", done: ["plan", "assets", "launch", "read", "decide"] }, pending_count: 1,
        running: { count: 6, unknown: 0, read_at: "2026-10-11T04:30:00Z", stale: false } })));
    const word = chips()[0];
    expect(word).toBe("已結束・待結案");
    expect(document.querySelector('[data-slot=chip][data-state="ended"]')!.getAttribute("data-tone")).toBe("warn");
    expect(chips().join("|")).not.toContain("投放中");
    expect(chips()[1]).toBe("購買・在投 6 則");
  });

  it("F49 Contract L (drill-11 E5): a stale read prints its time beside 在投, unknown ads apart; never a read stays honest", () => {
    renderHead(detail(), ready(ws({ active_ads: 0, running: { count: 0, unknown: 2, read_at: "2026-10-04T04:28:00Z", stale: true } })));
    expect(chips()[1]).toMatch(/^購買・在投 0 則（10\/04 \d\d:28 讀取）・2 則狀態不明$/);
    cleanup();
    renderHead(detail(), ready(ws({ active_ads: 0, running: { count: 0, unknown: 0, read_at: null, stale: true } })));
    expect(chips()[1]).toBe("購買・在投 0 則（還沒讀到平台）");
  });

  it("the stage rail and the 總覽 badge are the served stage and pending_count: an approved, confirmed cleanup leaves no badge and the rail off 決策", () => {
    renderHead(detail(), ready(ws({ stage: { key: "read", done: ["plan", "assets", "launch"] }, pending_count: 0 })));
    expect(screen.getByRole("button", { name: /^總覽/ }).textContent).toBe("總覽");
    expect(screen.getByRole("link", { current: "step" }).textContent).toContain("判讀");
    expect(screen.getByRole("link", { current: "step" }).textContent).not.toContain("決策");
  });

  it("no period at all says so", () => {
    expect(periodText(detail({ start_date: null, end_date: null }))).toBe("投放期間尚未設定");
  });
});
