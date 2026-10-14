import type { LearningEvidence, LearningEvidenceContext } from "@/lib/adsLearningEvidence";

function learningEvidence(id = "learning-fixture"): LearningEvidence {
  return {
    schema_version: 1, id, meaning_revision: "meaning-fixture", display_text: "歷史紀錄",
    support_label: "來源尚未核實", provenance: "unknown",
    sources: [{kind: null, id: null, version: null, period: {start: null, end: null}, label: null}],
    scope: {product_id: null, product_label: null, audience_key: null, customer_group_id: null,
      claim_key: null, claim_family: null, objective_family: null, result_kind: null, currency: null, attribution: null},
    conditions: {price_version: null, offer_key: null, offer_version: null, material_version: null,
      target_version: null, valid_until: null},
    sample: {result_events: null, sufficient: null}, independent_count: 0, same_direction_count: 0,
    contrary_count: 0, use_state: "history", reason_codes: ["unknown_source"],
    reason_labels: ["來源尚未核實，保留為歷史"], allowed_uses: [], limits: ["conditions_unknown"],
  };
}
const evidenceContext: LearningEvidenceContext = {
  schema_version: 1, revision: "context-fixture", scope_product_id: null, scope_label: null,
  eligible_count: 0, items: [], omitted: 0,
};
/** frontend/src/components/ads/PerformanceTab.test.tsx — F04-I23: 結案卡片今天只在
 * `status === "ended"` 出現，但那個狀態沒有任何程式會寫——這支測試證明 `live` 也看得到
 * 結案卡、看得到提前結案的說明句，以及確認對話框裡同一句話也在。
 * F40-I06: the dialog itself now lives in `CloseCampaignDialog.tsx` (shared with the 成效分頁's 這期狀態列); the
 * 立即結案 cases below prove the folded old panel still opens it, and the F37 cases prove its behaviour is unchanged. */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import type { AdRow, CampaignCard, CampaignDetail, CampaignPerformance, DeliveryGroupRow, ResultEvidence } from "@/lib/adsApi";
import type { ExternalView, NativeObservation } from "@/lib/adsExternalApi";
import { closeCampaign, coverageGapOf, getPerformance, listCampaigns } from "@/lib/adsApi";
import { ApiResponseError } from "@/lib/http";
import { getCoordinateLearnings, type CoordinateLearnings, type LearningCampaign } from "@/lib/adsLearningsApi";
import { readComparison } from "@/lib/adsExperimentApi";
import { readSimulation } from "@/lib/adsSimulationApi";
import { PerformanceTab } from "./PerformanceTab";
import { PeriodStatusRow } from "./detail/PeriodStatusRow";
import { AllCampaignsPage } from "./AllCampaignsPage";

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
    listCampaigns: vi.fn(),
  };
});

vi.mock("@/lib/adsLearningsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsLearningsApi")>("@/lib/adsLearningsApi");
  return { ...actual, getCoordinateLearnings: vi.fn() };
});

/** F46 Contract L for `?campaign_id=cmp_1` in its served shape (drill-10 numbers): cap 450, two ads under it → 留下,
 * the third over it → 換掉; rows in the served rank order. */
const LEARNED_CAMPAIGN: LearningCampaign = {
  campaign_id: "cmp_1", campaign_name: "三盒組・09/19～10/01", sell_way_id: "prd_box",
  start_date: "2026-09-19", end_date: "2026-10-01", closed_on: "2026-10-02", cap: 450, currency: "TWD",
  spend: 4806, sales: 13, cost_per_sale: 369.7, counts: { keep: 2, replace: 1 },
  rule_text: "2 則每筆低於上限 450 → 留下；其餘換掉", empty_reason: null,
  rows: [
    {
      rank: 1, of: 3, ad_id: "ada_1", ad_name: "備考生・讀到深夜", customer_group: { id: "pcg_study", who: "學生備考" },
      coordinates: [{ dimension: "angle", dimension_label: "角度", key: "late", label: "陪你撐完最後一章" }],
      spend: 1160, sales: 4, cost_per_sale: 290, verdict: "keep", verdict_label: "留下", flags: ["樣本少"], evidence: learningEvidence(), learning_id: "lrn_1",
    },
    {
      rank: 2, of: 3, ad_id: "ada_2", ad_name: "考前一週・書包一盒", customer_group: { id: "pcg_study", who: "學生備考" },
      coordinates: [{ dimension: "angle", dimension_label: "角度", key: "box", label: "書包裡放一盒就好" }],
      spend: 2226, sales: 7, cost_per_sale: 318, verdict: "keep", verdict_label: "留下", flags: [], evidence: learningEvidence(), learning_id: "lrn_2",
    },
    {
      rank: 3, of: 3, ad_id: "ada_3", ad_name: "會議前・午休五分鐘", customer_group: null,
      coordinates: [], spend: 1420, sales: 2, cost_per_sale: 710, verdict: "replace", verdict_label: "換掉", flags: ["樣本少"], evidence: learningEvidence(), learning_id: "lrn_3",
    },
  ],
};
const LEARNED: CoordinateLearnings = {
  evidence_context: evidenceContext, campaigns: [LEARNED_CAMPAIGN],
  groups: [{ customer_group_id: "pcg_study", who: "學生備考", ads: 2, spend: 3386, sales: 11, cap: 450, cost_per_sale: 307.8 }],
  next: { sell_way_id: "prd_box", new_campaign_href: "/brands/brd_1/ads/new?sell_way=prd_box" },
};

