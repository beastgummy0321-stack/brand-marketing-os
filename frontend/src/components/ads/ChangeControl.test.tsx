import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "@/lib/adsChangeApi";
import * as workspaceApi from "@/lib/adsWorkspaceApi";
import type { NativeEntity } from "@/lib/adsExternalApi";
import { ChangeControl } from "./ChangeControl";
import { MonthlyBudgetPanel } from "./MonthlyBudgetPanel";

// The handoff panel reports whether it lists anything to verify (`onHandoffWork`); tests set what it reports.
const handoff = vi.hoisted(() => ({ work: false }));
vi.mock("./ManualHandoffPanel", async () => {
  const { useEffect } = await import("react");
  return { ManualHandoffPanel: ({ onHandoffWork }: { onHandoffWork?: (hasWork: boolean) => void }) => { useEffect(() => { onHandoffWork?.(handoff.work); }, [onHandoffWork]); return null; } };
});
vi.mock("@/lib/auth", () => ({ getOrgId: () => "org_test" }));
vi.mock("@/lib/adsWorkspaceApi", async importOriginal => ({ ...await importOriginal<typeof workspaceApi>(), getCampaignTimeline: vi.fn() }));
vi.mock("@/lib/adsChangeApi", async importOriginal => ({
  ...await importOriginal<typeof api>(),
  getMonthlyBudget: vi.fn(), saveMonthlyBudget: vi.fn(), getChangeControl: vi.fn(),
  createChangeSet: vi.fn(), approveChangeSet: vi.fn(), decideChangeSet: vi.fn(), actOnChangeItem: vi.fn(),
}));
const budget: api.MonthlyBudget = { month: "2026-09", currency: "TWD", amount: 60000, revision: 1,
  known_spend: 22000, ongoing_estimate: null, reserved_increases: 0, available: null,
  uncertainties: ["帳戶預算單位尚未確認"], can_increase: false, period_end: "2026-09-30", confirmed_at: null, notice: "目前餘額不確定。" };
const target: NativeEntity = { id: "entity_b", platform: "fixture", source_account: "account_1", native_id: "B", native_kind: "ad", native_label: "廣告", name: "原廣告 B", parent_native_id: "G", native_status: "ACTIVE", start_date: null, end_date: null, budget_amount: null, budget_type: "unknown", budget_raw: {}, currency: "TWD", last_success_at: null, sync_error: null, creative: { kind: "image", fields: { title: "舊標題", body: "舊內文" } } };
function change(overrides: Partial<api.ChangeSet> = {}): api.ChangeSet {
  return { id: "change_1", campaign_id: "campaign_1", title: "保留圖片，調整文案", month: "2026-09", operation_id: "operation_saved", content_hash: "hash_saved", status: "draft", reason: null, revisit_at: null, approval_id: null, created_at: "2026-09-19T00:00:00Z", approved_at: null, items: [{ id: "item_1", kind: "copy", target_id: target.id, target, before: { body: "舊內文" }, after: { body: "新內文" }, reason: "測試不同訴求", verification_state: "pending", evidence_json: {}, reported_at: null, first_observed_at: null, verified_at: null, platform_url: null }], ...overrides };
}
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear(); handoff.work = false;
  vi.mocked(api.getMonthlyBudget).mockResolvedValue(budget);
  vi.mocked(api.getChangeControl).mockResolvedValue({ targets: [target], change_sets: [change()] });
  vi.mocked(workspaceApi.getCampaignTimeline).mockResolvedValue({ rows: [], truncated: false });
});
function page(brand = "brand_a", entry = "/") { return <MemoryRouter initialEntries={[entry]}><ChangeControl brandId={brand} campaignId="campaign_1" /></MemoryRouter>; }
// v10 (F30-I09): the list, composer, month budget and handoff live in the fold 「進階：自己建一份變更」.
async function openAdvanced() { await userEvent.click(await screen.findByRole("button", { name: "進階：自己建一份變更" })); }

