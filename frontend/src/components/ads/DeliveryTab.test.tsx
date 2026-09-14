/** frontend/src/components/ads/DeliveryTab.test.tsx — F06-I02: 投放結構長得跟策略頁一樣——
 * 判斷帶＋數字條＋整寬主要按鈕，樹與編輯面板收進「調整結構（進階）」，預設關閉、預設不選中
 * 任何節點。 */
import type { ReactElement } from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import type { AdRow, CampaignDetail, DeliveryGroupRow } from "@/lib/adsApi";
import { adoptStrategy, dispatchPack, getCampaign } from "@/lib/adsApi";
import { DeliveryTab } from "./DeliveryTab";

function renderWithRouter(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return {
    ...actual,
    adoptStrategy: vi.fn(),
    dispatchPack: vi.fn(),
    getCampaign: vi.fn(),
    patchGroup: vi.fn(),
    patchAd: vi.fn(),
    createAd: vi.fn(),
  };
});

vi.mock("@/lib/coordinatesApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/coordinatesApi")>("@/lib/coordinatesApi");
  return { ...actual, fetchCoordinates: vi.fn().mockResolvedValue([]) };
});

vi.mock("@/lib/adsLaunchApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsLaunchApi")>("@/lib/adsLaunchApi");
  return { ...actual, fetchChannels: vi.fn().mockResolvedValue([]) };
});

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

const WITH_STRATEGY = {
  strategy: { allocation: [{ role: "new" as const, label: "新客", pct: 100, rationale: null, amount: null }], why: [], unknowns: [], alternatives: [], learning_goals: [] },
};

function campaign(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    id: "cmp_1",
    name: "測試 Campaign",
    goal_text: "想在雙十一衝一波業績",
    objective: "conversion",
    success_metric: "cpa",
    success_target: null,
    success_basis: null,
    start_date: "2026-01-01",
    end_date: "2026-01-15",
    status: "draft",
    budget_planned: null,
    budget_scenario: null,
    budget_basis_json: WITH_STRATEGY,
    budget_total: null,
    context_json: {},
    constraints_json: {},
    verdict: null,
    verdict_json: {},
    closed_at: null,
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    groups: [group({ ads: [ad({ id: "ad_1" }), ad({ id: "ad_2", name: "廣告二" })] })],
    actions: [],
    outcome: { spend: 0, purchases: 0, revenue: 0 },
    asset_readiness: { ready_count: 0, total: 0 },
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
      <DeliveryTab brandId="brd_1" campaign={c} onCampaignChange={onCampaignChange} onChangeTab={onChangeTab} />,
    ),
  };
}

