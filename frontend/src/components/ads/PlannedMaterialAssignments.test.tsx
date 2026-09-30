import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { PlannedMaterialAssignments } from "./PlannedMaterialAssignments";
import { assignPlannedMaterial, getPlannedMaterials, type PlannedMaterialWorkspace } from "@/lib/adsHandoffApi";
import { uploadIntoSlot } from "@/lib/adsSlotsApi";

vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "u:o" }) }));
vi.mock("@/lib/adsHandoffApi", () => ({ assignPlannedMaterial: vi.fn(), getPlannedMaterials: vi.fn() }));
vi.mock("@/lib/adsSlotsApi", () => ({ uploadIntoSlot: vi.fn() }));
type Placed = Awaited<ReturnType<typeof uploadIntoSlot>>;
const placed = (confirmed_at: string | null, pending_reason = ""): Placed =>
  ({ placement: { id: "slot-placement", revision: 1, confirmed_at, pending_reason }, slots: { ready: 0, total: 1, groups: [], requests: [], requests_truncated: false } }) as unknown as Placed;
const empty: PlannedMaterialWorkspace = {
  planned_ads: [{ id: "ad", name: "首次廣告", group_id: "group", group_name: "首檔投放組", placement_id: null, placement_revision: null, assignment_status: "unassigned", filename: null, copy_fields: {}, reason: null }],
  ready_placements: [{ id: "placement", revision: 3, filename: "已完成素材.png", copy_fields: { headline: "已確認標題", body: "已確認內文" } }],
};
const confirmed: PlannedMaterialWorkspace = { ...empty, planned_ads: [{ ...empty.planned_ads[0], placement_id: "placement", placement_revision: 3, filename: "已完成素材.png", assignment_status: "confirmed" }] };
const view = (brandId = "brand") => <MemoryRouter><PlannedMaterialAssignments brandId={brandId} campaignId="same-campaign" /></MemoryRouter>;
beforeEach(() => { vi.clearAllMocks(); vi.mocked(getPlannedMaterials).mockResolvedValue(empty); });

it("requires explicit ad and confirmed-version choices, places it through the slot upload, and reopens the persisted mapping", async () => {
  vi.mocked(uploadIntoSlot).mockResolvedValue(placed("2026-09-30T08:00:00Z"));
  const first = render(view());
  const ad = await screen.findByRole("combobox", { name: "計畫中的廣告" });
  expect(ad).toHaveProperty("value", "");
  expect(screen.getByRole("button", { name: "保存素材指派" })).toHaveProperty("disabled", true);
  await userEvent.selectOptions(ad, "ad");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "已確認成品版本" }), "placement");
  expect(screen.getByText("已確認內文")).toBeTruthy();
  vi.mocked(getPlannedMaterials).mockResolvedValue(confirmed);
  await userEvent.click(screen.getByRole("button", { name: "保存素材指派" }));
  // F41-I01: one rule set with the slot upload (the ad's workbench copy rides in); the workspace is re-read after it.
  expect(uploadIntoSlot).toHaveBeenCalledWith("brand", "same-campaign", "ad", { placement_id: "placement" }, expect.any(AbortSignal));
  expect(await screen.findByText(/已指派確認版本 · 已完成素材.png · 版本 3/)).toBeTruthy();
  expect(screen.getByText("素材版本已指派，首次上架清單會核對這份對應。")).toBeTruthy();
  first.unmount();
  vi.mocked(getPlannedMaterials).mockResolvedValue(confirmed);
  render(view());
  expect(await screen.findByText(/已指派確認版本 · 已完成素材.png · 版本 3/)).toBeTruthy();
  expect(uploadIntoSlot).toHaveBeenCalledTimes(1);
  expect(assignPlannedMaterial).not.toHaveBeenCalled();
});
it("says the slot still waits when the placed version is not confirmed yet", async () => {
  vi.mocked(uploadIntoSlot).mockResolvedValue(placed(null, "請補活動目標，才能確認此批用途"));
  render(view());
  await userEvent.selectOptions(await screen.findByRole("combobox", { name: "計畫中的廣告" }), "ad");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "已確認成品版本" }), "placement");
  await userEvent.click(screen.getByRole("button", { name: "保存素材指派" }));
  expect(await screen.findByText("已放進「首次廣告」這一格；請補活動目標，才能確認此批用途。")).toBeTruthy();
  expect(screen.getByText("尚未指派")).toBeTruthy();
  expect(screen.queryByText(/素材版本已指派/)).toBeNull();
});
it("shows stale mappings and allows an explicit unlink without inventing a replacement", async () => {
  vi.mocked(getPlannedMaterials).mockResolvedValue({ ...confirmed, planned_ads: [{ ...confirmed.planned_ads[0], assignment_status: "stale", reason: "素材已改版" }] });
  vi.mocked(assignPlannedMaterial).mockResolvedValue(empty);
  render(view());
  expect(await screen.findByText("素材已改版")).toBeTruthy();
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "計畫中的廣告" }), "ad");
  await userEvent.click(screen.getByRole("button", { name: "解除此廣告的素材指派" }));
  expect(assignPlannedMaterial).toHaveBeenCalledWith("brand", "same-campaign", "ad", { placement_id: null, revision: null }, expect.any(AbortSignal));
  expect(await screen.findByText("尚未指派")).toBeTruthy();
});
it("shows the slot upload's refusal verbatim and keeps the unassigned state", async () => {
  vi.mocked(uploadIntoSlot).mockRejectedValue(new Error("這則廣告已在平台上；要換素材請用「換掉這一則」。"));
  render(view());
  await userEvent.selectOptions(await screen.findByRole("combobox", { name: "計畫中的廣告" }), "ad");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "已確認成品版本" }), "placement");
  await userEvent.click(screen.getByRole("button", { name: "保存素材指派" }));
  expect(await screen.findByText("這則廣告已在平台上；要換素材請用「換掉這一則」。")).toBeTruthy();
  expect(screen.getByText("尚未指派")).toBeTruthy();
  expect(screen.queryByText(/素材版本已指派/)).toBeNull();
});
it("aborts an old brand read and does not show its late mapping for another brand", async () => {
  let resolveOld!: (data: PlannedMaterialWorkspace) => void;
  vi.mocked(getPlannedMaterials).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
  const ui = render(view("old"));
  const signal = vi.mocked(getPlannedMaterials).mock.calls[0][2];
  ui.rerender(view("new"));
  expect(signal?.aborted).toBe(true);
  await screen.findByText("尚未指派");
  resolveOld(confirmed);
  await waitFor(() => expect(screen.queryByText(/已指派確認版本/)).toBeNull());
});
