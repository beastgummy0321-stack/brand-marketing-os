import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ManualHandoffPanel } from "./ManualHandoffPanel";
import { assignPlannedMaterial, getHandoff, getPlannedMaterials, HandoffRequestRejected, reapproveLaunch, revertLaunch, type HandoffItem, type HandoffWorkspace, type LaunchStale } from "@/lib/adsHandoffApi";
import { existingCampaigns, externalView } from "@/lib/adsExternalApi";

vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org" }) }));
vi.mock("@/lib/adsHandoffApi", async () => ({ ...await vi.importActual("@/lib/adsHandoffApi"), getHandoff: vi.fn(), reapproveLaunch: vi.fn(), revertLaunch: vi.fn(), getPlannedMaterials: vi.fn(), assignPlannedMaterial: vi.fn(), checkHandoff: vi.fn(), reportHandoff: vi.fn() }));
vi.mock("@/lib/adsExternalApi", () => ({ existingCampaigns: vi.fn(), externalView: vi.fn() }));

// Realistic shape: a long campaign name, a budget change, a renamed ad, a revised material, several verified items.
const SET = "acs_launch_v1";
const item = (id: string, planned_kind: string, name: string, status: HandoffItem["status"] = "pending", change_set_id = SET): HandoffItem => ({
  id, name, planned_kind, planned_id: `plan_${id}`, status, change_set_id, parent_item_id: null, expected_parent_name: null, placement_id: null, placement_revision: null,
  entity_id: status === "confirmed" ? `ent_${id}` : null, platform: null, source_account: null, native_kind: null, native_id: null, reported_at: null, observed_at: null,
  entity_exists: status === "confirmed", setting_matches: status === "confirmed" ? true : null, material_evidence: "unknown", expected_json: {}, evidence_json: {},
});
const items = [
  item("i1", "campaign", "9/15~9/30廣告日常排程，搭配中秋活動優惠，滿3000送月餅禮盒，到9/30為止", "confirmed"),
  item("i2", "group", "探索｜輕巧高強度生活", "confirmed"),
  item("i3", "ad", "不用配水也能隨手補給", "confirmed"),
  item("i4", "group", "再行銷｜中秋回訪優惠", "confirmed"),
  item("i5", "ad", "中秋滿三千送月餅禮盒", "confirmed"),
  item("i6", "ad", "全館九五折至九月三十日"),
  item("i7", "ad", "回來帶走適合日常的補給"),
];
const hash = "a".repeat(64);
const stale = (overrides: Partial<LaunchStale> = {}): LaunchStale => ({
  change_set_id: SET, approved_at: "2026-09-20T06:05:00Z", changed_at: "2026-09-22T07:10:00Z", content_hash: hash, unchanged_count: 4, revertible: true, revert_blocker: null,
  diff: [
    { kind: "group", item_id: "i4", name: "再行銷｜中秋回訪優惠", field: "daily_budget", field_label: "每日預算", before: 580, after: 750.5 },
    { kind: "ad", item_id: "i6", name: "全館九五折至九月三十日・中秋限定加碼", field: "name", field_label: "廣告名稱", before: "全館九五折至九月三十日", after: "全館九五折至九月三十日・中秋限定加碼" },
  ],
  ...overrides,
});
const workspace = (launch: LaunchStale | null, list = items): HandoffWorkspace => ({ items: list, items_truncated: false, ready_placements: [], destinations: [], destinations_truncated: false, launch_stale: launch, notice: "人工交接不代表平台已投遞。", settings_readback: null });
const view = () => <MemoryRouter><ManualHandoffPanel brandId="brand" campaignId="campaign" mode="items" /></MemoryRouter>;
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getHandoff).mockResolvedValue(workspace(stale()));
  vi.mocked(existingCampaigns).mockResolvedValue({ sources: [], platform: "fixture", source_account: "account", items: [], next_cursor: null, job: null });
  vi.mocked(externalView).mockResolvedValue({ entities: [], observations: [], next_entity_cursor: null, next_observation_cursor: null, window: { start: "2026-09-01", end: "2026-09-19" }, connections: [], sync: {}, coverage: {} });
});

