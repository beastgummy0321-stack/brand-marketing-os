/** F30-I11: the assets tab body (prototype `tabAssets()`) over real-shaped `GET …/slots` fixtures — a draft with
 * ready／missing／in-progress slots, a live campaign with a 「換掉這一則」 request, a request whose replaced ad was
 * deleted, an authenticated thumbnail, the slot upload and its next step, and the slots read failing on its own.
 * F40-I09 (prototype `#/assets`): the tab polls while a slot is 處理中 and stops when none is, a video-format slot asks
 * for a video and refuses a photo, and a thumbnail two slots share prints 「同一張圖，文案不同」 with 換一張. */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CampaignDetail } from "@/lib/adsApi";
import { cancelMaterialTask, MaterialRequestError } from "@/lib/adsMaterialApi";
import { chooseSlotCopy, fetchSlotThumbnail, getSlotCopyOptions, getSlots, uploadIntoSlot, type CampaignSlots, type Slot } from "@/lib/adsSlotsApi";
import { AssetApiError, createUploadBatch, putUpload, type Placement } from "@/lib/adsUserAssetsApi";
import { AssetsBody } from "./AssetsBody";

vi.mock("@/lib/adsSlotsApi", async (original) => ({
  ...await original<typeof import("@/lib/adsSlotsApi")>(),
  getSlots: vi.fn(), uploadIntoSlot: vi.fn(), fetchSlotThumbnail: vi.fn(), getSlotCopyOptions: vi.fn(), chooseSlotCopy: vi.fn(),
}));
vi.mock("@/lib/adsMaterialApi", async (original) => ({ ...await original<typeof import("@/lib/adsMaterialApi")>(), cancelMaterialTask: vi.fn() }));
vi.mock("@/lib/adsUserAssetsApi", async (original) => ({
  ...await original<typeof import("@/lib/adsUserAssetsApi")>(), createUploadBatch: vi.fn(), putUpload: vi.fn(),
}));

const IMG = "https://scontent.example/creative/2.jpg";
const AUTH = "/api/ads/brands/brd_1/user-assets/uas_1/thumbnail";

function slot(overrides: Partial<Slot>): Slot {
  return { ad_id: "ad_x", entity_id: null, name: "廣告", state: "ready", thumbnail_url: IMG, confirmed: true, replace_task_id: null, copy: null, workbench_href: null, ...overrides };
}

function slots(overrides: Partial<CampaignSlots> = {}): CampaignSlots {
  const groups = overrides.groups ?? [
    { group_id: "adg_a", name: "A・廣泛受眾", slots: [
      slot({ ad_id: "ad_a1", name: "晨光隨行杯・日常出發（秋季新色）" }),
      slot({ ad_id: "ad_a2", name: "通勤情境單圖・好攜帶，走到哪都適合（最多數量 1150706）" }),
      slot({ ad_id: "ad_a3", name: "辦公室一角・質感桌面", state: "in_progress", confirmed: false, thumbnail_url: null }),
      slot({ ad_id: "ad_a4", name: "早晨第一口・單圖", state: "missing", confirmed: false, thumbnail_url: null }),
    ] },
    { group_id: "adg_b", name: "B・再行銷 30 天", slots: [slot({ ad_id: "ad_b1", name: "再行銷・兩入組 NT$1,680 免運" })] },
  ];
  const flat = groups.flatMap((g) => g.slots);
  return {
    ready: flat.filter((s) => s.state === "ready").length, total: flat.length, groups,
    requests: [], requests_truncated: false, ...overrides,
  };
}

function campaign(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    id: "cmp_1", name: "秋季新色預購", goal_text: "", objective: "購買",
    cap: { value: null, basis: null, own_value: null, break_even: null, price: null, product_id: null, result_kind: "purchase", result_label: "購買", missing: ["product"], revision: 0 },
    start_date: "2026-10-01", end_date: "2026-10-31", status: "draft", budget_planned: null, budget_scenario: null,
    budget_basis_json: {}, budget_total: null, context_json: {}, constraints_json: {}, verdict: null, verdict_json: {},
    closed_at: null, created_by: null, created_at: "2026-09-20T00:00:00Z", groups: [], actions: [],
    outcome: { spend: null, purchases: null, revenue: null }, asset_readiness: { ready_count: 0, total: 0, pack_id: "pk_9" },
    external_id: null, external_name: null, external_status: null, local_state: "unbound", bound_at: null,
    ...overrides,
  };
}

const placement = (overrides: Partial<Placement> = {}): Placement => ({
  id: "pl_1", revision: 1, is_current: true, asset_id: "uas_2", filename: "morning.png", mime_type: "image/png",
  asset_status: "ready", asset_error: null, copy_fields: {}, suggested_copy: {}, purpose: null, destination_entity_id: null,
  start_date: null, end_date: null, status: "pending", pending_reason: "請核對文案、用途與媒體後確認安排", required: true,
  confirmed_at: null, suggestion_batch_id: null, ...overrides,
});

function renderBody(c = campaign(), extra: Partial<Parameters<typeof AssetsBody>[0]> = {}) {
  const props = {
    brandId: "brd_1", campaign: c, refreshKey: 0, advanced: <p>進階內容</p>,
    onPlacementChanged: vi.fn(), onOpenPlacements: vi.fn(), onRequestsChanged: vi.fn(), ...extra,
  };
  const view = render(<MemoryRouter><AssetsBody {...props} /></MemoryRouter>);
  return { ...view, props };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getSlots).mockResolvedValue(slots());
});