describe("DeliveryTab（F06-I02）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("預設面：開始做素材 → 在，進階收合是關的，沒有未綁定／儲存變更／日期輸入框", () => {
    renderTab(campaign());
    const button = screen.getByRole("button", { name: "開始做素材 →" });
    expect(button.className).toContain("h-12");
    expect(
      screen.getByRole("button", { name: "調整結構（進階）" }).getAttribute("aria-expanded"),
    ).toBe("false");
    expect(screen.queryByText("未綁定")).toBeNull();
    expect(screen.queryByText("儲存變更")).toBeNull();
    expect(document.querySelector("input[type=date]")).toBeNull();
  });

  it("交棒：dispatchPack 一次，接著 getCampaign，回呼帶著新資料，跳去素材分頁", async () => {
    const user = userEvent.setup();
    vi.mocked(dispatchPack).mockResolvedValue("pk_1");
    const dispatched = campaign({ asset_readiness: { ready_count: 0, total: 2, pack_id: "pk_1" } });
    vi.mocked(getCampaign).mockResolvedValue(dispatched);
    const { onCampaignChange, onChangeTab } = renderTab(campaign());

    await user.click(screen.getByRole("button", { name: "開始做素材 →" }));

    expect(dispatchPack).toHaveBeenCalledWith("brd_1", "cmp_1");
    expect(getCampaign).toHaveBeenCalledWith("brd_1", "cmp_1");
    expect(onCampaignChange).toHaveBeenCalledWith(dispatched);
    expect(onChangeTab).toHaveBeenCalledWith("assets");
  });

  it("交棒競速：dispatchPack 失敗、getCampaign 回來已經有 pack_id → 直接跳素材，不印錯誤", async () => {
    const user = userEvent.setup();
    vi.mocked(dispatchPack).mockRejectedValue(new Error("已經交棒過了"));
    const fresh = campaign({ asset_readiness: { ready_count: 0, total: 2, pack_id: "pk_1" } });
    vi.mocked(getCampaign).mockResolvedValue(fresh);
    const { onChangeTab } = renderTab(campaign());

    await user.click(screen.getByRole("button", { name: "開始做素材 →" }));

    expect(onChangeTab).toHaveBeenCalledWith("assets");
    expect(screen.queryByText("已經交棒過了")).toBeNull();
  });

  it("已經有任務包：按鈕是「前往素材 →」，按下去跳素材、不呼叫 dispatchPack", async () => {
    const user = userEvent.setup();
    const { onChangeTab } = renderTab(
      campaign({ asset_readiness: { ready_count: 0, total: 2, pack_id: "pk_1" } }),
    );

    const button = screen.getByRole("button", { name: "前往素材 →" });
    await user.click(button);

    expect(onChangeTab).toHaveBeenCalledWith("assets");
    expect(dispatchPack).not.toHaveBeenCalled();
  });

  it("有策略、沒投放組：讀規則不自己採用，按「前往策略 →」跳策略分頁", async () => {
    const user = userEvent.setup();
    const { onChangeTab } = renderTab(campaign({ groups: [], status: "draft", budget_scenario: null }));

    expect(screen.getByText("策略已產生，確認後系統會建立投放結構。")).toBeTruthy();
    const button = screen.getByRole("button", { name: "前往策略 →" });
    expect(button.className).toContain("h-12");
    expect(screen.queryByRole("button", { name: "採用策略（建立投放結構）" })).toBeNull();

    await user.click(button);

    expect(onChangeTab).toHaveBeenCalledWith("strategy");
    expect(adoptStrategy).not.toHaveBeenCalled();
  });

  it("沒有策略、沒投放組：按「前往策略 →」跳策略分頁", async () => {
    const user = userEvent.setup();
    const { onChangeTab } = renderTab(campaign({ groups: [], budget_basis_json: {} }));

    expect(screen.getByText("還沒有策略，先產生策略建議。")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "前往策略 →" }));

    expect(onChangeTab).toHaveBeenCalledWith("strategy");
  });

  it("沒有廣告：按鈕是「新增廣告 →」，按下去開新增廣告對話框", async () => {
    const user = userEvent.setup();
    renderTab(campaign({ groups: [group({ ads: [] })] }));

    await user.click(screen.getByRole("button", { name: "新增廣告 →" }));

    expect(screen.getByText("新增廣告")).toBeTruthy();
  });

  it("日期與儲存：打開進階、點投放組（空白日期）——看得到跟活動同期間、沒有儲存變更；改名稱後儲存變更出現", async () => {
    const user = userEvent.setup();
    renderTab(campaign());

    await user.click(screen.getByRole("button", { name: "調整結構（進階）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));

    expect(screen.getByText("跟活動同期間（2026-01-01 ~ 2026-01-15）")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "儲存變更" })).toBeNull();

    const nameInput = screen.getByDisplayValue("投放組");
    await user.clear(nameInput);
    await user.type(nameInput, "改名的投放組");

    expect(screen.getByRole("button", { name: "儲存變更" })).toBeTruthy();
  });

  it("status live：打開進階後看得到未綁定徽章", async () => {
    const user = userEvent.setup();
    renderTab(campaign({ status: "live" }));

    await user.click(screen.getByRole("button", { name: "調整結構（進階）" }));

    expect(screen.getAllByText("未綁定").length).toBeGreaterThan(0);
  });

  it("status ready、沒有發布動作：打開進階後看不到綁定徽章", async () => {
    const user = userEvent.setup();
    renderTab(campaign({ status: "ready" }));

    await user.click(screen.getByRole("button", { name: "調整結構（進階）" }));

    expect(screen.queryByText("未綁定")).toBeNull();
  });
});
