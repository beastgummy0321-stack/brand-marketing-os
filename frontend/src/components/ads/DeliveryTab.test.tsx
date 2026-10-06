/** frontend/src/components/ads/DeliveryTab.test.tsx — F06-I02 behaviours, v10 layout (F30-I08): the tab shows the
 * structure tree; each group's node editors and manual settings sit in its closed 「進階：編輯這一組（…）」 fold, and
 * the in-fold next-step button, numbers, budget and 新增節點 sit in the closed campaign-wide 「調整結構（進階）」. No node
 * is selected by default. F35 ruling 3: the material hand-off (「開始做素材 →」／「前往素材 →」) is the action bar's
 * primary with its hint, not a button in the fold. The tree itself is covered in `workspace/StructureTab.test.tsx`. */
import { ApiResponseError } from "@/lib/http";
import type { ReactElement } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import type { AdRow, CampaignDetail, DeliveryGroupRow } from "@/lib/adsApi";
import { adoptStrategy, dispatchPack, getCampaign, patchAd, patchGroup } from "@/lib/adsApi";
import { fetchCoordinates, type Coordinate } from "@/lib/coordinatesApi";
import { fetchChannels } from "@/lib/adsLaunchApi";
import { getCampaignStructure } from "@/lib/adsWorkspaceApi";
import { DeliveryTab } from "./DeliveryTab";

function renderWithRouter(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ scope: "user_1:org_1" }),
}));

