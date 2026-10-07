vi.mock("@/lib/figures", async (actual) => ({ ...await actual<typeof import("@/lib/figures")>(), useFigureBases: () => ({roas_at_cap: {label: "花到上限時", formula: "售價 ÷ 每筆上限", unit: "ratio"}, roas_all_spend: {label: "保守", formula: "營收 ÷ 全部花費", unit: "ratio"}, roas_tracked_spend: {label: "樂觀", formula: "營收 ÷ 有追到營收的那部分花費", unit: "ratio"}}) }));
/** F30-I07: the v10 workspace frame — tab routing (six tabs, `perf` key, `?tab=performance` redirect), the perf tab's
 * 「進階：每日資料、次要指標與舊版檢討」 fold, the two independent reads (campaign, workspace progress) and the step targets. The tab
 * bodies are stubs: each has its own tests. */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { assetHandoff, type Placement } from "@/lib/adsUserAssetsApi";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { closeCampaign, getCampaign, getPerformance, type CampaignDetail, type CampaignPerformance } from "@/lib/adsApi";
import { ApiResponseError } from "@/lib/http";
import { getTriage, getQueue, type CampaignTriage, type TriageItem } from "@/lib/adsTriageApi";
import { getAbPairs } from "@/lib/adsAbApi";
import { listMaterialTasks } from "@/lib/adsMaterialApi";
import { readComparison } from "@/lib/adsExperimentApi";
import { completeExternalView, existingCampaigns, syncCampaign, syncJob, syncOutcome, type CampaignSyncOutcome } from "@/lib/adsExternalApi";
import { getCampaignWorkspace, type CampaignWorkspace as WorkspaceRead } from "@/lib/adsWorkspaceApi";
import type { StepTarget } from "./nextStep";
import { CampaignWorkspace } from "./CampaignWorkspace";
import { AssetHandoffPanel } from "./AssetHandoffPanel";
import { currentBudgetMonth } from "./MonthlyBudgetPanel";

