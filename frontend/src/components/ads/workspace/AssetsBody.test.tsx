/** F30-I11: the assets tab body (prototype `tabAssets()`) over real-shaped `GET …/slots` fixtures — a draft with
 * ready／missing／in-progress slots, a live campaign with a 「換掉這一則」 request, a request whose replaced ad was
 * deleted, an authenticated thumbnail, the slot upload and its next step, and the slots read failing on its own.
 * F40-I09 (prototype `#/assets`): the tab polls while a slot is 處理中 and stops when none is, a video-format slot asks
 * for a video and refuses a photo, and a thumbnail two slots share prints 「同一張圖，文案不同」 with 換一張.
 * F44-I05 (prototype `f44-blocked-slot`, Contract D): a blocked slot says why (the quoted words marked, 「另有 N 個原因」),
 * offers the exit of its reason (換一版文案 / 到工作檯改文案 / 換一張) and 再檢查一次, is counted in the head, the progress bar
 * and the draft bar, never keeps the poll alive, and every planned slot's head carries its offer chip. */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CampaignDetail } from "@/lib/adsApi";
import { cancelMaterialTask, MaterialRequestError } from "@/lib/adsMaterialApi";
import { chooseSlotCopy, fetchSlotThumbnail, getSlotCopyOptions, getSlots, recheckSlot, SlotRecheckError, uploadIntoSlot, type CampaignSlots, type Slot } from "@/lib/adsSlotsApi";
import { AssetApiError, createUploadBatch, putUpload, type Placement } from "@/lib/adsUserAssetsApi";
import { AssetsBody } from "./AssetsBody";

