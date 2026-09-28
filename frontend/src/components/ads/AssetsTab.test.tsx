vi.mock("./PlannedMaterialAssignments", () => ({ PlannedMaterialAssignments: () => null }));
/** frontend/src/components/ads/AssetsTab.test.tsx — F06-I03: 素材分頁底部整寬按鈕改讀
 * `nextStep(c)`；派工到工作檯的入口只留投放結構那顆，這裡只保留「查看素材任務包」；
 * 交棒之後才新增的廣告在列上提示，不重新交棒。 */
import type { ReactElement } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import type { AdRow, AssetReadinessRow, CampaignDetail, DeliveryGroupRow } from "@/lib/adsApi";
import { getAssets, getCampaign, setAssetReady } from "@/lib/adsApi";
import { getSlots } from "@/lib/adsSlotsApi";
import { AssetsTab } from "./AssetsTab";

/** The real request panel renders behind a marker line (the deep-link cases find the marker; the F35 case reads its cards). */
vi.mock("./MaterialTasksPanel", async () => {
  const actual = await vi.importActual<typeof import("./MaterialTasksPanel")>("./MaterialTasksPanel");
  return { MaterialTasksPanel: (props: Parameters<typeof actual.MaterialTasksPanel>[0]) => <><p>素材分流入口</p><actual.MaterialTasksPanel {...props} /></> };
});
vi.mock("@/lib/auth", () => ({ getOrgId: () => "test_org", getAccessToken: async () => "test_token" }));
vi.mock("@/lib/adsMaterialApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsMaterialApi")>("@/lib/adsMaterialApi");
  return { ...actual, listMaterialTasks: vi.fn().mockResolvedValue({ tasks: [] }) };
});
vi.mock("./ManualHandoffPanel", () => ({ ManualHandoffPanel: () => null }));
vi.mock("./UserAssetPlacements", () => ({ UserAssetPlacements: () => <div>自帶素材安排</div> }));

vi.mock("@/lib/adsSlotsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsSlotsApi")>("@/lib/adsSlotsApi");
  return { ...actual, getSlots: vi.fn() };
});

/** The old readiness list lives in the 「進階」 fold (F30-I11): open it, then the old list inside it. */
function renderWithRouter(ui: ReactElement, entry = "/") {
  const result = render(<MemoryRouter initialEntries={[entry]}>{ui}</MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: ADVANCED }));
  fireEvent.click(screen.getByRole("button", { name: "原有任務包與平台素材" }));
  return result;
}

const ADVANCED = "進階：素材需求、自帶素材與人工交接";
const noSlots = { ready: 0, total: 0, groups: [], requests: [], requests_truncated: false };

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return {
    ...actual,
    getAssets: vi.fn(),
    setAssetReady: vi.fn(),
    getCampaign: vi.fn(),
  };
});

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

