import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getCampaign, getPublish, publishCampaign, type CampaignDetail } from "@/lib/adsApi";
import { fetchLaunchView, saveManualSettings, type LaunchView } from "@/lib/adsLaunchApi";
import { getLaunchSettings, saveLaunchSettings, type LaunchSettingsValues, type LaunchSettingsView } from "@/lib/adsLaunchSettingsApi";
import type { PublishGetResponse } from "@/lib/adsPublishTypes";
import { ApiNetworkError, ApiResponseError } from "@/lib/http";
import { LaunchSettingsCard } from "./LaunchSettingsCard";
import { PublishList } from "./PublishList";

vi.mock("@/lib/adsApi", () => ({ getCampaign: vi.fn(), getPublish: vi.fn(), publishCampaign: vi.fn() }));
vi.mock("@/lib/adsLaunchApi", () => ({ fetchLaunchView: vi.fn(), saveManualSettings: vi.fn() }));
vi.mock("@/lib/adsLaunchSettingsApi", () => ({ getLaunchSettings: vi.fn(), saveLaunchSettings: vi.fn() }));
vi.mock("@/lib/auth", () => ({ getOrgId: () => "org" }));
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org", identity: { org: { timezone: "Asia/Taipei" } } }) }));

const VALUES: LaunchSettingsValues = {
  optimization_event: "purchase", bid_strategy: "lowest_cost", placement: { mode: "auto", positions: [] },
  audience: { age_min: 18, age_max: 65, gender: "all", countries: ["TW"] }, pixel_id: "px1",
  utm: "utm_source=meta&utm_campaign=fall",
};
function settings(values = VALUES): LaunchSettingsView {
  return { values, recommended: VALUES, edited: [], errors: [], options: {
    optimization_event: [{ value: "purchase", label: "購買", note: "購買" }],
    bid_strategy: [{ value: "lowest_cost", label: "最低成本", note: "最低成本" }],
    placement_modes: [{ value: "auto", label: "自動", note: "自動" }], positions: [],
    countries: [{ value: "TW", label: "台灣", note: "台灣" }],
    genders: [{ value: "all", label: "不限", note: "不限" }], ages: [18, 65],
    pixels: [{ id: "px1", name: "官網" }, { id: "px2", name: "新官網" }], pixels_error: null,
    field_notes: { audience: "受眾", pixel_id: "像素", utm: "追蹤參數" },
  } };
}
const CAMPAIGN = {
  id: "cmp", name: "秋季上架", status: "ready", cap: { value: 40, basis: "own", result_kind: "purchase", result_label: "購買" },
  manual_handoff: { pending_count: 0, fields: [{ key: "landing_url", label: "落地頁網址", section: "追蹤", required: true, readable: true }],
    groups: [{ id: "grp", name: "新客組", status: "資料已填齊，待平台核對", missing: [], sources: {},
      saved_at: null, saved_by: null, ads: [], values: { landing_url: "https://example.com/old" } }] },
} as unknown as CampaignDetail;
function launch(hash = "revision-a", values = VALUES): LaunchView {
  return { step: "list", content_hash: hash, launch_settings: values, version: null, approved_at: null,
    summary: { campaigns: 1, groups: 1, ads: 1, daily_total: 300, start: "2026-10-07", end: "2026-10-14", cap: 40, slots_ready: 1, slots_total: 1 },
    items: [], deferred_ads: [], read_at: null, settings_readback: null, month_budget: null };
}
function publish(hash = "revision-a", values = VALUES): PublishGetResponse {
  return { adapters: [{ key: "manual", label: "人工上架" }], adapter: "manual",
    describe: { adapter: "manual", message: null, checklist: [], content_hash: hash, launch_settings: values } };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function renderList(view = launch()) {
  const onApproved = vi.fn();
  const onCampaignSaved = vi.fn();
  const result = render(<MemoryRouter><PublishList brandId="brd" campaignId="cmp" name={CAMPAIGN.name}
    campaign={CAMPAIGN} campaignFailed={null} onCampaignRetry={vi.fn()} onCampaignSaved={onCampaignSaved}
    view={view} onApproved={onApproved} /></MemoryRouter>);
  return { ...result, onApproved, onCampaignSaved };
}
const approve = () => screen.getByRole("button", { name: "核准上架清單 →" }) as HTMLButtonElement;

beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear();
  vi.mocked(getPublish).mockResolvedValue(publish());
  vi.mocked(fetchLaunchView).mockResolvedValue(launch());
  vi.mocked(getLaunchSettings).mockResolvedValue(settings());
  vi.mocked(saveLaunchSettings).mockImplementation(async (_b, _c, values) => settings(values));
  vi.mocked(saveManualSettings).mockResolvedValue(undefined);
  vi.mocked(getCampaign).mockResolvedValue(CAMPAIGN);
  vi.mocked(publishCampaign).mockResolvedValue(publish().describe);
});
afterEach(cleanup);