describe("ChangeControl 核准與逐項核對", () => {
  it("核准傳本份內容指紋，回報完成不冒充平台已讀回", async () => {
    const user = userEvent.setup();
    const approved = change({ status: "approved", approval_id: "approval_1" });
    vi.mocked(api.approveChangeSet).mockResolvedValue(approved);
    vi.mocked(api.actOnChangeItem).mockResolvedValue({ ...approved, items: [{ ...approved.items[0], verification_state: "reported", reported_at: "2026-09-19T01:00:00Z" }] });
    render(page()); await openAdvanced();
    await user.click(await screen.findByRole("button", { name: "核准這份變更清單" }));
    expect(api.approveChangeSet).toHaveBeenCalledWith("brand_a", "campaign_1", expect.objectContaining({ content_hash: "hash_saved" }), expect.any(AbortSignal));
    await user.click(await screen.findByRole("button", { name: "我已手動完成這一項" }));
    expect(await screen.findByText("已自行回報，待核對")).toBeTruthy();
    expect(screen.queryByText("設定已讀回")).toBeNull();
    expect(api.actOnChangeItem).toHaveBeenCalledWith("brand_a", "campaign_1", "change_1", "item_1", "report", expect.any(AbortSignal));
  });

  it("保存回應遺失後鎖住原內容並沿用同一次操作識別重試", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getChangeControl).mockResolvedValue({ targets: [target], change_sets: [] });
    vi.mocked(api.createChangeSet).mockRejectedValueOnce(new Error("回應未收到，請重試核對")).mockResolvedValueOnce(change());
    render(page()); await openAdvanced();
    await user.click((await screen.findAllByRole("button", { name: "建立變更清單" }))[0]);
    await user.type(screen.getByLabelText("變更 1 原因"), "測試新訴求");
    await user.click(screen.getByRole("button", { name: "保存清單，檢視並核准" }));
    expect(await screen.findByText("回應未收到，請重試核對")).toBeTruthy();
    const first = vi.mocked(api.createChangeSet).mock.calls[0][2];
    expect(first.operation_id).not.toBe(first.title);
    expect((screen.getByLabelText("變更 1 新內文") as HTMLTextAreaElement).disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "重試同一份清單" }));
    await screen.findByRole("button", { name: "核准這份變更清單" });
    expect(vi.mocked(api.createChangeSet).mock.calls[1][2]).toEqual(first);
    expect(sessionStorage.getItem("ads-change-operation:org_test:brand_a:campaign_1")).toBeNull();
  });

  it("切換品牌中止舊讀取，遲到回應不顯示另一品牌清單", async () => {
    let resolveOld: (value: api.ChangeControlData) => void = () => {};
    vi.mocked(api.getChangeControl).mockImplementation((brand) => brand === "brand_a" ? new Promise(resolve => { resolveOld = resolve; }) : Promise.resolve({ targets: [], change_sets: [] }));
    const view = render(page()); await openAdvanced();
    await waitFor(() => expect(api.getChangeControl).toHaveBeenCalled());
    const oldSignal = vi.mocked(api.getChangeControl).mock.calls[0][2];
    view.rerender(page("brand_b")); await openAdvanced();
    expect(await screen.findByText("還沒有可核對的廣告對象")).toBeTruthy();
    resolveOld({ targets: [target], change_sets: [change({ title: "不該顯示的 A 品牌清單" })] });
    await waitFor(() => expect(oldSignal?.aborted).toBe(true));
    expect(screen.queryByText("不該顯示的 A 品牌清單")).toBeNull();
  });

  it("交接仍有上架項目要核對時，不顯示「還沒有可核對的廣告對象」", async () => {
    vi.mocked(api.getChangeControl).mockResolvedValue({ targets: [], change_sets: [] });
    handoff.work = true;
    render(page()); await openAdvanced();
    // Loaded: the reading placeholder is gone, so an empty state would render now if it were allowed to.
    await waitFor(() => expect(screen.queryByText("正在讀取清單與平台對象…")).toBeNull());
    expect(screen.queryByText("還沒有可核對的廣告對象")).toBeNull();
  });

  it("交接與變更都沒有東西時，才顯示「還沒有可核對的廣告對象」", async () => {
    vi.mocked(api.getChangeControl).mockResolvedValue({ targets: [], change_sets: [] });
    render(page()); await openAdvanced();
    expect(await screen.findByText("還沒有可核對的廣告對象")).toBeTruthy();
  });

  it("部分完成保留逐項結果，降額尚未核對不釋放額度", async () => {
    const set = change({ status: "approved" });
    set.items[0].verification_state = "confirmed";
    set.items.push({ ...set.items[0], id: "item_2", kind: "budget", target: { ...target, name: "G", native_kind: "adset" }, before: { daily_amount: 1000 }, after: { daily_amount: 800 }, verification_state: "unknown" });
    vi.mocked(api.getChangeControl).mockResolvedValue({ targets: [target], change_sets: [set] });
    render(page()); await openAdvanced();
    expect(await screen.findByText(/1 \/ 2 項設定已核對/)).toBeTruthy();
    expect(screen.getByText(/降額尚未核對，不會先釋放額度/)).toBeTruthy();
    expect(screen.getByText("結果未知，待補核對")).toBeTruthy();
    expect(screen.queryByText("全部完成")).toBeNull();
  });

  it("失效只顯示相關項差異，不提供直接核准覆蓋平台的捷徑", async () => {
    const set = change({ status: "approved" });
    set.items[0] = { ...set.items[0], verification_state: "stale", stale_reason: "平台文案已變更", evidence_json: { observed: { body: "平台第三版" } } };
    vi.mocked(api.getChangeControl).mockResolvedValue({ targets: [target], change_sets: [set] });
    render(page()); await openAdvanced();
    expect(await screen.findByText("平台第三版")).toBeTruthy();
    expect(screen.getByText("平台文案已變更")).toBeTruthy();
    expect(screen.getByRole("button", { name: "依目前設定另建清單" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "核准這份變更清單" })).toBeNull();
  });

  it("核准後尚未核對的項目不能直接修改，讀回授權由後端決定", async () => {
    vi.mocked(api.getChangeControl).mockResolvedValue({ targets: [target], change_sets: [change({ status: "approved", can_revise: false })] });
    render(page()); await openAdvanced();
    const revise = await screen.findByRole("button", { name: "修改尚未執行項目" });
    expect((revise as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "讀回核對這一項" })).toBeTruthy();
  });

  it("重審重新讀取目前素材，已完成項目不再次列入", async () => {
    const user = userEvent.setup();
    const set = change({ status: "approved", can_revise: true });
    set.items.push({ ...set.items[0], id: "done", target_id: "done", verification_state: "confirmed" });
    vi.mocked(api.getChangeControl).mockResolvedValueOnce({ targets: [target], change_sets: [set] }).mockResolvedValue({ targets: [{ ...target, creative: { kind: "image", fields: { body: "最新讀回文案" } } }], change_sets: [set] });
    render(page()); await openAdvanced();
    await user.click(await screen.findByRole("button", { name: "修改尚未執行項目" }));
    expect(await screen.findByText("最新讀回文案")).toBeTruthy();
    expect(screen.getAllByLabelText(/新內文/)).toHaveLength(1);
    expect(api.getChangeControl).toHaveBeenCalledTimes(2);
  });

  it("明確拒絕的保存可修正內容，不誤判成回應遺失而鎖死", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getChangeControl).mockResolvedValue({ targets: [target], change_sets: [] });
    vi.mocked(api.createChangeSet).mockRejectedValue(new api.ChangeRequestRejected("原清單仍有未核對的操作"));
    render(page()); await openAdvanced();
    await user.click((await screen.findAllByRole("button", { name: "建立變更清單" }))[0]);
    await user.type(screen.getByLabelText("變更 1 原因"), "測試");
    await user.click(screen.getByRole("button", { name: "保存清單，檢視並核准" }));
    expect(await screen.findByText("原清單仍有未核對的操作")).toBeTruthy();
    expect((screen.getByLabelText("變更 1 新內文") as HTMLInputElement).disabled).toBe(false);
    expect(sessionStorage.getItem("ads-change-operation:org_test:brand_a:campaign_1")).toBeNull();
  });
});

