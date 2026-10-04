import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import * as api from "@/lib/adsMaterialApi";
import { MaterialTasksPanel } from "./MaterialTasksPanel";

vi.mock("@/lib/auth", () => ({ getOrgId: () => "test_org", getAccessToken: async () => "test_token" }));
vi.mock("@/lib/adsMaterialApi", async original => ({ ...await original<typeof api>(), listMaterialTasks: vi.fn(), saveMaterialOperation: vi.fn(), materialOptions: vi.fn() }));
vi.mock("./UserAssetsLibrary", () => ({ CopyEditor: () => <p>文案編輯</p>, UserAssetsLibrary: () => <p>品牌原檔</p> }));
vi.mock("./AuthAssetMedia", () => ({ AuthAssetMedia: () => <p>原檔預覽</p> }));
const task: api.MaterialTask = { id: "task_a", campaign_id: "campaign_a", revision: 1, title: "使用已有成品", mode: "existing", instruction: "", copy_fields: {}, prompt: { source: "none" }, reference_asset_ids: [], review_id: null, recommendation_id: null, review_context: null, content_hash: "a".repeat(64), candidates: [], selected_candidate_id: null, placement_id: null, placement_revision: null, placement_current: null, pack_id: null, dispatch_status: "not_requested", history: [{ revision: 1, content_hash: "a", created_at: "2026-09-19" }], limitations: [], created_at: "2026-09-19", replaces: null, cancelled_at: null };
function page(brandId = "brand_a", query = "") { return <MemoryRouter initialEntries={[`/${query}`]}><MaterialTasksPanel brandId={brandId} campaignId="campaign_a" /></MemoryRouter>; }
beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); vi.mocked(api.listMaterialTasks).mockResolvedValue({ tasks: [] }); vi.mocked(api.materialOptions).mockResolvedValue({ options: [] }); });

const SOURCE_CARDS = ["使用已有成品", "回收外部生圖", "請工作台準備新圖"];

it("a draft campaign offers three sources, never 只準備新文案 (F35 ruling 3); a saved copy task still shows and opens", async () => {
  const user = userEvent.setup();
  const copyTask = { ...task, id: "task_copy", mode: "copy" as const, title: "只準備新文案" };
  vi.mocked(api.listMaterialTasks).mockResolvedValue({ tasks: [copyTask] });
  render(<MemoryRouter initialEntries={["/"]}><MaterialTasksPanel brandId="brand_a" campaignId="campaign_a" draft /></MemoryRouter>);
  expect(await screen.findByText("已保存的需求")).toBeTruthy();
  const cards = screen.getAllByRole("heading", { level: 3 }).map(h => h.textContent).filter(t => t !== "已保存的需求");
  expect(cards).toEqual(SOURCE_CARDS);
  const saved = screen.getByRole("button", { name: /只準備新文案 · 版本 1/ });
  await user.click(saved);
  expect(screen.getByRole("heading", { level: 3, name: "只準備新文案" })).toBeTruthy();
  expect(screen.getByText("圖片保持不變；在工作台整理新的文字方向。")).toBeTruthy();
});

it("without draft (a live campaign) all four sources show, 只準備新文案 included", async () => {
  render(page());
  await screen.findByRole("button", { name: /使用已有成品/ });
  const cards = screen.getAllByRole("heading", { level: 3 }).map(h => h.textContent);
  expect(cards).toEqual([...SOURCE_CARDS, "只準備新文案"]);
});

it("saves existing artwork without dispatching a generation", async () => {
  const user = userEvent.setup(); vi.mocked(api.saveMaterialOperation).mockResolvedValue({ task }); render(page());
  await user.click(await screen.findByRole("button", { name: /使用已有成品/ }));
  await user.click(screen.getByRole("button", { name: "保存素材需求" }));
  await screen.findByRole("button", { name: "上傳或選擇成品" });
  expect(api.saveMaterialOperation).toHaveBeenCalledTimes(1);
  expect(vi.mocked(api.saveMaterialOperation).mock.calls[0][0].body).toMatchObject({ mode: "existing", prompt: { source: "none" } });
  expect(screen.queryByRole("button", { name: "確認需求，交給工作台" })).toBeNull();
});