it("pending settings read blocks the no-edit first click, then approves exactly once", async () => {
  const read = deferred<LaunchSettingsView>();
  vi.mocked(getLaunchSettings).mockReturnValue(read.promise);
  const { onApproved } = renderList();
  await waitFor(() => expect(getPublish).toHaveBeenCalled());
  expect(approve().disabled).toBe(true);
  fireEvent.click(approve()); expect(publishCampaign).not.toHaveBeenCalled();
  await act(async () => read.resolve(settings()));
  await waitFor(() => expect(approve().disabled).toBe(false));
  await userEvent.setup().click(approve());
  await waitFor(() => expect(onApproved).toHaveBeenCalledTimes(1));
  expect(publishCampaign).toHaveBeenCalledWith("brd", "cmp", "manual", expect.objectContaining({ content_hash: "revision-a" }));
});

it("manual settings remain blocking while the successful PUT's follow-up campaign read is pending", async () => {
  const read = deferred<CampaignDetail>();
  vi.mocked(getCampaign).mockReturnValue(read.promise);
  renderList(); const user = userEvent.setup();
  await waitFor(() => expect(approve().disabled).toBe(false));
  await user.click(screen.getByRole("button", { name: /進階設定/ }));
  await user.click(screen.getByRole("button", { name: /新客組 ·/ }));
  const field = screen.getByLabelText(/落地頁網址/);
  await user.clear(field); await user.type(field, "https://example.com/new");
  await user.click(screen.getByRole("button", { name: "儲存這組設定" }));
  await waitFor(() => expect(getCampaign).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "儲存中…" })).toBeTruthy();
  expect(approve().disabled).toBe(true);
  fireEvent.click(approve()); expect(publishCampaign).not.toHaveBeenCalled();
});

it("a newer hash cannot approve older settings still displayed by a reversed read", async () => {
  vi.mocked(getPublish).mockResolvedValue(publish("revision-b", { ...VALUES, pixel_id: "px2" }));
  renderList();
  await screen.findByLabelText(/像素/);
  await waitFor(() => expect(getPublish).toHaveBeenCalled());
  expect((screen.getByLabelText(/像素/) as HTMLSelectElement).value).toBe("px1");
  expect(approve().disabled).toBe(true);
  fireEvent.click(approve()); expect(publishCampaign).not.toHaveBeenCalled();
});

it("a real 409 refreshes the displayed budget/settings and requires another explicit click", async () => {
  const nextValues = { ...VALUES, pixel_id: "px2" };
  const next = { ...launch("revision-b", nextValues), summary: { ...launch().summary, daily_total: 600 } };
  vi.mocked(publishCampaign).mockRejectedValueOnce(new ApiResponseError(
    "計畫、素材或月份已改變，請重新檢視後核准。", 409, {}, { code: "launch_content_changed" }));
  const { onApproved } = renderList();
  await waitFor(() => expect(approve().disabled).toBe(false));
  vi.mocked(getPublish).mockResolvedValue(publish("revision-b", nextValues));
  vi.mocked(fetchLaunchView).mockResolvedValue(next);
  vi.mocked(getLaunchSettings).mockResolvedValue(settings(nextValues));
  await userEvent.setup().click(approve());
  await screen.findByRole("alert");
  await waitFor(() => expect(screen.getByText("600", { selector: "b" })).toBeTruthy());
  expect(publishCampaign).toHaveBeenCalledTimes(1); expect(onApproved).not.toHaveBeenCalled();
  await waitFor(() => expect(approve().disabled).toBe(false));
  expect((screen.getByLabelText(/像素/) as HTMLSelectElement).value).toBe("px2");
  await userEvent.setup().click(approve());
  await waitFor(() => expect(onApproved).toHaveBeenCalledTimes(1));
  expect(publishCampaign).toHaveBeenLastCalledWith("brd", "cmp", "manual", expect.objectContaining({ content_hash: "revision-b" }));
});