beforeEach(() => {
  vi.mocked(getCoordinateLearnings).mockResolvedValue(LEARNED);
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
      roas_tracked_spend: null,
      roas_all_spend: null,
    },
    daily: [],
    groups: [],
    ads: [],
    coverage: { start: null, end: null, expected: 0, missing: 0, missing_days: [], never_synced: false },
    last_data_at: null,
  };
}

function resultEvidence(overrides: Partial<ResultEvidence> = {}): ResultEvidence {
  return {result_kind: "lead", result_label: "名單", result_action: "lead", result_attribution: "7d_click",
    currency: "TWD", spend: 1000, count: 10, known_count: 10, cost_per_result: 100,
    state: "known_positive", data_state: "known_positive", comparison_state: "ready", reasons: [],
    target: {value: 100, basis: "own", result_kind: "lead", revision: 1},
    sample: {count: 10, result_kind: "lead", days: 7, days_present: 7, days_known: 7, derived_zero_days: 0},
    evidence_refs: ["observation"], evidence_ref_count: 1, evidence_refs_omitted: 0, ...overrides};
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

/** F49 Contract L: the served lifecycle for a stored status, as `app/ads/lifecycle.py` labels it (imported never closes). */
function lifecycleOf(status: CampaignDetail["status"], imported: boolean): CampaignDetail["lifecycle"] {
  if (status === "draft" || status === "ready") return { state: imported ? "live" : "draft", label: imported ? "投放中" : "草稿", can_close: false };
  if (status === "closed") return { state: "closed", label: "已結案", can_close: false };
  if (status === "ended") return { state: "ended", label: imported ? "已結束" : "已結束・待結案", can_close: !imported };
  return { state: "live", label: "投放中", can_close: !imported };
}

function campaign(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    lifecycle: lifecycleOf(overrides.status ?? "live", overrides.origin === "imported"),
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
    // F46: the dialog stays on the result; the closed campaign is handed back when it is dismissed.
    await screen.findByText("已結案：留下 2 則、換掉 1 則");
    expect(onCampaignChange).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "關閉" }));
    expect(onCampaignChange).toHaveBeenCalledWith(updated);
  });

  it("ended：維持原句，不顯示「現在結案等於提前結束」", async () => {
    renderTab(campaign({ status: "ended", end_date: "2099-12-31" }));

    expect(await screen.findByRole("button", { name: "立即結案" })).toBeTruthy();
    expect(screen.getByText("投放已結束，待人工結案；可以現在手動結案。")).toBeTruthy();
    expect(screen.queryByText(/現在結案等於提前結束/)).toBeNull();
  });

  it("F49 Contract L：served lifecycle 是 ended（儲存狀態還是 live）就是已結束的句子；can_close 為 false 就沒有結案卡", async () => {
    const { unmount } = renderTab(campaign({ status: "live", lifecycle: { state: "ended", label: "已結束・待結案", can_close: true } }));
    expect(await screen.findByText("投放已結束，待人工結案；可以現在手動結案。")).toBeTruthy();
    unmount();
    renderTab(campaign({ status: "live", lifecycle: { state: "live", label: "投放中", can_close: false } }));
    expect(await screen.findByText("目前成果")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "立即結案" })).toBeNull();
  });

  it("F49 Contract O：上一次讀取平台的結果原句印在「重新讀取平台」下面", async () => {
    render(
      <MemoryRouter>
        <PerformanceTab brandId="brd_1" campaign={campaign({ status: "live" })} onCampaignChange={vi.fn()} onChangeTab={vi.fn()}
          onSync={vi.fn()} syncNote={{ state: "empty", text: "沒有讀到資料：平台在這段期間沒有回傳任何資料" }} />
      </MemoryRouter>,
    );
    const note = await screen.findByRole("status");
    expect(note.textContent).toBe("沒有讀到資料：平台在這段期間沒有回傳任何資料");
    expect(note.getAttribute("data-state")).toBe("empty");
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
    const view = (syncing: boolean, readGeneration = 0) => (
      <MemoryRouter>
        <PerformanceTab brandId="brd_1" campaign={c} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} onSync={sync} syncing={syncing} readGeneration={readGeneration} />
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
    rerender(view(false, 1));
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
    const view = (s: boolean, readGeneration = 0) => (
      <MemoryRouter>
        <PerformanceTab brandId="brd_1" campaign={c} onCampaignChange={onCampaignChange} onChangeTab={vi.fn()} onSync={onSync} syncing={s} readGeneration={readGeneration} />
      </MemoryRouter>
    );
    const utils = render(view(syncing));
    return { c, onCampaignChange, rerenderSyncing: (s: boolean, readGeneration = 0) => utils.rerender(view(s, readGeneration)) };
  }
  const gap = (can_skip: boolean) => new ApiResponseError("有 2 天還沒讀到平台資料，先重新讀取平台。", 409, {}, {
    code: "coverage_missing", details: { missing_days: ["2026-09-27", "2026-09-28"], never_synced: false, can_skip },
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
    rerenderSyncing(false, 1);
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
    await user.click(await screen.findByRole("button", { name: "關閉" }));
    await waitFor(() => expect(onCampaignChange).toHaveBeenCalledWith(closed));
  });

  it("從沒讀過：說先讀取再結案，不列日子", async () => {
    const user = userEvent.setup();
    vi.mocked(closeCampaign).mockRejectedValue(new ApiResponseError("這個活動還沒讀過平台資料，先重新讀取平台。", 409, {}, {
      code: "coverage_missing", details: { missing_days: [], never_synced: true, can_skip: false },
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
  vi.mocked(getPerformance).mockResolvedValue({origin: "imported", external_view: c.external_view!});
  render(
    <MemoryRouter>
      <PerformanceTab brandId="b" campaign={c} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} onSync={sync} />
    </MemoryRouter>,
  );
  expect(await screen.findByText(/活動 · USD · 7d · 2026-09-01 ～ 2026-09-30/)).toBeTruthy();
  expect(screen.getByText("目前成果")).toBeTruthy(); expect(screen.getByText("12 USD")).toBeTruthy(); expect(screen.queryByText(/保守值/)).toBeNull();
  expect((screen.getByRole("button", { name: "立即結案" }) as HTMLButtonElement).disabled).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "重新讀取平台" })); expect(sync).toHaveBeenCalledOnce();
  await userEvent.click(screen.getByRole("button", { name: /查看每日資料/ }));
  await userEvent.selectOptions(screen.getByLabelText("資料範圍"), JSON.stringify(["ad", "USD", "7d"]));
  expect(screen.getAllByText("999 USD").length).toBeGreaterThan(0);
  await userEvent.click(screen.getByRole("button", { name: "成效比較" }));
  expect(screen.getByText("既有平台活動不支援內部成效比較。")).toBeTruthy();
  expect(getPerformance).toHaveBeenCalledWith("b", "cmp_1", true); expect(readComparison).not.toHaveBeenCalled(); expect(closeCampaign).not.toHaveBeenCalled();
});


