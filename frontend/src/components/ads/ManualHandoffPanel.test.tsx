import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ManualHandoffPanel } from "./ManualHandoffPanel";
import { checkHandoff, createNewAdHandoff, getHandoff, HandoffRequestRejected, reconsiderHandoff, refreshHandoffSources, reportHandoff, type HandoffItem, type HandoffWorkspace } from "@/lib/adsHandoffApi";
import { existingCampaigns, externalView, syncJob, syncOutcome, type NativeEntity, type SyncOutcome } from "@/lib/adsExternalApi";
import type { ChangeSet } from "@/lib/adsChangeApi";

vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-09-28" }, orgs: [] } }) }));
vi.mock("@/lib/adsHandoffApi", async () => ({ ...await vi.importActual("@/lib/adsHandoffApi"), getHandoff: vi.fn(), reportHandoff: vi.fn(), checkHandoff: vi.fn(), reconsiderHandoff: vi.fn(), createNewAdHandoff: vi.fn(), refreshHandoffSources: vi.fn() }));
vi.mock("@/lib/adsExternalApi", () => ({ existingCampaigns: vi.fn(), externalView: vi.fn(), syncJob: vi.fn(), syncOutcome: vi.fn() }));
const node = (id: string, kind = "ad", parent: string | null = "group"): NativeEntity => ({ id, platform: "fixture", source_account: "account", native_kind: kind, native_id: id, parent_native_id: parent, name: `平台 ${id}`, native_label: kind, native_status: "ACTIVE", start_date: null, end_date: null, budget_amount: null, budget_type: "unknown", budget_raw: {}, currency: null, last_success_at: null, sync_error: null, creative: {} });
const item = (overrides: Partial<HandoffItem> = {}): HandoffItem => ({ id: "handoff", name: "B2", planned_kind: "ad", planned_id: "placement", status: "unknown", change_set_id: "set", parent_item_id: null, expected_parent_name: "既有組", placement_id: "placement", placement_revision: 2, entity_id: null, platform: null, source_account: null, native_kind: null, native_id: null, reported_at: null, observed_at: null, entity_exists: false, setting_matches: null, material_evidence: "unknown", expected_json: { copy: { body: "核准文案" } }, evidence_json: {}, ...overrides });
const workspace = (items = [item()]): HandoffWorkspace => ({ items, items_truncated: false, ready_placements: [{ id: "placement", filename: "B2.png", revision: 2, purpose: "ad", destination_entity_id: "group" }], destinations: [node("root", "campaign", null), node("group", "adset", "root"), node("old-ad")], destinations_truncated: false, launch_stale: null, notice: "人工交接不代表平台已投遞。", settings_readback: null });
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
    vi.mocked(reportHandoff).mockResolvedValue(item({ parent_item_id: "missing-parent", status: "reported", status_label: "已回報，待讀回", reported_at: "2026-09-19T01:00:00Z" }));
    render(view("brand", "campaign", "items"));
    await userEvent.click(await screen.findByRole("button", { name: "我已到平台操作" }));
    expect(await screen.findByText("已回報，待讀回")).toBeTruthy();
    expect(screen.getByRole("button", { name: "讀回並核對此物件" })).toHaveProperty("disabled", true);
    expect(checkHandoff).not.toHaveBeenCalled();
  });
  it("F47-I06: greyed-out buttons say why; a stored failed read says when it happened beside 重新讀回核對", async () => {
    const at = "2026-10-28T14:59:00Z";
    const stamp = (() => { const d = new Date(at); const p = (n: number) => String(n).padStart(2, "0"); return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; })();
    vi.mocked(getHandoff).mockResolvedValue(workspace([item({
      status: "unknown", reported_at: at, evidence_json: { message: "平台無法讀取此資料（代碼 2）。", attempted_at: at } as HandoffItem["evidence_json"],
    })]));
    render(view("brand", "campaign", "items"));
    const row = await screen.findByRole("article", { name: "交接 B2" });
    expect(within(row).getByRole("button", { name: "已回報人工操作" })).toHaveProperty("disabled", true);
    expect(within(row).getByText(`${stamp} 已回報；接著讀回核對這一項`)).toBeTruthy();
    expect(within(row).getByRole("button", { name: "重新讀回核對" })).toHaveProperty("disabled", true);
    expect(within(row).getByText("還缺物件層級、平台物件識別：選一個平台候選，或在「進階：手填平台識別」填上")).toBeTruthy();
    expect(within(row).getByText(`${stamp} 讀回時讀不到：平台無法讀取此資料（代碼 2）。`)).toBeTruthy();
  });
  it("reconsiders a known disabled ad only through the dedicated check and a stated reason", async () => {
    const bound = item({ entity_id: "B2", native_kind: "ad", native_id: "B2", platform: "fixture", source_account: "account", status: "deviated", entity_exists: true });
    vi.mocked(getHandoff).mockResolvedValue(workspace([bound]));
    vi.mocked(reconsiderHandoff).mockResolvedValue({ ...bound, status: "stale", status_label: "需重新確認" });
    render(view("brand", "campaign", "items"));
    await userEvent.click(await screen.findByRole("button", { name: "已停用的廣告：重新檢視方案" }));
    expect(screen.getByRole("button", { name: "核對已停用，重審新方案" })).toHaveProperty("disabled", true);
    await userEvent.type(screen.getByLabelText("重審原因"), "平台已停用，重做素材版本");
    await userEvent.click(screen.getByRole("button", { name: "核對已停用，重審新方案" }));
    expect(reconsiderHandoff).toHaveBeenCalledWith("brand", "campaign", "handoff", "平台已停用，重做素材版本", expect.any(AbortSignal));
    expect(await screen.findByText("需重新確認")).toBeTruthy();
    expect(createNewAdHandoff).not.toHaveBeenCalled();
  });
  it("status words are the served status_label (no local word table)", async () => {
    vi.mocked(getHandoff).mockResolvedValue(workspace([item({ status: "unknown", status_label: "讀到了但無法核對" }), item({ id: "other", name: "B3", status: "pending", status_label: "尚未回報" })]));
    render(view("brand", "campaign", "items"));
    const row = await screen.findByRole("article", { name: "交接 B2" });
    expect(within(row).getByText("讀到了但無法核對")).toBeTruthy();
    expect(screen.getByRole("option", { name: "B3 · 尚未回報" })).toBeTruthy();
  });
  describe("更新平台候選 follows the read it posted (F49-I14, Contract O)", () => {
    const job = { id: "aes_1", status: "pending", last_success_at: null };
    const answer = (state: SyncOutcome["state"], text: string, code: string | null = null) => ({ job, connected: true, outcome: { state, code, text } });
    const cases: [SyncOutcome["state"], string][] = [
      ["failed", "這次沒讀到平台資料：平台授權已失效或權限不足，請重新授權"],
      ["empty", "沒有讀到資料：平台在這段期間沒有回傳任何資料"],
      ["found", "已讀到平台資料"],
    ];
    for (const [state, text] of cases) {
      it(`a ${state} read prints its sentence and reads the candidates again`, async () => {
        vi.mocked(refreshHandoffSources).mockResolvedValue({ job, jobs: [job] });
        vi.mocked(syncJob).mockResolvedValue(answer(state, text, state === "failed" ? "permission_denied" : state === "empty" ? "no_rows" : null));
        render(view("brand", "campaign", "items"));
        await screen.findByRole("article", { name: "交接 B2" });
        expect(externalView).toHaveBeenCalledTimes(1);
        await userEvent.click(screen.getByRole("button", { name: "更新平台候選" }));
        const line = await screen.findByText(text);
        expect(line.getAttribute("data-state")).toBe(state);
        expect(syncJob).toHaveBeenCalledWith("brand", "aes_1", expect.any(AbortSignal), "campaign");
        await waitFor(() => expect(externalView).toHaveBeenCalledTimes(2));
        expect(screen.getByText(text)).toBeTruthy();
        expect(screen.queryByText(/來源讀取已排入/)).toBeNull();
      });
    }
    it("a re-read that requested several accounts follows the campaign's outcome over them", async () => {
      vi.mocked(refreshHandoffSources).mockResolvedValue({ job, jobs: [job, { ...job, id: "aes_2" }] });
      vi.mocked(syncOutcome).mockResolvedValue({ state: "partial", code: "source_error", text: "有部分平台資料沒讀到：平台暫時沒有回應，稍後會再試", job_ids: ["aes_1", "aes_2"], last_success_at: null });
      render(view("brand", "campaign", "items"));
      await screen.findByRole("article", { name: "交接 B2" });
      await userEvent.click(screen.getByRole("button", { name: "更新平台候選" }));
      expect(await screen.findByText("有部分平台資料沒讀到：平台暫時沒有回應，稍後會再試")).toBeTruthy();
      expect(syncOutcome).toHaveBeenCalledWith("brand", "campaign", expect.any(AbortSignal));
      expect(syncJob).not.toHaveBeenCalled();
    });
  });
  it("tells the host whether the handoff has anything to verify", async () => {
    const onHandoffWork = vi.fn();
    const ui = render(<MemoryRouter><ManualHandoffPanel brandId="brand" campaignId="campaign" mode="items" onHandoffWork={onHandoffWork} /></MemoryRouter>);
    await waitFor(() => expect(onHandoffWork).toHaveBeenLastCalledWith(true));
    ui.unmount();
    vi.mocked(getHandoff).mockResolvedValue(workspace([]));
    const empty = vi.fn();
    render(<MemoryRouter><ManualHandoffPanel brandId="brand" campaignId="campaign" mode="items" onHandoffWork={empty} /></MemoryRouter>);
    await waitFor(() => expect(empty).toHaveBeenLastCalledWith(false));
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
  it("with no ad set to join, says why (destinations_note) on the page and on the greyed 保存 button", async () => {
    const note = "這個活動還沒上架，平台上還沒有投放組；新廣告請到投放結構加";
    vi.mocked(getHandoff).mockResolvedValue({ ...workspace(), destinations: [], destination_by_ad: {}, destinations_note: note });
    render(view("brand", "campaign", "new-ad"));
    expect(await screen.findByText(note, { selector: "[data-slot=destinations-note]" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "保存清單，檢視並核准" })).toHaveProperty("disabled", true);
    expect(screen.getAllByText(note).length).toBeGreaterThan(1);
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

describe("settings readback (F29-I16)", () => {
  const readback = { read_at: "2026-09-23T02:52:00Z", fields: [
    { key: "age" as const, label: "年齡", expected_label: "25–54 歲", observed_label: "18–65+ 歲", state: "differ" as const, reason: null },
  ] };
  it("shows the readback block and tells the host it is shown", async () => {
    vi.mocked(getHandoff).mockResolvedValue({ ...workspace(), settings_readback: readback });
    const shown = vi.fn();
    render(<MemoryRouter><ManualHandoffPanel brandId="brand" campaignId="campaign" mode="items" platformLabel="Meta" onSettingsReadback={shown} /></MemoryRouter>);
    expect(await screen.findByRole("region", { name: "投放設定讀回" })).toBeTruthy();
    expect(screen.getByText("1 項投放設定和核准的不一樣")).toBeTruthy();
    await waitFor(() => expect(shown).toHaveBeenLastCalledWith(true));
  });
  it("reports no readback before any read, and on a failed handoff read", async () => {
    const shown = vi.fn();
    const { unmount } = render(<MemoryRouter><ManualHandoffPanel brandId="brand" campaignId="campaign" mode="items" onSettingsReadback={shown} /></MemoryRouter>);
    await waitFor(() => expect(shown).toHaveBeenLastCalledWith(false));
    expect(screen.queryByRole("region", { name: "投放設定讀回" })).toBeNull();
    unmount();
    vi.mocked(getHandoff).mockRejectedValue(new Error("逾時"));
    const failed = vi.fn();
    render(<MemoryRouter><ManualHandoffPanel brandId="brand" campaignId="campaign" mode="items" onSettingsReadback={failed} /></MemoryRouter>);
    await waitFor(() => expect(failed).toHaveBeenLastCalledWith(false));
  });
});