it("an unknown write preserves its message and operation identity without automatic replay", async () => {
  vi.mocked(publishCampaign).mockRejectedValueOnce(new ApiNetworkError(true));
  const { onApproved } = renderList();
  await waitFor(() => expect(approve().disabled).toBe(false));
  await userEvent.setup().click(approve());
  expect((await screen.findByRole("alert")).textContent).toContain("這次的結果還不確定");
  expect(onApproved).not.toHaveBeenCalled(); expect(publishCampaign).toHaveBeenCalledTimes(1);
  const firstOperation = vi.mocked(publishCampaign).mock.calls[0][3]?.operation_id;
  await waitFor(() => expect(approve().disabled).toBe(false));
  await userEvent.setup().click(approve());
  await waitFor(() => expect(onApproved).toHaveBeenCalledTimes(1));
  expect(vi.mocked(publishCampaign).mock.calls[1][3]?.operation_id).toBe(firstOperation);
});

it("a duplicate click cannot start a second in-flight approval", async () => {
  const write = deferred<PublishGetResponse["describe"]>();
  vi.mocked(publishCampaign).mockReturnValue(write.promise);
  const { onApproved } = renderList();
  await waitFor(() => expect(approve().disabled).toBe(false));
  act(() => { fireEvent.click(approve()); fireEvent.click(approve()); });
  expect(publishCampaign).toHaveBeenCalledTimes(1);
  await act(async () => write.resolve(publish().describe));
  expect(onApproved).toHaveBeenCalledTimes(1);
});

it("an old owner's settings save cannot overwrite the new owner's displayed values", async () => {
  const oldSave = deferred<LaunchSettingsView>();
  vi.mocked(saveLaunchSettings).mockReturnValue(oldSave.promise);
  const onSaved = vi.fn();
  const card = (id: string) => <LaunchSettingsCard brandId="brd" campaign={{ ...CAMPAIGN, id }}
    locked={false} onSaved={onSaved} onCampaignSaved={vi.fn()} />;
  const result = render(card("cmp")); const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText(/像素/), "px2");
  await waitFor(() => expect(saveLaunchSettings).toHaveBeenCalledTimes(1));
  vi.mocked(getLaunchSettings).mockResolvedValue(settings({ ...VALUES, pixel_id: "px2" }));
  result.rerender(card("other"));
  await waitFor(() => expect(vi.mocked(getLaunchSettings).mock.calls.at(-1)?.[1]).toBe("other"));
  await waitFor(() => expect((screen.getByLabelText(/像素/) as HTMLSelectElement).value).toBe("px2"));
  await act(async () => oldSave.resolve(settings({ ...VALUES, pixel_id: "px1" })));
  expect((screen.getByLabelText(/像素/) as HTMLSelectElement).value).toBe("px2");
  expect(onSaved).not.toHaveBeenCalled();
});

it("repeated mount drops the old pending revision response before a no-edit first click", async () => {
  const old = deferred<PublishGetResponse>();
  vi.mocked(getPublish).mockReturnValueOnce(old.promise);
  const first = renderList();
  await waitFor(() => expect(getPublish).toHaveBeenCalledTimes(1)); first.unmount();
  const second = renderList();
  await waitFor(() => expect(approve().disabled).toBe(false));
  const reads = vi.mocked(fetchLaunchView).mock.calls.length;
  await act(async () => old.resolve(publish("old-owner", { ...VALUES, pixel_id: "px2" })));
  expect(fetchLaunchView).toHaveBeenCalledTimes(reads);
  expect((screen.getByLabelText(/像素/) as HTMLSelectElement).value).toBe("px1");
  await userEvent.setup().click(approve());
  await waitFor(() => expect(second.onApproved).toHaveBeenCalledTimes(1));
  expect(first.onApproved).not.toHaveBeenCalled();
});