it("native reported zero spend is distinct from missing spend", async () => {
  const c = campaign({ origin: "imported", external_view: { entities: [], observations: [{ id: "o", entity_id: "c", day: "2026-09-01", metric_scope: "campaign", attribution_key: "7d", currency: "USD", spend: 0, impressions: 0, clicks: 0, purchases: null, revenue: null, availability: {} }], next_entity_cursor: null, next_observation_cursor: null, window: { start: "2026-09-01", end: "2026-09-30" }, connections: [], sync: {}, coverage: {} } });
  vi.mocked(getPerformance).mockResolvedValue({origin: "imported", external_view: c.external_view!});
  render(
    <MemoryRouter>
      <PerformanceTab brandId="b" campaign={c} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} />
    </MemoryRouter>,
  );
  expect(await screen.findByText("已讀回花費為 0，暫時無法判讀 CPA 或 ROAS。")).toBeTruthy();
  expect(screen.getByText("0 USD")).toBeTruthy();
});

// F27-I22（Feature Screens「Performance tab」）：`?ad=<entity_id>` 深連結——「廣告花費占比」
// 那張表才有「這則廣告」的一列，比對到就展開次要資料區塊、捲到並高亮那一列；比對不到就印
// 一行誠實訊息，不是靜默失敗或當機。
function outcomeAdRow(overrides: Partial<CampaignPerformance["ads"][number]> = {}): CampaignPerformance["ads"][number] {
  return {
    ad_id: "aex_1", name: "廣告一", spend: 500, impressions: 1000, clicks: 20,
    purchases: 2, revenue: 1500, cpa: 250, ctr: 0.02, roas_tracked_spend: 3, roas_all_spend: 3,
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

it("CPA goes through the one per-sale rule: 971.54 prints 972 TWD like home (F47-I06)", async () => {
  vi.mocked(getPerformance).mockResolvedValue({ ...performance(), totals: { ...performance().totals, spend: 9715.4, purchases: 10, cpa: 971.54 } });
  renderTab(campaign({ status: "live" }));
  expect((await screen.findAllByText("972 TWD")).length).toBeGreaterThan(0);
  expect(screen.queryByText(/971\.54/)).toBeNull();
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
// throws an `ApiResponseError` coded `coverage_missing` whose details `coverageGapOf` reads; any other 409 has
// no gap and keeps the server's message.
describe("closeCampaign 409 coverage_missing", () => {
  afterEach(() => { vi.unstubAllGlobals(); });
  const reply = (status: number, body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

  it("reads error.details into the coverage gap and sends skip_missing", async () => {
    const { closeCampaign: realClose } = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
    const fetchMock = reply(409, { error: { code: "coverage_missing", message: "有 2 天還沒讀到平台資料，先重新讀取平台。",
      details: { missing_days: ["2026-09-27", "2026-09-28"], never_synced: false, can_skip: true } } });
    vi.stubGlobal("fetch", fetchMock);
    const err = await realClose("brd_1", "cmp_1", { skip_missing: true }).catch((e: unknown) => e);
    expect(err).toMatchObject({ code: "coverage_missing", status: 409, message: "有 2 天還沒讀到平台資料，先重新讀取平台。" });
    expect(coverageGapOf(err)).toEqual({ missing_days: ["2026-09-27", "2026-09-28"], never_synced: false, can_skip: true });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ reason: null, skip_missing: true });
  });

  it("another 409 has no coverage gap and keeps the server message", async () => {
    const { closeCampaign: realClose } = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
    vi.stubGlobal("fetch", reply(409, { error: { code: "campaign_locked", message: "已鎖定" } }));
    const err = await realClose("brd_1", "cmp_1").catch((e: unknown) => e);
    expect(coverageGapOf(err)).toBeNull();
    expect(err).toMatchObject({ code: "campaign_locked", message: "已鎖定" });
  });
});

// F46-I07 (prototype f46-learnings `#/close`): confirm → 結案中… → result with the two exits. The result reads Contract
// L for this campaign after the close; the parent only hears about the closed campaign when the dialog is dismissed.
const EARLY_CLOSE_TEXT = "提前結案會用到目前為止的成效判定，判定後這個 Campaign 不再更新成效";

describe("F46 結案對話框：結果與兩個出口", () => {
  const planned = () => [group({ ads: [ad({ id: "ada_1", name: "備考生・讀到深夜" }), ad({ id: "ada_2", name: "考前一週・書包一盒" })] }),
    group({ id: "grp_2", ads: [ad({ id: "ada_3", group_id: "grp_2", name: "會議前・午休五分鐘" })] })];
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getPerformance).mockResolvedValue(performance());
    vi.mocked(getCoordinateLearnings).mockResolvedValue(LEARNED);
  });

  async function openAndConfirm(c: CampaignDetail) {
    const user = userEvent.setup();
    const closed = { ...c, status: "closed" as const, lifecycle: lifecycleOf("closed", false) };
    vi.mocked(closeCampaign).mockResolvedValue(closed);
    const utils = renderTab(c);
    await user.click(await screen.findByRole("button", { name: "立即結案" }));
    return { user, closed, ...utils };
  }

  it("confirm names no ad count (F48-I11); 結案中… holds until the learnings are read; result = counts, rule, ranked rows, exits", async () => {
    let release: (v: CoordinateLearnings) => void = () => {};
    vi.mocked(getCoordinateLearnings).mockReturnValue(new Promise((resolve) => { release = resolve; }));
    const { user, closed, onCampaignChange } = await openAndConfirm(campaign({ status: "ended", groups: planned() }));
    const dialog = screen.getByRole("dialog");
    // F48-I11: the planned ads are not the platform ads closeout ranks (that count is not on this payload) -- no count.
    expect(dialog.textContent).toContain("結案後會把這期的廣告照每筆成本排名、判定留下或換掉，寫進品牌智庫「投放學到的」。活動之後鎖定，不能再改。");
    expect(dialog.textContent).not.toMatch(/這期 \d+ 則/);
    expect(dialog.textContent).not.toContain(EARLY_CLOSE_TEXT); // ended: no early-close sentence

    await user.click(screen.getByRole("button", { name: "確認結案" }));
    expect(await screen.findByRole("button", { name: "結案中…" })).toBeTruthy();
    expect(getCoordinateLearnings).toHaveBeenCalledWith("brd_1", { campaignId: "cmp_1" });
    release(LEARNED);

    const result = await screen.findByRole("dialog", { name: "已結案：留下 2 則、換掉 1 則" });
    expect(within(result).getByText("2 則每筆低於上限 450 → 留下；其餘換掉")).toBeTruthy();
    const rows = within(result).getAllByRole("row");
    expect(rows.map((r) => r.getAttribute("data-ad"))).toEqual(["ada_1", "ada_2", "ada_3"]);
    expect(within(rows[0]).getByText("290")).toBeTruthy();
    expect(within(rows[0]).getByText("樣本少")).toBeTruthy();
    expect(within(rows[2]).getByText("換掉")).toBeTruthy();
    expect(within(rows[2]).getByText("未指定")).toBeTruthy();
    expect(within(result).queryByRole("columnheader")).toBeNull(); // headless: no column header row
    expect(within(result).getByRole("link", { name: "看學到什麼 →" }).getAttribute("href"))
      .toBe("/brands/brd_1/library?tab=ads-learnings&campaign=cmp_1");
    expect(within(result).getByRole("link", { name: "用這些學習排下一期 →" }).getAttribute("href"))
      .toBe("/brands/brd_1/ads/new?sell_way=prd_box");

    expect(onCampaignChange).not.toHaveBeenCalled();
    await user.click(within(result).getByRole("button", { name: "關閉" }));
    expect(onCampaignChange).toHaveBeenCalledWith(closed);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("live: the early-close sentence stays after the new confirm sentence", async () => {
    await openAndConfirm(campaign({ status: "live", groups: planned() }));
    expect(screen.getByRole("dialog").textContent).toContain(`活動之後鎖定，不能再改。 ${EARLY_CLOSE_TEXT}`);
  });

  it("a failed learnings read after a successful close: says so, both exits stay (next = the plain create page)", async () => {
    vi.mocked(getCoordinateLearnings).mockRejectedValue(new Error("讀取投放學到的失敗。"));
    const { user, closed, onCampaignChange } = await openAndConfirm(campaign({ status: "ended", groups: planned() }));
    await user.click(screen.getByRole("button", { name: "確認結案" }));
    const result = await screen.findByRole("dialog", { name: "已結案，學到的暫時讀不到" });
    expect(within(result).queryByRole("table")).toBeNull();
    expect(within(result).getByRole("link", { name: "看學到什麼 →" }).getAttribute("href"))
      .toBe("/brands/brd_1/library?tab=ads-learnings&campaign=cmp_1");
    const next = within(result).getByRole("link", { name: "用這些學習排下一期 →" });
    expect(next.getAttribute("href")).toBe("/brands/brd_1/ads/new");
    // Leaving through an exit also hands the closed campaign back.
    await user.click(next);
    expect(onCampaignChange).toHaveBeenCalledWith(closed);
  });

  it("an empty view (no ranked rows) prints its empty_reason and still offers both exits", async () => {
    vi.mocked(getCoordinateLearnings).mockResolvedValue({
      ...LEARNED,
      evidence_context: evidenceContext, campaigns: [{ ...LEARNED_CAMPAIGN, rows: [], counts: { keep: 0, replace: 0 }, spend: null, sales: null, cost_per_sale: null,
        rule_text: "", empty_reason: "資料缺天，這期沒有記學習" }],
      groups: [],
    });
    const { user } = await openAndConfirm(campaign({ status: "ended", groups: planned() }));
    await user.click(screen.getByRole("button", { name: "確認結案" }));
    const result = await screen.findByRole("dialog", { name: "已結案" });
    expect(within(result).getByText("資料缺天，這期沒有記學習")).toBeTruthy();
    expect(within(result).queryByRole("table")).toBeNull();
    expect(within(result).getByRole("link", { name: "看學到什麼 →" })).toBeTruthy();
    expect(within(result).getByRole("link", { name: "用這些學習排下一期 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/new?sell_way=prd_box");
  });
});

vi.mock("@/lib/figures", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/figures")>(),
  useFigureBases: () => ({
    roas_all_spend: {label: "保守", formula: "營收 ÷ 全部花費", unit: "ratio"},
    roas_tracked_spend: {label: "樂觀", formula: "營收 ÷ 有追到營收的那部分花費", unit: "ratio"},
    roas_platform: {label: "平台回報", formula: "平台回報營收 ÷ 花費", unit: "ratio"},
  }),
}));


it("prints the served closeout sentence verbatim without rebuilding verdict arithmetic", async () => {
  vi.mocked(getPerformance).mockResolvedValue(performance());
  renderTab(campaign({status: "closed", lifecycle: {state: "closed", label: "已結案", can_close: false}, verdict: "達成", learning_sentence: "這是後端保存的結案原句；不使用前端重新計算。"}));
  expect(await screen.findByText("這是後端保存的結案原句；不使用前端重新計算。")).toBeTruthy();
});

it("prints both served ROAS bases for the KPI, daily and group rows", async () => {
  const data = performance();
  data.totals.roas_all_spend = 2.25; data.totals.roas_tracked_spend = 3.75;
  vi.mocked(getPerformance).mockResolvedValue(data);
  renderTab(campaign({status: "live"}));
  expect(await screen.findByText("2.25x")).toBeTruthy();
  expect(screen.getByText("3.75x")).toBeTruthy();
  expect(screen.getAllByRole("button", {name: "保守怎麼算：營收 ÷ 全部花費"}).length).toBeGreaterThan(0);
  expect(screen.getAllByRole("button", {name: "樂觀怎麼算：營收 ÷ 有追到營收的那部分花費"}).length).toBeGreaterThan(0);
});

it.each(["currency", "reason"])("actual campaign list preserves served incomparable-money %s", async (field) => {
  const reason = "本期花費與 TWD 預算的幣別不同或尚未核實，無法比較進度。";
  const card: CampaignCard = {
    id: "cmp_usd", name: "USD actual period vs TWD plan", status: "live", origin: "internal",
    capabilities: campaign().capabilities, objective: "購買", created_at: "2026-10-24T00:00:00Z",
    created_by: null, start_date: "2026-10-24", end_date: "2026-10-30", budget_planned: 500,
    budget_total: 497, budget_progress: {spent: 900, total: 497, pct: null},
    outcome: {spend: 900, purchases: 12, revenue: 18720},
    lifecycle: {state: "live", label: "進行中", can_close: true},
    judgment: {tone: "neutral", text: "投放中，預算進度無法比較",
      detail: "已花費 USD 900・第 3／7 天；本期花費與 TWD 預算的幣別不同或尚未核實。"},
  };
  Object.assign(card.budget_progress, {currency: "USD", budget_currency: "TWD", reason});
  vi.mocked(listCampaigns).mockResolvedValue([card]);
  render(<MemoryRouter><AllCampaignsPage brandId="brd_1" /></MemoryRouter>);
  const row = await screen.findByRole("row", {name: /USD actual period vs TWD plan/});
  const budgetCell = within(row).getAllByRole("cell")[3];
  if (field === "currency") expect(budgetCell.textContent).toContain("900 USD / NT$ 497");
  if (field === "reason") expect(budgetCell.textContent).toContain(reason);
});

it("prints the served completed period and currency without reconstructing dates or money", async () => {
  const data = performance();
  data.totals.spend = 123.45;
  data.totals.cpa = 24.69;
  data.totals.purchases = 5;
  data.totals.revenue = 1000;
  data.scope = {start: "2026-10-24", end: "2026-10-26", days: 3, basis: "campaign_window",
    state: "ready", last_complete_day: "2026-10-26", incomplete_day_policy: "excluded",
    day_basis: "account_timezone", account_timezone: "America/New_York", currency: "USD",
    attribution_key: "7d", caption: "本期 2026-10-24 ～ 2026-10-26；只計完整帳戶日，今日尚未完整的資料不計入。"};
  data.cap_comparison = {basis: "break_even", currency: "TWD", reason: "cap_currency_mismatch",
    message: "上限與本期成效的幣別不同或尚未核實，不能比較。"};
  vi.mocked(getPerformance).mockResolvedValue(data);
  renderTab(campaign({status: "live", end_date: "2026-10-30"}));
  expect(await screen.findByText(data.scope.caption)).toBeTruthy();
  expect(screen.getByText("123.45 USD")).toBeTruthy();
  expect(screen.getByText("25 USD")).toBeTruthy();
  expect(screen.getByText(data.cap_comparison.message!)).toBeTruthy();
});

it("uses the scoped imported performance read after workspace hydration supplied raw today", async () => {
  const complete: NativeObservation = { id: "complete", entity_id: "native", day: "2026-10-26", metric_scope: "campaign", attribution_key: "test", currency: "TWD", spend: 300, impressions: null, clicks: null, purchases: 4, revenue: 6240, availability: {} };
  const raw: ExternalView = { entities: [], observations: [complete, {...complete, id: "today", day: "2026-10-27", spend: 999}], next_entity_cursor: null, next_observation_cursor: null, window: {start: "2026-09-28", end: "2026-10-27"}, connections: [], sync: {}, coverage: {} };
  const c = campaign({origin: "imported", external_view: raw});
  const actualScopedResponse = {origin: "imported" as const, external_view: {...raw, observations: [complete], window: {...raw.window, end: "2026-10-26"}}};
  vi.mocked(getPerformance).mockResolvedValue(actualScopedResponse);
  renderTab(c);
  expect(await screen.findByText("300 TWD")).toBeTruthy();
  expect(screen.queryByText("1,299 TWD")).toBeNull();
  expect(getPerformance).toHaveBeenCalledWith("brd_1", "cmp_1", true);
});

it.each(["currency", "window", "days"])("the full workspace status row uses served %s", async (field) => {
  vi.useFakeTimers({toFake: ["Date"]});
  vi.setSystemTime(new Date("2026-10-27T04:00:00Z"));
  const data = performance();
  data.totals.spend = 900; data.totals.purchases = 12; data.totals.cpa = 75;
  data.scope = {start: "2026-10-24", end: "2026-10-26", days: 3, basis: "campaign_window",
    state: "ready", last_complete_day: "2026-10-26", incomplete_day_policy: "excluded",
    day_basis: "account_timezone", account_timezone: "America/New_York", currency: "USD",
    caption: "本期 2026-10-24 ～ 2026-10-26；只計完整帳戶日，今日尚未完整的資料不計入。"};
  vi.mocked(getPerformance).mockResolvedValue(data);
  render(<MemoryRouter><PeriodStatusRow brandId="brd_1"
    campaign={campaign({start_date: "2026-10-24", end_date: "2026-10-30"})}
    onCampaignChange={vi.fn()} /></MemoryRouter>);
  const row = within(screen.getByTestId("period-status-row"));
  await waitFor(() => expect(getPerformance).toHaveBeenCalled());
  try {
    if (field === "currency") expect(await row.findByText("900 USD")).toBeTruthy();
    if (field === "window") expect(await row.findByText("10/24～10/26")).toBeTruthy();
    if (field === "days") expect(await row.findByText("3 天")).toBeTruthy();
  } finally { vi.useRealTimers(); }
});

it.each([
  {currency: "TWD", capCurrency: "TWD", source: "user", reason: null},
  {currency: "USD", capCurrency: "TWD", source: "user", reason: "cap_currency_mismatch"},
  {currency: "TWD", capCurrency: null, source: "copied", reason: "cap_currency_unknown"},
])("actual status row names the recorded $source cap unit beside $currency CPA", async ({currency, capCurrency, source, reason}) => {
  const data = performance();
  data.totals = {...data.totals, spend: 1200, purchases: 3, cpa: 400};
  data.scope = {basis: "campaign_window", start: "2026-10-24", end: "2026-10-26", days: 3,
    last_complete_day: "2026-10-26", incomplete_day_policy: "excluded", state: "ready", currency,
    day_basis: "account_timezone", account_timezone: "Asia/Taipei",
    caption: "本期 2026-10-24 ～ 2026-10-26；只計完整帳戶日。"};
  data.cap_comparison = {basis: "own", currency: capCurrency, source,
    unit_basis: capCurrency ? "manual_ntd_input" : null, reason,
    message: reason ? "上限與本期成效的幣別不同或尚未核實，不能比較。" : null};
  vi.mocked(getPerformance).mockResolvedValue(data);
  const c = campaign(); c.cap = {...c.cap, value: 350, basis: "own"};
  render(<MemoryRouter><PeriodStatusRow brandId="brd_1" campaign={c} onCampaignChange={vi.fn()} /></MemoryRouter>);
  const row = within(screen.getByTestId("period-status-row"));
  expect(await row.findByText(`400 ${currency}`)).toBeTruthy();
  expect(row.getByText(`對上限 350 ${capCurrency ?? "幣別未知"}`)).toBeTruthy();
  if (reason) expect(row.getByText(data.cap_comparison.message!)).toBeTruthy();
});

it("actual closed verdict preserves distinct saved cap and result currencies", async () => {
  vi.mocked(getPerformance).mockResolvedValue(performance());
  renderTab(campaign({status: "closed", verdict: "看不出", verdict_json: {
    metric: "cpa", target: 350, actual: 400, scope: {currency: "USD"},
    cap_comparison: {currency: "TWD", source: "user", unit_basis: "manual_ntd_input",
      reason: "cap_currency_mismatch"},
    missing: "上限與本期成效的幣別不同或尚未核實，不能比較。",
  }}));
  const heading = await screen.findByRole("heading", {name: /結案判定/});
  const card = within(heading.closest("div.surface")!);
  expect(card.getByText("350 TWD")).toBeTruthy();
  expect(card.getByText("400 USD")).toBeTruthy();
});

describe("F52 current performance request generation", () => {
  function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (reason: Error) => void;
    const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
  }
  function scoped(spend: number): CampaignPerformance {
    return {...performance(), totals: {...performance().totals, spend},
      scope: {basis: "campaign_window", start: "2026-10-24", end: "2026-10-26", days: 3,
        state: "ready", last_complete_day: "2026-10-26", incomplete_day_policy: "excluded",
        day_basis: "account_timezone", account_timezone: "Asia/Taipei", currency: "TWD",
        caption: "本期 2026-10-24 ～ 2026-10-26；只計完整帳戶日。"}};
  }
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(readComparison).mockResolvedValue({proposal: null, missing: "缺少合格對照", stale: false,
      closed: false, simulation: false, confirmed: null, result: {verdict: "看不出", reason: "缺資料", values: []}});
  });
  it.each(["success", "rejection"] as const)("ignores an older %s after newer displayed performance", async (answer) => {
    const old = deferred<CampaignPerformance>(); const fresh = deferred<CampaignPerformance>();
    const trace: string[] = [];
    vi.mocked(getPerformance).mockImplementationOnce(() => {trace.push("start old"); return old.promise;})
      .mockImplementationOnce(() => {trace.push("start fresh"); return fresh.promise;});
    const c = campaign();
    const view = (syncing: boolean, readGeneration = 0) => <MemoryRouter><PerformanceTab brandId="brd_1" campaign={c}
      onCampaignChange={vi.fn()} onChangeTab={vi.fn()} syncing={syncing} readGeneration={readGeneration} /></MemoryRouter>;
    const ui = render(view(false));
    await waitFor(() => expect(getPerformance).toHaveBeenCalledTimes(1));
    ui.rerender(view(true)); ui.rerender(view(false, 1));
    await waitFor(() => expect(getPerformance).toHaveBeenCalledTimes(2));
    await act(async () => {trace.push("resolve fresh 1200 TWD"); fresh.resolve(scoped(1200));});
    expect(await screen.findByText("1,200 TWD")).toBeTruthy();
    await act(async () => {
      trace.push(`resolve old ${answer}`);
      if (answer === "success") old.resolve(scoped(900)); else old.reject(new Error("obsolete performance error"));
    });
    console.info("F52 performance request trace", JSON.stringify(trace));
    expect(screen.getByText("1,200 TWD")).toBeTruthy();
    expect(screen.queryByText("900 TWD")).toBeNull();
    expect(screen.queryByText("obsolete performance error")).toBeNull();
  });
  it("keeps the new campaign when the old campaign returns later", async () => {
    const old = deferred<CampaignPerformance>(); const fresh = deferred<CampaignPerformance>();
    vi.mocked(getPerformance).mockImplementationOnce(() => old.promise).mockImplementationOnce(() => fresh.promise);
    const view = (id: string) => <MemoryRouter><PerformanceTab brandId="brd_1" campaign={campaign({id})}
      onCampaignChange={vi.fn()} onChangeTab={vi.fn()} /></MemoryRouter>;
    const ui = render(view("old"));
    ui.rerender(view("new"));
    await act(async () => fresh.resolve(scoped(1200)));
    expect(await screen.findByText("1,200 TWD")).toBeTruthy();
    await act(async () => old.resolve(scoped(900)));
    expect(screen.getByText("1,200 TWD")).toBeTruthy();
  });
  it("keeps the opened daily fold mounted during a same-owner reread", async () => {
    const fresh = deferred<CampaignPerformance>();
    vi.mocked(getPerformance).mockResolvedValueOnce(scoped(900)).mockImplementationOnce(() => fresh.promise);
    const c = campaign();
    const view = (readGeneration: number) => <MemoryRouter><PerformanceTab brandId="brd_1" campaign={c}
      onCampaignChange={vi.fn()} onChangeTab={vi.fn()} readGeneration={readGeneration} /></MemoryRouter>;
    const ui = render(view(0));
    await screen.findByText("900 TWD");
    const fold = screen.getByRole("button", {name: "查看每日資料、次要指標與公式"});
    await userEvent.click(fold);
    ui.rerender(view(1));
    await waitFor(() => expect(getPerformance).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", {name: "查看每日資料、次要指標與公式"})).toBe(fold);
    expect(fold.getAttribute("aria-expanded")).toBe("true");
    await act(async () => fresh.resolve(scoped(1200)));
    expect(await screen.findByText("1,200 TWD")).toBeTruthy();
    expect(fold.getAttribute("aria-expanded")).toBe("true");
  });
  it("posting true-to-false without a served terminal generation does not reread", async () => {
    vi.mocked(getPerformance).mockResolvedValue(scoped(900));
    const c = campaign();
    const view = (syncing: boolean) => <MemoryRouter><PerformanceTab brandId="brd_1" campaign={c}
      onCampaignChange={vi.fn()} onChangeTab={vi.fn()} syncing={syncing} /></MemoryRouter>;
    const ui = render(view(false)); await screen.findByText("900 TWD");
    ui.rerender(view(true)); ui.rerender(view(false));
    await act(async () => {});
    expect(getPerformance).toHaveBeenCalledTimes(1);
    expect(screen.getByText("900 TWD")).toBeTruthy();
  });
  it.each(["success", "rejection"] as const)("does not replace the remounted owner after dismissed %s", async (answer) => {
    const old = deferred<CampaignPerformance>();
    vi.mocked(getPerformance).mockImplementationOnce(() => old.promise).mockResolvedValue(scoped(1200));
    const ui = renderTab(campaign()); ui.unmount();
    renderTab(campaign({id: "new"}));
    await screen.findByText("1,200 TWD");
    await act(async () => {
      if (answer === "success") old.resolve(scoped(900)); else old.reject(new Error("dismissed owner error"));
    });
    expect(screen.getByText("1,200 TWD")).toBeTruthy();
    expect(screen.queryByText("dismissed owner error")).toBeNull();
    expect(screen.queryByText("900 TWD")).toBeNull();
  });
});

