/** frontend/src/components/ads/PerformanceTab.test.tsx — F04-I23: 結案卡片今天只在
 * `status === "ended"` 出現，但那個狀態沒有任何程式會寫——這支測試證明 `live` 也看得到
 * 結案卡、看得到提前結案的說明句，以及確認對話框裡同一句話也在。
 * F40-I06: the dialog itself now lives in `CloseCampaignDialog.tsx` (shared with the 成效分頁's 這期狀態列); the
 * 立即結案 cases below prove the folded old panel still opens it, and the F37 cases prove its behaviour is unchanged. */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import type { AdRow, CampaignDetail, CampaignPerformance, DeliveryGroupRow } from "@/lib/adsApi";
import { closeCampaign, CoverageMissingError, getPerformance } from "@/lib/adsApi";
import { readComparison } from "@/lib/adsExperimentApi";
import { readSimulation } from "@/lib/adsSimulationApi";
import { PerformanceTab } from "./PerformanceTab";

vi.mock("@/lib/useEchart", () => ({ useEchart: () => ({ current: null }) }));
vi.mock("@/lib/auth", () => ({ getOrgId: () => "test_org", getAccessToken: async () => "test_token", setOrgId: vi.fn(), signOut: vi.fn() }));

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

vi.mock("@/lib/adsExperimentApi", () => ({
  readComparison: vi.fn(),
  confirmComparison: vi.fn(),
  saveComparisonSettings: vi.fn(),
}));

vi.mock("@/lib/adsSimulationApi", () => ({
  readSimulation: vi.fn(),
  saveSimulation: vi.fn(),
  startSimulation: vi.fn(),
}));

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return {
    ...actual,
    getPerformance: vi.fn(),
    closeCampaign: vi.fn(),
  };
});

function performance(): CampaignPerformance {
  return {
    totals: {
      spend: 0,
      impressions: 0,
      clicks: 0,
      purchases: null,
      revenue: null,
      cpa: null,
      ctr: null,
      roas: null,
      roas_conservative: null,
    },
    daily: [],
    groups: [],
    ads: [],
    coverage: { start: null, end: null, expected: 0, missing: 0, missing_days: [], never_synced: false },
    last_data_at: null,
  };
}

function group(overrides: Partial<DeliveryGroupRow> = {}): DeliveryGroupRow {
  return {
    id: "grp_1",
    campaign_id: "cmp_1",
    channel_key: "meta",
    name: "投放組",
    role: "new",
    daily_budget: 1000,
    start_date: null,
    end_date: null,
    ads: [],
    external_id: null,
    external_name: null,
    external_status: null,
    local_state: "unbound",
    bound_at: null,
    ...overrides,
  };
}

function ad(overrides: Partial<AdRow> = {}): AdRow {
  return {
    id: "ad_1",
    campaign_id: "cmp_1",
    group_id: "grp_1",
    name: "廣告一",
    audience_key: null,
    pain_key: null,
    angle_key: null,
    hook_key: null,
    proof_key: null,
    offer_key: null,
    format_key: null,
    coordinates_snapshot_json: {},
    product_id: null,
    asset_ready_source: null,
    asset_ready_by: null,
    asset_ready_at: null,
    external_id: null,
    external_name: null,
    external_status: null,
    local_state: "unbound",
    bound_at: null,
    ...overrides,
  };
}

function campaign(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    id: "cmp_1",
    name: "測試 Campaign",
    goal_text: "想在雙十一衝一波業績",
    objective: "增加新客購買",
    cap: { value: null, basis: null, own_value: null, break_even: null, price: null, product_id: null, result_kind: "purchase", result_label: "購買", missing: ["product"], revision: 0 },
    start_date: "2026-01-01",
    end_date: "2099-12-31",
    status: "live",
    budget_planned: null,
    budget_scenario: null,
    budget_basis_json: {},
    budget_total: null,
    context_json: {},
    constraints_json: {},
    verdict: null,
    verdict_json: {},
    closed_at: null,
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    groups: [],
    actions: [],
    outcome: { spend: 0, purchases: 0, revenue: 0 },
    asset_readiness: { ready_count: 0, total: 0 },
    judgment: { tone: "neutral", text: "投放中", detail: "還沒有花費資料" },
    action_lines: [],
    external_id: null,
    external_name: null,
    external_status: null,
    local_state: "unbound",
    bound_at: null,
    ...overrides,
  };
}

