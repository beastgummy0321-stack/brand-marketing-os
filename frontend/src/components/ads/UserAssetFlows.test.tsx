import { StrictMode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UserAssetsLibrary, twoAtATime, uploadChunks } from "./UserAssetsLibrary";
import { AuthAssetMedia } from "./AuthAssetMedia";
import { UserAssetPlacements } from "./UserAssetPlacements";
import { AssetHandoffPanel } from "./AssetHandoffPanel";
import { AssetsTab } from "./AssetsTab";
import { nextStep } from "./nextStep";
import { NewCampaignPage } from "./NewCampaignPage";
import { createCampaignFromPicks, getWizardOptions } from "@/lib/adsWizardApi";
import { listUserAssets, createUploadBatch, putUpload, retryUpload, getUploadBatch, attachUpload, assetBlob, listPlacements, listSuggestionBatches, suggestAssets, getSuggestionBatch, revisePlacement, confirmPlacement, assetHandoff, type AssetLibrary, type Placement, type AssetUpload, type SuggestionBatch } from "@/lib/adsUserAssetsApi";
import * as materialApi from "@/lib/adsMaterialApi";
import { existingCampaigns, externalView, type NativeEntity } from "@/lib/adsExternalApi";
import { getHandoff, type HandoffWorkspace } from "@/lib/adsHandoffApi";
import type { CampaignDetail } from "@/lib/adsApi";

