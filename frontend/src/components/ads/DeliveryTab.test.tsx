/** frontend/src/components/ads/DeliveryTab.test.tsx — F06-I02 behaviours, v10 layout (F30-I08): the tab shows the
 * structure tree; each group's node editors and manual settings sit in its closed 「進階：編輯這一組（…）」 fold, and
 * the in-fold next-step button, numbers, budget and 新增節點 sit in the closed campaign-wide 「調整結構（進階）」. No node
 * is selected by default. F35 ruling 3: the material hand-off (「開始做素材 →」／「前往素材 →」) is the action bar's
 * primary with its hint, not a button in the fold. The tree itself is covered in `workspace/StructureTab.test.tsx`. */
import type { ReactElement } from "react";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import type { AdRow, CampaignDetail, DeliveryGroupRow } from "@/lib/adsApi";
import { adoptStrategy, dispatchPack, getCampaign, patchGroup } from "@/lib/adsApi";
import { fetchCoordinates } from "@/lib/coordinatesApi";
import { fetchChannels } from "@/lib/adsLaunchApi";
import { DeliveryTab } from "./DeliveryTab";

function renderWithRouter(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ scope: "user_1:org_1" }),
}));

vi.mock("@/lib/adsApi", () => ({
  adoptStrategy: vi.fn(),
  dispatchPack: vi.fn(),
  getCampaign: vi.fn(),
  deleteAd: vi.fn(),
  deleteGroup: vi.fn(),
  patchGroup: vi.fn(),
  patchAd: vi.fn(),
  createAd: vi.fn(),
  createGroup: vi.fn(),
  currentBudgetTotal: vi.fn((c: CampaignDetail) => {
    const dailySum = c.groups.reduce((sum, row) => sum + row.daily_budget, 0);
    const days = c.start_date && c.end_date ? 15 : 0;
    return { dailySum, days, total: days ? dailySum * days : null };
  }),
}));

vi.mock("@/lib/coordinatesApi", () => ({
  COORDINATE_DIMENSIONS: [
    ["audience", "受眾"], ["pain", "痛點"], ["angle", "角度"], ["hook", "鉤子"],
    ["proof", "證據"], ["offer", "優惠"], ["format", "格式"],
  ],
  fetchCoordinates: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/lib/adsWorkspaceApi", () => ({
  getCampaignStructure: vi.fn().mockResolvedValue({ groups: [] }),
}));

vi.mock("@/lib/adsLaunchApi", () => ({
  fetchChannels: vi.fn().mockResolvedValue([]),
  saveManualSettings: vi.fn(),
}));

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
    cap: { value: null, basis: null, own_value: null, break_even: null, price: null, product_id: null, result_kind: "purchase", result_label: "購買", missing: ["product"], revision: 0 },
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

/** The sticky action bar (`patterns/ActionBar`, `data-slot="action-bar"`): its primary and hint. */
function actionBar() {
  const bar = document.querySelector<HTMLElement>("[data-slot=action-bar]");
  if (!bar) throw new Error("action bar not rendered");
  return bar;
}
function barButton(name: string) {
  return within(actionBar()).getByRole("button", { name });
}
function barHint() {
  return actionBar().querySelector("small")?.textContent ?? null;
}

function renderTab(c: CampaignDetail, onCampaignChange = vi.fn(), onChangeTab = vi.fn(), brandId = "brd_1") {
  return {
    onCampaignChange,
    onChangeTab,
    ...renderWithRouter(
      <DeliveryTab brandId={brandId} campaign={c} onCampaignChange={onCampaignChange} onChangeTab={onChangeTab} />,
    ),
  };
}