describe("AssetsBody — the slots card", () => {
  it("draft: x／y 格已備妥, per-group counts, a chip per slot state, the reserved seat per group", async () => {
    renderBody();
    expect(await screen.findByRole("heading", { name: "3／5 格已備妥" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "3／5 格已備妥" })).toBeTruthy();
    const a = screen.getByRole("list", { name: "A・廣泛受眾" });
    expect(within(a).getAllByText("已確認")).toHaveLength(2);
    expect(within(a).getByText("處理中")).toBeTruthy();
    expect(within(a).getByText("缺 1 則")).toBeTruthy();
    expect(screen.getByText("2／4")).toBeTruthy();
    expect(screen.getByText("1／1")).toBeTruthy();
    expect(screen.getAllByText("站內出圖")).toHaveLength(2);
    // The reserved seat is not a control.
    expect(screen.queryByRole("button", { name: /站內出圖/ })).toBeNull();
    expect(screen.getByRole("link", { name: "到素材工作檯" }).getAttribute("href")).toBe("/brands/brd_1/workbench/packs/pk_9");
    expect(within(a).getByRole("link", { name: "從素材工作檯" }).getAttribute("href")).toBe("/brands/brd_1/workbench/packs/pk_9");
  });

  it("draft bar: 確認上架清單 counts ready slots only, goes to …/publish, and says the missing ones are not built", async () => {
    renderBody();
    const go = await screen.findByRole("link", { name: "確認上架清單（3 則） →" });
    expect(go.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/publish");
    expect(screen.getByText("缺圖的那 2 則先不建立，不會花到錢；補上圖後再加上去")).toBeTruthy();
    expect(screen.getByRole("link", { name: "← 總覽" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1");
  });

  it("draft with nothing ready: the primary action is disabled, never a link", async () => {
    vi.mocked(getSlots).mockResolvedValue(slots({ groups: [{ group_id: "g", name: "A", slots: [slot({ state: "missing", thumbnail_url: null, confirmed: false })] }] }));
    renderBody();
    const button = await screen.findByRole("button", { name: "確認上架清單（0 則） →" });
    expect(button).toHaveProperty("disabled", true);
    expect(screen.queryByRole("link", { name: /確認上架清單/ })).toBeNull();
  });

  it("live campaign: no publish action and no 缺圖 hint", async () => {
    renderBody(campaign({ status: "live" }));
    await screen.findByRole("heading", { name: "3／5 格已備妥" });
    expect(screen.queryByText(/確認上架清單/)).toBeNull();
    expect(screen.queryByText(/缺圖的那/)).toBeNull();
  });

  it("an empty plan says so instead of 0／0", async () => {
    vi.mocked(getSlots).mockResolvedValue(slots({ groups: [] }));
    renderBody();
    expect(await screen.findByText("還沒有要放素材的格子")).toBeTruthy();
    expect(screen.queryByText("0／0 格已備妥")).toBeNull();
  });

  it("a failed slots read is ReadFailed with 重試; the folded panels stay; 重試 re-reads", async () => {
    const user = userEvent.setup();
    vi.mocked(getSlots).mockRejectedValueOnce(new Error("連線逾時")).mockResolvedValue(slots());
    renderBody();
    expect(await screen.findByText(/素材格子讀不到：連線逾時/)).toBeTruthy();
    expect(screen.getByText("進階內容")).toBeTruthy();
    // Unknown count: the draft bar still leads to the publish page, without inventing a number.
    expect(screen.getByRole("link", { name: "確認上架清單 →" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByRole("heading", { name: "3／5 格已備妥" })).toBeTruthy();
  });

  it("a new refreshKey re-reads in place, keeping the last slots on screen", async () => {
    const { rerender, props } = renderBody();
    await screen.findByRole("heading", { name: "3／5 格已備妥" });
    vi.mocked(getSlots).mockResolvedValue(slots({ groups: [{ group_id: "g", name: "A", slots: [slot({})] }] }));
    rerender(<MemoryRouter><AssetsBody {...props} refreshKey={1} /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "3／5 格已備妥" })).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "1／1 格已備妥" })).toBeTruthy();
  });
});

describe("AssetsBody — thumbnails", () => {
  const created: string[] = [];
  beforeEach(() => {
    created.length = 0;
    URL.createObjectURL = vi.fn(() => { const url = `blob:thumb-${created.length}`; created.push(url); return url; });
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => { vi.mocked(fetchSlotThumbnail).mockReset(); });

  it("a user-uploaded thumbnail is fetched with auth and shown from an object URL, never as a bare src", async () => {
    vi.mocked(fetchSlotThumbnail).mockResolvedValue(new Blob(["png"], { type: "image/png" }));
    vi.mocked(getSlots).mockResolvedValue(slots({ groups: [{ group_id: "g", name: "A", slots: [
      slot({ ad_id: "ad_1", name: "自帶一", thumbnail_url: AUTH }), slot({ ad_id: "ad_2", name: "平台二", thumbnail_url: IMG }),
    ] }] }));
    const { container, unmount } = renderBody();
    await waitFor(() => expect(container.querySelector('img[src="blob:thumb-0"]')).toBeTruthy());
    expect(fetchSlotThumbnail).toHaveBeenCalledWith(AUTH, expect.any(AbortSignal));
    expect(container.querySelector(`img[src="${AUTH}"]`)).toBeNull();
    expect(container.querySelector(`img[src="${IMG}"]`)).toBeTruthy();
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:thumb-0");
  });

  it("a thumbnail that cannot be fetched is the neutral tile; the grid still renders", async () => {
    vi.mocked(fetchSlotThumbnail).mockRejectedValue(new Error("404"));
    vi.mocked(getSlots).mockResolvedValue(slots({ groups: [{ group_id: "g", name: "A", slots: [slot({ name: "自帶一", thumbnail_url: AUTH })] }] }));
    const { container } = renderBody();
    expect(await screen.findByText("自帶一")).toBeTruthy();
    await waitFor(() => expect(fetchSlotThumbnail).toHaveBeenCalled());
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("AssetsBody — 素材需求 card", () => {
  const request = { task_id: "mt_1", replaces: { entity_id: "aex_2", name: "晨光隨行杯・隨時有你｜好攜帶", thumbnail_url: IMG }, created_at: "2026-09-24T04:00:00Z", state_label: "等素材工作檯" as const };
  const live = () => slots({
    groups: [{ group_id: "g", name: "A・廣泛受眾", slots: [slot({ ad_id: "ad_2", entity_id: "aex_2", name: "晨光隨行杯・隨時有你｜好攜帶", replace_task_id: "mt_1" })] }],
    requests: [request, { task_id: "mt_2", replaces: { entity_id: "aex_gone", name: null, thumbnail_url: null }, created_at: "2026-09-20T04:00:00Z", state_label: "有候選圖" }],
  });

  it("only with requests: the replaced ad, its state label with the date, and 要換掉 on its slot", async () => {
    vi.mocked(getSlots).mockResolvedValue(live());
    renderBody(campaign({ status: "live" }));
    const card = await screen.findByRole("region", { name: "素材需求" });
    expect(within(card).getByRole("heading", { name: "素材需求 2 張" })).toBeTruthy();
    expect(within(card).getByText("等素材工作檯・09/24")).toBeTruthy();
    expect(within(card).getByText("有候選圖・09/20")).toBeTruthy();
    // A deleted replaced ad reads as unknown, never blank.
    expect(within(card).getByText("名稱讀不到（這則廣告可能已從平台刪除）")).toBeTruthy();
    expect(within(screen.getByRole("list", { name: "A・廣泛受眾" })).getByText("要換掉")).toBeTruthy();
  });

  it("no card without requests", async () => {
    renderBody();
    await screen.findByRole("heading", { name: "3／5 格已備妥" });
    expect(screen.queryByRole("region", { name: "素材需求" })).toBeNull();
  });

  it("取消需求 cancels by task id and asks for a re-read", async () => {
    const user = userEvent.setup();
    vi.mocked(getSlots).mockResolvedValue(live());
    vi.mocked(cancelMaterialTask).mockResolvedValue({ task: {} as never });
    const { props } = renderBody(campaign({ status: "live" }));
    const card = await screen.findByRole("region", { name: "素材需求" });
    await user.click(within(card).getAllByRole("button", { name: "取消需求" })[0]);
    expect(cancelMaterialTask).toHaveBeenCalledWith("brd_1", "cmp_1", "mt_1");
    expect(props.onRequestsChanged).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["material_task_in_use", "此素材需求已被核准的變更清單採用，不能取消。"],
    ["material_unavailable", "找不到此品牌活動的素材任務或版本。"],
  ])("a 409 (%s) says why under the row and re-reads", async (_code, message) => {
    const user = userEvent.setup();
    vi.mocked(getSlots).mockResolvedValue(live());
    vi.mocked(cancelMaterialTask).mockRejectedValue(new MaterialRequestError(message, 409));
    const { props } = renderBody(campaign({ status: "live" }));
    const card = await screen.findByRole("region", { name: "素材需求" });
    await user.click(within(card).getAllByRole("button", { name: "取消需求" })[0]);
    expect(await within(card).findByRole("alert")).toHaveProperty("textContent", `沒有取消：${message}`);
    expect(props.onRequestsChanged).toHaveBeenCalledTimes(1);
  });
});

describe("AssetsBody — uploading into a slot", () => {
  function pick(name: string) {
    const file = new File(["png"], "morning.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText(`選擇「${name}」的檔案`), { target: { files: [file] } });
    return file;
  }

  it("uploads the file, binds it to the planned ad, shows the returned slots and the next step from the placement", async () => {
    const user = userEvent.setup();
    vi.mocked(createUploadBatch).mockResolvedValue({ batch: { id: "ub_1", uploads: [{ id: "up_1", batch_id: "ub_1", filename: "morning.png", expected_size: 3, status: "pending", error: null, asset_id: null, copy_fields: {} }] } });
    vi.mocked(putUpload).mockResolvedValue({ upload: { id: "up_1", batch_id: "ub_1", filename: "morning.png", expected_size: 3, status: "complete", error: null, asset_id: "uas_2", copy_fields: {} } });
    const after = slots();
    after.groups[0].slots[3] = slot({ ad_id: "ad_a4", name: "早晨第一口・單圖", state: "in_progress", confirmed: false, thumbnail_url: null });
    vi.mocked(uploadIntoSlot).mockResolvedValue({ placement: placement(), slots: after });
    const { props } = renderBody();
    await screen.findByRole("heading", { name: "3／5 格已備妥" });
    const file = pick("早晨第一口・單圖");

    const next = await screen.findByRole("status");
    expect(next.textContent).toContain("已放進「早晨第一口・單圖」這一格；請核對文案、用途與媒體後確認安排。");
    expect(createUploadBatch).toHaveBeenCalledWith("brd_1", [{ filename: "morning.png", size: 3, content_type: "image/png", copy_fields: {} }]);
    expect(putUpload).toHaveBeenCalledWith("brd_1", "up_1", file);
    expect(uploadIntoSlot).toHaveBeenCalledWith("brd_1", "cmp_1", "ad_a4", { upload_id: "up_1" });
    // The slot is in progress, not ready: the count did not move and the missing tile is gone.
    expect(screen.getByRole("heading", { name: "3／5 格已備妥" })).toBeTruthy();
    expect(screen.queryByText("缺 1 則")).toBeNull();
    expect(props.onPlacementChanged).toHaveBeenCalledTimes(1);
    await user.click(within(next).getByRole("button", { name: "去確認安排 →" }));
    expect(props.onOpenPlacements).toHaveBeenCalledTimes(1);
  });

  it("a deduplicated upload skips the byte transfer; a confirmed placement needs no next step", async () => {
    vi.mocked(createUploadBatch).mockResolvedValue({ batch: { id: "ub_1", uploads: [{ id: "up_1", batch_id: "ub_1", filename: "morning.png", expected_size: 3, status: "complete", error: null, asset_id: "uas_2", copy_fields: {}, deduplicated: true }] } });
    vi.mocked(uploadIntoSlot).mockResolvedValue({ placement: placement({ confirmed_at: "2026-09-25T02:00:00Z" }), slots: slots() });
    renderBody();
    await screen.findByRole("heading", { name: "3／5 格已備妥" });
    pick("早晨第一口・單圖");
    const next = await screen.findByRole("status");
    expect(next.textContent).toBe("已放進「早晨第一口・單圖」這一格，文案跟著帶進去了，這一格備妥。");
    expect(putUpload).not.toHaveBeenCalled();
    expect(within(next).queryByRole("button")).toBeNull();
  });

  it("a refused upload says why and leaves the slot missing", async () => {
    vi.mocked(createUploadBatch).mockResolvedValue({ batch: { id: "ub_1", uploads: [{ id: "up_1", batch_id: "ub_1", filename: "morning.png", expected_size: 3, status: "complete", error: null, asset_id: "uas_2", copy_fields: {} }] } });
    vi.mocked(uploadIntoSlot).mockRejectedValue(new Error("首次投放清單已核准，不能改寫原交接素材；請先處理原核准清單。"));
    const { props } = renderBody();
    await screen.findByRole("heading", { name: "3／5 格已備妥" });
    pick("早晨第一口・單圖");
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "「早晨第一口・單圖」沒有上傳成功：首次投放清單已核准，不能改寫原交接素材；請先處理原核准清單。");
    expect(screen.getByText("缺 1 則")).toBeTruthy();
    expect(props.onPlacementChanged).not.toHaveBeenCalled();
  });

  it("an imported campaign's platform ads take no upload", async () => {
    vi.mocked(getSlots).mockResolvedValue(slots({ groups: [{ group_id: null, name: "Advantage+ 購物・全台", slots: [
      slot({ ad_id: null, entity_id: "aex_1", name: "UGC_開箱_v3_1080x1350" }),
    ] }] }));
    renderBody(campaign({ origin: "imported", status: "live" }));
    expect(await screen.findByRole("heading", { name: "1／1 格已備妥" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /上傳/ })).toBeNull();
    expect(screen.queryByText(/確認上架清單/)).toBeNull();
  });
});

describe("AssetsBody — two halves (F35 Contract T)", () => {
  const SET_HREF = "/app/brands/brd_1/workbench/packs/pk_9/sets/wb_set_1";
  const copy1 = { source: "workbench" as const, label: "工作檯第 1 版", headline: "讀書工作通勤，少一個步驟", body: "免配水、免拆包裝，一顆 50 mg，思緒不被打斷。", description: null };
  const copy2 = { source: "placement" as const, label: "已確認", headline: "通勤路上，一顆就好", body: "捷運上不用找水，包裝單手撕開。", description: "免配水" };
  /** The realistic draft: one copy-only, one ready, one image-only, one missing (the drill-6 names, longest first). */
  const twoHalves = () => slots({ groups: [
    { group_id: "g1", name: "再行銷興趣承接（看過商品頁 30 天）", slots: [
      slot({ ad_id: "a1", name: "看過還在猶豫的你重新確認購買理由（再行銷單圖）", state: "copy_only", confirmed: false, thumbnail_url: null, copy: copy1, workbench_href: SET_HREF }),
    ] },
    { group_id: "g2", name: "探索受眾與訊息組合", slots: [
      slot({ ad_id: "a2", name: "用日常情境示範・通勤路上一顆", state: "ready", copy: copy2, workbench_href: SET_HREF }),
      slot({ ad_id: "a3", name: "真實使用感受・午後三點的第二口", state: "missing", confirmed: false, thumbnail_url: null, workbench_href: SET_HREF }),
    ] },
    { group_id: "g3", name: "新客觸及與購買", slots: [
      slot({ ad_id: "a4", name: "新客觸及・體驗包 3 入免運（後來加的廣告，沒有工作檯版本）", state: "image_only", confirmed: false, thumbnail_url: IMG, copy: null, workbench_href: null }),
    ] },
  ] });
  const options = () => ({ options: [
    { set_id: "wb_set_1", version_id: "wo_1", label: "超能特惠組 · 版本 1", copy_fields: { headline: "讀書工作通勤，少一個步驟", body: "免配水、免拆包裝，一顆 50 mg，思緒不被打斷。" } },
    { set_id: "wb_set_3", version_id: "wo_3", label: "新客觸及與購買 · 版本 1", copy_fields: { headline: "第一次試，3 入免運", body: "體驗包 3 入，不喜歡免費退。" } },
  ] });
  const tile = (name: string) => screen.getByText(name).closest("[data-slot=slot-tile]") as HTMLElement;
  const NAME_COPY_ONLY = "看過還在猶豫的你重新確認購買理由（再行銷單圖）";
  const NAME_IMAGE_ONLY = "新客觸及・體驗包 3 入免運（後來加的廣告，沒有工作檯版本）";

  it("the four states: their chips, the image half, the copy half and the dashed halves", async () => {
    vi.mocked(getSlots).mockResolvedValue(twoHalves());
    renderBody();
    await screen.findByRole("heading", { name: "1／4 格已備妥" });
    const copyOnly = tile(NAME_COPY_ONLY);
    expect(copyOnly.dataset.variant).toBe("copy-only");
    expect(within(copyOnly).getByText("有文案，缺圖")).toBeTruthy();
    expect(within(copyOnly).getByText("缺圖")).toBeTruthy();
    expect(within(copyOnly).getByRole("button", { name: `上傳：${NAME_COPY_ONLY}` })).toBeTruthy();
    expect(within(copyOnly).getByText(/文案 · 工作檯第 1 版/)).toBeTruthy();
    expect(within(copyOnly).getByText(/^讀書工作通勤，少一個步驟\s免配水、免拆包裝，一顆 50 mg，思緒不被打斷。$/)).toBeTruthy();
    expect(within(copyOnly).queryByRole("button", { name: /選一版文案/ })).toBeNull();

    const ready = tile("用日常情境示範・通勤路上一顆");
    expect(ready.dataset.variant).toBe("ready");
    expect(within(ready).getByText("已確認", { selector: "[data-slot=chip]" })).toBeTruthy();
    expect(within(ready).getByText(/文案 · 已確認/)).toBeTruthy();
    expect(within(ready).getByText(/^通勤路上，一顆就好\s捷運上不用找水，包裝單手撕開。$/)).toBeTruthy();
    expect(ready.querySelector(`img[src="${IMG}"]`)).toBeTruthy();

    const imageOnly = tile(NAME_IMAGE_ONLY);
    expect(imageOnly.dataset.variant).toBe("image-only");
    expect(within(imageOnly).getByText("有圖，缺文案")).toBeTruthy();
    expect(within(imageOnly).getByText("缺文案")).toBeTruthy();
    expect(within(imageOnly).getByRole("button", { name: `選一版文案：${NAME_IMAGE_ONLY}` })).toBeTruthy();
    expect(imageOnly.querySelector(`img[src="${IMG}"]`)).toBeTruthy();
    expect(within(imageOnly).queryByRole("button", { name: /上傳/ })).toBeNull();

    const missing = screen.getByText("缺 1 則").closest("[data-slot=slot-tile]") as HTMLElement;
    expect(missing.dataset.variant).toBe("missing");
    // The missing tile's 從素材工作檯 goes to the ad's own set when it has one (the /app prefix stripped for the router).
    expect(within(missing).getByRole("link", { name: "從素材工作檯" }).getAttribute("href")).toBe("/brands/brd_1/workbench/packs/pk_9/sets/wb_set_1");
    // Progress: only the ready slot is ok.
    expect(screen.getByRole("img", { name: "1／4 格已備妥" }).querySelectorAll("[data-state=ok]").length).toBe(1);
  });

  it("看圖片提示詞 on a copy-only tile links to the ad's workbench set, and is absent when the ad has no set", async () => {
    const data = twoHalves();
    data.groups[0].slots.push(slot({ ad_id: "a5", name: "沒有集合的文案", state: "copy_only", confirmed: false, thumbnail_url: null, copy: copy1, workbench_href: null }));
    data.total = 5;
    vi.mocked(getSlots).mockResolvedValue(data);
    renderBody();
    await screen.findByRole("heading", { name: "1／5 格已備妥" });
    expect(within(tile(NAME_COPY_ONLY)).getByRole("link", { name: "看圖片提示詞" }).getAttribute("href")).toBe("/brands/brd_1/workbench/packs/pk_9/sets/wb_set_1");
    expect(within(tile("沒有集合的文案")).queryByRole("link", { name: "看圖片提示詞" })).toBeNull();
  });

  function pickFile(name: string) {
    const file = new File(["png"], "morning.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText(`選擇「${name}」的檔案`), { target: { files: [file] } });
    return file;
  }
  const completeBatch = () => ({ batch: { id: "ub_1", uploads: [{ id: "up_1", batch_id: "ub_1", filename: "morning.png", expected_size: 3, status: "complete" as const, error: null, asset_id: "uas_2", copy_fields: {} }] } });

  it("an upload into a copy-only slot sends no copy_fields; the confirmed placement makes the slot ready with no next step", async () => {
    vi.mocked(getSlots).mockResolvedValue(twoHalves());
    vi.mocked(createUploadBatch).mockResolvedValue(completeBatch());
    const after = twoHalves();
    after.groups[0].slots[0] = slot({ ad_id: "a1", name: NAME_COPY_ONLY, state: "ready", thumbnail_url: IMG, copy: { ...copy1, source: "placement", label: "已確認" }, workbench_href: SET_HREF });
    after.ready = 2;
    vi.mocked(uploadIntoSlot).mockResolvedValue({ placement: placement({ confirmed_at: "2026-09-28T02:00:00Z", purpose: NAME_COPY_ONLY }), slots: after });
    const { props } = renderBody();
    await screen.findByRole("heading", { name: "1／4 格已備妥" });
    pickFile(NAME_COPY_ONLY);
    const next = await screen.findByRole("status");
    expect(next.textContent).toBe(`已放進「${NAME_COPY_ONLY}」這一格，文案跟著帶進去了，這一格備妥。`);
    expect(within(next).queryByRole("button")).toBeNull();
    expect(uploadIntoSlot).toHaveBeenCalledWith("brd_1", "cmp_1", "a1", { upload_id: "up_1" });
    expect(screen.getByRole("heading", { name: "2／4 格已備妥" })).toBeTruthy();
    expect(tile(NAME_COPY_ONLY).dataset.variant).toBe("ready");
    expect(props.onPlacementChanged).toHaveBeenCalledTimes(1);
  });

  it("an upload into an ad without copy comes back image-only: the line says to pick a version, no next-step button", async () => {
    vi.mocked(getSlots).mockResolvedValue(twoHalves());
    vi.mocked(createUploadBatch).mockResolvedValue(completeBatch());
    const after = twoHalves();
    after.groups[1].slots[1] = slot({ ad_id: "a3", name: "真實使用感受・午後三點的第二口", state: "image_only", confirmed: false, thumbnail_url: IMG, workbench_href: SET_HREF });
    vi.mocked(uploadIntoSlot).mockResolvedValue({ placement: placement({ pending_reason: "文案缺少標題與內文" }), slots: after });
    renderBody();
    await screen.findByRole("heading", { name: "1／4 格已備妥" });
    pickFile("真實使用感受・午後三點的第二口");
    const next = await screen.findByRole("status");
    expect(next.textContent).toBe("已放進「真實使用感受・午後三點的第二口」這一格；還缺文案，選一版就備妥。");
    expect(within(next).queryByRole("button")).toBeNull();
    expect(within(tile("真實使用感受・午後三點的第二口")).getByRole("button", { name: /選一版文案/ })).toBeTruthy();
  });

  it("選一版文案 opens the picker over the workbench versions; choosing writes the version and renders the returned slots", async () => {
    const user = userEvent.setup();
    vi.mocked(getSlots).mockResolvedValue(twoHalves());
    vi.mocked(getSlotCopyOptions).mockResolvedValue(options());
    const after = twoHalves();
    after.groups[2].slots[0] = slot({ ad_id: "a4", name: NAME_IMAGE_ONLY, state: "ready", thumbnail_url: IMG, copy: { source: "placement", label: "已確認", headline: "第一次試，3 入免運", body: "體驗包 3 入，不喜歡免費退。", description: null } });
    after.ready = 2;
    vi.mocked(chooseSlotCopy).mockResolvedValue({ placement: placement({ confirmed_at: "2026-09-28T02:00:00Z" }), slots: after });
    const { props } = renderBody();
    await screen.findByRole("heading", { name: "1／4 格已備妥" });
    await user.click(screen.getByRole("button", { name: /選一版文案/ }));
    const dialog = await screen.findByRole("dialog", { name: `選一版文案放進「${NAME_IMAGE_ONLY}」` });
    expect(getSlotCopyOptions).toHaveBeenCalledWith("brd_1", "cmp_1", expect.any(AbortSignal));
    const list = await within(dialog).findByRole("list", { name: "文案版本" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      "超能特惠組 · 版本 1讀書工作通勤，少一個步驟　免配水、免拆包裝，一顆 50 mg，思緒不被打斷。",
      "新客觸及與購買 · 版本 1第一次試，3 入免運　體驗包 3 入，不喜歡免費退。",
    ]);
    // Focus lands on the first option.
    expect(document.activeElement).toBe(rows[0]);
    await user.click(rows[1]);
    expect(chooseSlotCopy).toHaveBeenCalledWith("brd_1", "cmp_1", "a4", { set_id: "wb_set_3", version_id: "wo_3" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("heading", { name: "2／4 格已備妥" })).toBeTruthy();
    expect(tile(NAME_IMAGE_ONLY).dataset.variant).toBe("ready");
    expect(screen.getByRole("status").textContent).toBe("文案已放進這一格，備妥。");
    expect(props.onPlacementChanged).toHaveBeenCalledTimes(1);
  });

  it("a 409 from the choice stays inside the picker with its message; Escape closes it", async () => {
    const user = userEvent.setup();
    vi.mocked(getSlots).mockResolvedValue(twoHalves());
    vi.mocked(getSlotCopyOptions).mockResolvedValue(options());
    vi.mocked(chooseSlotCopy).mockRejectedValue(new AssetApiError("這一格還沒有圖，先上傳圖再選文案。", 409));
    renderBody();
    await screen.findByRole("heading", { name: "1／4 格已備妥" });
    await user.click(screen.getByRole("button", { name: /選一版文案/ }));
    const dialog = await screen.findByRole("dialog");
    await user.click((await within(dialog).findAllByRole("listitem"))[0]);
    expect(await within(dialog).findByRole("alert")).toHaveProperty("textContent", "沒有放進去：這一格還沒有圖，先上傳圖再選文案。");
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("a failed options read is ReadFailed inside the picker, with 重試", async () => {
    const user = userEvent.setup();
    vi.mocked(getSlots).mockResolvedValue(twoHalves());
    vi.mocked(getSlotCopyOptions).mockRejectedValueOnce(new Error("連線逾時")).mockResolvedValue(options());
    renderBody();
    await screen.findByRole("heading", { name: "1／4 格已備妥" });
    await user.click(screen.getByRole("button", { name: /選一版文案/ }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("文案版本讀不到：連線逾時")).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: "重試" }));
    expect(await within(dialog).findByRole("list", { name: "文案版本" })).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: "取消" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("AssetsBody — F40-I09: the tab updates itself and says what each slot needs (prototype #/assets)", () => {
  const P1 = "/api/ads/brands/brd_1/user-assets/uas_11/thumbnail";
  const P2 = "/api/ads/brands/brd_1/user-assets/uas_12/thumbnail";
  const copyA = { source: "placement" as const, label: "已確認", headline: "練完就補一顆", body: "忙到沒空吃飯也不怕", description: null };
  const copyB = { source: "placement" as const, label: "已確認", headline: "捷運上的 30 秒", body: "把今天的維他命補齊", description: null };
  const copyC = { source: "workbench" as const, label: "工作檯第 1 版", headline: "讀到凌晨一點", body: "讓軟糖陪你撐完最後一章", description: null };
  /** The prototype's four tiles: one 處理中, one sharing its photo with the first, one video-format, one ready. */
  const fourTiles = (first: Slot["state"] = "in_progress") => slots({ groups: [
    { group_id: "g_new", name: "新客", slots: [
      slot({ ad_id: "a1", name: "運動後與忙碌日常", state: first, confirmed: first === "ready", thumbnail_url: P1, copy: copyA, format_key: "single_image" }),
      slot({ ad_id: "a2", name: "早晨通勤", state: "ready", thumbnail_url: P1, copy: copyB, format_key: "single_image" }),
      slot({ ad_id: "a3", name: "深夜讀書", state: "copy_only", confirmed: false, thumbnail_url: null, copy: copyC, format_key: "video" }),
      slot({ ad_id: "a4", name: "上班日午休", state: "ready", thumbnail_url: P2, copy: copyB, format_key: "single_image" }),
    ] },
  ] });
  const tile = (name: string) => screen.getByText(name).closest("[data-slot=slot-tile]") as HTMLElement;

  beforeEach(() => { vi.mocked(fetchSlotThumbnail).mockResolvedValue(new Blob(["png"])); });
  afterEach(() => { vi.useRealTimers(); });

  it("polls every 3 s while a slot is 處理中, the tile says so, and the poll flips it to 已確認 and stops", async () => {
    vi.useFakeTimers();
    vi.mocked(getSlots).mockResolvedValueOnce(fourTiles("in_progress")).mockResolvedValueOnce(fourTiles("in_progress")).mockResolvedValue(fourTiles("ready"));
    const view = renderBody();
    await act(async () => {});
    expect(screen.getByRole("heading", { name: "2／4 格已備妥" })).toBeTruthy();
    const running = tile("運動後與忙碌日常");
    expect(within(running).getByText("處理中")).toBeTruthy();
    expect(within(running).getByText("處理中・自動更新，不用重整")).toBeTruthy();
    // No caption on the tile still being processed, even though it shares its photo.
    expect(within(running).queryByText("同一張圖，文案不同")).toBeNull();
    expect(getSlots).toHaveBeenCalledTimes(1);

    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(getSlots).toHaveBeenCalledTimes(2);
    expect(within(tile("運動後與忙碌日常")).getByText("處理中・自動更新，不用重整")).toBeTruthy();

    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(getSlots).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("heading", { name: "3／4 格已備妥" })).toBeTruthy();
    const done = tile("運動後與忙碌日常");
    expect(within(done).getByText("已確認・剛處理好")).toBeTruthy();
    expect(within(done).queryByText("處理中・自動更新，不用重整")).toBeNull();

    // Nothing is in progress any more: the interval is gone.
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(getSlots).toHaveBeenCalledTimes(3);
    view.unmount();
  });

  it("unmounting while a slot is 處理中 clears the poll", async () => {
    vi.useFakeTimers();
    vi.mocked(getSlots).mockResolvedValue(fourTiles("in_progress"));
    const view = renderBody();
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(getSlots).toHaveBeenCalledTimes(2);
    view.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(getSlots).toHaveBeenCalledTimes(2);
  });

  it("a video-format slot asks for a video script, offers 上傳影片 instead of 上傳, and refuses a photo before any upload", async () => {
    vi.mocked(getSlots).mockResolvedValue(fourTiles("ready"));
    renderBody();
    await screen.findByRole("heading", { name: "3／4 格已備妥" });
    const video = tile("深夜讀書");
    expect(within(video).getByText("這格要影片腳本，照片不算")).toBeTruthy();
    expect(within(video).getByText("缺影片")).toBeTruthy();
    expect(within(video).getByRole("button", { name: "上傳影片：深夜讀書" })).toBeTruthy();
    expect(within(video).queryByRole("button", { name: "上傳：深夜讀書" })).toBeNull();
    expect(within(video).getByLabelText("選擇「深夜讀書」的檔案").getAttribute("accept")).toBe("video/*");

    const photo = new File(["png"], "night.png", { type: "image/png" });
    fireEvent.change(within(video).getByLabelText("選擇「深夜讀書」的檔案"), { target: { files: [photo] } });
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "「深夜讀書」沒有上傳成功：這格要影片腳本，照片不算");
    expect(createUploadBatch).not.toHaveBeenCalled();
    expect(uploadIntoSlot).not.toHaveBeenCalled();
    expect(within(tile("深夜讀書")).getByText("缺影片")).toBeTruthy();
  });

  it("a video-format slot with no copy is the dashed placeholder with the same sentence", async () => {
    vi.mocked(getSlots).mockResolvedValue(slots({ groups: [{ group_id: "g", name: "新客", slots: [
      slot({ ad_id: "a3", name: "深夜讀書", state: "missing", confirmed: false, thumbnail_url: null, copy: null, format_key: "video" }),
    ] }] }));
    renderBody();
    await screen.findByRole("heading", { name: "0／1 格已備妥" });
    const list = screen.getByRole("list", { name: "新客" });
    expect(within(list).getByText("這格要影片腳本，照片不算")).toBeTruthy();
    expect(within(list).queryByText("缺 1 則")).toBeNull();
    expect(within(list).getByRole("button", { name: "上傳影片：深夜讀書" })).toBeTruthy();
    expect(within(list).getByRole("link", { name: "從素材工作檯" })).toBeTruthy();
  });

  it("two slots showing the same photo say 同一張圖，文案不同, and 換一張 reopens the upload into that slot", async () => {
    vi.mocked(getSlots).mockResolvedValue(fourTiles("ready"));
    vi.mocked(createUploadBatch).mockResolvedValue({ batch: { id: "ub_1", uploads: [{ id: "up_1", batch_id: "ub_1", filename: "other.png", expected_size: 3, status: "complete", error: null, asset_id: "uas_13", copy_fields: {} }] } });
    vi.mocked(uploadIntoSlot).mockResolvedValue({ placement: placement({ confirmed_at: "2026-09-29T02:00:00Z" }), slots: fourTiles("ready") });
    renderBody();
    await screen.findByRole("heading", { name: "3／4 格已備妥" });
    const shared = tile("早晨通勤");
    expect(within(shared).getByText("同一張圖，文案不同")).toBeTruthy();
    expect(within(shared).getByText("已確認")).toBeTruthy();
    expect(within(tile("運動後與忙碌日常")).getByText("同一張圖，文案不同")).toBeTruthy();
    // The one photo nobody else uses says nothing.
    expect(within(tile("上班日午休")).queryByText("同一張圖，文案不同")).toBeNull();

    const swap = within(shared).getByRole("button", { name: "換一張：早晨通勤" });
    const input = within(shared).getByLabelText("選擇「早晨通勤」的檔案") as HTMLInputElement;
    const click = vi.spyOn(input, "click");
    fireEvent.click(swap);
    expect(click).toHaveBeenCalledTimes(1);
    fireEvent.change(input, { target: { files: [new File(["png"], "other.png", { type: "image/png" })] } });
    await waitFor(() => expect(uploadIntoSlot).toHaveBeenCalledWith("brd_1", "cmp_1", "a2", { upload_id: "up_1" }));
  });

  it("an imported campaign's platform ads sharing one creative get the caption but no 換一張", async () => {
    vi.mocked(getSlots).mockResolvedValue(slots({ groups: [{ group_id: null, name: "Advantage+ 購物・全台", slots: [
      slot({ ad_id: null, entity_id: "aex_1", name: "UGC_開箱_v3_1080x1350", thumbnail_url: IMG }),
      slot({ ad_id: null, entity_id: "aex_2", name: "UGC_開箱_v3_1080x1080", thumbnail_url: IMG }),
    ] }] }));
    renderBody(campaign({ origin: "imported", status: "live" }));
    await screen.findByRole("heading", { name: "2／2 格已備妥" });
    expect(screen.getAllByText("同一張圖，文案不同")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /換一張/ })).toBeNull();
  });
});