describe("F55 goal evidence, cap comparison and legacy limits", () => {
  it("uses the served lead result and keeps incidental purchases in secondary data", async () => {
    const data = performance();
    data.result_view = resultEvidence();
    data.totals = {...data.totals, spend: 1000, purchases: 1, cpa: 1000};
    vi.mocked(getPerformance).mockResolvedValue(data);
    renderTab(campaign());
    await screen.findByText("名單數");
    expect((screen.getByText("名單數").closest("article"))?.textContent).toContain("10");
    expect((screen.getByText("每次名單成本").closest("article"))?.textContent).toContain("100 TWD");
    expect((screen.getByText("樣本範圍").closest("article"))?.textContent).toContain("7 天");
    await userEvent.click(screen.getByRole("button", {name: "查看每日資料、次要指標與公式"}));
    expect((screen.getByText("購買數（次要資料）").closest("article"))?.textContent).toContain("1");
  });

  it.each([
    ["known_zero", "known_zero", "ready", "已追蹤到零成果", 0, null],
    ["incomplete", "incomplete", "unknown", "成果資料仍有缺漏", null, null],
    ["incompatible", "known_positive", "incompatible", "核實平台成果定義", 10, 100],
    ["unconfigured", "known_positive", "unconfigured", "回到策略", 10, 100],
  ] as const)("keeps %s distinct from missing and from cap eligibility", async (state, data_state, comparison_state, text, count, cost_per_result) => {
    const data = performance();
    data.result_view = resultEvidence({state, data_state, comparison_state, count, cost_per_result});
    data.totals.grade = {grade: "wasted", label: "沒賣出"};
    vi.mocked(getPerformance).mockResolvedValue(data);
    renderTab(campaign());
    await screen.findByText(new RegExp(text));
    expect((screen.getByText("名單數").closest("article"))?.textContent).toContain(count === null ? "未知" : String(count));
    expect((screen.getByText(/成本與支出提示/))?.textContent).toContain("零成果且支出達到風險門檻");
    expect(screen.queryByText(/賣越多虧越多/)).toBeNull();
  });

  it("reads a saved goal-specific verdict and its learning without client recalculation", async () => {
    const result = resultEvidence({cost_per_result: 150});
    vi.mocked(getPerformance).mockResolvedValue({...performance(), result_view: result});
    renderTab(campaign({status: "closed", verdict: "未達成", learning_sentence: "後端保存：每次名單成本150，超過上限100；樣本有限。",
      verdict_json: {schema_version: 2, metric: "cost_per_result", target: 100, actual: 150,
        result_view: result, scope: {currency: "TWD"}, cap_comparison: {currency: "TWD"},
        risk: {grade: "over", label: "太貴"}}}));
    const heading = await screen.findByRole("heading", {name: /結案判定/});
    expect((heading.closest(".surface"))?.textContent).toContain("每次名單成本");
    expect((heading.closest(".surface"))?.textContent).toContain("後端保存：每次名單成本150");
    expect(screen.queryByText(/歷史判定：/)).toBeNull();
  });

  it("preserves a historical verdict while displaying its missing evidence limit", async () => {
    vi.mocked(getPerformance).mockResolvedValue(performance());
    renderTab(campaign({status: "closed", verdict: "達成", verdict_json: {metric: "cpa", actual: 100, target: 150}}));
    await screen.findByText(/歷史判定：未保存當時完整/);
    expect((screen.getByRole("heading", {name: /結案判定/}))?.textContent).toContain("達成");
  });
});