// F27-I22：`useSearchParams`（`?ad=` 深連結）要有 Router context 才不會炸掉——即使這次
// 沒帶 `?ad=`，元件也無條件呼叫這顆 hook，全部測試都要包 `MemoryRouter`。
function renderTab(c: CampaignDetail, onCampaignChange = vi.fn(), onChangeTab = vi.fn(), path = "/") {
  return { onCampaignChange, onChangeTab, ...render(
    <MemoryRouter initialEntries={[path]}>
      <PerformanceTab brandId="brd_1" campaign={c} onCampaignChange={onCampaignChange} onChangeTab={onChangeTab} />
    </MemoryRouter>,
  ) };
}

// jsdom（v30）沒有實作 `Element.prototype.scrollIntoView`（`?ad=` 深連結用它捲到那一列，
// precedent: `CampaignDetailPage.test.tsx`）——補一個 no-op，測試環境本來就不驗證真的捲動位置。
beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

describe("PerformanceTab 結案卡片（F04-I23）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getPerformance).mockResolvedValue(performance());
    vi.mocked(readComparison).mockResolvedValue({
      proposal: null, missing: "缺少合格對照", stale: false, closed: false, simulation: false,
      confirmed: null, result: { verdict: "看不出", reason: "缺資料", values: [] },
    });
    vi.mocked(readSimulation).mockResolvedValue({
      enabled: true, reason: null, started: false, day: "2026-01-01", revision: 0,
      saved_at: null, saved_by: null, rows: [], closed: false, receipts: {},
    });
  });

  it("live ＋ end_date 在未來：看得到立即結案按鈕與提前結案說明", async () => {
    renderTab(campaign({ status: "live", end_date: "2099-12-31" }));

    expect(await screen.findByRole("button", { name: "立即結案" })).toBeTruthy();
    expect(screen.getByText(/提前結案會用到目前為止的成效判定/)).toBeTruthy();
    expect(screen.getByText(/投放期間到 2099-12-31，現在結案等於提前結束/)).toBeTruthy();
  });

  it("點立即結案：對話框也看得到同一句，確認結案會呼叫 closeCampaign 與 onCampaignChange", async () => {
    const user = userEvent.setup();
    const c = campaign({ status: "live", end_date: "2099-12-31" });
    const updated = campaign({ status: "closed" });
    vi.mocked(closeCampaign).mockResolvedValue(updated);
    const { onCampaignChange } = renderTab(c);

    await screen.findByRole("button", { name: "立即結案" });
    await user.click(screen.getByRole("button", { name: "立即結案" }));

    expect(screen.getAllByText(/提前結案會用到目前為止的成效判定/).length).toBeGreaterThan(1);

    await user.click(screen.getByRole("button", { name: "確認結案" }));

    expect(closeCampaign).toHaveBeenCalledWith("brd_1", c.id);
    expect(onCampaignChange).toHaveBeenCalledWith(updated);
  });

  it("ended：維持原句，不顯示「現在結案等於提前結束」", async () => {
    renderTab(campaign({ status: "ended", end_date: "2099-12-31" }));

    expect(await screen.findByRole("button", { name: "立即結案" })).toBeTruthy();
    expect(screen.getByText("投放已結束，待人工結案；可以現在手動結案。")).toBeTruthy();
    expect(screen.queryByText(/現在結案等於提前結束/)).toBeNull();
  });

  it("draft：結案卡不存在，畫面是空狀態", () => {
    renderTab(campaign({ status: "draft" }));

    expect(screen.queryByText("立即結案")).toBeNull();
    expect(screen.getByText("還沒有成效資料")).toBeTruthy();
  });

  it("ready、素材都就位：空狀態下面看得到規則按鈕「發布 →」", () => {
    renderTab(
      campaign({
        status: "ready",
        budget_basis_json: { strategy: { allocation: [], why: [], unknowns: [], alternatives: [] } },
        groups: [group({ ads: [ad()] })],
        asset_readiness: { ready_count: 1, total: 1, pack_id: "pk_1" },
      }),
    );

    expect(screen.getByText("還沒有成效資料")).toBeTruthy();
    expect(screen.getByRole("button", { name: "發布 →" })).toBeTruthy();
  });

  it("labels 是名單時：draft 空狀態說明與已發布的 KPI 標籤都改印「名單」，不是寫死的「購買」", async () => {
    const labels = { conversion: "名單", count: "名單數", cpa: "每筆名單成本" };
    renderTab(campaign({ status: "draft", labels }));
    expect(screen.getByText(/每日花費、名單與 ROAS 趨勢/)).toBeTruthy();

    renderTab(campaign({ status: "live", end_date: "2099-12-31", labels }));
    await screen.findByText("花費 ÷ 名單");
    expect(screen.getAllByText("名單數").length).toBeGreaterThan(0);
    expect(screen.getByText("花費 ÷ 名單")).toBeTruthy();
  });

  it("先顯示主要成果，次要資料與素材比較都要明確展開才讀取", async () => {
    const user = userEvent.setup();
    renderTab(campaign({ status: "live" }));

    const result = await screen.findByRole("heading", { name: "目前成果" });
    const comparison = screen.getByRole("button", { name: "素材比較（選用）" });
    expect(result.compareDocumentPosition(comparison) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText("點擊率")).toBeNull();
    expect(readComparison).not.toHaveBeenCalled();
    expect(readSimulation).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "查看每日資料、次要指標與公式" }));
    expect(screen.getAllByText("點擊率").length).toBeGreaterThan(0);
    await user.click(comparison);
    await waitFor(() => expect(readComparison).toHaveBeenCalledWith("brd_1", "cmp_1"));
  });

  it("一般 Campaign 不掛載模擬回收；隔離模擬也只在內部工具展開後讀取", async () => {
    const ordinary = renderTab(campaign({ status: "live", simulation_mode: false }));
    await screen.findByRole("heading", { name: "目前成果" });
    expect(screen.queryByRole("button", { name: "內部驗收工具（隔離模擬）" })).toBeNull();
    expect(readSimulation).not.toHaveBeenCalled();
    ordinary.unmount();

    const user = userEvent.setup();
    renderTab(campaign({ status: "live", simulation_mode: true }));
    await screen.findByRole("heading", { name: "目前成果" });
    expect(readSimulation).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "內部驗收工具（隔離模擬）" }));
    await waitFor(() => expect(readSimulation).toHaveBeenCalledTimes(1));
  });

  it("舊 sim_ adapter campaign 仍標示模擬資料，但不開放內部回收工具", async () => {
    renderTab(campaign({ status: "live", simulation_mode: false, external_id: "sim_legacy" }));

    await screen.findByRole("heading", { name: "目前成果" });
    expect(screen.getAllByText(/模擬回收/).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "內部驗收工具（隔離模擬）" })).toBeNull();
    expect(readSimulation).not.toHaveBeenCalled();
  });

  it("F37：自建活動的「重新讀取平台」就是工作區的平台同步；讀完重載成效，已展開的比較也重讀", async () => {
    const user = userEvent.setup();
    const sync = vi.fn();
    const c = campaign({ status: "live" });
    const view = (syncing: boolean) => (
      <MemoryRouter>
        <PerformanceTab brandId="brd_1" campaign={c} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} onSync={sync} syncing={syncing} />
      </MemoryRouter>
    );
    const { rerender } = render(view(false));
    await screen.findByRole("heading", { name: "目前成果" });
    expect(screen.queryByRole("button", { name: "重新整理成效" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "重新讀取平台" }));
    expect(sync).toHaveBeenCalledOnce();
    expect(getPerformance).toHaveBeenCalledTimes(1);
    expect(readComparison).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "素材比較（選用）" }));
    await waitFor(() => expect(readComparison).toHaveBeenCalledTimes(1));
    rerender(view(true));
    expect((screen.getByRole("button", { name: /讀取中/ }) as HTMLButtonElement).disabled).toBe(true);
    rerender(view(false));
    await waitFor(() => expect(getPerformance).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(readComparison).toHaveBeenCalledTimes(2));
  });
});