it("replays the same frozen operation after a lost response", async () => {
  const user = userEvent.setup(); vi.mocked(api.saveMaterialOperation).mockRejectedValueOnce(new TypeError("response lost")).mockResolvedValueOnce({ task }); render(page());
  await user.click(await screen.findByRole("button", { name: /使用已有成品/ })); await user.click(screen.getByRole("button", { name: "保存素材需求" }));
  await user.click(await screen.findByRole("button", { name: "核對同一次保存" }));
  await screen.findByRole("button", { name: "上傳或選擇成品" });
  const calls = vi.mocked(api.saveMaterialOperation).mock.calls;
  expect(calls[1][0]).toEqual(calls[0][0]); expect(sessionStorage.length).toBe(0);
});

it("keeps a saved operation scoped to its own brand on remount", async () => {
  const pending = { path: api.materialPath("brand_a", "campaign_a"), method: "POST", body: { operation_id: "pending_a", mode: "existing" } };
  sessionStorage.setItem("material-operation:test_org:brand_a:campaign_a", JSON.stringify(pending));
  const { rerender } = render(page()); await screen.findByRole("button", { name: "核對同一次保存" });
  rerender(page("brand_b")); await waitFor(() => expect(screen.queryByRole("button", { name: "核對同一次保存" })).toBeNull());
  expect(api.saveMaterialOperation).not.toHaveBeenCalled(); expect(sessionStorage.getItem("material-operation:test_org:brand_a:campaign_a")).not.toBeNull();
});

it("retains review provenance in the new material request", async () => {
  const user = userEvent.setup(); vi.mocked(api.saveMaterialOperation).mockResolvedValue({ task: { ...task, review_id: "review_a", recommendation_id: "rec_a" } }); render(page("brand_a", "?material_new=1&review=review_a&recommendation=rec_a"));
  await user.click(await screen.findByRole("button", { name: /回收外部生圖/ })); await user.click(screen.getByRole("button", { name: "保存素材需求" }));
  await waitFor(() => expect(api.saveMaterialOperation).toHaveBeenCalledOnce());
  expect(vi.mocked(api.saveMaterialOperation).mock.calls[0][0].body).toMatchObject({ review_id: "review_a", recommendation_id: "rec_a", mode: "external_image" });
});

it("serializes a selected workbench prompt without trusting echoed text", () => {
  expect(api.promptInput({ source: "workbench", text: "browser altered", set_id: "s", version_id: "v", card_index: 1 })).toEqual({ source: "workbench", set_id: "s", version_id: "v", card_index: 1 });
});

it("raises a one-click replace request and cancels by id without a request body", async () => {
  const replaced = { ...task, mode: "workbench_image" as const, title: "換掉：舊廣告", replaces: { entity_id: "aex_1", name: "舊廣告", thumbnail_url: null } };
  const fetchMock = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({ task: replaced }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: "material_task_in_use", message: "此素材需求已被核准的變更清單採用，不能取消。" } }), { status: 409 }));
  try {
    const { task: saved } = await api.createReplaceRequest("brand_a", "campaign_a", "aex_1", "op_1");
    expect(saved.replaces?.entity_id).toBe("aex_1");
    const [path, init] = fetchMock.mock.calls[0];
    expect(path).toBe(api.materialPath("brand_a", "campaign_a"));
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ operation_id: "op_1", replaces_entity_id: "aex_1" });
    await expect(api.cancelMaterialTask("brand_a", "campaign_a", "task_a")).rejects.toMatchObject({ status: 409, message: "此素材需求已被核准的變更清單採用，不能取消。" });
    expect(fetchMock.mock.calls[1][0]).toBe(`${api.materialPath("brand_a", "campaign_a")}/task_a/cancel`);
    expect(fetchMock.mock.calls[1][1]?.body).toBeUndefined();
  } finally { fetchMock.mockRestore(); }
});