it("a dirty manual draft and a failed post-PUT read both block; retry only repeats the read", async () => {
  renderList(); const user = userEvent.setup();
  await waitFor(() => expect(approve().disabled).toBe(false));
  await user.click(screen.getByRole("button", { name: /進階設定/ }));
  await user.click(screen.getByRole("button", { name: /新客組 ·/ }));
  const field = screen.getByLabelText(/落地頁網址/);
  await user.clear(field); await user.type(field, "https://example.com/chosen");
  await waitFor(() => expect(approve().disabled).toBe(true));
  vi.mocked(getCampaign).mockRejectedValueOnce(new Error("活動重讀失敗"));
  await user.click(screen.getByRole("button", { name: "儲存這組設定" }));
  expect((await screen.findByRole("alert")).textContent).toContain("設定已寫入，但活動資料讀不到");
  expect((field as HTMLInputElement).value).toBe("https://example.com/chosen");
  expect(approve().disabled).toBe(true);
  expect((screen.getByRole("button", { name: "取消變更" }) as HTMLButtonElement).disabled).toBe(true);
  await user.click(screen.getByRole("button", { name: "重新讀取設定" }));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  await waitFor(() => expect(approve().disabled).toBe(false));
  expect(saveManualSettings).toHaveBeenCalledTimes(1); expect(getCampaign).toHaveBeenCalledTimes(2);
});

it("a debounced valid settings draft blocks until PUT and a coherent new revision settle", async () => {
  const saved = deferred<LaunchSettingsView>();
  vi.mocked(saveLaunchSettings).mockReturnValue(saved.promise);
  renderList(); const user = userEvent.setup();
  await waitFor(() => expect(approve().disabled).toBe(false));
  await user.click(screen.getByRole("button", { name: /進階設定/ }));
  const utm = screen.getByLabelText(/UTM 追蹤參數/);
  fireEvent.change(utm, { target: { value: "utm_source=manual&utm_campaign=chosen" } });
  await waitFor(() => expect(approve().disabled).toBe(true));
  expect(saveLaunchSettings).not.toHaveBeenCalled();
  await waitFor(() => expect(saveLaunchSettings).toHaveBeenCalledTimes(1));
  const nextValues = { ...VALUES, utm: "utm_source=manual&utm_campaign=chosen" };
  vi.mocked(getPublish).mockResolvedValue(publish("revision-b", nextValues));
  vi.mocked(fetchLaunchView).mockResolvedValue(launch("revision-b", nextValues));
  vi.mocked(getLaunchSettings).mockResolvedValue(settings(nextValues));
  await act(async () => saved.resolve(settings(nextValues)));
  await waitFor(() => expect(approve().disabled).toBe(false));
  expect((utm as HTMLInputElement).value).toBe(nextValues.utm);
  await user.click(approve());
  expect(publishCampaign).toHaveBeenLastCalledWith("brd", "cmp", "manual", expect.objectContaining({ content_hash: "revision-b" }));
});

it("queued edits stay visible while earlier PUT and revision reads settle; only the last revision can approve", async () => {
  const first = deferred<LaunchSettingsView>();
  const second = deferred<LaunchSettingsView>();
  vi.mocked(saveLaunchSettings).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  renderList(); const user = userEvent.setup();
  await waitFor(() => expect(approve().disabled).toBe(false));
  await user.selectOptions(screen.getByLabelText(/像素/), "px2");
  await user.click(screen.getByRole("button", { name: /進階設定/ }));
  const utm = screen.getByLabelText(/UTM 追蹤參數/);
  fireEvent.change(utm, { target: { value: "utm_source=meta&utm_campaign=latest" } });
  fireEvent.blur(utm);
  expect(saveLaunchSettings).toHaveBeenCalledTimes(1);
  const lastValues = { ...VALUES, pixel_id: "px2", utm: "utm_source=meta&utm_campaign=latest" };
  await act(async () => first.resolve(settings({ ...VALUES, pixel_id: "px2" })));
  await waitFor(() => expect(saveLaunchSettings).toHaveBeenCalledTimes(2));
  expect(vi.mocked(saveLaunchSettings).mock.calls[1][2]).toEqual(lastValues);
  await waitFor(() => expect(getPublish).toHaveBeenCalledTimes(2));
  expect((utm as HTMLInputElement).value).toBe(lastValues.utm);
  expect((screen.getByLabelText(/像素/) as HTMLSelectElement).value).toBe("px2");
  expect(approve().disabled).toBe(true);
  vi.mocked(getPublish).mockResolvedValue(publish("last-revision", lastValues));
  vi.mocked(fetchLaunchView).mockResolvedValue(launch("last-revision", lastValues));
  vi.mocked(getLaunchSettings).mockResolvedValue(settings(lastValues));
  await act(async () => second.resolve(settings(lastValues)));
  await waitFor(() => expect(approve().disabled).toBe(false));
  await user.click(approve());
  expect(publishCampaign).toHaveBeenCalledWith("brd", "cmp", "manual", expect.objectContaining({ content_hash: "last-revision" }));
});