function assetRow(overrides: Partial<AssetReadinessRow> = {}): AssetReadinessRow {
  return {
    ad_id: "ad_1",
    state: "not_started",
    pack_id: null,
    brief_id: null,
    source: null,
    by: null,
    at: null,
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
    end_date: "2026-01-15",
    status: "ready",
    budget_planned: null,
    budget_scenario: "recommended",
    budget_basis_json: { strategy: { allocation: [], why: [], unknowns: [], alternatives: [] } },
    budget_total: 30000,
    context_json: {},
    constraints_json: {},
    verdict: null,
    verdict_json: {},
    closed_at: null,
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    groups: [group({ ads: [ad({ id: "ad_1", name: "廣告一" }), ad({ id: "ad_2", name: "廣告二" })] })],
    actions: [],
    outcome: { spend: 0, purchases: 0, revenue: 0 },
    asset_readiness: { ready_count: 0, total: 2, pack_id: null },
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
  return {
    onCampaignChange,
    onChangeTab,
    ...renderWithRouter(
      <AssetsTab brandId="brd_1" campaign={c} onCampaignChange={onCampaignChange} onChangeTab={onChangeTab} />,
    ),
  };
}

describe("AssetsTab（F06-I03）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getSlots).mockResolvedValue(noSlots);
  });

  it("兩則都已就位：底部按鈕是「發布 →」，點下去 onChangeTab(\"publish\")", async () => {
    const user = userEvent.setup();
    vi.mocked(getAssets).mockResolvedValue({
      assets: [
        assetRow({ ad_id: "ad_1", state: "ready_manual", pack_id: "pk_1", brief_id: "brf_1" }),
        assetRow({ ad_id: "ad_2", state: "ready_manual", pack_id: "pk_1", brief_id: "brf_2" }),
      ],
      ready_count: 2,
      total: 2,
    });
    const c = campaign({ asset_readiness: { ready_count: 2, total: 2, pack_id: "pk_1" } });
    const { onChangeTab } = renderTab(c);

    const button = await screen.findByRole("button", { name: "發布 →" });
    await user.click(button);
    expect(onChangeTab).toHaveBeenCalledWith("publish");
  });

  it("交棒了、還沒全部就位：底部是連到工作檯的連結，也看得到「查看素材任務包」，沒有「發布 →」", async () => {
    vi.mocked(getAssets).mockResolvedValue({
      assets: [
        assetRow({ ad_id: "ad_1", state: "ready_manual", pack_id: "pk_1", brief_id: "brf_1" }),
        assetRow({ ad_id: "ad_2", state: "not_started", pack_id: "pk_1", brief_id: "brf_2" }),
      ],
      ready_count: 1,
      total: 2,
    });
    const c = campaign({ asset_readiness: { ready_count: 1, total: 2, pack_id: "pk_1" } });
    renderTab(c);

    const link = await screen.findByRole("link", { name: "前往素材工作檯 →" });
    expect(link.getAttribute("href")).toContain("/workbench/packs/pk_1");
    expect(screen.getByRole("link", { name: "查看素材任務包" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "發布 →" })).toBeNull();
  });

  it("還沒交棒：底部是「前往投放結構 →」，畫面上找不到「派工到素材工作檯」", async () => {
    vi.mocked(getAssets).mockResolvedValue({
      assets: [assetRow({ ad_id: "ad_1" }), assetRow({ ad_id: "ad_2" })],
      ready_count: 0,
      total: 2,
    });
    const c = campaign({ asset_readiness: { ready_count: 0, total: 2, pack_id: null } });
    renderTab(c);

    expect(await screen.findByRole("button", { name: "前往投放結構 →" })).toBeTruthy();
    expect(screen.queryByText("派工到素材工作檯")).toBeNull();
  });

  it("勾素材已就位、確認：setAssetReady 之後叫 getCampaign，onCampaignChange 拿到它的結果", async () => {
    const user = userEvent.setup();
    vi.mocked(getAssets).mockResolvedValue({
      assets: [assetRow({ ad_id: "ad_1" }), assetRow({ ad_id: "ad_2" })],
      ready_count: 0,
      total: 2,
    });
    vi.mocked(setAssetReady).mockResolvedValue(ad({ id: "ad_1" }));
    const refreshed = campaign({ asset_readiness: { ready_count: 1, total: 2, pack_id: null } });
    vi.mocked(getCampaign).mockResolvedValue(refreshed);

    const c = campaign();
    const { onCampaignChange } = renderTab(c);

    const checkboxes = await screen.findAllByRole("checkbox");
    await user.click(checkboxes[0]);
    await user.click(screen.getByRole("button", { name: "確認" }));

    expect(setAssetReady).toHaveBeenCalledWith("brd_1", "ad_1", true);
    expect(getCampaign).toHaveBeenCalledWith("brd_1", "cmp_1");
    expect(onCampaignChange).toHaveBeenCalledWith(refreshed);
  });

  it("一個投放組沒有任何廣告：空狀態讀規則，按鈕是「前往投放結構 →」，點下去 onChangeTab(\"structure\")", async () => {
    const user = userEvent.setup();
    const c = campaign({ groups: [group({ ads: [] })], asset_readiness: { ready_count: 0, total: 0, pack_id: null } });
    const { onChangeTab } = renderTab(c);

    expect(screen.getByText("這個 Campaign 還沒有廣告")).toBeTruthy();
    await user.click(screen.getByText("前往投放結構 →"));
    expect(onChangeTab).toHaveBeenCalledWith("structure");
  });

  it("交棒之後才新增的廣告：那一列印出提示，不重新交棒", async () => {
    vi.mocked(getAssets).mockResolvedValue({
      assets: [
        assetRow({ ad_id: "ad_1", state: "ready_manual", pack_id: "pk_1", brief_id: "brf_1" }),
        assetRow({ ad_id: "ad_2", state: "not_started", pack_id: null, brief_id: null }),
      ],
      ready_count: 1,
      total: 2,
    });
    const c = campaign({ asset_readiness: { ready_count: 1, total: 2, pack_id: "pk_1" } });
    renderTab(c);

    expect(
      await screen.findByText("交棒之後才新增的，不在素材任務包裡；做好後勾「素材已就位」。"),
    ).toBeTruthy();
  });
});

function importedView(): NonNullable<CampaignDetail["external_view"]> {
  return {
    entities: [{ id: "native-root", platform: "meta", source_account: "account", native_kind: "campaign", native_id: "root", native_label: "活動", name: "平台活動", parent_native_id: null, native_status: "PAUSED", start_date: "2026-08-01", end_date: null, budget_amount: null, budget_type: "daily", budget_raw: { daily_budget: "30000" }, currency: "TWD", last_success_at: "2026-09-19", sync_error: null, creative: {} }],
    observations: [], next_entity_cursor: null, next_observation_cursor: null,
    window: { start: "2026-08-01", end: "2026-09-19" }, connections: [], sync: {}, coverage: {},
  };
}

