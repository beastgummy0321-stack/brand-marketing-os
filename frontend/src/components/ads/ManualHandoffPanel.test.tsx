import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ManualHandoffPanel } from "./ManualHandoffPanel";
import { checkHandoff, createNewAdHandoff, getHandoff, HandoffRequestRejected, reconsiderHandoff, reportHandoff, type HandoffItem, type HandoffWorkspace } from "@/lib/adsHandoffApi";
import { existingCampaigns, externalView, type NativeEntity } from "@/lib/adsExternalApi";
import type { ChangeSet } from "@/lib/adsChangeApi";

vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org" }) }));
vi.mock("@/lib/adsHandoffApi", async () => ({ ...await vi.importActual("@/lib/adsHandoffApi"), getHandoff: vi.fn(), reportHandoff: vi.fn(), checkHandoff: vi.fn(), reconsiderHandoff: vi.fn(), createNewAdHandoff: vi.fn(), refreshHandoffSources: vi.fn() }));
vi.mock("@/lib/adsExternalApi", () => ({ existingCampaigns: vi.fn(), externalView: vi.fn() }));
const node = (id: string, kind = "ad", parent: string | null = "group"): NativeEntity => ({ id, platform: "fixture", source_account: "account", native_kind: kind, native_id: id, parent_native_id: parent, name: `平台 ${id}`, native_label: kind, native_status: "ACTIVE", start_date: null, end_date: null, budget_amount: null, budget_type: "unknown", budget_raw: {}, currency: null, last_success_at: null, sync_error: null, creative: {} });
const item = (overrides: Partial<HandoffItem> = {}): HandoffItem => ({ id: "handoff", name: "B2", planned_kind: "ad", planned_id: "placement", status: "unknown", change_set_id: "set", parent_item_id: null, expected_parent_name: "既有組", placement_id: "placement", placement_revision: 2, entity_id: null, platform: null, source_account: null, native_kind: null, native_id: null, reported_at: null, observed_at: null, entity_exists: false, setting_matches: null, material_evidence: "unknown", expected_json: { copy: { body: "核准文案" } }, evidence_json: {}, ...overrides });
const workspace = (items = [item()]): HandoffWorkspace => ({ items, items_truncated: false, ready_placements: [{ id: "placement", filename: "B2.png", revision: 2, purpose: "ad", destination_entity_id: "group" }], destinations: [node("root", "campaign", null), node("group", "adset", "root"), node("old-ad")], destinations_truncated: false, launch_stale: null, notice: "人工交接不代表平台已投遞。" });
function Location() { const where = useLocation(); return <output aria-label="目前位置">{where.pathname}{where.search}</output>; }
function view(brand = "brand", campaign = "campaign", mode: "all" | "items" | "new-ad" = "all") { return <MemoryRouter><ManualHandoffPanel brandId={brand} campaignId={campaign} mode={mode} /><Location /></MemoryRouter>; }
beforeEach(() => {
  vi.clearAllMocks(); sessionStorage.clear();
  vi.mocked(getHandoff).mockResolvedValue(workspace());
  vi.mocked(existingCampaigns).mockResolvedValue({ sources: [{ platform: "fixture", label: "測試平台", account_id: "account" }], platform: "fixture", source_account: "account", items: [], next_cursor: null, job: null });
  vi.mocked(externalView).mockResolvedValue({ entities: [node("B2")], observations: [], next_entity_cursor: null, next_observation_cursor: null, window: { start: "2026-09-01", end: "2026-09-19" }, connections: [], sync: {}, coverage: {} });
});
describe("manual handoff", () => {
  it("shows one pending item at a time and submits only the selected item", async () => {
    vi.mocked(getHandoff).mockResolvedValue(workspace([item(), item({ id: "other", name: "B3" })]));
    vi.mocked(reportHandoff).mockResolvedValue(item({ id: "other", name: "B3", status: "reported" }));
    render(view("brand", "campaign", "items"));
    const choice = await screen.findByLabelText("選擇這次要核對的項目", { exact: false });
    expect(screen.getAllByRole("article")).toHaveLength(1);
    await userEvent.selectOptions(choice, "other");
    const row = screen.getByRole("article", { name: "交接 B3" });
    await userEvent.click(within(row).getByRole("button", { name: "我已到平台操作" }));
    expect(reportHandoff).toHaveBeenCalledWith("brand", "campaign", "other", expect.any(AbortSignal));
    await userEvent.selectOptions(choice, "handoff");
    expect(screen.getByRole("article", { name: "交接 B2" })).toBeTruthy();
    expect(checkHandoff).not.toHaveBeenCalled();
  });
  it("keeps the three evidence levels separate and reads only the chosen candidate", async () => {
    vi.mocked(checkHandoff).mockResolvedValue(item({ entity_id: "B2", platform: "fixture", source_account: "account", native_kind: "ad", native_id: "B2", entity_exists: true, setting_matches: true, material_evidence: "unknown", observed_at: "2026-09-19T01:00:00Z" }));
    render(view());
    const row = await screen.findByRole("article", { name: "交接 B2" });
    await userEvent.selectOptions(within(row).getByRole("combobox", { name: "選擇平台候選物件" }), "fixture:account:ad:B2");
    await userEvent.click(within(row).getByRole("button", { name: "重新讀回核對" }));
    expect(checkHandoff).toHaveBeenCalledWith("brand", "campaign", "handoff", { platform: "fixture", source_account: "account", native_kind: "ad", native_id: "B2", user_verified: false }, expect.any(AbortSignal));
    expect(await screen.findByText("已讀回")).toBeTruthy();
    const updated = screen.getByRole("article", { name: "交接 B2" });
    expect(within(updated).getByText("相符")).toBeTruthy();
    expect(within(updated).getByText("未知")).toBeTruthy();
    expect(within(updated).getByText(/實際投遞與生效時間：尚未確認/)).toBeTruthy();
    expect(reportHandoff).not.toHaveBeenCalled();
  });
  it("does not convert reporting into confirmed settings and blocks children until parent is read back", async () => {
    vi.mocked(getHandoff).mockResolvedValue(workspace([item({ parent_item_id: "missing-parent" })]));
    vi.mocked(reportHandoff).mockResolvedValue(item({ parent_item_id: "missing-parent", status: "reported", reported_at: "2026-09-19T01:00:00Z" }));
    render(view("brand", "campaign", "items"));
    await userEvent.click(await screen.findByRole("button", { name: "我已到平台操作" }));
    expect(await screen.findByText("已回報，待讀回")).toBeTruthy();
    expect(screen.getByRole("button", { name: "讀回並核對此物件" })).toHaveProperty("disabled", true);
    expect(checkHandoff).not.toHaveBeenCalled();
  });
  it("reconsiders a known disabled ad only through the dedicated check and a stated reason", async () => {
    const bound = item({ entity_id: "B2", native_kind: "ad", native_id: "B2", platform: "fixture", source_account: "account", status: "deviated", entity_exists: true });
    vi.mocked(getHandoff).mockResolvedValue(workspace([bound]));
    vi.mocked(reconsiderHandoff).mockResolvedValue({ ...bound, status: "stale" });
    render(view("brand", "campaign", "items"));
    await userEvent.click(await screen.findByRole("button", { name: "已停用的廣告：重新檢視方案" }));
    expect(screen.getByRole("button", { name: "核對已停用，重審新方案" })).toHaveProperty("disabled", true);
    await userEvent.type(screen.getByLabelText("重審原因"), "平台已停用，重做素材版本");
    await userEvent.click(screen.getByRole("button", { name: "核對已停用，重審新方案" }));
    expect(reconsiderHandoff).toHaveBeenCalledWith("brand", "campaign", "handoff", "平台已停用，重做素材版本", expect.any(AbortSignal));
    expect(await screen.findByText("需重新確認")).toBeTruthy();
    expect(createNewAdHandoff).not.toHaveBeenCalled();
  });
  it("aborts old reads and ignores late responses when the brand changes with the same campaign id", async () => {
    let resolveOld!: (value: HandoffWorkspace) => void;
    vi.mocked(getHandoff).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const ui = render(view("old", "same", "new-ad"));
    const signal = vi.mocked(getHandoff).mock.calls[0][2];
    ui.rerender(view("new", "same", "new-ad"));
    expect(signal?.aborted).toBe(true);
    await screen.findByLabelText("新廣告名稱");
    resolveOld(workspace([item({ name: "舊品牌項目" })]));
    await waitFor(() => expect(screen.queryByText("舊品牌項目")).toBeNull());
  });
});
async function fillNewAd() {
  await userEvent.type(await screen.findByLabelText("新廣告名稱"), "B2 新測試");
  await userEvent.selectOptions(screen.getByLabelText("已確認素材"), "placement");
  await userEvent.type(screen.getByLabelText("新增理由"), "測試新素材，保留原廣告");
}
describe("new independent ad", () => {
  it("uses the confirmed revision and a group, then links to approval without platform creation", async () => {
    vi.mocked(createNewAdHandoff).mockResolvedValue({ id: "new-set" } as ChangeSet);
    render(view("brand", "campaign", "new-ad"));
    await fillNewAd();
    const choices = within(screen.getByLabelText("加入既有投放組")).getAllByRole("option");
    expect(choices.map(option => option.getAttribute("value"))).toEqual(["", "group"]);
    await userEvent.click(screen.getByRole("button", { name: "保存清單，檢視並核准" }));
    expect(createNewAdHandoff).toHaveBeenCalledWith("brand", "campaign", expect.objectContaining({ operation_id: expect.any(String), revision: 2, placement_id: "placement", destination_entity_id: "group" }), expect.any(AbortSignal));
    expect(await screen.findByText("/brands/brand/ads/campaigns/campaign?tab=changes&change=new-set")).toBeTruthy();
    expect(checkHandoff).not.toHaveBeenCalled();
  });
  it("retains the exact unknown request across remount and retries the same operation once", async () => {
    vi.mocked(createNewAdHandoff).mockRejectedValueOnce(new Error("回應遺失"));
    const first = render(view("brand", "campaign", "new-ad"));
    await fillNewAd();
    await userEvent.click(screen.getByRole("button", { name: "保存清單，檢視並核准" }));
    expect(await screen.findByText("回應遺失")).toBeTruthy();
    const original = vi.mocked(createNewAdHandoff).mock.calls[0][2];
    first.unmount();
    render(view("brand", "campaign", "new-ad"));
    const retry = await screen.findByRole("button", { name: "重試同一份新增清單" });
    expect(screen.getByLabelText("新廣告名稱")).toHaveProperty("disabled", true);
    vi.mocked(createNewAdHandoff).mockResolvedValue({ id: "same-set" } as ChangeSet);
    await userEvent.click(retry);
    expect(vi.mocked(createNewAdHandoff).mock.calls[1][2]).toEqual(original);
    expect(createNewAdHandoff).toHaveBeenCalledTimes(2);
  });
  it("unlocks editing only after a definitive request rejection", async () => {
    vi.mocked(createNewAdHandoff).mockRejectedValueOnce(new HandoffRequestRejected("素材版本已變更"));
    render(view("brand", "campaign", "new-ad"));
    await fillNewAd();
    await userEvent.click(screen.getByRole("button", { name: "保存清單，檢視並核准" }));
    expect(await screen.findByText("素材版本已變更")).toBeTruthy();
    expect(screen.getByLabelText("新廣告名稱")).toHaveProperty("disabled", false);
    expect(sessionStorage.getItem("ads-new-ad-handoff:user:org:brand:campaign")).toBeNull();
  });
});