describe("F37 資料狀態：平台讀到哪一天、哪幾天還沒讀到", () => {
  const coverage = (o: Partial<CampaignPerformance["coverage"]>) => ({
    ...performance(), coverage: { start: "2026-09-01", end: "2026-09-28", expected: 28, missing: 0, missing_days: [], never_synced: false, ...o },
  });
  beforeEach(() => { vi.clearAllMocks(); });

  it("全部讀到：說平台已讀到的期間，沒有警告行", async () => {
    vi.mocked(getPerformance).mockResolvedValue(coverage({}));
    renderTab(campaign({ status: "live" }));
    expect(await screen.findByText("資料狀態：平台已讀到 09/01 ～ 09/28；來源為平台回報。")).toBeTruthy();
    expect(screen.queryByText(/還沒讀到平台資料：/)).toBeNull();
  });

  it("缺日：已讀到的期間不含尾端缺日，警告行列出日子並說不算 0", async () => {
    vi.mocked(getPerformance).mockResolvedValue(coverage({ missing: 2, missing_days: ["2026-09-27", "2026-09-28"] }));
    renderTab(campaign({ status: "live" }));
    expect(await screen.findByText("資料狀態：平台已讀到 09/01 ～ 09/26；來源為平台回報。")).toBeTruthy();
    expect(screen.getByText(/有 2 天還沒讀到平台資料：/).textContent).toContain("這幾天不算 0，按「重新讀取平台」補讀。");
    expect(screen.getByText("09/27")).toBeTruthy();
    expect(screen.getByText("09/28")).toBeTruthy();
  });

  it("缺超過 5 天：只列前 5 天再接「…」", async () => {
    const days = ["2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26"];
    vi.mocked(getPerformance).mockResolvedValue(coverage({ missing: 7, missing_days: days }));
    renderTab(campaign({ status: "live" }));
    expect(await screen.findByText(/有 7 天還沒讀到平台資料：/)).toBeTruthy();
    expect(screen.getByText("09/24")).toBeTruthy();
    expect(screen.queryByText("09/25")).toBeNull();
    expect(screen.getByText("…")).toBeTruthy();
  });

  it("從沒讀過：說還沒讀過平台資料，不是一整排日子", async () => {
    vi.mocked(getPerformance).mockResolvedValue(coverage({ never_synced: true, missing: 0, missing_days: [] }));
    renderTab(campaign({ status: "live" }));
    expect(await screen.findByText("資料狀態：還沒讀過平台資料；來源為平台回報。")).toBeTruthy();
    expect(screen.queryByText(/平台已讀到/)).toBeNull();
  });
});