it("F55 primary period strip agrees with the advanced goal result, excluding purchase CPA", async () => {
  vi.mocked(getPerformance).mockResolvedValue({...performance(), result_view: resultEvidence(),
    totals: {...performance().totals, spend: 1000, purchases: 1, cpa: 1000, grade: {grade: "on_target", label: "划算"}}});
  render(<MemoryRouter><PeriodStatusRow brandId="brd_1" campaign={campaign()} onCampaignChange={vi.fn()} /></MemoryRouter>);
  const strip = screen.getByTestId("period-status-row");
  await within(strip).findByText("每次名單成本");
  await waitFor(() => expect(strip.textContent).toContain("100 TWD"));
  expect(strip.textContent).toContain("10 次");
  const costCell = within(strip).getByText("每次名單成本").parentElement;
  expect(costCell?.textContent).toContain("100 TWD");
  expect(costCell?.textContent).not.toContain("1,000 TWD");
  expect(strip.textContent).toContain("不代表已證明有效或已付款利潤");
});

it("F55 imported performance selects served goal projections without adding ad and adset grains", async () => {
  const key = (scope: string) => JSON.stringify([scope, "TWD", "7d"]);
  const base: NativeObservation = {id: "set", entity_id: "set", day: "2026-10-01", metric_scope: "adset", attribution_key: "7d",
    currency: "TWD", spend: 1000, impressions: 100, clicks: 10, purchases: 1, revenue: null,
    result_kind: "lead", result_count: 10, result_action: "lead", result_attribution: "7d_click", availability: {}};
  const raw: ExternalView = {entities: [], observations: [base, {...base, id: "ad", entity_id: "ad", metric_scope: "ad", spend: 400, result_count: 2}],
    next_entity_cursor: null, next_observation_cursor: null, window: {start: "2026-10-01", end: "2026-10-07"}, connections: [], sync: {}, coverage: {},
    result_views: [{...resultEvidence(), scope_key: key("adset")},
      {...resultEvidence({spend: 400, count: 2, known_count: 2, cost_per_result: 200}), scope_key: key("ad")}]};
  vi.mocked(getPerformance).mockResolvedValue({origin: "imported", external_view: raw});
  renderTab(campaign({origin: "imported", external_view: raw}));
  await screen.findByText("名單數");
  expect(screen.getByText("名單數").closest("article")?.textContent).toContain("10");
  expect(screen.getByText("每次名單成本").closest("article")?.textContent).toContain("100 TWD");
  await userEvent.click(screen.getByRole("button", {name: "查看每日資料、次要指標與公式"}));
  await userEvent.selectOptions(screen.getByLabelText("資料範圍"), key("ad"));
  expect(screen.getByText("名單數").closest("article")?.textContent).toContain("2");
  expect(screen.getByText("每次名單成本").closest("article")?.textContent).toContain("200 TWD");
});