it.each(["newer", "older"])("a later successful child read has a visible read-only exit to a complete current pair before a new click (%s child)", async (direction) => {
  const child = deferred<LaunchSettingsView>();
  vi.mocked(getLaunchSettings).mockReturnValue(child.promise);
  if (direction === "older") {
    const newer = { ...VALUES, pixel_id: "px2" };
    vi.mocked(getPublish).mockResolvedValue(publish("newer-pair", newer));
    vi.mocked(fetchLaunchView).mockResolvedValue(launch("newer-pair", newer));
  }
  renderList(); const user = userEvent.setup();
  await waitFor(() => expect(fetchLaunchView).toHaveBeenCalledTimes(1));
  const laterValues = direction === "newer" ? { ...VALUES, pixel_id: "px2" } : VALUES;
  await act(async () => child.resolve(settings(laterValues)));
  await waitFor(() => expect((screen.getByLabelText(/像素/) as HTMLSelectElement).value).toBe(laterValues.pixel_id));
  expect(approve().disabled).toBe(true);
  expect(screen.getByText("投放設定與清單不是同一版，請重新讀取後再核准。")).toBeTruthy();
  expect(publishCampaign).not.toHaveBeenCalled();
  vi.mocked(getPublish).mockResolvedValue(publish("later-revision", laterValues));
  vi.mocked(fetchLaunchView).mockResolvedValue({ ...launch("later-revision", laterValues), summary: { ...launch().summary, daily_total: 600 } });
  vi.mocked(getLaunchSettings).mockResolvedValue(settings(laterValues));
  await user.click(screen.getByRole("button", { name: "重新讀取本版清單" }));
  await waitFor(() => expect(approve().disabled).toBe(false));
  expect(screen.getByRole("region", { name: "上架摘要" }).textContent).toContain("600");
  expect(publishCampaign).not.toHaveBeenCalled();
  await user.click(approve());
  expect(publishCampaign).toHaveBeenCalledWith("brd", "cmp", "manual", expect.objectContaining({ content_hash: "later-revision" }));
});

it("an explicit revision reread cannot discard a newer unsent draft while its child read is pending", async () => {
  const laterValues = { ...VALUES, pixel_id: "px2" };
  vi.mocked(getLaunchSettings).mockResolvedValue(settings(laterValues));
  renderList(); const user = userEvent.setup();
  const retry = await screen.findByRole("button", { name: "重新讀取本版清單" });
  const pendingRead = deferred<LaunchSettingsView>();
  vi.mocked(getLaunchSettings).mockReturnValue(pendingRead.promise);
  vi.mocked(getPublish).mockResolvedValue(publish("later-revision", laterValues));
  vi.mocked(fetchLaunchView).mockResolvedValue(launch("later-revision", laterValues));
  await user.click(retry);
  await user.click(screen.getByRole("button", { name: /進階設定/ }));
  const utm = screen.getByLabelText(/UTM 追蹤參數/);
  fireEvent.change(utm, { target: { value: "utm_source=meta&utm_campaign=unsent" } });
  await act(async () => pendingRead.resolve(settings(laterValues)));
  expect((utm as HTMLInputElement).value).toBe("utm_source=meta&utm_campaign=unsent");
  expect(approve().disabled).toBe(true);
  expect(saveLaunchSettings).not.toHaveBeenCalled();
  expect(publishCampaign).not.toHaveBeenCalled();
});