describe("DeliveryTab（F06-I02）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it("預設面：結構樹與返回總覽；兩種進階收合都是關的，沒有未綁定／儲存變更／日期輸入框；開始做素材 → 是動作列的主按鈕、帶提示", async () => {
    renderTab(campaign());
    expect(screen.getByRole("heading", { name: "活動 → 廣告組 → 廣告" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "← 總覽" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1");
    expect(screen.getByRole("button", { name: "調整結構（進階）" }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }).getAttribute("aria-expanded")).toBe("false");
    expect(barButton("開始做素材 →")).toBeTruthy();
    expect(barHint()).toBe("交棒後工作檯替每則廣告寫文案和圖片提示詞；圖仍由你上傳");
    expect(screen.queryByText("未綁定")).toBeNull();
    expect(screen.queryByText("儲存變更")).toBeNull();
    expect(document.querySelector("input[type=date]")).toBeNull();
  });

  it("下一步是交棒時，「調整結構（進階）」裡不再有開始做素材（只在動作列）", async () => {
    const user = userEvent.setup();
    renderTab(campaign());
    await user.click(screen.getByRole("button", { name: "調整結構（進階）" }));
    expect(screen.getAllByRole("button", { name: "開始做素材 →" })).toHaveLength(1);
    const summary = screen.getByRole("button", { name: "調整結構（進階）" });
    const fold = document.getElementById(summary.getAttribute("aria-controls")!)!;
    expect(within(fold).queryByRole("button", { name: "開始做素材 →" })).toBeNull();
    expect(within(fold).queryByRole("button", { name: "前往素材 →" })).toBeNull();
    expect(within(fold).getByRole("button", { name: "新增節點" })).toBeTruthy();
    expect(actionBar().contains(screen.getByRole("button", { name: "開始做素材 →" }))).toBe(true);
  });

  it("每個投放組各有一個「進階：編輯這一組」；在這一組新增廣告時預設選這一組", async () => {
    const user = userEvent.setup();
    renderTab(campaign({ groups: [group(), group({ id: "grp_2", name: "再行銷", ads: [ad({ id: "ad_9", group_id: "grp_2", name: "廣告九" })] })] }));
    expect(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（再行銷）" }));
    expect(screen.getByRole("button", { name: /^廣告九/ })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "在這一組新增廣告" }));
    expect((screen.getByRole("combobox", { name: /投放組/ }) as HTMLSelectElement).value).toBe("grp_2");
    // F47-I06 (V7): the greyed-out 新增 names what is still empty.
    const add = screen.getByRole("button", { name: "新增" });
    expect(add.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(/^還沒選：名稱、/)).toBeTruthy();
  });

  it("交棒：dispatchPack 一次，接著 getCampaign，回呼帶著新資料，跳去素材分頁", async () => {
    const user = userEvent.setup();
    vi.mocked(dispatchPack).mockResolvedValue("pk_1");
    const dispatched = campaign({ asset_readiness: { ready_count: 0, total: 2, pack_id: "pk_1" } });
    vi.mocked(getCampaign).mockResolvedValue(dispatched);
    const { onCampaignChange, onChangeTab } = renderTab(campaign());

    expect(barHint()).toBe("交棒後工作檯替每則廣告寫文案和圖片提示詞；圖仍由你上傳");
    await user.click(barButton("開始做素材 →"));

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

    expect(barHint()).toBe("交棒後工作檯替每則廣告寫文案和圖片提示詞；圖仍由你上傳");
    await user.click(barButton("開始做素材 →"));

    expect(onChangeTab).toHaveBeenCalledWith("assets");
    expect(screen.queryByText("已經交棒過了")).toBeNull();
  });

  it("交棒失敗、重讀後仍沒有 pack_id：錯誤印在動作列旁，按鈕還在", async () => {
    const user = userEvent.setup();
    vi.mocked(dispatchPack).mockRejectedValue(new Error("工作檯暫時沒回應"));
    vi.mocked(getCampaign).mockResolvedValue(campaign());
    const { onChangeTab } = renderTab(campaign());

    await user.click(barButton("開始做素材 →"));

    expect(within(actionBar()).getByRole("alert").textContent).toBe("工作檯暫時沒回應");
    expect(barButton("開始做素材 →")).toBeTruthy();
    expect(onChangeTab).not.toHaveBeenCalled();
  });

  it("已經有任務包：動作列主按鈕是「前往素材 →」、提示換成工作檯文案會出現在格子裡；按下去跳素材、不呼叫 dispatchPack", async () => {
    const user = userEvent.setup();
    const { onChangeTab } = renderTab(
      campaign({ asset_readiness: { ready_count: 0, total: 2, pack_id: "pk_1" } }),
    );

    expect(barHint()).toBe("工作檯做好的文案會出現在素材頁的格子裡");
    expect(screen.queryByRole("button", { name: "開始做素材 →" })).toBeNull();
    await user.click(barButton("前往素材 →"));

    expect(onChangeTab).toHaveBeenCalledWith("assets");
    expect(dispatchPack).not.toHaveBeenCalled();
  });

  it("讀回的平台活動：動作列只有返回總覽，沒有主按鈕也沒有提示", () => {
    renderTab(campaign({ origin: "imported", groups: [], external_view: {
      entities: [], observations: [], next_entity_cursor: null, next_observation_cursor: null,
      window: { start: "2026-01-01", end: "2026-01-15" }, connections: [], sync: {}, coverage: {},
    } }));
    expect(within(actionBar()).queryAllByRole("button")).toHaveLength(0);
    expect(barHint()).toBeNull();
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

    await user.click(screen.getByRole("button", { name: "調整結構（進階）" }));
    await user.click(screen.getByRole("button", { name: "新增廣告 →" }));

    expect(screen.getByText("新增廣告")).toBeTruthy();
  });

  it("日期與儲存：打開進階、點投放組（空白日期）——看得到跟活動同期間、沒有儲存變更；改名稱後儲存變更出現", async () => {
    const user = userEvent.setup();
    renderTab(campaign());

    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));

    expect(screen.getByText("跟活動同期間（2026-01-01 ~ 2026-01-15）")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "儲存變更" })).toBeNull();

    const nameInput = screen.getByDisplayValue("投放組");
    await user.clear(nameInput);
    await user.type(nameInput, "改名的投放組");

    expect(screen.getByRole("button", { name: "儲存變更" })).toBeTruthy();
  });

  it("只剩一個投放組：刪除按鈕停用並寫出原因；有兩組時可刪", async () => {
    const user = userEvent.setup();
    const { unmount } = renderTab(campaign());
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));
    expect((screen.getByRole("button", { name: "刪除" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("至少要留一個投放組；想換掉請先新增再刪。")).toBeTruthy();
    unmount();

    renderTab(campaign({ groups: [group(), group({ id: "grp_2", name: "再行銷" })] }));
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));
    expect((screen.getByRole("button", { name: "刪除" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText("至少要留一個投放組；想換掉請先新增再刪。")).toBeNull();
  });

  it("status live：打開這一組的進階後看得到未綁定徽章", async () => {
    const user = userEvent.setup();
    renderTab(campaign({ status: "live" }));

    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));

    expect(screen.getAllByText("未綁定").length).toBeGreaterThan(0);
  });

  it("status ready、沒有發布動作：打開這一組的進階後看不到綁定徽章", async () => {
    const user = userEvent.setup();
    renderTab(campaign({ status: "ready" }));

    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));

    expect(screen.queryByText("未綁定")).toBeNull();
  });

  it("結構有未存變更時攔下分頁下一步，並註冊瀏覽器離開保護", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderTab(campaign());
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));
    const name = screen.getByDisplayValue("投放組");
    await user.clear(name);
    await user.type(name, "未存草稿");

    const beforeUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(beforeUnload);
    expect(beforeUnload.defaultPrevented).toBe(true);
    await user.click(barButton("開始做素材 →"));

    expect(confirm).toHaveBeenCalledWith("還有未儲存的變更，確定要離開嗎？");
    expect(dispatchPack).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("接受離開 dirty 結構後只確認一次，交棒成功直接前往素材", async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(dispatchPack).mockResolvedValueOnce("pk_1");
    vi.mocked(getCampaign).mockResolvedValueOnce(campaign({ asset_readiness: { ready_count: 0, total: 2, pack_id: "pk_1" } }));
    const { onChangeTab } = renderTab(campaign());
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));
    const name = screen.getByDisplayValue("投放組");
    await user.clear(name);
    await user.type(name, "不保存直接前往");

    expect(barHint()).toBe("交棒後工作檯替每則廣告寫文案和圖片提示詞；圖仍由你上傳");
    await user.click(barButton("開始做素材 →"));

    expect(confirm).toHaveBeenCalledTimes(1);
    expect(onChangeTab).toHaveBeenCalledWith("assets");
    confirm.mockRestore();
  });

  it("離開再回同一身份品牌與 Campaign 會恢復結構草稿，不跨品牌恢復", async () => {
    const user = userEvent.setup();
    const first = renderTab(campaign());
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));
    const name = screen.getByDisplayValue("投放組");
    await user.clear(name);
    await user.type(name, "待回來繼續");
    first.unmount();

    const restored = renderTab(campaign());
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));
    expect(await screen.findByText(/已恢復未儲存草稿/)).toBeTruthy();
    expect((screen.getByDisplayValue("待回來繼續") as HTMLInputElement).value).toBe("待回來繼續");
    restored.unmount();

    renderTab(campaign(), vi.fn(), vi.fn(), "brd_2");
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));
    expect(screen.queryByText(/已恢復未儲存草稿/)).toBeNull();
    expect((screen.getByDisplayValue("投放組") as HTMLInputElement).value).toBe("投放組");
  });

  it("伺服器重新讀取不覆蓋 dirty 結構草稿；取消改回最新保存值", async () => {
    const user = userEvent.setup();
    const onCampaignChange = vi.fn();
    const onChangeTab = vi.fn();
    const view = renderTab(campaign(), onCampaignChange, onChangeTab);
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));
    const name = screen.getByDisplayValue("投放組");
    await user.clear(name);
    await user.type(name, "本地草稿");

    const refreshed = campaign({ groups: [group({ name: "伺服器新值", ads: [ad(), ad({ id: "ad_2", name: "廣告二" })] })] });
    view.rerender(<MemoryRouter><DeliveryTab brandId="brd_1" campaign={refreshed}
      onCampaignChange={onCampaignChange} onChangeTab={onChangeTab} /></MemoryRouter>);
    expect((screen.getByDisplayValue("本地草稿") as HTMLInputElement).value).toBe("本地草稿");

    await user.click(screen.getByRole("button", { name: "取消變更" }));
    expect((screen.getByDisplayValue("伺服器新值") as HTMLInputElement).value).toBe("伺服器新值");
  });

  it("結構儲存成功後清除離開草稿", async () => {
    const user = userEvent.setup();
    const savedGroup = group({ name: "已保存名稱" });
    vi.mocked(patchGroup).mockResolvedValueOnce(savedGroup);
    const first = renderTab(campaign());
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));
    const name = screen.getByDisplayValue("投放組");
    await user.clear(name);
    await user.type(name, "已保存名稱");
    await user.click(screen.getByRole("button", { name: "儲存變更" }));
    expect(patchGroup).toHaveBeenCalled();
    first.unmount();

    renderTab(campaign({ groups: [{ ...savedGroup, ads: [ad(), ad({ id: "ad_2", name: "廣告二" })] }] }));
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（已保存名稱）" }));
    await user.click(screen.getByRole("button", { name: /^已保存名稱/ }));
    expect(screen.queryByText(/已恢復未儲存草稿/)).toBeNull();
  });
});