describe("ChangeControl v10 變更紀錄與進階收合", () => {
  const timelineRow = (overrides: Partial<workspaceApi.TimelineRow>): workspaceApi.TimelineRow => ({ change_set_id: "change_1", title: "保留圖片，調整文案", at: "2026-09-19T00:00:00Z", state: "draft", reason: null, checked: 0, total: 1, version: null, ...overrides });

  it("預設只見變更紀錄；清單、月預算與交接收在「進階：自己建一份變更」", async () => {
    vi.mocked(workspaceApi.getCampaignTimeline).mockResolvedValue({ rows: [timelineRow({})], truncated: false });
    render(page());
    expect(await screen.findByRole("list", { name: "變更紀錄" })).toBeTruthy();
    const fold = screen.getByRole("button", { name: "進階：自己建一份變更" });
    expect(fold.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("button", { name: "核准這份變更清單" })).toBeNull();
    expect(api.getMonthlyBudget).not.toHaveBeenCalled();
    await userEvent.click(fold);
    expect(await screen.findByRole("button", { name: "核准這份變更清單" })).toBeTruthy();
    expect(api.getMonthlyBudget).toHaveBeenCalled();
  });

  it("帶著 ?change= 進來（交接頁的連結）直接展開進階區", async () => {
    render(page("brand_a", "/?tab=changes&change=change_1"));
    expect(await screen.findByRole("button", { name: "核准這份變更清單" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "進階：自己建一份變更" }).getAttribute("aria-expanded")).toBe("true");
  });

  it("單項清單連到既有步驟頁；上架與多項清單在進階區打開", async () => {
    const multi = change({ id: "change_multi", title: "兩項文案", status: "approved" });
    multi.items.push({ ...multi.items[0], id: "item_2" });
    const launch = change({ id: "change_launch", title: "首次上架", status: "approved" });
    vi.mocked(api.getChangeControl).mockResolvedValue({ targets: [target], change_sets: [change(), multi, launch] });
    vi.mocked(workspaceApi.getCampaignTimeline).mockResolvedValue({ rows: [
      timelineRow({}), timelineRow({ change_set_id: "change_multi", title: "兩項文案", state: "platform", total: 2 }),
      timelineRow({ change_set_id: "change_launch", title: "首次上架", state: "check", checked: 3, total: 11, version: 1 }),
    ], truncated: false });
    render(page());
    expect((await screen.findByRole("link", { name: "打開：保留圖片，調整文案" })).getAttribute("href")).toBe("/brands/brand_a/ads/campaigns/campaign_1/changes/change_1/confirm");
    await userEvent.click(await screen.findByRole("button", { name: "打開：兩項文案" }));
    expect(screen.getByRole("button", { name: "進階：自己建一份變更" }).getAttribute("aria-expanded")).toBe("true");
    expect(await screen.findByRole("heading", { name: "兩項文案" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "去核對：首次上架" }));
    expect(await screen.findByRole("heading", { name: "首次上架" })).toBeTruthy();
  });
});