// F36-I09 (ruling G): the component reads the org clock through `useWorkspace().identity.org`; the
// timezone is mutable so one case can move the org to UTC+14 without re-mocking the module.
let orgTimezone = "Asia/Taipei";
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({
    scope: "user:org", brands: [], brandsLoading: false, brandsError: null, refreshBrands: () => {},
    identity: {
      user: { id: "usr_1", email: "a@example.com" },
      org: { id: "org_test", name: "測試組織", kind: "personal", role: "owner", timezone: orgTimezone, today: "2020-01-01" },
      orgs: [],
    },
  }),
}));
// 2026-02-28 10:30Z: Kiritimati (UTC+14) is already 2026-03-01 00:30; UTC and the test runner zone
// (Asia/Taipei, UTC+8 = 18:30) are still on 2026-02-28. Only `Date` is faked so timers stay real.
const KIRITIMATI_INSTANT = new Date("2026-02-28T10:30:00Z");
function useKiritimati() {
  beforeEach(() => { orgTimezone = "Pacific/Kiritimati"; vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(KIRITIMATI_INSTANT); });
  afterEach(() => { vi.useRealTimers(); orgTimezone = "Asia/Taipei"; });
}
const composed = vi.hoisted(() => ({ enabled: false }));
vi.mock("@/lib/adsApi", async importOriginal => ({...await importOriginal<object>(), getCampaign: vi.fn(), getPerformance: vi.fn(), closeCampaign: vi.fn()}));
vi.mock("@/lib/adsTriageApi", async importOriginal => ({...await importOriginal<object>(), getTriage: vi.fn(), getQueue: vi.fn()}));
vi.mock("@/lib/adsAbApi", async importOriginal => ({...await importOriginal<object>(), getAbPairs: vi.fn()}));
vi.mock("@/lib/adsMaterialApi", async importOriginal => ({...await importOriginal<object>(), listMaterialTasks: vi.fn()}));
vi.mock("@/lib/adsExperimentApi", async importOriginal => ({...await importOriginal<object>(), readComparison: vi.fn()}));
vi.mock("@/lib/useEchart", () => ({useEchart: () => ({current: null})}));
vi.mock("@/lib/adsWorkspaceApi", () => ({ getCampaignWorkspace: vi.fn() }));
vi.mock("@/lib/adsExternalApi", () => ({ completeExternalView: vi.fn(), syncCampaign: vi.fn(), syncJob: vi.fn(), syncOutcome: vi.fn(), existingCampaigns: vi.fn() }));
// F36-I09: `AssetHandoffPanel` and `currentBudgetMonth` have no suite of their own; this is the nearest one (issue Done #4).
vi.mock("@/lib/adsUserAssetsApi", async importOriginal => ({ ...await importOriginal<object>(), assetHandoff: vi.fn(), bindingAction: vi.fn(), bindingCandidates: vi.fn(), versionMetrics: vi.fn() }));
vi.mock("./AuthAssetMedia", () => ({ AuthAssetMedia: () => null }));
let go: ((t: StepTarget) => void) | null = null;
vi.mock("./workspace/OverviewBody", () => ({
  capOf: () => null,
  OverviewBody: (p: { onGo: (t: StepTarget) => void; advanced: unknown }) => { go = p.onGo; return <h2>v10 總覽</h2>; },
}));
vi.mock("./OverviewTab", () => ({ OverviewTab: () => <h2>舊總覽內容</h2> }));
vi.mock("./StrategyTab", () => ({ StrategyTab: (p: { launchApproved: boolean | null }) => <h2>共用策略 {String(p.launchApproved)}</h2> }));
vi.mock("./DeliveryTab", () => ({ DeliveryTab: () => <h2>共用結構</h2> }));
vi.mock("./AssetsTab", () => ({ AssetsTab: () => <h2>共用素材</h2> }));
vi.mock("./ChangeControl", () => ({ ChangeControl: () => <h2>共用變更</h2> }));
vi.mock("./ReviewPanel", () => ({ ReviewPanel: () => <h2>單則廣告檢討</h2> }));
vi.mock("./PerformanceTab", async importOriginal => {
  const actual = await importOriginal<typeof import("./PerformanceTab")>();
  return {PerformanceTab: (props: Parameters<typeof actual.PerformanceTab>[0]) => composed.enabled
    ? <actual.PerformanceTab {...props} /> : <h2>共用成效</h2>};
});
// The perf body stub exposes what the workspace hands it for the platform read: its button, the busy flag, the
// finished read's served sentence and the close dialog's failure text.
vi.mock("./detail/CampaignDetailPage", async importOriginal => {
  const actual = await importOriginal<typeof import("./detail/CampaignDetailPage")>();
  return {CampaignPerfBody: (props: Parameters<typeof actual.CampaignPerfBody>[0]) => composed.enabled
    ? <actual.CampaignPerfBody {...props} /> : <StubPerfBody {...props} />};
});
function StubPerfBody({ advanced, onSync, syncing, syncNote, syncError }: {
  advanced?: unknown; onSync?: () => void; syncing?: boolean; syncNote?: {state: string; text: string} | null; syncError?: string;
}) {
  return <div><h2>F29 成效本體</h2>
    <button type="button" onClick={onSync} disabled={syncing}>{syncing ? "讀取中…" : "重新讀取平台"}</button>
    <p data-testid="sync-note" data-state={syncNote?.state ?? ""}>{syncNote?.text ?? ""}</p>
    <p data-testid="sync-error">{syncError}</p>{advanced as never}</div>;
}