describe("F37 結案對話框：缺日不放行，重讀仍失敗才可跳過", () => {
  function renderClose(onSync = vi.fn(), syncing = false, extra: Partial<CampaignDetail> = {}) {
    const c = campaign({ status: "ended", ...extra });
    const onCampaignChange = vi.fn();
    const view = (s: boolean) => (
      <MemoryRouter>
        <PerformanceTab brandId="brd_1" campaign={c} onCampaignChange={onCampaignChange} onChangeTab={vi.fn()} onSync={onSync} syncing={s} />
      </MemoryRouter>
    );
    const utils = render(view(syncing));
    return { c, onCampaignChange, rerenderSyncing: (s: boolean) => utils.rerender(view(s)) };
  }
  const gap = (can_skip: boolean) => new CoverageMissingError("有 2 天還沒讀到平台資料，先重新讀取平台。", {
    missing_days: ["2026-09-27", "2026-09-28"], never_synced: false, can_skip,
  });
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getPerformance).mockResolvedValue(performance());
  });

  it("409 缺日：日子列成小方塊、確認結案鎖住，「重新讀取平台」呼叫同步；讀完才重新放行", async () => {
    const user = userEvent.setup();
    const sync = vi.fn();
    vi.mocked(closeCampaign).mockRejectedValue(gap(false));
    const { rerenderSyncing } = renderClose(sync);
    await user.click(await screen.findByRole("button", { name: "立即結案" }));
    await user.click(screen.getByRole("button", { name: "確認結案" }));

    const dialog = await screen.findByRole("dialog");
    expect(await screen.findByText("有 2 天還沒讀到平台資料，先補讀再結案。")).toBeTruthy();
    expect(dialog.textContent).toContain("09/27");
    expect(dialog.textContent).toContain("09/28");
    expect(screen.getByText("缺的日子不會被當成 0；讀到之後這裡會自動放行。")).toBeTruthy();
    expect((screen.getByRole("button", { name: "確認結案" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "仍讀不到，跳過缺日結案" })).toBeNull();

    const reads = screen.getAllByRole("button", { name: "重新讀取平台" });
    await user.click(reads[reads.length - 1]);
    expect(sync).toHaveBeenCalledOnce();
    rerenderSyncing(true);
    expect((screen.getByRole("button", { name: "確認結案" }) as HTMLButtonElement).disabled).toBe(true);
    rerenderSyncing(false);
    await waitFor(() => expect((screen.getByRole("button", { name: "確認結案" }) as HTMLButtonElement).disabled).toBe(false));
  });

  it("can_skip（上次讀取失敗）：紅色說明帶同步錯誤，「仍讀不到，跳過缺日結案」送 skip_missing: true", async () => {
    const user = userEvent.setup();
    const closed = campaign({ status: "closed", verdict: "看不出" });
    vi.mocked(closeCampaign).mockRejectedValueOnce(gap(true)).mockResolvedValueOnce(closed);
    const { c, onCampaignChange } = renderClose(vi.fn(), false, {
      context_json: { external_sync: { observations: { status: "error", error: "來源讀取失敗或連線已解除；已保留前次資料。" } } },
    });
    await user.click(await screen.findByRole("button", { name: "立即結案" }));
    await user.click(screen.getByRole("button", { name: "確認結案" }));

    expect(await screen.findByText("重新讀取失敗：來源讀取失敗或連線已解除；已保留前次資料。")).toBeTruthy();
    expect(screen.getByText(/仍有 2 天讀不到（09\/27、09\/28）/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "再讀一次" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "確認結案" }) as HTMLButtonElement).disabled).toBe(true);

    await user.click(screen.getByRole("button", { name: "仍讀不到，跳過缺日結案" }));
    expect(closeCampaign).toHaveBeenLastCalledWith("brd_1", c.id, { skip_missing: true });
    await waitFor(() => expect(onCampaignChange).toHaveBeenCalledWith(closed));
  });

  it("從沒讀過：說先讀取再結案，不列日子", async () => {
    const user = userEvent.setup();
    vi.mocked(closeCampaign).mockRejectedValue(new CoverageMissingError("這個活動還沒讀過平台資料，先重新讀取平台。", {
      missing_days: [], never_synced: true, can_skip: false,
    }));
    renderClose();
    await user.click(await screen.findByRole("button", { name: "立即結案" }));
    await user.click(screen.getByRole("button", { name: "確認結案" }));
    expect(await screen.findByText("這個活動還沒讀過平台資料，先讀取再結案。")).toBeTruthy();
    expect((screen.getByRole("button", { name: "確認結案" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

it("imported shares the KPI layout and sync while disabling internal operations", async () => {
  vi.clearAllMocks();
  const sync = vi.fn();
  const c = campaign({ origin: "imported", status: "draft", external_view: {
    entities: [], observations: [
      { id: "o", entity_id: "c", day: "2026-09-01", metric_scope: "campaign", attribution_key: "7d", currency: "USD", spend: 12, impressions: null, clicks: null, purchases: null, revenue: null, availability: {} },
      { id: "a", entity_id: "a", day: "2026-09-01", metric_scope: "ad", attribution_key: "7d", currency: "USD", spend: 999, impressions: null, clicks: null, purchases: null, revenue: null, availability: {} },
    ], next_entity_cursor: null, next_observation_cursor: null, window: { start: "2026-09-01", end: "2026-09-30" }, connections: [], sync: {}, coverage: {},
  } });
  render(
    <MemoryRouter>
      <PerformanceTab brandId="b" campaign={c} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} onSync={sync} />
    </MemoryRouter>,
  );
  expect(screen.getByText(/活動 · USD · 7d · 2026-09-01 ～ 2026-09-30/)).toBeTruthy();
  expect(screen.getByText("目前成果")).toBeTruthy(); expect(screen.getByText("12 USD")).toBeTruthy(); expect(screen.queryByText(/保守值/)).toBeNull();
  expect((screen.getByRole("button", { name: "立即結案" }) as HTMLButtonElement).disabled).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "重新讀取平台" })); expect(sync).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole("button", { name: /查看每日資料/ }));
  await userEvent.selectOptions(screen.getByLabelText("資料範圍"), JSON.stringify(["ad", "USD", "7d"]));
  expect(screen.getAllByText("999 USD").length).toBeGreaterThan(0);
  await userEvent.click(screen.getByRole("button", { name: "成效比較" }));
  expect(screen.getByText("既有平台活動不支援內部成效比較。")).toBeTruthy();
  expect(getPerformance).not.toHaveBeenCalled(); expect(readComparison).not.toHaveBeenCalled(); expect(closeCampaign).not.toHaveBeenCalled();
});


it("native reported zero spend is distinct from missing spend", () => {
  const c = campaign({ origin: "imported", external_view: { entities: [], observations: [{ id: "o", entity_id: "c", day: "2026-09-01", metric_scope: "campaign", attribution_key: "7d", currency: "USD", spend: 0, impressions: 0, clicks: 0, purchases: null, revenue: null, availability: {} }], next_entity_cursor: null, next_observation_cursor: null, window: { start: "2026-09-01", end: "2026-09-30" }, connections: [], sync: {}, coverage: {} } });
  render(
    <MemoryRouter>
      <PerformanceTab brandId="b" campaign={c} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} />
    </MemoryRouter>,
  );
  expect(screen.getByText("已讀回花費為 0，暫時無法判讀 CPA 或 ROAS。")).toBeTruthy();
  expect(screen.getByText("0 USD")).toBeTruthy();
});