it("a failed request list read is ReadFailed with 重試, and a new refreshKey re-reads the list (F30-I11)", async () => {
  const user = userEvent.setup();
  vi.mocked(api.listMaterialTasks).mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ tasks: [task] });
  const view = render(page());
  expect(await screen.findByText(/素材需求暫時讀不到/)).toBeTruthy();
  expect(screen.queryByRole("status")).toBeNull();
  await user.click(screen.getByRole("button", { name: "重試" }));
  expect(await screen.findByText("已保存的需求")).toBeTruthy();
  expect(screen.queryByText(/素材需求暫時讀不到/)).toBeNull();
  expect(api.listMaterialTasks).toHaveBeenCalledTimes(2);
  view.rerender(<MemoryRouter initialEntries={["/"]}><MaterialTasksPanel brandId="brand_a" campaignId="campaign_a" refreshKey={1} /></MemoryRouter>);
  await waitFor(() => expect(api.listMaterialTasks).toHaveBeenCalledTimes(3));
});

it("F49 Contract T: a hand-off left unknown prints the served state and offers 重新交給工作台 — the same dispatch call, never a disabled button", async () => {
  const user = userEvent.setup();
  const stuck = { ...task, id: "task_w", mode: "workbench_image" as const, title: "請工作台準備新圖", pack_id: "pack_1", dispatch_status: "unknown" as const, state_label: "交棒沒送出・可重試" };
  const queued = { ...stuck, dispatch_status: "queued" as const, state_label: "工作檯製作中" };
  vi.mocked(api.listMaterialTasks).mockResolvedValueOnce({ tasks: [stuck] }).mockResolvedValue({ tasks: [queued] });
  vi.mocked(api.saveMaterialOperation).mockResolvedValue({ task: queued });
  render(page());
  await user.click(await screen.findByRole("button", { name: /請工作台準備新圖 · 版本 1/ }));
  expect(screen.getByText("目前：交棒沒送出・可重試")).toBeTruthy();
  expect(screen.queryByText(/請先重新讀取/)).toBeNull();
  const retry = screen.getByRole("button", { name: "重新交給工作台" });
  expect(retry).toHaveProperty("disabled", false);
  await user.click(retry);
  await waitFor(() => expect(api.saveMaterialOperation).toHaveBeenCalledTimes(1));
  const call = vi.mocked(api.saveMaterialOperation).mock.calls[0][0];
  expect(call.path).toBe(`${api.materialPath("brand_a", "campaign_a")}/task_w/dispatch`);
  expect(call.body).toMatchObject({ expected_revision: 1, content_hash: stuck.content_hash });
  // Queued now: the request's served word, and the way to its pack.
  expect(await screen.findByText("目前：工作檯製作中")).toBeTruthy();
  expect(screen.getByRole("link", { name: "前往本次工作台任務" }).getAttribute("href")).toBe("/brands/brand_a/workbench/packs/pack_1");
});

it("F47-I06: 「新增素材需求」 shows only while an editor is open, and brings the request cards back with focus on the first", async () => {
  const user = userEvent.setup();
  render(page());
  await screen.findByRole("button", { name: /使用已有成品/ });
  expect(screen.queryByRole("button", { name: "新增素材需求" })).toBeNull(); // the cards are already all there is
  await user.click(screen.getByRole("button", { name: /使用已有成品/ }));
  await user.click(screen.getByRole("button", { name: "新增素材需求" }));
  const cards = screen.getByRole("group", { name: "選擇素材來源" });
  await waitFor(() => expect(cards.contains(document.activeElement)).toBe(true));
  expect(screen.queryByRole("button", { name: "新增素材需求" })).toBeNull();
});