const CAP: CampaignDetail["cap"] = { value: 450, basis: "own", own_value: 450, break_even: 520, price: 1580, product_id: null, result_kind: "purchase", result_label: "購買", missing: [], revision: 1 };
function detail(o: Partial<CampaignDetail> = {}): CampaignDetail {
  return { id: "c", name: "日常商品推廣・轉換", objective: "購買", origin: "internal", status: "live", groups: [], cap: CAP,
    start_date: "2026-09-08", end_date: "2026-10-08", capabilities: { allowed: [], unavailable: {} }, ...o } as unknown as CampaignDetail;
}
function ws(o: Partial<WorkspaceRead> = {}): WorkspaceRead {
  return { stage: { key: "decide", done: ["plan", "assets", "launch", "read"] }, pending_count: 2, delivery: "live", daily_budget: 1200, active_ads: 8, can_support: 6,
    next_sync_at: null, missing_days: [], totals: null, draft: null, ...o };
}
function Where() { const l = useLocation(); return <p data-testid="where">{l.search}</p>; }
function renderAt(path = "/brands/b/ads/campaigns/c") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:b/ads/campaigns/:c" element={<><CampaignWorkspace brandId="b" campaignId="c" /><Where /></>} />
        <Route path="/brands/:b/ads/campaigns/:c/publish" element={<h2>發布頁</h2>} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  composed.enabled = false;
  go = null;
  vi.mocked(getCampaign).mockResolvedValue(detail());
  vi.mocked(getCampaignWorkspace).mockResolvedValue(ws());
  vi.mocked(completeExternalView).mockResolvedValue({ entities: [], observations: [], next_entity_cursor: null, next_observation_cursor: null, window: { start: "2026-08-20", end: "2026-09-18" }, connections: [], sync: {}, coverage: {} });
});

