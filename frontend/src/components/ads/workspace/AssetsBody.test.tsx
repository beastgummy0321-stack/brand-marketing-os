/** F30-I11: the assets tab body (prototype `tabAssets()`) over real-shaped `GET …/slots` fixtures — a draft with
 * ready／missing／in-progress slots, a live campaign with a 「換掉這一則」 request, a request whose replaced ad was
 * deleted, an authenticated thumbnail, the slot upload and its next step, and the slots read failing on its own. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CampaignDetail } from "@/lib/adsApi";
import { cancelMaterialTask, MaterialRequestError } from "@/lib/adsMaterialApi";
import { fetchSlotThumbnail, getSlots, uploadIntoSlot, type CampaignSlots, type Slot } from "@/lib/adsSlotsApi";
import { createUploadBatch, putUpload, type Placement } from "@/lib/adsUserAssetsApi";
import { AssetsBody } from "./AssetsBody";

vi.mock("@/lib/adsSlotsApi", async (original) => ({
  ...await original<typeof import("@/lib/adsSlotsApi")>(), getSlots: vi.fn(), uploadIntoSlot: vi.fn(), fetchSlotThumbnail: vi.fn(),
}));
vi.mock("@/lib/adsMaterialApi", async (original) => ({ ...await original<typeof import("@/lib/adsMaterialApi")>(), cancelMaterialTask: vi.fn() }));
vi.mock("@/lib/adsUserAssetsApi", async (original) => ({
  ...await original<typeof import("@/lib/adsUserAssetsApi")>(), createUploadBatch: vi.fn(), putUpload: vi.fn(),
}));

const IMG = "https://scontent.example/creative/2.jpg";
const AUTH = "/api/ads/brands/brd_1/user-assets/uas_1/thumbnail";

function slot(overrides: Partial<Slot>): Slot {
  return { ad_id: "ad_x", entity_id: null, name: "廣告", state: "ready", thumbnail_url: IMG, confirmed: true, replace_task_id: null, ...overrides };
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
    expect(next.textContent).toContain("這一格已備妥");
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