it("uses the existing structure tree for native groups and keeps native edits unavailable", async () => {
  const user = userEvent.setup();
  const native = {
    id: "native-group", platform: "meta", source_account: "account", native_kind: "adset", native_id: "native-42",
    native_label: null, name: "真實平台投放組", parent_native_id: "native-campaign", native_status: "ACTIVE",
    start_date: null, end_date: null, budget_amount: null, budget_type: "unknown", budget_raw: {},
    currency: null, last_success_at: null, sync_error: null, creative: {},
  };
  renderTab(campaign({ origin: "imported", groups: [], external_view: {
    entities: [native], observations: [], next_entity_cursor: null, next_observation_cursor: null,
    window: {start: "2026-01-01", end: "2026-01-15"}, connections: [], sync: {}, coverage: {},
  }}));
  expect(screen.queryByRole("button", { name: /進階：編輯這一組/ })).toBeNull();
  await user.click(screen.getByText("調整結構（進階）"));
  expect(screen.getByText(/平台投放結構已載入 1 筆/)).toBeTruthy();
  expect(screen.getByRole("button", {name: "新增節點"}).hasAttribute("disabled")).toBe(true);
  await user.click(screen.getByRole("button", {name: /真實平台投放組/}));
  expect(screen.getByText("平台 ID：native-42")).toBeTruthy();
  expect(screen.getByText("預算：未知")).toBeTruthy();
  expect(screen.getByRole("button", {name: "儲存"}).hasAttribute("disabled")).toBe(true);
  expect(screen.queryByText("採用時的計畫")).toBeNull();
});

describe("DeliveryTab failed reads (F29-I10 Contract K)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it("a failed coordinates or channels read shows the error line with 重試 (never a silent empty list); 重試 re-requests only what failed", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchCoordinates).mockRejectedValueOnce(new Error("x"));
    vi.mocked(fetchChannels).mockRejectedValueOnce(new Error("y"));
    renderTab(campaign());
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("座標選項、通路連線狀態讀取失敗");
    expect(barButton("開始做素材 →")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "重試" }));
    expect(vi.mocked(fetchCoordinates)).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fetchChannels)).toHaveBeenCalledTimes(2);
    await vi.waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("only the channels read fails: the line names it and 重試 does not re-read the coordinates", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchChannels).mockRejectedValueOnce(new Error("y"));
    renderTab(campaign());
    expect((await screen.findByRole("alert")).textContent).toContain("通路連線狀態讀取失敗");
    expect(screen.getByRole("alert").textContent).not.toContain("座標選項");
    await user.click(screen.getByRole("button", { name: "重試" }));
    expect(vi.mocked(fetchCoordinates)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetchChannels)).toHaveBeenCalledTimes(2);
  });
});