it("six tabs in prototype order; each tab mounts its body (structure, assets, changes are slots)", async () => {
  renderAt();
  await screen.findByText("v10 總覽");
  const tabs = screen.getByRole("group", { name: "活動分頁" });
  expect([...tabs.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["總覽2", "策略", "投放結構", "素材", "成效", "變更與核對"]);
  for (const [label, content] of [["策略", "共用策略 false"], ["投放結構", "共用結構"], ["素材", "共用素材"], ["變更與核對", "共用變更"], ["成效", "F29 成效本體"]]) {
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${label}`) }));
    expect(await screen.findByText(content)).toBeTruthy();
  }
  expect(screen.getByTestId("where").textContent).toBe("?tab=perf");
  expect(completeExternalView).not.toHaveBeenCalled();
});

it("an unknown pending count shows no number on 總覽 — never 0", async () => {
  vi.mocked(getCampaignWorkspace).mockResolvedValue(ws({ pending_count: null }));
  renderAt();
  await screen.findByText("v10 總覽");
  expect(screen.getByRole("button", { name: "總覽" }).textContent).toBe("總覽");
});

it("?tab=performance lands on perf keeping ?ad=; the old review and platform charts fold opens for it", async () => {
  renderAt("/brands/b/ads/campaigns/c?tab=performance&ad=ad_1");
  await screen.findByText("F29 成效本體");
  expect(screen.getByTestId("where").textContent).toBe("?tab=perf&ad=ad_1");
  expect(screen.getByRole("button", { name: "進階：每日資料、次要指標與舊版檢討" }).getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByText("單則廣告檢討")).toBeTruthy();
  expect(screen.getByText("共用成效")).toBeTruthy();
});

it("perf without ?ad= or ?review= keeps the old review and platform charts folded (and unread)", async () => {
  renderAt("/brands/b/ads/campaigns/c?tab=perf");
  await screen.findByText("F29 成效本體");
  expect(screen.getByRole("button", { name: "進階：每日資料、次要指標與舊版檢討" }).getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByText("單則廣告檢討")).toBeNull();
});

it("imported campaigns read the complete platform view once and use the same tabs", async () => {
  vi.mocked(getCampaign).mockResolvedValue(detail({ origin: "imported" }));
  renderAt();
  await screen.findByText("v10 總覽");
  fireEvent.click(screen.getByRole("button", { name: "素材" }));
  expect(await screen.findByText("共用素材")).toBeTruthy();
  expect(completeExternalView).toHaveBeenCalledTimes(1);
});

it("offers retry when complete native data cannot be loaded", async () => {
  vi.mocked(getCampaign).mockResolvedValue(detail({ origin: "imported" }));
  vi.mocked(completeExternalView).mockRejectedValueOnce(new Error("第二頁讀取失敗"));
  renderAt();
  await screen.findByText("第二頁讀取失敗");
  fireEvent.click(screen.getByRole("button", { name: "重新載入" }));
  await screen.findByText("v10 總覽");
});

it("the progress read fails on its own: the head says so with 重試, the tabs keep working, the old overview stays reachable", async () => {
  vi.mocked(getCampaignWorkspace).mockRejectedValueOnce(new Error("伺服器忙碌"));
  renderAt();
  expect(await screen.findByText(/活動進度讀不到：伺服器忙碌/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "進階：更多活動資訊" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "策略" }));
  expect(await screen.findByText("共用策略 null")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "重試" }));
  expect(await screen.findByRole("navigation", { name: "活動進度" })).toBeTruthy();
  expect(getCampaignWorkspace).toHaveBeenCalledTimes(2);
});

it("step targets: the old 'performance' key opens perf (a draft's empty perf keeps the old fold); 'publish' goes to the publish page's URL", async () => {
  vi.mocked(getCampaign).mockResolvedValue(detail({ status: "draft" }));
  vi.mocked(getCampaignWorkspace).mockResolvedValue(ws({ stage: { key: "plan", done: [] }, pending_count: 0, draft: { cap_set: false, budget_set: false, slots_ready: 0, slots_total: 3, launch_checked: 0, launch_total: 0 } }));
  renderAt();
  await screen.findByText("v10 總覽");
  go!("performance");
  expect(await screen.findByText("還沒上架，沒有成效")).toBeTruthy();
  expect(screen.getByRole("button", { name: "進階：每日資料、次要指標與舊版檢討" })).toBeTruthy(); // the comparison plan stays reachable on a draft
  expect(screen.getByTestId("where").textContent).toBe("?tab=perf");
  fireEvent.click(screen.getByRole("button", { name: "確認上架清單 →" }));
  expect(await screen.findByText("發布頁")).toBeTruthy();
  expect(screen.queryByRole("group", { name: "活動分頁" })).toBeNull();
});

it("'publish' on a campaign that cannot publish (imported) opens the assets tab instead", async () => {
  vi.mocked(getCampaign).mockResolvedValue(detail({ origin: "imported" }));
  renderAt();
  await screen.findByText("v10 總覽");
  go!("publish");
  expect(await screen.findByText("共用素材")).toBeTruthy();
  expect(screen.getByTestId("where").textContent).toBe("?tab=assets");
});

describe("F49 Contract O: 重新讀取平台 follows the campaign's one served outcome", () => {
  const outcome = (state: CampaignSyncOutcome["state"], text: string, code: string | null = null): CampaignSyncOutcome =>
    ({ state, code, text, job_ids: ["aes_1"], last_success_at: "2026-10-11T04:30:00Z" });
  const JOB = { id: "aes_1", status: "pending", last_success_at: null };

  it("a half-failed read is never silent: the partial outcome's reason prints, the campaign and progress re-read, the job is never polled", async () => {
    vi.mocked(syncCampaign).mockResolvedValue({ job: JOB, jobs: [JOB] });
    vi.mocked(syncOutcome).mockResolvedValue(outcome("partial", "有部分平台資料沒讀到：平台暫時沒有回應，稍後會再試", "source_error"));
    renderAt("/brands/b/ads/campaigns/c?tab=perf");
    fireEvent.click(await screen.findByRole("button", { name: "重新讀取平台" }));
    await vi.waitFor(() => expect(screen.getByTestId("sync-note").textContent).toBe("有部分平台資料沒讀到：平台暫時沒有回應，稍後會再試"));
    expect(screen.getByTestId("sync-note").getAttribute("data-state")).toBe("partial");
    expect(screen.getByTestId("sync-error").textContent).toBe("有部分平台資料沒讀到：平台暫時沒有回應，稍後會再試");
    expect(screen.getByRole("button", { name: "重新讀取平台" })).toBeTruthy();
    expect(syncCampaign).toHaveBeenCalledWith("b", "c");
    expect(syncOutcome).toHaveBeenCalledWith("b", "c", expect.any(AbortSignal));
    expect(syncJob).not.toHaveBeenCalled();
    expect(getCampaign).toHaveBeenCalledTimes(2);
    expect(getCampaignWorkspace).toHaveBeenCalledTimes(2);
  });

  it("while the read runs the button is busy; it settles on the served outcome after polling (found prints, no failure text)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.mocked(syncCampaign).mockResolvedValue({ job: JOB });
      vi.mocked(syncOutcome)
        .mockResolvedValueOnce(outcome("running", "正在讀取平台資料"))
        .mockResolvedValueOnce(outcome("found", "已讀到平台資料"));
      renderAt("/brands/b/ads/campaigns/c?tab=perf");
      fireEvent.click(await screen.findByRole("button", { name: "重新讀取平台" }));
      expect(await screen.findByRole("button", { name: "讀取中…" })).toBeTruthy();
      await vi.advanceTimersByTimeAsync(3000);
      await vi.waitFor(() => expect(screen.getByTestId("sync-note").textContent).toBe("已讀到平台資料"));
      expect(screen.getByTestId("sync-error").textContent).toBe("");
      expect(syncOutcome).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a failed read names why; a request that fails prints its own error", async () => {
    vi.mocked(syncCampaign).mockResolvedValueOnce({ job: JOB }).mockRejectedValueOnce(new Error("同步失敗：伺服器忙碌"));
    vi.mocked(syncOutcome).mockResolvedValue(outcome("failed", "這次沒讀到平台資料：平台授權已失效或權限不足，請重新授權", "permission_denied"));
    renderAt("/brands/b/ads/campaigns/c?tab=perf");
    fireEvent.click(await screen.findByRole("button", { name: "重新讀取平台" }));
    await vi.waitFor(() => expect(screen.getByTestId("sync-note").getAttribute("data-state")).toBe("failed"));
    expect(screen.getByTestId("sync-note").textContent).toBe("這次沒讀到平台資料：平台授權已失效或權限不足，請重新授權");
    fireEvent.click(screen.getByRole("button", { name: "重新讀取平台" }));
    await vi.waitFor(() => expect(screen.getByTestId("sync-note").textContent).toBe("同步失敗：伺服器忙碌"));
    expect(screen.getByTestId("sync-note").getAttribute("data-state")).toBe("error");
  });
});

describe("F52 actual composed settlement", () => {
  function observed(cpp: number): CampaignTriage {
    const unit = {basis: "own" as const, currency: "TWD", source: "user", unit_basis: "manual_ntd_input"};
    const metrics = {spend: cpp * 30, result_count: 30, cost_per_result: cpp, result_kind: "purchase",
      result_label: "購買", derived_zero_days: 0, reason: null, currency: "TWD"};
    const item: TriageItem = {entity_id: "e1", native_id: "n1", name: "實際廣告・同步後仍開著的列", campaign_id: "c",
      campaign_name: "日常商品推廣・轉換", thumbnail_url: null, class: "flat", label: "持平", reason_code: "",
      grade: "watch", grade_label: "偏貴", previous_grade: null, grade_move: null,
      delivery: {state: "running", label: "投放中"}, delivery_label: "投放中",
      window: {start: "2026-09-10", end: "2026-09-23", days: 14, previous_start: "2026-08-27",
        previous_end: "2026-09-09", extended_from: null},
      target: {value: 350, basis: "own", result_kind: "purchase", result_label: "購買", missing: [],
        break_even: null, cap_unit: unit}, cap_comparison: {...unit, reason: null, message: null},
      current: metrics, previous: {...metrics, spend: null, result_count: null, cost_per_result: null},
      change_pct: null, sample: {gate: true, spend_multiple: null, days_with_events: 14}};
    return {window_days: 14, items: [item], closed: {groups: [], total: 0, items: [], truncated: false},
      data: {sync: {state: "ok", error: null, last_success_at: "2026-09-24T00:00:00Z"},
        coverage: {start: "2026-09-10", end: "2026-09-23"}, missing_days: [],
        status: {state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: "2026-09-24T00:00:00Z"}}};
  }
  function period(spend: number): CampaignPerformance {
    return {totals: {spend, impressions: 10000, clicks: 100, purchases: 30, revenue: 24000, cpa: spend / 30,
      ctr: 0.01, roas_tracked_spend: 24000 / spend, roas_all_spend: 24000 / spend}, daily: [], groups: [], ads: [],
      coverage: {start: "2026-09-08", end: "2026-09-23", expected: 16, missing: 0, missing_days: [], never_synced: false},
      last_data_at: "2026-09-24T00:00:00Z", scope: {basis: "campaign_window", start: "2026-09-08", end: "2026-09-23",
        days: 16, state: "ready", currency: "TWD", last_complete_day: "2026-09-23", incomplete_day_policy: "excluded",
        day_basis: "account_timezone", account_timezone: "Asia/Taipei", caption: "本期 2026-09-08 ～ 2026-09-23；只計完整帳戶日。"},
      cap_comparison: {basis: "own", currency: "TWD", source: "user", unit_basis: "manual_ntd_input", reason: null, message: null}};
  }
  beforeEach(() => {
    composed.enabled = true;
    Element.prototype.scrollIntoView = vi.fn();
    vi.mocked(getQueue).mockResolvedValue({items: [], counts: {stop_loss: 0, worse: 0, better: 0, flat: 0,
      insufficient: 0, no_target: 0}, total_ads: 1, kinds_available: [], kinds_pending: []});
    vi.mocked(getAbPairs).mockResolvedValue({pairs: [], unavailable: null});
    vi.mocked(listMaterialTasks).mockResolvedValue({tasks: []});
    vi.mocked(readComparison).mockResolvedValue({proposal: null, missing: "缺少合格對照", stale: false,
      closed: false, simulation: false, confirmed: null, result: {verdict: "看不出", reason: "缺資料", values: []}});
  });
  it.each(["found", "partial"] as const)("refreshes the real row, ruler, period and opened advanced view only after served %s", async (outcomeState) => {
    vi.useFakeTimers({shouldAdvanceTime: true}); vi.setSystemTime(new Date("2026-09-24T04:30:00Z"));
    const trace: string[] = []; let terminal = false;
    let acknowledge!: () => void;
    const ack = new Promise<void>(resolve => {acknowledge = resolve;});
    const c = detail({context_json: {}, constraints_json: {}, asset_readiness: {ready_count: 1, total: 1},
      outcome: {spend: 12000, purchases: 30, revenue: 24000},
      lifecycle: {state: "live", label: "投放中", can_close: true}, cap: {...CAP, value: 350, own_value: 350},
      running: {count: 1, unknown: 0, read_at: "2026-09-24T00:00:00Z", stale: false}});
    vi.mocked(getCampaign).mockImplementation(async () => {trace.push(`campaign ${terminal ? "fresh" : "old"}`); return c;});
    vi.mocked(getCampaignWorkspace).mockImplementation(async () => {trace.push(`workspace ${terminal ? "fresh" : "old"}`);
      return ws({active_ads: 1, delivery: "running", lifecycle: c.lifecycle, running: c.running});});
    vi.mocked(getPerformance).mockImplementation(async () => {trace.push(`performance ${terminal ? "fresh" : "old"}`); return period(terminal ? 11400 : 12000);});
    vi.mocked(getTriage).mockImplementation(async () => {trace.push(`triage ${terminal ? "fresh" : "old"}`); return observed(terminal ? 380 : 400);});
    vi.mocked(syncCampaign).mockImplementation(async () => {trace.push("POST start"); await ack; trace.push("POST acknowledged");
      return {job: {id: "aes_1", status: "pending", last_success_at: null}};});
    vi.mocked(syncOutcome).mockImplementationOnce(async () => {trace.push("outcome running"); return {state: "running", code: null,
      text: "正在讀取平台資料", job_ids: ["aes_1"], last_success_at: null};})
      .mockImplementationOnce(async () => {terminal = true; trace.push(`outcome ${outcomeState}`); return {state: outcomeState,
        code: outcomeState === "partial" ? "source_error" : null,
        text: outcomeState === "partial" ? "有部分平台資料沒讀到：素材讀取失敗" : "已讀到平台資料",
        job_ids: ["aes_1"], last_success_at: "2026-09-24T04:30:00Z"};});
    try {
      renderAt("/brands/b/ads/campaigns/c?tab=perf&ad=e1");
      const row = within(await screen.findByTestId("ad-row-e1"));
      expect(row.getByText("400 TWD")).toBeTruthy();
      const status = within(screen.getByTestId("period-status-row"));
      expect(await status.findByText("12,000 TWD")).toBeTruthy();
      const fold = screen.getByRole("button", {name: "進階：每日資料、次要指標與舊版檢討"});
      const advanced = document.getElementById(fold.getAttribute("aria-controls")!)!;
      expect(fold.getAttribute("aria-expanded")).toBe("true");
      await within(advanced).findByText("12,000 TWD");
      fireEvent.click(status.getByRole("button", {name: "重新讀取平台"}));
      await act(async () => acknowledge());
      await vi.waitFor(() => expect(trace).toContain("outcome running"));
      expect(status.getByRole("button", {name: "讀取中…"})).toBeTruthy();
      expect(trace.some(event => event.endsWith("fresh"))).toBe(false);
      await act(async () => vi.advanceTimersByTimeAsync(3000));
      expect(await status.findByText("11,400 TWD")).toBeTruthy();
      expect(await within(advanced).findByText("11,400 TWD")).toBeTruthy();
      console.info("F52 actual composed request trace", JSON.stringify(trace));
      expect(await within(screen.getByTestId("ad-row-e1")).findByText("380 TWD")).toBeTruthy();
      expect(within(screen.getByRole("region", {name: "對照上限"})).getByRole("button", {name: /實際廣告.*380 TWD/})).toBeTruthy();
      expect(fold.getAttribute("aria-expanded")).toBe("true");
      expect(screen.getByTestId("ad-row-e1").className).toContain("ring-primary");
      if (outcomeState === "partial") expect(status.getByText("有部分平台資料沒讀到：素材讀取失敗")).toBeTruthy();
      expect(syncJob).not.toHaveBeenCalled();
    } finally {vi.useRealTimers();}
  });
  it.each(["rejected_post", "unknown_outcome", "failed", "empty"] as const)("keeps explicit %s recovery in the real composed screen", async (caseName) => {
    vi.mocked(getCampaign).mockResolvedValue(detail({context_json: {}, asset_readiness: {ready_count: 1, total: 1},
      lifecycle: {state: "live", label: "投放中", can_close: true}}));
    vi.mocked(getTriage).mockResolvedValue(observed(400));
    vi.mocked(getPerformance).mockResolvedValue(period(12000));
    const message = {rejected_post: "沒有送出平台讀取", unknown_outcome: "讀取結果暫時無法核實",
      failed: "這次沒讀到平台資料：授權已失效", empty: "這次讀取沒有新的平台資料"}[caseName];
    if (caseName === "rejected_post") vi.mocked(syncCampaign).mockRejectedValueOnce(new Error(message));
    else {
      vi.mocked(syncCampaign).mockResolvedValueOnce({job: {id: "aes_1", status: "pending", last_success_at: null}});
      if (caseName === "unknown_outcome") vi.mocked(syncOutcome).mockRejectedValueOnce(new Error(message));
      else vi.mocked(syncOutcome).mockResolvedValueOnce({state: caseName, code: caseName === "failed" ? "permission_denied" : null,
        text: message, job_ids: ["aes_1"], last_success_at: null});
    }
    renderAt("/brands/b/ads/campaigns/c?tab=perf");
    const row = within(await screen.findByTestId("ad-row-e1"));
    const status = within(screen.getByTestId("period-status-row"));
    fireEvent.click(status.getByRole("button", {name: "重新讀取平台"}));
    expect(await status.findByText(message)).toBeTruthy();
    expect(status.getByRole("button", {name: "重新讀取平台"})).toBeTruthy();
    expect(row.getByText("400 TWD")).toBeTruthy();
    const settled = caseName === "failed" || caseName === "empty";
    await vi.waitFor(() => expect(getTriage).toHaveBeenCalledTimes(settled ? 2 : 1));
    expect(screen.getByRole("button", {name: "進階：每日資料、次要指標與舊版檢討"}).getAttribute("aria-expanded")).toBe("false");
    if (caseName === "rejected_post") expect(syncOutcome).not.toHaveBeenCalled();
  });
  it("does not claim the open dialog reread or release its coverage hold after POST rejection", async () => {
    vi.mocked(getCampaign).mockResolvedValue(detail({context_json: {}, asset_readiness: {ready_count: 1, total: 1},
      lifecycle: {state: "live", label: "投放中", can_close: true}}));
    vi.mocked(getTriage).mockResolvedValue(observed(400));
    vi.mocked(getPerformance).mockResolvedValue(period(12000));
    vi.mocked(closeCampaign).mockRejectedValueOnce(new ApiResponseError("有一天還沒讀到平台資料", 409, {}, {
      code: "coverage_missing", details: {missing_days: ["2026-09-22"], never_synced: false, can_skip: false}}));
    let rejectPost!: (reason: Error) => void;
    vi.mocked(syncCampaign).mockImplementationOnce(() => new Promise((_, reject) => {rejectPost = reject;}));
    renderAt("/brands/b/ads/campaigns/c?tab=perf");
    const status = within(await screen.findByTestId("period-status-row"));
    fireEvent.click(status.getByRole("button", {name: "結案這一期 →"}));
    const dialog = within(await screen.findByRole("dialog"));
    fireEvent.click(dialog.getByRole("button", {name: "確認結案"}));
    await dialog.findByText("有 1 天還沒讀到平台資料，先補讀再結案。");
    expect((dialog.getByRole("button", {name: "確認結案"}) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(dialog.getByRole("button", {name: "重新讀取平台"}));
    await dialog.findByRole("button", {name: "讀取中…"});
    await act(async () => rejectPost(new Error("沒有送出平台讀取")));
    await status.findByText("沒有送出平台讀取");
    console.info("F52 real dialog POST rejection", JSON.stringify({post: vi.mocked(syncCampaign).mock.calls.length,
      outcomes: vi.mocked(syncOutcome).mock.calls.length, closeWrites: vi.mocked(closeCampaign).mock.calls.length,
      confirmDisabled: (dialog.getByRole("button", {name: "確認結案"}) as HTMLButtonElement).disabled,
      text: dialog.getByRole("alert").textContent}));
    expect(dialog.queryByText("已重新讀取；按「確認結案」再核對一次。")).toBeNull();
    expect((dialog.getByRole("button", {name: "確認結案"}) as HTMLButtonElement).disabled).toBe(true);
    expect(closeCampaign).toHaveBeenCalledTimes(1);
  });
});

describe("F36-I09 組織時鐘：交接面板與月預算月份", () => {
  useKiritimati();
  const placement: Placement = { id: "p1", revision: 1, is_current: true, asset_id: "asset1", filename: "p1.png", mime_type: "image/png", asset_status: "ready", asset_error: null, copy_fields: { headline: "原標題" }, suggested_copy: {}, purpose: "產品介紹", destination_entity_id: null, start_date: null, end_date: null, status: "pending", pending_reason: "尚待確認安排", required: true, confirmed_at: null, suggestion_batch_id: null };
  it("版本成效日期預設是組織的最近 30 天（UTC+14 已是 3/1），不再是 UTC 的今天", async () => {
    vi.mocked(existingCampaigns).mockResolvedValue({ sources: [] } as unknown as Awaited<ReturnType<typeof existingCampaigns>>);
    vi.mocked(assetHandoff).mockResolvedValue({ original_copy: {}, suggested_copy: {}, effective_copy: {}, tracking_name: "MOS-p1-v1", notice: "內部確認不代表已上架", destination_entity_id: null, download_url: "/api/private", purpose: "產品介紹", start_date: null, end_date: null, bindings: [] });
    render(<MemoryRouter><AssetHandoffPanel brandId="b" campaignId="c" placement={placement} readOnly={false} /></MemoryRouter>);
    await screen.findByText("內部確認不代表已上架");
    expect((screen.getByLabelText("版本成效開始日") as HTMLInputElement).value).toBe("2026-01-31");
    expect((screen.getByLabelText("版本成效結束日") as HTMLInputElement).value).toBe("2026-03-01");
  });
  it("currentBudgetMonth 依組織時區取月份：UTC+14 已是 2026-03，台北還在 2026-02", () => {
    expect(currentBudgetMonth("Pacific/Kiritimati")).toBe("2026-03");
    expect(currentBudgetMonth("Asia/Taipei")).toBe("2026-02");
    expect(currentBudgetMonth()).toBe("2026-02");
  });
});