// F27-I22（Feature Screens「Performance tab」）：`?ad=<entity_id>` 深連結——「廣告花費占比」
// 那張表才有「這則廣告」的一列，比對到就展開次要資料區塊、捲到並高亮那一列；比對不到就印
// 一行誠實訊息，不是靜默失敗或當機。
function outcomeAdRow(overrides: Partial<CampaignPerformance["ads"][number]> = {}): CampaignPerformance["ads"][number] {
  return {
    ad_id: "aex_1", name: "廣告一", spend: 500, impressions: 1000, clicks: 20,
    purchases: 2, revenue: 1500, cpa: 250, ctr: 0.02, roas: 3, roas_conservative: 3,
    spend_share: 1,
    ...overrides,
  };
}

describe("PerformanceTab `?ad=` 深連結（F27-I22）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getPerformance).mockResolvedValue({
      ...performance(),
      ads: [outcomeAdRow({ ad_id: "aex_01M2T3J698SPKTJMBV5A6SN80Z", name: "廣告一" })],
    });
  });

  it("比對到：次要資料區塊自動展開，那一列被捲到並高亮", async () => {
    renderTab(
      campaign({ status: "live" }),
      vi.fn(),
      vi.fn(),
      "/?tab=performance&ad=aex_01M2T3J698SPKTJMBV5A6SN80Z",
    );

    const row = await screen.findByTestId("ad-perf-row-aex_01M2T3J698SPKTJMBV5A6SN80Z");
    expect(row.className).toMatch(/ring-primary/);
    // 次要資料的 Disclosure 沒有另外點開也看得到（`defaultOpen`），這裡用只在展開後才會
    // 出現的「點擊率」欄位當作展開的證據，跟既有測試「先顯示主要成果」同一套斷言方式。
    expect(screen.getAllByText("點擊率").length).toBeGreaterThan(0);
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    expect(screen.queryByText("這則廣告沒有成效資料")).toBeNull();
  });

  it("比對不到：印一行「這則廣告沒有成效資料」，次要資料維持收合", async () => {
    renderTab(campaign({ status: "live" }), vi.fn(), vi.fn(), "/?tab=performance&ad=not_this_ad");

    expect(await screen.findByText("這則廣告沒有成效資料")).toBeTruthy();
    expect(screen.queryByText("點擊率")).toBeNull();
    expect(screen.queryByTestId("ad-perf-row-aex_01M2T3J698SPKTJMBV5A6SN80Z")).toBeNull();
  });

  it("沒有 `?ad=`：不印訊息、次要資料維持既有的收合預設", async () => {
    renderTab(campaign({ status: "live" }));

    await screen.findByRole("heading", { name: "目前成果" });
    expect(screen.queryByText("這則廣告沒有成效資料")).toBeNull();
    expect(screen.queryByText("點擊率")).toBeNull();
  });
});