describe("stale launch", () => {
  it("shows approved → now, keeps verified items and locks per-item checks until a decision", async () => {
    render(view());
    expect(await screen.findByText("核准後方案又改過 2 處，清單先停在這裡")).toBeTruthy();
    const diff = screen.getByRole("region", { name: "核准時 → 現在" });
    expect(within(diff).getByText("750.5")).toBeTruthy();
    expect(within(diff).getByText("580")).toBeTruthy();
    expect(within(diff).getByText("其他 4 項沒有變")).toBeTruthy();
    const progress = screen.getByRole("region", { name: "核對進度" });
    expect(within(progress).getByRole("heading", { name: "4／7 已核對" })).toBeTruthy();
    expect(within(progress).getAllByText("✓ 已核對")).toHaveLength(4);
    expect(within(progress).getAllByText("有變更")).toHaveLength(2);
    expect(within(progress).getAllByText("等重新核准")).toHaveLength(1);
    // No per-item check while the launch is stale.
    expect(screen.queryByRole("button", { name: /讀回並核對此物件|重新讀回核對|我已到平台操作/ })).toBeNull();
    expect(screen.queryByLabelText("選擇這次要核對的項目", { exact: false })).toBeNull();
  });

  it("re-approves with the content hash and reports success only after the server answers", async () => {
    const answer = deferred<HandoffWorkspace>();
    vi.mocked(reapproveLaunch).mockReturnValue(answer.promise);
    render(view());
    await userEvent.click(await screen.findByRole("button", { name: "用現在的方案重新核准 →" }));
    expect(reapproveLaunch).toHaveBeenCalledWith("brand", "campaign", { change_set_id: SET, content_hash: hash }, expect.any(AbortSignal));
    expect(screen.getByRole("button", { name: "重新核准中…" })).toHaveProperty("disabled", true);
    expect(screen.queryByText(/已用現在的方案重新核准/)).toBeNull();
    vi.mocked(getHandoff).mockResolvedValue(workspace(null));
    answer.resolve(workspace(null));
    expect(await screen.findByText("已用現在的方案重新核准；沒有變的已核對項目保留結果。")).toBeTruthy();
    await waitFor(() => expect(getHandoff).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(/核准後方案又改過/)).toBeNull();
  });

  it("reloads and says the plan changed again when re-approval is refused (409)", async () => {
    vi.mocked(reapproveLaunch).mockRejectedValue(new HandoffRequestRejected("計畫、素材或月份已改變，請重新檢視後核准。"));
    render(view());
    const button = await screen.findByRole("button", { name: "用現在的方案重新核准 →" });
    vi.mocked(getHandoff).mockResolvedValue(workspace(stale({ content_hash: "b".repeat(64), diff: [...stale().diff, { kind: "campaign", item_id: "i1", name: "活動", field: "end_date", field_label: "結束日期", before: "2026-09-30", after: "2026-10-05" }] })));
    await userEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "沒有完成：計畫、素材或月份已改變，請重新檢視後核准。已重新載入最新的差異，請再看一次。");
    expect(await screen.findByText("核准後方案又改過 3 處，清單先停在這裡")).toBeTruthy();
    expect(getHandoff).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/已用現在的方案重新核准/)).toBeNull();
  });

  it("reverts only after one confirm that lists each field now → approved", async () => {
    vi.mocked(revertLaunch).mockResolvedValue(workspace(null));
    render(view());
    await userEvent.click(await screen.findByRole("button", { name: "改回核准時的設定" }));
    expect(revertLaunch).not.toHaveBeenCalled();
    const sheet = screen.getByRole("alertdialog", { name: "改回核准時的設定？" });
    expect(within(sheet).getByText("每日預算：750.5 → 580")).toBeTruthy();
    expect(within(sheet).getByText("廣告名稱：全館九五折至九月三十日・中秋限定加碼 → 全館九五折至九月三十日")).toBeTruthy();
    await userEvent.click(within(sheet).getByRole("button", { name: "取消" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "改回核准時的設定" }));
    vi.mocked(getHandoff).mockResolvedValue(workspace(null));
    await userEvent.click(screen.getByRole("button", { name: "改回，沿用原本的核准" }));
    expect(revertLaunch).toHaveBeenCalledWith("brand", "campaign", { change_set_id: SET, content_hash: hash }, expect.any(AbortSignal));
    expect(await screen.findByText("已改回核准時的設定；原本的核准繼續有效。")).toBeTruthy();
  });

  it("shows the revert blocker in place of the revert action", async () => {
    vi.mocked(getHandoff).mockResolvedValue(workspace(stale({ revertible: false, revert_blocker: "核准後新增或移除了投放組或廣告，無法自動改回；請用現在的方案重新核准。" })));
    render(view());
    expect(await screen.findByText("核准後新增或移除了投放組或廣告，無法自動改回；請用現在的方案重新核准。")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "改回核准時的設定" })).toBeNull();
    expect(screen.getByRole("button", { name: "用現在的方案重新核准 →" })).toHaveProperty("disabled", false);
    expect(revertLaunch).not.toHaveBeenCalled();
  });

  it("re-points a revised material before re-approval can run", async () => {
    const material = stale({ revertible: false, revert_blocker: "核准時的素材版本已修訂或不存在，無法改回；請用現在的方案重新核准。", diff: [{ kind: "ad", item_id: "i5", name: "中秋滿三千送月餅禮盒", field: "material", field_label: "素材", before: "mooncake.png・第 2 版", after: "mooncake.png・第 2 版（已修訂或未確認）" }] });
    vi.mocked(getHandoff).mockResolvedValue(workspace(material));
    const planned = { id: "plan_i5", name: "中秋滿三千送月餅禮盒", group_id: "g", group_name: "再行銷｜中秋回訪優惠", placement_id: "plc_moon", placement_revision: 2, filename: "mooncake.png", copy_fields: {}, reason: null };
    vi.mocked(getPlannedMaterials).mockResolvedValue({ planned_ads: [{ ...planned, assignment_status: "stale" }], ready_placements: [{ id: "plc_moon", revision: 3, filename: "mooncake.png", copy_fields: {} }] });
    vi.mocked(assignPlannedMaterial).mockResolvedValue({ planned_ads: [{ ...planned, placement_revision: 3, assignment_status: "confirmed" }], ready_placements: [] });
    render(view());
    const repoint = await screen.findByRole("button", { name: "改用第 3 版" });
    expect(screen.getByRole("button", { name: "用現在的方案重新核准 →" })).toHaveProperty("disabled", true);
    expect(screen.getByText("先換成確認過的素材版本，才能重新核准")).toBeTruthy();
    vi.mocked(getPlannedMaterials).mockResolvedValue({ planned_ads: [{ ...planned, placement_revision: 3, assignment_status: "confirmed" }], ready_placements: [] });
    vi.mocked(getHandoff).mockResolvedValue(workspace({ ...material, content_hash: "c".repeat(64), diff: [{ ...material.diff[0], after: "mooncake.png・第 3 版" }] }));
    await userEvent.click(repoint);
    expect(assignPlannedMaterial).toHaveBeenCalledWith("brand", "campaign", "plan_i5", { placement_id: "plc_moon", revision: 3 }, expect.any(AbortSignal));
    expect(await screen.findByText("mooncake.png・第 3 版")).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("button", { name: "用現在的方案重新核准 →" })).toHaveProperty("disabled", false));
    expect(reapproveLaunch).not.toHaveBeenCalled();
  });

  it("is absent while the approved launch still matches the plan", async () => {
    vi.mocked(getHandoff).mockResolvedValue(workspace(null, [item("i6", "ad", "全館九五折至九月三十日")]));
    render(view());
    expect(await screen.findByRole("article", { name: "交接 全館九五折至九月三十日" })).toBeTruthy();
    expect(screen.queryByText(/核准後方案又改過/)).toBeNull();
    expect(screen.queryByRole("button", { name: "用現在的方案重新核准 →" })).toBeNull();
  });

  it("keeps other handoffs workable while the launch is stale", async () => {
    vi.mocked(getHandoff).mockResolvedValue(workspace(stale(), [...items, item("n1", "ad", "B2 新增廣告", "pending", "acs_new_ad")]));
    render(view());
    expect(await screen.findByText("核准後方案又改過 2 處，清單先停在這裡")).toBeTruthy();
    const row = await screen.findByRole("article", { name: "交接 B2 新增廣告" });
    expect(within(row).getByRole("button", { name: "我已到平台操作" })).toHaveProperty("disabled", false);
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });
});