describe("MonthlyBudgetPanel", () => {
  it("初次可修正推導幣別，接受零月額且未知花費不冒充零", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getMonthlyBudget).mockResolvedValue({ ...budget, amount: null, revision: 0, known_spend: null });
    vi.mocked(api.saveMonthlyBudget).mockResolvedValue({ ...budget, amount: 0, revision: 1, currency: "USD", known_spend: null });
    render(<MemoryRouter><MonthlyBudgetPanel brandId="brand_a" month="2026-09" /></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "設定月總額" }));
    await user.clear(screen.getByLabelText("月預算幣別"));
    await user.type(screen.getByLabelText("月預算幣別"), "USD");
    await user.type(screen.getByLabelText("每月品牌總額"), "0");
    await user.click(screen.getByRole("button", { name: "確認月總額" }));
    expect(await screen.findByText("月總額已保存；不會另外增加可花的錢。")).toBeTruthy();
    expect(api.saveMonthlyBudget).toHaveBeenCalledWith("brand_a", { month: "2026-09", currency: "USD", amount: 0, expected_revision: 0 }, expect.any(AbortSignal));
    expect(screen.getAllByText("尚待確認")).toHaveLength(3);
  });
  it("餘額未知仍能保存月總額，不把未知填0或宣稱平台已限額", async () => {
    const user = userEvent.setup();
    vi.mocked(api.saveMonthlyBudget).mockResolvedValue({ ...budget, amount: 65000, revision: 2 });
    render(<MemoryRouter><MonthlyBudgetPanel brandId="brand_a" month="2026-09" /></MemoryRouter>);
    await user.click(await screen.findByRole("button", { name: "調整月總額" }));
    await user.clear(screen.getByLabelText("每月品牌總額"));
    await user.type(screen.getByLabelText("每月品牌總額"), "65000");
    await user.click(screen.getByRole("button", { name: "確認月總額" }));
    expect(await screen.findByText("月總額已保存；不會另外增加可花的錢。")).toBeTruthy();
    expect(api.saveMonthlyBudget).toHaveBeenCalledWith("brand_a", { month: "2026-09", currency: "TWD", amount: 65000, expected_revision: 1 }, expect.any(AbortSignal));
    expect(screen.getAllByText("尚待確認").length).toBe(2);
    expect(screen.getByText("本機設定不會讓平台自動停止花費。")).toBeTruthy();
  });
});