describe("F36-I09 組織時鐘：提前結案說明", () => {
  useKiritimati();
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getPerformance).mockResolvedValue(performance());
    vi.mocked(readComparison).mockResolvedValue({
      proposal: null, missing: "缺少合格對照", stale: false, closed: false, simulation: false,
      confirmed: null, result: { verdict: "看不出", reason: "缺資料", values: [] },
    });
    vi.mocked(readSimulation).mockResolvedValue({
      enabled: true, reason: null, started: false, day: "2026-01-01", revision: 0,
      saved_at: null, saved_by: null, rows: [], closed: false, receipts: {},
    });
  });
  it("end_date 等於組織的今天（UTC+14 已是 3/1）就不是提前結束；瀏覽器的 2/28 會誤判成提前", async () => {
    renderTab(campaign({ status: "live", end_date: "2026-03-01" }));
    expect(await screen.findByRole("button", { name: "立即結案" })).toBeTruthy();
    expect(screen.queryByText(/現在結案等於提前結束/)).toBeNull();
  });
});

// F37 Contract S: the real `closeCampaign` reads the standard envelope's `error.details` (F37-I03) and
// throws `CoverageMissingError`; any other 409 stays a plain Error with the server's message.
describe("closeCampaign 409 coverage_missing", () => {
  afterEach(() => { vi.unstubAllGlobals(); });
  const reply = (status: number, body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

  it("reads error.details into CoverageMissingError and sends skip_missing", async () => {
    const { closeCampaign: realClose } = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
    const fetchMock = reply(409, { error: { code: "coverage_missing", message: "有 2 天還沒讀到平台資料，先重新讀取平台。",
      details: { missing_days: ["2026-09-27", "2026-09-28"], never_synced: false, can_skip: true } } });
    vi.stubGlobal("fetch", fetchMock);
    const err = await realClose("brd_1", "cmp_1", { skip_missing: true }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(CoverageMissingError);
    expect(err).toMatchObject({ missing_days: ["2026-09-27", "2026-09-28"], never_synced: false, can_skip: true, message: "有 2 天還沒讀到平台資料，先重新讀取平台。" });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ reason: null, skip_missing: true });
  });

  it("another 409 is a plain Error with the server message", async () => {
    const { closeCampaign: realClose } = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
    vi.stubGlobal("fetch", reply(409, { error: { code: "campaign_locked", message: "已鎖定" } }));
    const err = await realClose("brd_1", "cmp_1").catch((e: unknown) => e);
    expect(err).not.toBeInstanceOf(CoverageMissingError);
    expect((err as Error).message).toBe("已鎖定");
  });
});