it("原生廣告在原素材表查看，不呼叫內部就緒 API 或建立假工作檯連結", async () => {
  vi.mocked(getAssets).mockClear();
  const view = importedView();
  view.entities.push({ ...view.entities[0], id: "native-ad", native_id: "ad", native_kind: "ad", name: "平台廣告素材", parent_native_id: "root", creative: { kind: "image", fields: { body: "平台原文案" } } });
  const { onChangeTab } = renderTab(campaign({ origin: "imported", external_view: view, groups: [], asset_readiness: { total: 0, ready_count: 0 } }));
  expect(await screen.findByText("平台廣告素材")).toBeTruthy();
  expect(screen.getByRole("table")).toBeTruthy();
  expect(screen.queryByText("素材已就位")).toBeNull();
  expect(screen.queryByRole("link", { name: "素材組" })).toBeNull();
  expect(getAssets).not.toHaveBeenCalled();
  await userEvent.click(screen.getByText("查看素材"));
  expect(screen.getByText("內文：平台原文案")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "查看成效 →" }));
  expect(onChangeTab).toHaveBeenCalledWith("performance");
});

describe("AssetsTab 進階 fold（F30-I11）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getSlots).mockResolvedValue(noSlots);
  });

  it("the old readiness list labels a row by material_ready, never 已就位 for material that cannot go out", async () => {
    vi.mocked(getAssets).mockResolvedValue({
      assets: [
        { ...assetRow({ ad_id: "ad_1", state: "ready_manual", by: "小美", at: "09/20" }), material_ready: false } as AssetReadinessRow,
        { ...assetRow({ ad_id: "ad_2", state: "ready_workbench", pack_id: "pk_1", brief_id: "brf_2" }), material_ready: true } as AssetReadinessRow,
      ],
      ready_count: 1,
      total: 2,
    });
    renderTab(campaign({ asset_readiness: { ready_count: 1, total: 2, pack_id: "pk_1" } }));

    expect(await screen.findByRole("heading", { name: "1／2 則素材已備妥" })).toBeTruthy();
    const [first, second] = screen.getAllByRole("row").slice(1);
    expect(first.textContent).toContain("還不能上架");
    expect(first.textContent).toContain("已手動標記");
    expect(second.textContent).toContain("素材已備妥");
    expect(second.textContent).toContain("工作檯已完成");
    expect(screen.queryByText(/已就位（/)).toBeNull();
  });

  it("a failed old readiness read shows ReadFailed with 重試 and re-reads", async () => {
    const user = userEvent.setup();
    vi.mocked(getAssets).mockRejectedValueOnce(new Error("連線逾時")).mockResolvedValue({ assets: [assetRow()], ready_count: 0, total: 2 });
    renderTab(campaign());

    expect(await screen.findByText(/舊版素材就位清單讀不到：連線逾時/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByRole("heading", { name: "0／2 則素材已備妥" })).toBeTruthy();
  });

  it.each(["?material=mt_1", "?material_new=1", "?review=rv_1", "?recommendation=rc_1"])("deep link %s opens the fold on arrival", async (query) => {
    render(
      <MemoryRouter initialEntries={[`/brands/brd_1/ads/campaigns/cmp_1${query}`]}>
        <AssetsTab brandId="brd_1" campaign={campaign()} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: ADVANCED }).getAttribute("aria-expanded")).toBe("true");
    expect(await screen.findByText("素材分流入口")).toBeTruthy();
  });

  it("#material-placements opens the fold and the placement list", async () => {
    window.location.hash = "#material-placements";
    try {
      render(
        <MemoryRouter>
          <AssetsTab brandId="brd_1" campaign={campaign()} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} />
        </MemoryRouter>,
      );
      expect(screen.getByRole("button", { name: ADVANCED }).getAttribute("aria-expanded")).toBe("true");
      expect(screen.getByRole("button", { name: "素材安排與人工交接" }).getAttribute("aria-expanded")).toBe("true");
      expect(await screen.findByText("自帶素材安排")).toBeTruthy();
    } finally {
      window.location.hash = "";
    }
  });

  it("a draft campaign's fold offers three material sources, never 只準備新文案 (F35 ruling 3)", async () => {
    render(
      <MemoryRouter initialEntries={["/brands/brd_1/ads/campaigns/cmp_1?material_new=1"]}>
        <AssetsTab brandId="brd_1" campaign={campaign({ status: "draft" })} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("button", { name: /使用已有成品/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /回收外部生圖/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /請工作台準備新圖/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /只準備新文案/ })).toBeNull();
  });

  it("a live campaign's fold keeps all four sources", async () => {
    render(
      <MemoryRouter initialEntries={["/brands/brd_1/ads/campaigns/cmp_1?material_new=1"]}>
        <AssetsTab brandId="brd_1" campaign={campaign({ status: "live" })} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("button", { name: /只準備新文案/ })).toBeTruthy();
  });

  it("without a deep link the fold stays closed and the old panels are not read", async () => {
    render(
      <MemoryRouter>
        <AssetsTab brandId="brd_1" campaign={campaign()} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("button", { name: ADVANCED }).getAttribute("aria-expanded")).toBe("false");
    expect(await screen.findByText("還沒有要放素材的格子")).toBeTruthy();
    expect(getAssets).not.toHaveBeenCalled();
  });
});