vi.mock("@/lib/adsSlotsApi", async (original) => ({
  ...await original<typeof import("@/lib/adsSlotsApi")>(),
  getSlots: vi.fn(), uploadIntoSlot: vi.fn(), fetchSlotThumbnail: vi.fn(), getSlotCopyOptions: vi.fn(), chooseSlotCopy: vi.fn(),
  recheckSlot: vi.fn(),
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

describe("AssetsBody — F44-I05: a blocked slot says why and offers its exit (prototype f44-blocked-slot)", () => {
  const SET_HREF = "/app/brands/brd_1/workbench/packs/pk_9/sets/wb_set_1";
  const thumbOf = (id: string) => `https://scontent.example/creative/${id}.jpg`;
  const waiting = (headline: string, body: string) => ({ source: "placement" as const, label: "待確認", headline, body, description: "每天兩顆" });
  const NAME_READY = "通勤族・三盒組優惠價";
  const NAME_MISMATCH = "通勤情境單圖・好攜帶，走到哪都適合（最多數量 1150706）";
  const NAME_UNBACKED = "訓練前・一顆就好";
  const NAME_FILE = "會議前・午休五分鐘";
  const NAME_RUNNING = "上班日・下午三點";
  const MISMATCH = { text: "這則規劃的是「無優惠」，文案卻寫了「優惠」。", terms: ["優惠"], fix: "copy" as const, more: 0 };
  const ready = slot({ ad_id: "ada_1", name: NAME_READY, state: "ready", thumbnail_url: thumbOf("1"), blocked: null, offer_label: "組合優惠", workbench_href: SET_HREF,
    copy: { source: "placement", label: "已確認", headline: "晨光軟糖三盒組", body: "三盒組優惠價 NT$999（原價 NT$1,500）", description: "每天兩顆" } });
  const mismatch = slot({ ad_id: "ada_2", name: NAME_MISMATCH, state: "blocked", confirmed: false, thumbnail_url: thumbOf("2"), offer_label: "無優惠", workbench_href: SET_HREF,
    copy: waiting("晨光軟糖三盒組", "三盒組優惠價 NT$999（原價 NT$1,500）"), blocked: MISMATCH });
  /** An ad added later: no workbench set, two offending words and one more reason behind the first. */
  const unbacked = slot({ ad_id: "ada_3", name: NAME_UNBACKED, state: "blocked", confirmed: false, thumbnail_url: thumbOf("3"), offer_label: "無優惠", workbench_href: null,
    copy: waiting("訓練前一顆", "現在下單加贈一盒，滿千免運"),
    blocked: { text: "文案寫了「加贈、免運」，品牌資料裡沒有登記這個優惠或背書。", terms: ["加贈", "免運"], fix: "copy", more: 1 } });
  const failedFile = slot({ ad_id: "ada_4", name: NAME_FILE, state: "blocked", confirmed: false, thumbnail_url: null, offer_label: "無優惠", workbench_href: SET_HREF,
    copy: null, blocked: { text: "這個檔案處理失敗：圖片格式讀不出來。", terms: [], fix: "file", more: 1 } });
  const running = slot({ ad_id: "ada_5", name: NAME_RUNNING, state: "in_progress", confirmed: false, thumbnail_url: null, blocked: null, offer_label: "無優惠", workbench_href: SET_HREF,
    copy: waiting("下午三點的會議前", "先補一顆") });
  /** The prototype's grid: one ready, three blocked (coordinate mismatch, unbacked promise, failed file), one 處理中. */
  const grid = (list: Slot[] = [ready, mismatch, unbacked, failedFile, running]) => slots({ groups: [{ group_id: "adg_new", name: "新客", slots: list }] });
  const tile = (name: string) => screen.getByText(name).closest("[data-slot=slot-tile]") as HTMLElement;
  const options = () => ({ options: [
    { set_id: "wb_set_1", version_id: "wo_2", label: "新客 · 版本 2", copy_fields: { headline: "讀到凌晨一點", body: "讓軟糖陪你撐完最後一章" } },
  ] });

  afterEach(() => { vi.useRealTimers(); });

  it("the head counts the blocked slots, their segments are the danger colour and the draft bar says they are not in the launch list", async () => {
    vi.mocked(getSlots).mockResolvedValue(grid());
    renderBody();
    expect(await screen.findByRole("heading", { name: "1／5 格已備妥" })).toBeTruthy();
    const count = screen.getByText("3 格卡住");
    expect(count.dataset.tone).toBe("bad");
    const bar = screen.getByRole("img", { name: "1／5 格已備妥，3 格卡住" });
    expect([...bar.querySelectorAll("[data-state]")].map((i) => (i as HTMLElement).dataset.state)).toEqual(["ok", "blocked", "blocked", "blocked", "running"]);
    expect(bar.querySelector("[data-state=blocked]")?.className).toContain("bg-danger");
    expect(screen.getByText("3 格卡住，處理好才會進上架清單")).toBeTruthy();
    expect(screen.queryByText(/缺圖的那/)).toBeNull();
    // A blocked slot is not ready: the launch list counts the one ready slot.
    expect(screen.getByRole("link", { name: "確認上架清單（1 則） →" })).toBeTruthy();
    expect(screen.getByText("1／5", { selector: "[data-slot=chip]" })).toBeTruthy();
  });

  it("no blocked slot: no 卡住 chip, and the bar keeps the 缺圖 hint", async () => {
    renderBody();
    await screen.findByRole("heading", { name: "3／5 格已備妥" });
    expect(screen.queryByText(/格卡住/)).toBeNull();
    expect(screen.getByText("缺圖的那 2 則先不建立，不會花到錢；補上圖後再加上去")).toBeTruthy();
  });

  it("a blocked tile keeps its two halves, reads 卡住 and marks only the quoted words of the reason", async () => {
    vi.mocked(getSlots).mockResolvedValue(grid());
    renderBody();
    await screen.findByRole("heading", { name: "1／5 格已備妥" });
    const first = tile(NAME_MISMATCH);
    expect(first.dataset.variant).toBe("blocked");
    expect(within(first).getByText("卡住", { selector: "[data-slot=chip]" }).dataset.tone).toBe("bad");
    expect(first.querySelector(`img[src="${thumbOf("2")}"]`)?.className).toContain("grayscale");
    expect(within(first).getByText(/文案 · 待確認/)).toBeTruthy();
    expect(within(first).getByText(/^晨光軟糖三盒組\s三盒組優惠價 NT\$999（原價 NT\$1,500）$/)).toBeTruthy();
    const reason = first.querySelector("[data-slot=slot-reason]") as HTMLElement;
    expect(reason.querySelector("p")?.textContent).toBe("這則規劃的是「無優惠」，文案卻寫了「優惠」。");
    // 「無優惠」 is the plan's label, not an offending word.
    expect([...reason.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["優惠"]);
    expect(within(first).queryByText(/另有/)).toBeNull();

    const second = tile(NAME_UNBACKED);
    expect([...second.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["加贈", "免運"]);
    expect(within(second).getByText("另有 1 個原因")).toBeTruthy();

    // A failed file has no copy half and nothing to mark.
    const third = tile(NAME_FILE);
    expect(third.dataset.variant).toBe("blocked");
    expect(third.querySelector("[data-slot=slot-copy]")).toBeNull();
    expect(third.querySelectorAll("mark")).toHaveLength(0);
    expect(within(third).getByText("這個檔案處理失敗：圖片格式讀不出來。")).toBeTruthy();
    expect(within(third).getByText("另有 1 個原因")).toBeTruthy();
    // The slot still being processed is not blocked.
    expect(tile(NAME_RUNNING).dataset.variant).toBe("ready");
    expect(within(tile(NAME_RUNNING)).getByText("處理中・自動更新，不用重整")).toBeTruthy();
  });

  it("every planned slot's head carries its offer chip — accent unless 無優惠; a slot without the label has none", async () => {
    vi.mocked(getSlots).mockResolvedValue(grid([
      ready, mismatch, running,
      slot({ ad_id: "ada_6", name: "只有文案的那一則", state: "copy_only", confirmed: false, thumbnail_url: null, offer_label: "免運", workbench_href: SET_HREF,
        copy: { source: "workbench", label: "工作檯第 1 版", headline: "滿千免運", body: "三盒一起帶", description: null } }),
      slot({ ad_id: "ada_7", name: "只有圖的那一則", state: "image_only", confirmed: false, thumbnail_url: thumbOf("7"), offer_label: "無優惠", copy: null }),
      slot({ ad_id: null, entity_id: "aex_1", name: "UGC_開箱_v3_1080x1350", thumbnail_url: thumbOf("8"), blocked: null, offer_label: null }),
    ]));
    renderBody();
    await screen.findByRole("heading", { name: "2／6 格已備妥" });
    const offer = (name: string) => tile(name).querySelector("[data-slot=slot-head] [data-slot=chip]") as HTMLElement | null;
    expect([offer(NAME_READY)?.textContent, offer(NAME_READY)?.dataset.tone]).toEqual(["組合優惠", "accent"]);
    expect([offer(NAME_MISMATCH)?.textContent, offer(NAME_MISMATCH)?.dataset.tone]).toEqual(["無優惠", "neutral"]);
    expect([offer(NAME_RUNNING)?.textContent, offer(NAME_RUNNING)?.dataset.tone]).toEqual(["無優惠", "neutral"]);
    expect([offer("只有文案的那一則")?.textContent, offer("只有文案的那一則")?.dataset.tone]).toEqual(["免運", "accent"]);
    expect(offer("只有圖的那一則")?.textContent).toBe("無優惠");
    expect(offer("UGC_開箱_v3_1080x1350")).toBeNull();
  });

  it("fix: copy → 換一版文案 opens the picker; the chosen version goes through chooseSlotCopy and the returned slots replace the grid", async () => {
    const user = userEvent.setup();
    vi.mocked(getSlots).mockResolvedValue(grid());
    vi.mocked(getSlotCopyOptions).mockResolvedValue(options());
    const fixed = slot({ ...mismatch, state: "ready", confirmed: true, blocked: null,
      copy: { source: "placement", label: "已確認", headline: "讀到凌晨一點", body: "讓軟糖陪你撐完最後一章", description: null } });
    vi.mocked(chooseSlotCopy).mockResolvedValue({ placement: placement({ confirmed_at: "2026-10-01T02:00:00Z" }), slots: grid([ready, fixed, unbacked, failedFile, running]) });
    const { props } = renderBody();
    await screen.findByRole("heading", { name: "1／5 格已備妥" });
    const first = tile(NAME_MISMATCH);
    // The ad has a workbench set: the second exit goes there (the /app prefix stripped for the router).
    expect(within(first).getByRole("link", { name: "到工作檯改文案 →" }).getAttribute("href")).toBe("/brands/brd_1/workbench/packs/pk_9/sets/wb_set_1");
    expect(within(first).queryByRole("button", { name: /換一張/ })).toBeNull();
    // An ad without a set offers the picker only.
    expect(within(tile(NAME_UNBACKED)).getByRole("button", { name: `換一版文案：${NAME_UNBACKED}` })).toBeTruthy();
    expect(within(tile(NAME_UNBACKED)).queryByRole("link", { name: "到工作檯改文案 →" })).toBeNull();

    await user.click(within(first).getByRole("button", { name: `換一版文案：${NAME_MISMATCH}` }));
    const dialog = await screen.findByRole("dialog", { name: `「${NAME_MISMATCH}」換一版文案` });
    expect(within(dialog).getByText("選一版沒有寫「優惠」的文案，這一格會馬上再檢查一次。")).toBeTruthy();
    await user.click((await within(dialog).findAllByRole("listitem"))[0]);
    expect(chooseSlotCopy).toHaveBeenCalledWith("brd_1", "cmp_1", "ada_2", { set_id: "wb_set_1", version_id: "wo_2" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByRole("heading", { name: "2／5 格已備妥" })).toBeTruthy();
    expect(screen.getByText("2 格卡住")).toBeTruthy();
    expect(tile(NAME_MISMATCH).dataset.variant).toBe("ready");
    expect(await within(tile(NAME_MISMATCH)).findByText("已確認・剛處理好")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe("文案換好了，這一格已確認");
    expect(props.onPlacementChanged).toHaveBeenCalledTimes(1);
  });

  it("a chosen copy that is refused again never reads as ready: the tile carries the new reason", async () => {
    const user = userEvent.setup();
    vi.mocked(getSlots).mockResolvedValue(grid());
    vi.mocked(getSlotCopyOptions).mockResolvedValue(options());
    const again = slot({ ...mismatch, copy: waiting("讀到凌晨一點", "現在下單加贈一盒"),
      blocked: { text: "文案寫了「加贈」，品牌資料裡沒有登記這個優惠或背書。", terms: ["加贈"], fix: "copy", more: 0 } });
    vi.mocked(chooseSlotCopy).mockResolvedValue({ placement: placement(), slots: grid([ready, again, unbacked, failedFile, running]) });
    renderBody();
    await screen.findByRole("heading", { name: "1／5 格已備妥" });
    await user.click(within(tile(NAME_MISMATCH)).getByRole("button", { name: `換一版文案：${NAME_MISMATCH}` }));
    await user.click((await within(await screen.findByRole("dialog")).findAllByRole("listitem"))[0]);
    expect((await screen.findByRole("status")).textContent).toBe("文案換好了，這一格還是卡住，原因寫在格子裡。");
    expect(screen.getByRole("heading", { name: "1／5 格已備妥" })).toBeTruthy();
    expect(tile(NAME_MISMATCH).dataset.variant).toBe("blocked");
    expect(tile(NAME_MISMATCH).querySelector("[data-slot=slot-reason] p")?.textContent).toBe("文案寫了「加贈」，品牌資料裡沒有登記這個優惠或背書。");
    expect(screen.queryByText(/備妥。$/)).toBeNull();
  });

  it("fix: file → 換一張 uploads into that slot; no copy exit on the tile", async () => {
    vi.mocked(getSlots).mockResolvedValue(grid());
    vi.mocked(createUploadBatch).mockResolvedValue({ batch: { id: "ub_1", uploads: [{ id: "up_1", batch_id: "ub_1", filename: "noon.png", expected_size: 3, status: "complete", error: null, asset_id: "uas_31", copy_fields: {} }] } });
    const replaced = slot({ ...failedFile, state: "ready", confirmed: true, blocked: null, thumbnail_url: thumbOf("4"),
      copy: { source: "placement", label: "已確認", headline: "午休 5 分鐘", body: "一顆就好", description: null } });
    vi.mocked(uploadIntoSlot).mockResolvedValue({ placement: placement({ confirmed_at: "2026-10-01T02:00:00Z" }), slots: grid([ready, mismatch, unbacked, replaced, running]) });
    renderBody();
    await screen.findByRole("heading", { name: "1／5 格已備妥" });
    const failed = tile(NAME_FILE);
    expect(within(failed).getByRole("button", { name: `換一張：${NAME_FILE}` })).toBeTruthy();
    expect(within(failed).queryByRole("button", { name: /換一版文案/ })).toBeNull();
    expect(within(failed).queryByRole("link", { name: "到工作檯改文案 →" })).toBeNull();
    expect(within(failed).getByRole("button", { name: `再檢查一次：${NAME_FILE}` })).toBeTruthy();
    fireEvent.change(within(failed).getByLabelText(`選擇「${NAME_FILE}」的檔案`), { target: { files: [new File(["png"], "noon.png", { type: "image/png" })] } });
    await waitFor(() => expect(uploadIntoSlot).toHaveBeenCalledWith("brd_1", "cmp_1", "ada_4", { upload_id: "up_1" }));
    expect(await screen.findByRole("heading", { name: "2／5 格已備妥" })).toBeTruthy();
    expect(tile(NAME_FILE).dataset.variant).toBe("ready");
  });

  it("an upload that comes back blocked says so and points at the tile, not at the folded placement list", async () => {
    const missing = slot({ ad_id: "ada_9", name: "早晨第一口・單圖", state: "missing", confirmed: false, thumbnail_url: null, offer_label: "無優惠", copy: null });
    vi.mocked(getSlots).mockResolvedValue(grid([ready, missing]));
    vi.mocked(createUploadBatch).mockResolvedValue({ batch: { id: "ub_1", uploads: [{ id: "up_1", batch_id: "ub_1", filename: "morning.png", expected_size: 3, status: "complete", error: null, asset_id: "uas_32", copy_fields: {} }] } });
    const refused = slot({ ...missing, state: "blocked", thumbnail_url: thumbOf("9"), copy: waiting("早晨第一口", "三盒組優惠價 NT$999"), blocked: MISMATCH });
    vi.mocked(uploadIntoSlot).mockResolvedValue({ placement: placement({ pending_reason: MISMATCH.text }), slots: grid([ready, refused]) });
    renderBody();
    await screen.findByRole("heading", { name: "1／2 格已備妥" });
    fireEvent.change(screen.getByLabelText("選擇「早晨第一口・單圖」的檔案"), { target: { files: [new File(["png"], "morning.png", { type: "image/png" })] } });
    const line = await screen.findByRole("status");
    expect(line.textContent).toBe("已放進「早晨第一口・單圖」這一格，但卡住了，原因寫在格子裡。");
    expect(within(line).queryByRole("button")).toBeNull();
    expect(tile("早晨第一口・單圖").dataset.variant).toBe("blocked");
  });

  it("fix: null → the reason and 再檢查一次 only", async () => {
    const noExit = slot({ ...mismatch, blocked: { text: "找不到此品牌商品。", terms: [], fix: null, more: 0 } });
    vi.mocked(getSlots).mockResolvedValue(grid([ready, noExit]));
    renderBody();
    await screen.findByRole("heading", { name: "1／2 格已備妥" });
    const blocked = tile(NAME_MISMATCH);
    expect(within(blocked).getByText("找不到此品牌商品。")).toBeTruthy();
    expect(within(blocked).getAllByRole("button").map((b) => b.textContent)).toEqual(["再檢查一次"]);
    expect(within(blocked).queryByRole("link")).toBeNull();
  });

  it("再檢查一次 reads 檢查中… while it runs, and the returned slots replace the grid", async () => {
    const user = userEvent.setup();
    vi.mocked(getSlots).mockResolvedValue(grid());
    let finish: (value: { slots: CampaignSlots }) => void = () => {};
    vi.mocked(recheckSlot).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const { props } = renderBody();
    await screen.findByRole("heading", { name: "1／5 格已備妥" });
    await user.click(within(tile(NAME_MISMATCH)).getByRole("button", { name: `再檢查一次：${NAME_MISMATCH}` }));
    expect(recheckSlot).toHaveBeenCalledWith("brd_1", "cmp_1", "ada_2");
    const busy = await within(tile(NAME_MISMATCH)).findByRole("button", { name: `檢查中…：${NAME_MISMATCH}` });
    expect(busy).toHaveProperty("disabled", true);
    expect(busy.textContent).toBe("檢查中…");
    // Only the slot being checked is busy.
    expect(within(tile(NAME_UNBACKED)).getByRole("button", { name: `再檢查一次：${NAME_UNBACKED}` })).toHaveProperty("disabled", false);

    const passed = slot({ ...mismatch, state: "ready", confirmed: true, blocked: null, copy: { ...waiting("晨光軟糖三盒組", "每天兩顆，通勤包裡放一盒"), label: "已確認" } });
    await act(async () => { finish({ slots: grid([ready, passed, unbacked, failedFile, running]) }); });
    expect(await screen.findByRole("heading", { name: "2／5 格已備妥" })).toBeTruthy();
    expect(tile(NAME_MISMATCH).dataset.variant).toBe("ready");
    expect(await within(tile(NAME_MISMATCH)).findByText("已確認・剛處理好")).toBeTruthy();
    expect(screen.getByText("2 格卡住")).toBeTruthy();
    expect(props.onPlacementChanged).toHaveBeenCalledTimes(1);
  });

  it("a recheck that is still refused says so on the tile: same reason, or the new one", async () => {
    const user = userEvent.setup();
    vi.mocked(getSlots).mockResolvedValue(grid());
    const other = slot({ ...unbacked, blocked: { text: "含品牌禁止宣稱，請修訂此安排的文案。", terms: [], fix: "copy", more: 0 } });
    vi.mocked(recheckSlot).mockResolvedValueOnce({ slots: grid() }).mockResolvedValueOnce({ slots: grid([ready, mismatch, other, failedFile, running]) });
    renderBody();
    await screen.findByRole("heading", { name: "1／5 格已備妥" });
    await user.click(within(tile(NAME_MISMATCH)).getByRole("button", { name: `再檢查一次：${NAME_MISMATCH}` }));
    expect(await within(tile(NAME_MISMATCH)).findByText("還是卡住：原因沒有變")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "1／5 格已備妥" })).toBeTruthy();
    expect(within(tile(NAME_MISMATCH)).getByRole("button", { name: `再檢查一次：${NAME_MISMATCH}` })).toHaveProperty("disabled", false);

    await user.click(within(tile(NAME_UNBACKED)).getByRole("button", { name: `再檢查一次：${NAME_UNBACKED}` }));
    expect(await within(tile(NAME_UNBACKED)).findByText("還是卡住：原因換了")).toBeTruthy();
    expect(within(tile(NAME_UNBACKED)).getByText("含品牌禁止宣稱，請修訂此安排的文案。")).toBeTruthy();
    // The line belongs to the last slot checked.
    expect(within(tile(NAME_MISMATCH)).queryByText(/還是卡住/)).toBeNull();
  });

  it("a failed recheck says why on the tile and leaves the grid; slot_no_file re-reads the slots and says nothing", async () => {
    const user = userEvent.setup();
    vi.mocked(getSlots).mockResolvedValue(grid());
    vi.mocked(recheckSlot).mockRejectedValueOnce(new SlotRecheckError("找不到這份素材，請重新上傳。", 409, "user_asset_unavailable"));
    const { props } = renderBody();
    await screen.findByRole("heading", { name: "1／5 格已備妥" });
    await user.click(within(tile(NAME_MISMATCH)).getByRole("button", { name: `再檢查一次：${NAME_MISMATCH}` }));
    expect(await within(tile(NAME_MISMATCH)).findByRole("alert")).toHaveProperty("textContent", "沒有檢查成功：找不到這份素材，請重新上傳。");
    expect(tile(NAME_MISMATCH).dataset.variant).toBe("blocked");
    expect(screen.getByRole("heading", { name: "1／5 格已備妥" })).toBeTruthy();
    expect(props.onPlacementChanged).not.toHaveBeenCalled();
    expect(getSlots).toHaveBeenCalledTimes(1);

    // The slot was confirmed somewhere else in the meantime: nothing to check, the re-read shows what is true now.
    const confirmed = slot({ ...unbacked, state: "ready", confirmed: true, blocked: null });
    vi.mocked(recheckSlot).mockRejectedValueOnce(new SlotRecheckError("這一格還沒有圖，先上傳圖再選文案。", 409, "slot_no_file"));
    vi.mocked(getSlots).mockResolvedValue(grid([ready, mismatch, confirmed, failedFile, running]));
    await user.click(within(tile(NAME_UNBACKED)).getByRole("button", { name: `再檢查一次：${NAME_UNBACKED}` }));
    expect(await screen.findByRole("heading", { name: "2／5 格已備妥" })).toBeTruthy();
    expect(getSlots).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/這一格還沒有圖/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("no polling when only blocked slots remain", async () => {
    vi.useFakeTimers();
    vi.mocked(getSlots).mockResolvedValue(grid([ready, mismatch, unbacked, failedFile]));
    const view = renderBody();
    await act(async () => {});
    expect(screen.getByRole("heading", { name: "1／4 格已備妥" })).toBeTruthy();
    expect(screen.getByText("3 格卡住")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(getSlots).toHaveBeenCalledTimes(1);
    view.unmount();
  });

  it("a 處理中 slot that the poll finds refused becomes 卡住 and the poll stops", async () => {
    vi.useFakeTimers();
    const before = slot({ ...mismatch, state: "in_progress", blocked: null });
    vi.mocked(getSlots).mockResolvedValueOnce(grid([ready, before])).mockResolvedValue(grid([ready, mismatch]));
    const view = renderBody();
    await act(async () => {});
    expect(within(tile(NAME_MISMATCH)).getByText("處理中・自動更新，不用重整")).toBeTruthy();
    expect(screen.queryByText(/格卡住/)).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(getSlots).toHaveBeenCalledTimes(2);
    expect(tile(NAME_MISMATCH).dataset.variant).toBe("blocked");
    expect(screen.getByText("1 格卡住")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(getSlots).toHaveBeenCalledTimes(2);
    view.unmount();
  });
});
