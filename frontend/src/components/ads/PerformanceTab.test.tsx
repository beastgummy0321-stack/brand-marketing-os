/** frontend/src/components/ads/PerformanceTab.test.tsx — F04-I23: 結案卡片今天只在
 * `status === "ended"` 出現，但那個狀態沒有任何程式會寫——這支測試證明 `live` 也看得到
 * 結案卡、看得到提前結案的說明句，以及確認對話框裡同一句話也在。 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";

import type { AdRow, CampaignDetail, CampaignPerformance, DeliveryGroupRow } from "@/lib/adsApi";
import { closeCampaign, getPerformance, ingestOutcome } from "@/lib/adsApi";
import { readComparison } from "@/lib/adsExperimentApi";
import { readSimulation } from "@/lib/adsSimulationApi";
import { PerformanceTab } from "./PerformanceTab";

vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ scope: "user:org" }),
}));

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
    ingestOutcome: vi.fn(),
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
    coverage: { expected: 0, missing: 0 },
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
    success_metric: "cpa",
    success_target: null,
    success_basis: null,
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

function renderTab(c: CampaignDetail, onCampaignChange = vi.fn(), onChangeTab = vi.fn()) {
  return { onCampaignChange, onChangeTab, ...render(
    <PerformanceTab brandId="brd_1" campaign={c} onCampaignChange={onCampaignChange} onChangeTab={onChangeTab} />,
  ) };
}

describe("PerformanceTab 結案卡片（F04-I23）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getPerformance).mockResolvedValue(performance());
    vi.mocked(ingestOutcome).mockResolvedValue(performance());
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
    expect(screen.getByText("投放已結束，7 天後系統會自動結案，也可以現在提前手動結案。")).toBeTruthy();
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

  it("成效重新整理後，已展開的比較同步重新讀取；未使用時仍不讀取", async () => {
    const user = userEvent.setup();
    renderTab(campaign({ status: "live" }));
    await screen.findByRole("heading", { name: "目前成果" });
    await user.click(screen.getByRole("button", { name: "重新整理成效" }));
    await waitFor(() => expect(ingestOutcome).toHaveBeenCalledTimes(1));
    expect(readComparison).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "素材比較（選用）" }));
    await waitFor(() => expect(readComparison).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "重新整理成效" }));
    await waitFor(() => expect(readComparison).toHaveBeenCalledTimes(2));
  });
});