vi.mock("@/lib/adsApi", async () => ({
  adoptStrategy: vi.fn(),
  dispatchPack: vi.fn(),
  getCampaign: vi.fn(),
  deleteAd: vi.fn(),
  deleteGroup: vi.fn(),
  patchGroup: vi.fn(),
  patchAd: vi.fn(),
  createAd: vi.fn(),
  createGroup: vi.fn(),
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
    // F49 Contract L: on a platform is the served lifecycle, not the stored status.
    renderTab(campaign({ status: "live", lifecycle: { state: "live", label: "投放中", can_close: true } }));

    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));

    expect(screen.getAllByText("未綁定").length).toBeGreaterThan(0);
  });

  it("status ready、沒有發布動作：打開這一組的進階後看不到綁定徽章", async () => {
    const user = userEvent.setup();
    renderTab(campaign({ status: "ready", lifecycle: { state: "draft", label: "草稿", can_close: false } }));

    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));

    expect(screen.queryByText("未綁定")).toBeNull();
  });

  it("F49 Contract T: 開始做素材 answered nothing_to_prepare is an outcome — the bar says so and offers the next step, no error, no tab jump", async () => {
    const user = userEvent.setup();
    vi.mocked(dispatchPack).mockResolvedValue(null);
    const carried = campaign({ asset_readiness: { ready_count: 2, total: 2, pack_id: null } });
    vi.mocked(getCampaign).mockResolvedValue(carried);
    const { onCampaignChange, onChangeTab } = renderTab(campaign());

    await user.click(barButton("開始做素材 →"));

    expect(dispatchPack).toHaveBeenCalledTimes(1);
    expect(onCampaignChange).toHaveBeenCalledWith(carried);
    expect(within(actionBar()).getByRole("status").textContent).toBe("這期的素材都沿用上一期，不用準備");
    expect(within(actionBar()).queryByRole("alert")).toBeNull();
    expect(onChangeTab).not.toHaveBeenCalled();
  });

  it("nothing_to_prepare then the next step: with every ad ready the bar leads to publish, never a second hand-off", async () => {
    const user = userEvent.setup();
    vi.mocked(dispatchPack).mockResolvedValue(null);
    const carried = campaign({ asset_readiness: { ready_count: 2, total: 2, pack_id: null } });
    vi.mocked(getCampaign).mockResolvedValue(carried);
    const onChangeTab = vi.fn();
    const view = renderTab(campaign(), vi.fn(), onChangeTab);
    await user.click(barButton("開始做素材 →"));
    // The workspace hands the re-read campaign back down.
    view.rerender(<MemoryRouter><DeliveryTab brandId="brd_1" campaign={carried} onCampaignChange={vi.fn()} onChangeTab={onChangeTab} /></MemoryRouter>);
    expect(within(actionBar()).getByRole("status").textContent).toBe("這期的素材都沿用上一期，不用準備");
    expect(within(actionBar()).queryByRole("button", { name: "開始做素材 →" })).toBeNull();
    await user.click(barButton("發布 →"));
    expect(onChangeTab).toHaveBeenCalledWith("publish");
    expect(dispatchPack).toHaveBeenCalledTimes(1);
  });

  it("nothing_to_prepare with a read that still says hand-off: the bar leads to the 素材 tab", async () => {
    const user = userEvent.setup();
    vi.mocked(dispatchPack).mockResolvedValue(null);
    vi.mocked(getCampaign).mockResolvedValue(campaign());
    const { onChangeTab } = renderTab(campaign());
    await user.click(barButton("開始做素材 →"));
    expect(within(actionBar()).queryByRole("button", { name: "開始做素材 →" })).toBeNull();
    await user.click(barButton("前往素材 →"));
    expect(onChangeTab).toHaveBeenCalledWith("assets");
    expect(dispatchPack).toHaveBeenCalledTimes(1);
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
    native_label: null, name: "真實平台投放組", parent_native_id: "native-campaign", native_status: "ACTIVE", delivery_label: "投放中",
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
  // F49 Contract L: the served delivery word, never the platform's own code.
  expect(screen.getByText("狀態：投放中")).toBeTruthy();
  expect(screen.queryByText(/ACTIVE/)).toBeNull();
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

describe("DeliveryTab: one budget, the period's menu and carried ads (F48-I10)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  function vocab(dimension: Coordinate["dimension"], key: string, label: string): Coordinate {
    return { id: `${dimension}-${key}`, dimension, key, label, category: null, canonical_key: null, attributes: {} as Coordinate["attributes"], disabled_at: null, rejected: false };
  }

  it("調整結構（進階） prints the campaign's one budget_total — no 差額, no 採用時的計畫, no raw scenario key", async () => {
    const user = userEvent.setup();
    // The server's total; budget_planned differs on purpose and is never subtracted or shown here.
    renderTab(campaign({ budget_total: 15000, budget_planned: 15004, budget_scenario: "recommended" }));
    await user.click(screen.getByRole("button", { name: "調整結構（進階）" }));
    const card = screen.getByRole("heading", { name: "預算（這個 Campaign）" }).closest(".surface") as HTMLElement;
    expect(card.textContent).toContain("15,000");
    expect(card.textContent).not.toMatch(/差額|採用時的計畫|recommended|15,004/);
    expect(screen.queryByText("差額")).toBeNull();
    expect(screen.queryByText("每日合計")).toBeNull();
  });

  it("no group budget or dates yet: the total says it is not set (never a 0)", async () => {
    const user = userEvent.setup();
    renderTab(campaign({ budget_total: null }));
    await user.click(screen.getByRole("button", { name: "調整結構（進階）" }));
    const card = screen.getByRole("heading", { name: "預算（這個 Campaign）" }).closest(".surface") as HTMLElement;
    expect(card.textContent).toContain("尚未設定");
  });

  it("after a group save the tab re-reads the campaign once and passes on the server's numbers", async () => {
    const user = userEvent.setup();
    const saved = group({ daily_budget: 1200 });
    const fresh = campaign({ budget_total: 18000, groups: [{ ...saved, ads: [ad(), ad({ id: "ad_2", name: "廣告二" })] }] });
    vi.mocked(patchGroup).mockResolvedValueOnce(saved);
    vi.mocked(getCampaign).mockResolvedValueOnce(fresh);
    const { onCampaignChange } = renderTab(campaign({ budget_total: 15000 }));
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));
    const daily = screen.getByDisplayValue("1000");
    await user.clear(daily);
    await user.type(daily, "1200");
    await user.click(screen.getByRole("button", { name: "儲存變更" }));
    await vi.waitFor(() => expect(onCampaignChange).toHaveBeenLastCalledWith(fresh));
    expect(getCampaign).toHaveBeenCalledTimes(1);
    expect(getCampaign).toHaveBeenCalledWith("brd_1", "cmp_1");
  });

  it("F52-I04: coordinate-only edit reads back the saved campaign and its revised contract", async () => {
    vi.mocked(getCampaign).mockReset();
    const user = userEvent.setup();
    vi.mocked(fetchCoordinates).mockResolvedValueOnce([vocab("offer", "free_shipping", "免運")]);
    const saved = ad({ offer_key: "free_shipping" });
    const fresh = campaign({ name: "伺服器確認的新安排", groups: [group({ ads: [saved] })],
      budget_basis_json: { ...WITH_STRATEGY, strategy: { ...WITH_STRATEGY.strategy,
        decision: { schema_version: 1, state: "modified", revision: "server-new-revision", slots: [],
          feasibility: { state: "blocked", reasons: [{ code: "structure_modified",
            message: "投放結構已修改，原策略理由與核准已失效。", slot_ids: [] }] },
          receipt: { revision: "accepted-revision", operation_id: "op", slots: [] } },
      } },
    });
    vi.mocked(patchAd).mockResolvedValueOnce(saved);
    vi.mocked(getCampaign).mockResolvedValueOnce(fresh);
    const { onCampaignChange } = renderTab(campaign());
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^廣告一/ }));
    await user.selectOptions(await screen.findByRole("combobox", { name: "優惠" }), "free_shipping");
    await user.click(screen.getByRole("button", { name: "儲存變更" }));
    await vi.waitFor(() => expect(onCampaignChange).toHaveBeenLastCalledWith(fresh));
    expect(getCampaign).toHaveBeenCalledWith("brd_1", "cmp_1");
  });

  it("F52-I04: a changed coordinate or role refreshes the structure even when names/budget stay", async () => {
    const c = campaign();
    const view = renderTab(c);
    await vi.waitFor(() => expect(getCampaignStructure).toHaveBeenCalledTimes(1));
    view.rerender(<MemoryRouter><DeliveryTab brandId="brd_1" campaign={{ ...c,
      groups: [{ ...c.groups[0], role: "explore", ads: c.groups[0].ads.map((a) => ({ ...a, offer_key: "free_shipping" })) }],
    }} onCampaignChange={view.onCampaignChange} onChangeTab={view.onChangeTab} /></MemoryRouter>);
    await vi.waitFor(() => expect(getCampaignStructure).toHaveBeenCalledTimes(2));
  });

  it("F52-I04: a pending save readback cannot update a different campaign/brand", async () => {
    vi.mocked(getCampaign).mockReset();
    const user = userEvent.setup();
    let complete!: (c: CampaignDetail) => void;
    vi.mocked(patchGroup).mockResolvedValueOnce(group({ name: "改名" }));
    vi.mocked(getCampaign).mockReturnValueOnce(new Promise((resolve) => { complete = resolve; }));
    const view = renderTab(campaign());
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));
    await user.clear(screen.getByDisplayValue("投放組"));
    await user.type(screen.getByRole("textbox", { name: "名稱" }), "改名");
    await user.click(screen.getByRole("button", { name: "儲存變更" }));
    await vi.waitFor(() => expect(getCampaign).toHaveBeenCalledOnce());
    view.onCampaignChange.mockClear();
    view.rerender(<MemoryRouter><DeliveryTab brandId="other_brand" campaign={campaign({ id: "other_campaign" })}
      onCampaignChange={view.onCampaignChange} onChangeTab={view.onChangeTab} /></MemoryRouter>);
    complete(campaign({ name: "late old result" }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(view.onCampaignChange).not.toHaveBeenCalled();
  });

  it("capacity prints as one line under the tree, as served", () => {
    renderTab(campaign({ capacity: { daily: 1500, cap: 450, can_support: 3, ceiling: 4, carried: 1 } }));
    const line = document.querySelector("[data-slot=plan-capacity]") as HTMLElement;
    expect(line.textContent).toBe("每天 1,500，撐得起 3 則，另加一則探索（這期最多 4 則，其中 1 則沿用上一期）");
    const tree = screen.getByRole("heading", { name: "活動 → 廣告組 → 廣告" });
    expect(tree.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("no capacity (no cap or no budget yet): no line", () => {
    renderTab(campaign({ capacity: null }));
    expect(document.querySelector("[data-slot=plan-capacity]")).toBeNull();
  });

  it("a carried ad shows the served 「沿用上一期」 chip in its group's list and its carry_note in the editor", async () => {
    const user = userEvent.setup();
    const carried = ad({ id: "ad_c", name: "考前一週・書包一盒", carried_label: "沿用上一期", carry_note: "上一期的素材找不到，這則要重新放素材" });
    renderTab(campaign({ groups: [group({ ads: [carried, ad({ id: "ad_2", name: "廣告二" })] })] }));
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    const node = screen.getByRole("button", { name: /^考前一週・書包一盒/ });
    expect(within(node).getByText("沿用上一期")).toBeTruthy();
    expect(within(screen.getByRole("button", { name: /^廣告二/ })).queryByText("沿用上一期")).toBeNull();
    await user.click(node);
    expect(document.querySelector("[data-slot=carry-note]")?.textContent).toBe("上一期的素材找不到，這則要重新放素材");
  });

  it("the ad editor offers only this period's menu for proof／offer／format; a held excluded key stays, marked 這期不能用", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchCoordinates).mockResolvedValueOnce([
      vocab("proof", "none", "不放證據"), vocab("proof", "lab_test", "檢驗報告"), vocab("proof", "review", "顧客好評"),
      vocab("offer", "none", "無優惠"), vocab("offer", "discount", "折扣特價"), vocab("offer", "limited_time", "限時"),
      vocab("audience", "cold", "陌生"), vocab("audience", "warm", "看過的人"),
    ]);
    const menu = [
      { dimension: "proof", key: "none", label: "不放證據" }, { dimension: "proof", key: "lab_test", label: "檢驗報告" },
      { dimension: "offer", key: "none", label: "無優惠" }, { dimension: "offer", key: "discount", label: "折扣特價" },
      { dimension: "audience", key: "cold", label: "陌生" }, { dimension: "audience", key: "warm", label: "看過的人" },
    ];
    renderTab(campaign({ menu, groups: [group({ ads: [ad({ offer_key: "limited_time" })] })] }));
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(await screen.findByRole("button", { name: /^廣告一/ }));
    const options = (label: string) => Array.from((screen.getByRole("combobox", { name: label }) as HTMLSelectElement).options).map((o) => o.textContent);
    await vi.waitFor(() => expect(options("證據")).toEqual(["未設定", "不放證據", "檢驗報告"]));
    expect(options("優惠")).toEqual(["限時（這期不能用）", "未設定", "無優惠", "折扣特價"]);
    // A dimension the menu does not narrow lists the vocabulary as before.
    expect(options("受眾")).toEqual(["未設定", "陌生", "看過的人"]);
  });

  it("a refused ad save: name_forbidden beside the name, coordinate_unavailable beside the coordinates, in the server's words", async () => {
    const user = userEvent.setup();
    vi.mocked(patchAd).mockRejectedValueOnce(new ApiResponseError("廣告名稱寫了「治療」，這是你標了不能講的話", 400, {}, { code: "name_forbidden" }));
    renderTab(campaign());
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^廣告一/ }));
    const name = screen.getByDisplayValue("廣告一");
    await user.clear(name);
    await user.type(name, "治療失眠");
    await user.click(screen.getByRole("button", { name: "儲存變更" }));
    const alert = await screen.findByText("廣告名稱寫了「治療」，這是你標了不能講的話");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.parentElement?.contains(name)).toBe(true);
    expect(name.getAttribute("aria-invalid")).toBe("true");

    vi.mocked(patchAd).mockRejectedValueOnce(new ApiResponseError("這期不能用這個優惠：這個賣法沒有登記這種優惠", 400, {}, { code: "coordinate_unavailable" }));
    await user.type(name, "好");
    await user.click(screen.getByRole("button", { name: "儲存變更" }));
    const coords = await screen.findByText("這期不能用這個優惠：這個賣法沒有登記這種優惠");
    expect(coords.previousElementSibling?.querySelector("select")).toBeTruthy();
    expect(screen.queryByText("廣告名稱寫了「治療」，這是你標了不能講的話")).toBeNull();
  });

  it("F50 Contract I (c1-08): a group date outside the campaign prints the server's sentence under the dates", async () => {
    const user = userEvent.setup();
    const sentence = "投放組日期要在活動期間（2026-01-01～2026-01-15）內。";
    vi.mocked(patchGroup).mockRejectedValueOnce(new ApiResponseError(sentence, 400, {}, { code: "group_dates_outside" }));
    renderTab(campaign());
    await user.click(screen.getByRole("button", { name: "進階：編輯這一組（投放組）" }));
    await user.click(screen.getByRole("button", { name: /^投放組/ }));
    await user.click(screen.getByRole("button", { name: "自訂日期" }));
    const [start, end] = Array.from(document.querySelectorAll<HTMLInputElement>('input[type="date"]'));
    fireEvent.change(start, { target: { value: "2026-01-10" } });
    fireEvent.change(end, { target: { value: "2026-01-31" } });
    await user.click(screen.getByRole("button", { name: "儲存變更" }));
    const alert = await screen.findByText(sentence);
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.parentElement?.contains(end)).toBe(true); // under the dates, inside 投放期間
    expect(screen.getAllByText(sentence)).toHaveLength(1); // not repeated under the form
    expect(patchGroup).toHaveBeenCalledWith("brd_1", "grp_1", expect.objectContaining({ start_date: "2026-01-10", end_date: "2026-01-31" }));
    fireEvent.change(end, { target: { value: "2026-01-14" } });
    expect(screen.queryByText(sentence)).toBeNull(); // a changed date clears it
  });
});