vi.mock("@/lib/http", async () => ({ ...(await vi.importActual<typeof import("@/lib/http")>("@/lib/http")), apiFetch: vi.fn() }));
import { ApiResponseError } from "@/lib/http";
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "u:o", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-09-28" }, orgs: [] } }) }));
vi.mock("@/lib/adsWizardApi", async original => ({...await original<object>(), getWizardOptions: vi.fn(), createCampaignFromPicks: vi.fn(), getNextPeriod: vi.fn()}));
vi.mock("@/lib/adsUserAssetsApi", async importOriginal => ({ ...await importOriginal<object>(), listUserAssets: vi.fn(), createUploadBatch: vi.fn(), putUpload: vi.fn(), retryUpload: vi.fn(), getUploadBatch: vi.fn(), attachUpload: vi.fn(), assetBlob: vi.fn(), listPlacements: vi.fn(), listSuggestionBatches: vi.fn(), suggestAssets: vi.fn(), getSuggestionBatch: vi.fn(), revisePlacement: vi.fn(), confirmPlacement: vi.fn(), assetHandoff: vi.fn() }));
vi.mock("@/lib/adsExternalApi", () => ({ existingCampaigns: vi.fn(), externalView: vi.fn() }));
vi.mock("@/lib/adsHandoffApi", async importOriginal => ({ ...await importOriginal<object>(), getHandoff: vi.fn() }));
vi.mock("@/lib/adsSlotsApi", async importOriginal => ({ ...await importOriginal<object>(), getSlots: vi.fn().mockResolvedValue({ ready: 0, total: 0, groups: [], requests: [], requests_truncated: false }) }));
vi.mock("@/lib/adsMaterialApi", async original => ({ ...await original<typeof materialApi>(), listMaterialTasks: vi.fn(), saveMaterialOperation: vi.fn(), materialOptions: vi.fn() }));
const library = (): AssetLibrary => ({ assets: [], uploads: [], next_cursor: null, next_upload_cursor: null });
const upload = (id = "u1", status = "complete"): AssetUpload => ({ id, batch_id: "batch1", filename: `${id}.png`, expected_size: 1, status, error: null, asset_id: status === "complete" ? "asset1" : null, copy_fields: { headline: "原標題", body: "原內文", description: "原說明", caption: "額外原文" } });
const placement = (id = "p1", revision = 1): Placement => ({ id, revision, is_current: true, asset_id: "asset1", filename: `${id}.png`, mime_type: "image/png", asset_status: "ready", asset_error: null, copy_fields: { headline: "原標題", body: "原內文", description: "原說明", caption: "額外原文" }, suggested_copy: {}, purpose: "產品介紹", destination_entity_id: null, start_date: null, end_date: null, status: "pending", pending_reason: "尚待確認安排", required: true, confirmed_at: null, suggestion_batch_id: null });
const campaign: CampaignDetail = {
  id: "c1", origin: "imported", capabilities: { allowed: ["view", "add_assets", "arrange", "confirm"], unavailable: { strategy: "平台唯讀", publish: "平台唯讀" } },
  name: "活動", goal_text: "產品介紹", objective: "產品介紹", cap: { value: null, basis: null, own_value: null, break_even: null, price: null, product_id: null, result_kind: "purchase", result_label: "購買", missing: ["product"], revision: 0 },
  start_date: null, end_date: null, status: "draft", budget_planned: null, budget_scenario: null, budget_basis_json: {}, budget_total: null, context_json: {}, constraints_json: {}, verdict: null, verdict_json: {}, closed_at: null, created_by: null, created_at: "2026-01-01", groups: [], actions: [], outcome: { spend: null, purchases: null, revenue: null }, asset_readiness: { total: 0, ready_count: 0 }, external_id: null, external_name: null, external_status: null, local_state: "unbound", bound_at: null,
};
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
function viewPlacements(c: CampaignDetail = campaign) { return render(<MemoryRouter><UserAssetPlacements brandId="b1" campaign={c} /></MemoryRouter>); }
/** The handoff read (`GET …/handoff`) the placements read their 目的節點 from (F49 Contract D). */
const handoffRead = (overrides: Partial<HandoffWorkspace> = {}): HandoffWorkspace => ({ items: [], items_truncated: false, ready_placements: [], destinations: [], destinations_truncated: false, launch_stale: null, notice: "", settings_readback: null, destination_by_ad: {}, destinations_note: null, ...overrides });
const adSet = (id: string, name: string): NativeEntity => ({ id, platform: "meta", source_account: "act_1", native_kind: "adset", native_id: `n_${id}`, native_label: "廣告組", name, parent_native_id: "root", native_status: "ACTIVE", start_date: null, end_date: null, budget_amount: null, budget_type: "daily", budget_raw: {}, currency: "TWD", last_success_at: null, sync_error: null, creative: {} });
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  vi.mocked(materialApi.listMaterialTasks).mockResolvedValue({ tasks: [] });
  vi.mocked(materialApi.materialOptions).mockResolvedValue({ options: [] });
  vi.mocked(listUserAssets).mockResolvedValue(library()); vi.mocked(listPlacements).mockResolvedValue({ placements: [] });
  vi.mocked(listSuggestionBatches).mockResolvedValue({ batches: [], next_cursor: null });
  vi.mocked(existingCampaigns).mockResolvedValue({ items: [], sources: [], next_cursor: null, job: null });
  vi.mocked(externalView).mockResolvedValue({ entities: [], observations: [], next_entity_cursor: null, next_observation_cursor: null, window: { start: "2026-01-01", end: "2026-01-30" }, connections: [], coverage: {}, sync: {} });
  vi.mocked(getHandoff).mockResolvedValue(handoffRead());
});
describe("durable upload UI", () => {
  it("keeps the upload library mounted while creating and retries attach without creating twice", async () => {
    vi.mocked(listUserAssets).mockResolvedValue({ ...library(), uploads: [upload()] });
    vi.mocked(getUploadBatch).mockResolvedValue({batch: {id: "batch1", uploads: [upload()]}});
    vi.mocked(getWizardOptions).mockResolvedValue({ products: [{ id: "prd_1", name: "商品一 · 單盒", display_name: "單盒", kind: "single", knowledge_product_id: "kp_1", knowledge_product_name: "商品一", price: 990, currency: "TWD", thumbnail_url: null, has_cost: true, break_even: 600, cap_per_sale: 600, derived_fields: [], offer_labels: [], customer_groups: [], landing_url: null, previous: null, learned: null }], objectives: [{ key: "購買", label: "購買", description: "看每賣一筆花多少", available: true, platforms: {} }], default_objective: null, default_platform: null });
    const create = deferred<CampaignDetail & { parsed: boolean }>(); vi.mocked(createCampaignFromPicks).mockReturnValue(create.promise);
    vi.mocked(attachUpload).mockRejectedValueOnce(new Error("附件暫時失敗")).mockResolvedValue({ placement: placement() });
    render(<MemoryRouter><NewCampaignPage brandId="b1" /></MemoryRouter>); const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /進階：一句話建立/ }));
    await user.click(await screen.findByLabelText("選取 u1.png"));
    await user.click(screen.getByRole("radio", { name: /單盒/ })); await user.click(screen.getByRole("radio", { name: /購買/ }));
    await user.type(screen.getByLabelText("這個活動最多花"), "30000");
    await user.click(screen.getByRole("button", { name: /下一步：系統理解/ }));
    expect(screen.getByText("自帶圖片／影片")).toBeTruthy(); expect(screen.getByLabelText("選取 u1.png")).toHaveProperty("disabled", true);
    await act(async () => create.resolve({ ...campaign, objective: "購買", context_json: { product_ids: ["prd_1"] }, constraints_json: { budget: 30000 }, parsed: true }));
    expect(await screen.findByText(/活動已建立，未完成素材仍可重試/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /重試加入未完成素材並繼續/ }));
    await waitFor(() => expect(attachUpload).toHaveBeenCalledTimes(2)); expect(createCampaignFromPicks).toHaveBeenCalledTimes(1);
    expect(attachUpload).toHaveBeenLastCalledWith("b1", "c1", "u1");
  });
  it("restores off-page reference intent through the batch facade, then respects explicit removal", async () => {
    const restored = {...upload("off-page"), status: "unverified", asset_id: null};
    vi.mocked(listUserAssets).mockResolvedValue({...library(), next_upload_cursor: "more"});
    vi.mocked(getUploadBatch).mockResolvedValue({batch: {id: "batch1", uploads: [upload("off-page")]}});
    const selection = vi.fn(); render(<UserAssetsLibrary brandId="b1" initialSelection={[restored]} onSelection={selection} />);
    const pick = await screen.findByLabelText("選取 off-page.png");
    await waitFor(() => expect(selection).toHaveBeenLastCalledWith([upload("off-page")]));
    expect(selection.mock.calls.every(([rows]) => rows.length === 1)).toBe(true);
    expect(pick).toHaveProperty("checked", true);
    await userEvent.setup().click(pick); expect(selection).toHaveBeenLastCalledWith([]);
  });
  it("failed reference reads keep selection and say unverified rather than missing original", async () => {
    const restored = {...upload("off-page"), status: "unverified", asset_id: null};
    vi.mocked(listUserAssets).mockRejectedValue(new Error("read unavailable"));
    const selection = vi.fn(); render(<UserAssetsLibrary brandId="b1" initialSelection={[restored]} onSelection={selection} />);
    await screen.findByText("read unavailable");
    expect(screen.getByLabelText("選取 off-page.png")).toHaveProperty("checked", true);
    expect(selection.mock.calls.every(([rows]) => rows.length === 1)).toBe(true);
    expect(screen.getByText(/原檔狀態尚未核實/)).toBeTruthy();
    expect(screen.queryByText(/尚未傳完；先重試/)).toBeNull();
  });
  it("keeps all 11 files, splits descriptor batches, and saves through raw PUT", async () => {
    let serial = 0;
    vi.mocked(createUploadBatch).mockImplementation(async (_brand, files) => ({ batch: { id: `batch${serial}`, uploads: files.map(f => ({ ...upload(`u${++serial}`, "pending"), filename: f.filename, expected_size: f.size, copy_fields: f.copy_fields })) } }));
    vi.mocked(putUpload).mockImplementation(async (_brand, id, file) => ({ upload: { ...upload(id), filename: file.name } }));
    render(<UserAssetsLibrary brandId="b1" />); const user = userEvent.setup();
    await user.upload(screen.getByLabelText("選擇自帶素材"), Array.from({ length: 11 }, (_, i) => new File(["x"], `photo${i}.png`, { type: "image/png" })));
    expect(screen.getByText(/待上傳 11 檔，分成 2 批/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "保存原檔與原文" }));
    await waitFor(() => expect(putUpload).toHaveBeenCalledTimes(11));
    expect(vi.mocked(createUploadBatch).mock.calls.map(c => c[1].length)).toEqual([10, 1]);
    expect(await screen.findByText("photo10.png")).toBeTruthy();
  });
  it("sends the shared copy for every file and keeps a file's own copy after 這張另外寫", async () => {
    vi.mocked(createUploadBatch).mockImplementation(async (_brand, files) => ({ batch: { id: "batch1", uploads: files.map((f, i) => ({ ...upload(`u${i + 1}`, "pending"), filename: f.filename, copy_fields: f.copy_fields })) } }));
    vi.mocked(putUpload).mockImplementation(async (_brand, id) => ({ upload: upload(id) }));
    render(<UserAssetsLibrary brandId="b1" />); const user = userEvent.setup();
    await user.upload(screen.getByLabelText("選擇自帶素材"), [new File(["x"], "a.png", { type: "image/png" }), new File(["x"], "b.png", { type: "image/png" })]);
    expect(screen.getByText("套在 2 檔")).toBeTruthy(); expect(screen.getAllByText("沿用共用原文")).toHaveLength(2);
    await user.type(screen.getByLabelText("共用標題"), "共用標"); await user.type(screen.getByLabelText("共用內文"), "共用文");
    expect(screen.queryByLabelText("b.png原文標題")).toBeNull();
    await user.click(screen.getAllByRole("button", { name: "這張另外寫" })[1]);
    expect(screen.getByText("套在 1 檔")).toBeTruthy(); expect(screen.getByText("自己的原文")).toBeTruthy();
    expect(screen.getByLabelText("b.png原文標題")).toHaveProperty("value", "共用標"); // seeded from the shared copy
    await user.clear(screen.getByLabelText("b.png原文標題")); await user.type(screen.getByLabelText("b.png原文標題"), "自己的");
    await user.type(screen.getByLabelText("共用標題"), "改"); // later shared edits do not leak into the own file
    await user.click(screen.getByRole("button", { name: "保存原檔與原文" }));
    await waitFor(() => expect(createUploadBatch).toHaveBeenCalledTimes(1));
    expect(vi.mocked(createUploadBatch).mock.calls[0][1].map(f => f.copy_fields)).toEqual([{ headline: "共用標改", body: "共用文" }, { headline: "自己的", body: "共用文" }]);
    expect(screen.queryByRole("button", { name: "改回共用" })).toBeNull();
  });
  it("bounds long Chinese originals by UTF-8 bytes without dropping copy", () => {
    const rows = Array.from({ length: 3 }, (_, i) => ({ file: new File(["x"], `${i}.png`), copy: { headline: "字".repeat(4000), body: "字".repeat(4000), description: "字".repeat(4000) } }));
    expect(uploadChunks(rows).map(c => c.length)).toEqual([1, 1, 1]);
    expect(uploadChunks(rows).flat().map(r => r.copy)).toEqual(rows.map(r => r.copy));
  });
  it("allows at most two concurrent raw uploads", async () => {
    const gate = deferred<void>(); let active = 0; let peak = 0; let count = 0;
    const job = twoAtATime([1, 2, 3, 4], async () => { active++; peak = Math.max(peak, active); await gate.promise; active--; count++; });
    expect(active).toBe(2); gate.resolve(); await job; expect(peak).toBe(2); expect(count).toBe(4);
  });
  it("reconciles a failed row before asking for bytes; already complete never retransmits", async () => {
    vi.mocked(listUserAssets).mockResolvedValue({ ...library(), uploads: [upload("u1", "failed")] });
    vi.mocked(retryUpload).mockResolvedValue({ upload: upload() });
    render(<UserAssetsLibrary brandId="b1" />); const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "重試／核對保存" }));
    expect(await screen.findByText("原檔已保存，無需重傳")).toBeTruthy(); expect(putUpload).not.toHaveBeenCalled();
  });
  it("ignores a late response after changing brands", async () => {
    const first = deferred<AssetLibrary>(); vi.mocked(listUserAssets).mockReturnValueOnce(first.promise);
    const v = render(<UserAssetsLibrary brandId="old" />); v.rerender(<UserAssetsLibrary brandId="new" />);
    await act(async () => { first.resolve({ ...library(), uploads: [upload("secret-old")] }); });
    expect(screen.queryByText("secret-old.png")).toBeNull();
  });
  it("freshly checks an unsaved descriptor before retrying selected bytes, but rejects a lock conflict", async () => {
    const failed = { ...upload("u1", "failed"), storage_key: null, sha256: null };
    vi.mocked(listUserAssets).mockResolvedValue({ ...library(), uploads: [failed] });
    // F51 Contract C: the retry branch reads `asset_file_missing`, never the sentence (reworded here on purpose).
    vi.mocked(retryUpload)
      .mockRejectedValueOnce(new ApiResponseError("此檔案正在上傳，請稍候。", 409, {}, { code: "user_asset_unavailable" }))
      .mockRejectedValueOnce(new ApiResponseError("原檔不在伺服器上（改寫過的句子）", 409, {}, { code: "asset_file_missing" }));
    vi.mocked(getUploadBatch).mockResolvedValue({ batch: { id: "batch1", uploads: [failed] } });
    vi.mocked(putUpload).mockResolvedValue({ upload: upload() });
    render(<UserAssetsLibrary brandId="b1" />); const user = userEvent.setup();
    const file = new File(["x"], "u1.png", { type: "image/png" });
    await user.upload(await screen.findByLabelText("重選 u1.png"), file);
    expect(await screen.findByText("此檔案正在上傳，請稍候。")).toBeTruthy(); expect(putUpload).not.toHaveBeenCalled();
    await user.upload(screen.getByLabelText("重選 u1.png"), file);
    await waitFor(() => expect(putUpload).toHaveBeenCalledTimes(1)); expect(getUploadBatch).toHaveBeenCalledWith("b1", "batch1", expect.any(AbortSignal));
  });
  it("downloads under StrictMode with fresh auth signal and revokes the URL", async () => {
    vi.mocked(assetBlob).mockResolvedValue(new Blob(["original"]));
    const make = vi.fn(() => "blob:original"); const revoke = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: make, revokeObjectURL: revoke }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<StrictMode><AuthAssetMedia brandId="b1" assetId="a1" filename="original.png" mime="image/png" /></StrictMode>);
    await userEvent.setup().click(screen.getByRole("button", { name: "下載原檔" }));
    expect(vi.mocked(assetBlob).mock.calls[0][3]?.aborted).toBe(false); expect(click).toHaveBeenCalled();
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("blob:original"), { timeout: 2000 }); click.mockRestore();
  });
});
describe("placement and evidence UI", () => {
  it("imported empty groups still expose uploads and never require generated ads", async () => {
    render(<MemoryRouter><AssetsTab brandId="b1" campaign={campaign} onCampaignChange={vi.fn()} onChangeTab={vi.fn()} /></MemoryRouter>);
    // F30-I11: the material request editor and the uploads live in the tab's 「進階」 fold.
    await userEvent.setup().click(screen.getByRole("button", { name: "進階：素材需求、自帶素材與人工交接" }));
    vi.mocked(materialApi.saveMaterialOperation).mockResolvedValue({ task: {
      id: "task1", campaign_id: "c1", revision: 1, title: "使用已有成品", mode: "existing", instruction: "", copy_fields: {}, prompt: { source: "none" }, reference_asset_ids: [], review_id: null, recommendation_id: null, review_context: null, content_hash: "a".repeat(64), candidates: [], selected_candidate_id: null, placement_id: null, placement_revision: null, placement_current: null, pack_id: null, dispatch_status: "not_requested", history: [], limitations: [], created_at: "2026-09-19", replaces: null, cancelled_at: null,
    } });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /使用已有成品/ }));
    await user.click(screen.getByRole("button", { name: "保存素材需求" }));
    await user.click(await screen.findByRole("button", { name: "上傳或選擇成品" }));
    expect(screen.getByText("自帶圖片／影片")).toBeTruthy();
    expect(screen.getByLabelText("選擇自帶素材")).toBeTruthy();
    expect(screen.queryByText("這個 Campaign 還沒有廣告")).toBeNull();
    expect(screen.queryByRole("button", { name: "確認需求，交給工作台" })).toBeNull();
    expect(materialApi.saveMaterialOperation).toHaveBeenCalledTimes(1);
    expect(vi.mocked(materialApi.saveMaterialOperation).mock.calls[0][0].body).toMatchObject({ mode: "existing" });
    expect(nextStep(campaign).target).toBe("assets");
  });
  it("shows all required pending rows beyond a ten-item suggestion batch", async () => {
    vi.mocked(listPlacements).mockResolvedValue({ placements: Array.from({ length: 11 }, (_, i) => ({ ...placement(`p${i}`), copy_fields: {} })) });
    vi.mocked(suggestAssets).mockResolvedValue({ batch: { id: "s1", status: "queued", created_at: "2026-01-01", error: null }, limits: { codex_notice: "" } });
    viewPlacements(); const user = userEvent.setup();
    expect(await screen.findByText(/必用 11 件.*待處理 11 件/)).toBeTruthy();
    expect(screen.getByText("11 件有空白欄")).toBeTruthy(); expect(screen.getByText(/其餘 1 件仍保留待處理/)).toBeTruthy(); expect(screen.getByText(/p10.png · 第 1 版/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "為 10 件補空白文案" }));
    await waitFor(() => expect(suggestAssets).toHaveBeenCalledTimes(1));
    expect(vi.mocked(suggestAssets).mock.calls[0][2]).toHaveLength(10);
  });
  it("applies one copy to every unconfirmed placement, never to a confirmed one, and reports the count", async () => {
    const confirmed = { ...placement("p1", 2), confirmed_at: "2026-01-01" };
    vi.mocked(listPlacements).mockResolvedValue({ placements: [confirmed, placement("p2"), placement("p3")] });
    vi.mocked(revisePlacement).mockImplementation(async (_b, _c, id) => ({ placement: placement(id, 2) }));
    viewPlacements(); const user = userEvent.setup();
    expect(await screen.findByText("有填的欄位會蓋掉那 2 件的原文；已確認的 1 件不動。")).toBeTruthy();
    // F47-I06 (Q6): three blank fields cannot be applied, and the button says why.
    expect(screen.getByRole("button", { name: "套用到 2 件待處理" })).toHaveProperty("disabled", true);
    expect(screen.getByText("三欄都是空的，沒有可以套用的內容。")).toBeTruthy();
    await user.type(screen.getByLabelText("套用標題"), "統一標題");
    await user.click(screen.getByRole("button", { name: "套用到 2 件待處理" }));
    expect(await screen.findByText("已套到 2 件待處理，各存了一版；逐件檢查並確認。")).toBeTruthy();
    expect(revisePlacement).toHaveBeenCalledTimes(2);
    expect(vi.mocked(revisePlacement).mock.calls.map(c => c[2])).toEqual(["p2", "p3"]);
    // Only apply_copy + expected_revision: purpose／dates stay untouched; the server keeps the current text of every
    // blank field (F47-I06, Q6) and every extra original key.
    expect(vi.mocked(revisePlacement).mock.calls[0][3]).toEqual({ apply_copy: { headline: "統一標題", body: "", description: "" }, expected_revision: 1 });
    expect(screen.queryByText(/伺服器已是第 2 版/)).toBeNull(); // the reloaded revision is adopted, not flagged as a conflict
  });
  it("stops apply-to-all at a 409 and names the conflicting file", async () => {
    vi.mocked(listPlacements).mockResolvedValue({ placements: [placement("p2"), placement("p3")] });
    vi.mocked(revisePlacement).mockRejectedValueOnce(new ApiResponseError("素材版本已更新", 409, {}, { code: "placement_copy_conflict" }));
    viewPlacements(); const user = userEvent.setup();
    await user.type(await screen.findByLabelText("套用標題"), "統一標題");
    await user.click(screen.getByRole("button", { name: "套用到 2 件待處理" }));
    expect(await screen.findByText(/p2.png 已有新版本，套用停在這件（已套 0 件）/)).toBeTruthy();
    expect(revisePlacement).toHaveBeenCalledTimes(1); expect(screen.queryByText(/已套到/)).toBeNull();
  });
  it("disables 補空白文案 with its reason when nothing is blank, counts blanks otherwise, and links to the slot picker", async () => {
    vi.mocked(listPlacements).mockResolvedValue({ placements: [placement("p1")] });
    const { unmount } = viewPlacements();
    expect(await screen.findByText("沒有空白欄")).toBeTruthy(); expect(screen.getByText("文案齊了")).toBeTruthy();
    expect(screen.getByRole("button", { name: "為 0 件補空白文案" })).toHaveProperty("disabled", true);
    expect(screen.getByText("選取的都填滿了，沒有可補的欄位。")).toBeTruthy();
    expect(screen.getByRole("link", { name: "到素材頁選一版文案 →" }).getAttribute("href")).toMatch(/\?tab=assets$/);
    unmount();
    vi.mocked(listPlacements).mockResolvedValue({ placements: [placement("p1"), { ...placement("p2"), copy_fields: { headline: "只有標題" } }] });
    viewPlacements();
    expect(await screen.findByText("1 件有空白欄")).toBeTruthy(); expect(screen.getByText("缺 2 欄")).toBeTruthy();
    expect(screen.getByRole("button", { name: "為 1 件補空白文案" })).toHaveProperty("disabled", false);
    expect(screen.queryByText("選取的都填滿了，沒有可補的欄位。")).toBeNull();
  });
  it("manual confirmation passes null batch and preserves a pending risk reason", async () => {
    vi.mocked(listPlacements).mockResolvedValue({ placements: [placement()] });
    vi.mocked(confirmPlacement).mockResolvedValue({ placement: { ...placement(), pending_reasons: ["原文宣稱需要核對來源"] } });
    viewPlacements(); await userEvent.setup().click(await screen.findByRole("button", { name: "只用我的文案，檢查並確認" }));
    expect(await screen.findByText("原文宣稱需要核對來源")).toBeTruthy(); expect(confirmPlacement).toHaveBeenCalledWith("b1", "c1", expect.objectContaining({ id: "p1", revision: 1 }), null); expect(suggestAssets).not.toHaveBeenCalled();
  });
  it("409 loads the current revision but retains local text and extra original fields", async () => {
    vi.mocked(listPlacements).mockResolvedValueOnce({ placements: [placement()] }).mockResolvedValue({ placements: [placement("p1", 2)] });
    vi.mocked(revisePlacement).mockRejectedValue(new ApiResponseError("素材版本已更新", 409, {}, { code: "placement_copy_conflict" }));
    viewPlacements(); const user = userEvent.setup();
    // The editor of an unconfirmed card is open by default (prototype #/placements).
    await user.clear(await screen.findByLabelText("p1.png安排標題")); await user.type(screen.getByLabelText("p1.png安排標題"), "我的修改");
    await user.click(screen.getByRole("button", { name: "儲存為新版安排" }));
    expect(await screen.findByText(/伺服器已是第 2 版/)).toBeTruthy(); expect(screen.getByLabelText("p1.png安排標題")).toHaveProperty("value", "我的修改");
    expect(revisePlacement).toHaveBeenCalledWith("b1", "c1", "p1", expect.objectContaining({ expected_revision: 1, copy_fields: expect.objectContaining({ headline: "我的修改", caption: "額外原文" }) }));
    expect(revisePlacement).toHaveBeenCalledTimes(1);
  });
  it("finds a queued batch again and polls it to a visible result", async () => {
    const queued: SuggestionBatch = { id: "s1", status: "queued", created_at: "2026-01-01", error: null };
    vi.mocked(listSuggestionBatches).mockResolvedValue({ batches: [queued], next_cursor: null });
    vi.mocked(getSuggestionBatch).mockResolvedValueOnce({ batch: queued }).mockResolvedValue({ batch: { ...queued, status: "succeeded", results: [], remaining_count: 0 } });
    viewPlacements(); const user = userEvent.setup(); await user.click(await screen.findByText(/先前建議批次/)); await user.click(await screen.findByRole("button", { name: "查看本批" }));
    expect(await screen.findByText(/建議已備妥，請逐件核對/, {}, { timeout: 4000 })).toBeTruthy();
  });
  it("F49-I14: an internal draft's placement says why it has no 目的節點 (destinations_note) instead of an empty picker", async () => {
    const note = "這個活動還沒上架，平台上還沒有投放組；新廣告請到投放結構加";
    vi.mocked(getHandoff).mockResolvedValue(handoffRead({ destinations_note: note }));
    vi.mocked(listPlacements).mockResolvedValue({ placements: [placement("p1")] });
    viewPlacements({ ...campaign, origin: "internal", capabilities: undefined, external_view: null, lifecycle: { state: "draft", label: "草稿", can_close: false } });
    expect(await screen.findByText(`安排目的：${note}`)).toBeTruthy();
    expect(screen.queryByLabelText("p1.png目的節點")).toBeNull();
    expect(screen.queryByRole("button", { name: /載入本活動目的節點/ })).toBeNull();
    expect(getHandoff).toHaveBeenCalledWith("b1", "c1");
    expect(externalView).not.toHaveBeenCalled();
  });
  it("F49-I14: the 目的節點 options are the handoff read's destinations, for any origin", async () => {
    vi.mocked(getHandoff).mockResolvedValue(handoffRead({ destinations: [adSet("aes_1", "既有投放組"), adSet("aes_2", "新客投放組")] }));
    vi.mocked(listPlacements).mockResolvedValue({ placements: [placement("p1")] });
    viewPlacements({ ...campaign, origin: "internal", capabilities: undefined, external_view: null, lifecycle: { state: "live", label: "投放中", can_close: true } });
    const picker = await screen.findByLabelText("p1.png目的節點");
    expect([...picker.querySelectorAll("option")].map(o => o.textContent)).toEqual(["未指定（沿活動安排）", "廣告組 · 既有投放組", "廣告組 · 新客投放組"]);
    expect(externalView).not.toHaveBeenCalled();
  });
  it("F49-I14: a closed campaign (served lifecycle) is read-only", async () => {
    vi.mocked(listPlacements).mockResolvedValue({ placements: [placement("p1")] });
    viewPlacements({ ...campaign, lifecycle: { state: "closed", label: "已結案", can_close: false } });
    await screen.findByText(/p1.png · 第 1 版/);
    expect(screen.queryByRole("button", { name: "只用我的文案，檢查並確認" })).toBeNull();
  });
  it("F49-I14: with no candidates, the handoff panel says the origin-aware note, never 「請先同步本活動的原始結構」", async () => {
    const p = { ...placement(), confirmed_at: "2026-01-01" };
    vi.mocked(existingCampaigns).mockResolvedValue({ items: [], sources: [{ platform: "meta", label: "Meta", account_id: "act_1" }], next_cursor: null, job: null });
    vi.mocked(assetHandoff).mockResolvedValue({ original_copy: p.copy_fields, suggested_copy: {}, effective_copy: p.copy_fields, tracking_name: "MOS-p1-v1", notice: "內部確認不代表已上架", destination_entity_id: null, download_url: "/api/private", purpose: "產品介紹", start_date: null, end_date: null, bindings: [] });
    render(<AssetHandoffPanel brandId="b1" campaignId="c1" placement={p} readOnly={false} destinationsNote="這個活動還沒上架，平台上還沒有投放組；新廣告請到投放結構加" />);
    const source = await screen.findByLabelText("核對平台帳號");
    const check = screen.getByRole("button", {name: "重新讀回並核對廣告"});
    expect(check).toHaveProperty("disabled", true);
    expect(document.getElementById(check.getAttribute("aria-describedby")!)?.textContent).toBe("先選擇要核對的廣告");
    await userEvent.setup().clear(screen.getByLabelText("版本成效開始日"));
    const metrics = screen.getByRole("button", {name: "讀取版本成效"});
    expect(metrics).toHaveProperty("disabled", true);
    expect(document.getElementById(metrics.getAttribute("aria-describedby")!)?.textContent).toBe("先填寫開始日與結束日");
    await userEvent.setup().selectOptions(source, "0");
    expect(screen.getByText("尚無已載入候選；這個活動還沒上架，平台上還沒有投放組；新廣告請到投放結構加。")).toBeTruthy();
    expect(screen.queryByText(/請先同步本活動的原始結構/)).toBeNull();
  });
  it("separates platform existence from user-checked media and unknown attribution", async () => {
    const p = { ...placement(), confirmed_at: "2026-01-01" };
    vi.mocked(assetHandoff).mockResolvedValue({ original_copy: p.copy_fields, suggested_copy: {}, effective_copy: p.copy_fields, tracking_name: "MOS-p1-v1", notice: "內部確認不代表已上架", destination_entity_id: null, download_url: "/api/private", purpose: "產品介紹", start_date: null, end_date: null, bindings: [{ id: "b1", placement_revision: 1, existence_status: "platform_confirmed", evidence_level: "user_verified", stale_reason: null, valid_to: null, last_verified_at: "2026-01-01", native_id: "ad1" }] });
    render(<AssetHandoffPanel brandId="b1" campaignId="c1" placement={p} readOnly={false} />);
    expect(await screen.findByText(/平台已讀回廣告與父層關係/)).toBeTruthy(); expect(screen.getByText(/使用者已核對；平台尚未證明素材等價/)).toBeTruthy(); expect(screen.getByText(/需完整日期與連續版本證據/)).toBeTruthy();
  });
});
