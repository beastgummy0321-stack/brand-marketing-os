import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { PlannedMaterialAssignments } from "./PlannedMaterialAssignments";
import { assignPlannedMaterial, getPlannedMaterials, type PlannedMaterialWorkspace } from "@/lib/adsHandoffApi";

vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "u:o" }) }));
vi.mock("@/lib/adsHandoffApi", () => ({ assignPlannedMaterial: vi.fn(), getPlannedMaterials: vi.fn() }));
const empty: PlannedMaterialWorkspace = {
  planned_ads: [{ id: "ad", name: "首次廣告", group_id: "group", group_name: "首檔投放組", placement_id: null, placement_revision: null, assignment_status: "unassigned", filename: null, copy_fields: {}, reason: null }],
  ready_placements: [{ id: "placement", revision: 3, filename: "已完成素材.png", copy_fields: { headline: "已確認標題", body: "已確認內文" } }],
};
const confirmed: PlannedMaterialWorkspace = { ...empty, planned_ads: [{ ...empty.planned_ads[0], placement_id: "placement", placement_revision: 3, filename: "已完成素材.png", assignment_status: "confirmed" }] };
const view = (brandId = "brand") => <MemoryRouter><PlannedMaterialAssignments brandId={brandId} campaignId="same-campaign" /></MemoryRouter>;
beforeEach(() => { vi.clearAllMocks(); vi.mocked(getPlannedMaterials).mockResolvedValue(empty); });

it("requires explicit ad and confirmed-version choices, saves the revision, and reopens the persisted mapping", async () => {
  vi.mocked(assignPlannedMaterial).mockResolvedValue(confirmed);
  const first = render(view());
  const ad = await screen.findByRole("combobox", { name: "計畫中的廣告" });
  expect(ad).toHaveProperty("value", "");
  expect(screen.getByRole("button", { name: "保存素材指派" })).toHaveProperty("disabled", true);
  await userEvent.selectOptions(ad, "ad");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "已確認成品版本" }), "placement");
  expect(screen.getByText("已確認內文")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "保存素材指派" }));
  expect(assignPlannedMaterial).toHaveBeenCalledWith("brand", "same-campaign", "ad", { placement_id: "placement", revision: 3 }, expect.any(AbortSignal));
  expect(await screen.findByText(/已指派確認版本 · 已完成素材.png · 版本 3/)).toBeTruthy();
  first.unmount();
  vi.mocked(getPlannedMaterials).mockResolvedValue(confirmed);
  render(view());
  expect(await screen.findByText(/已指派確認版本 · 已完成素材.png · 版本 3/)).toBeTruthy();
  expect(assignPlannedMaterial).toHaveBeenCalledTimes(1);
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
it("keeps the unassigned state when an in-progress approval rejects the edit", async () => {
  vi.mocked(assignPlannedMaterial).mockRejectedValue(new Error("請先處理已核准交接"));
  render(view());
  await userEvent.selectOptions(await screen.findByRole("combobox", { name: "計畫中的廣告" }), "ad");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "已確認成品版本" }), "placement");
  await userEvent.click(screen.getByRole("button", { name: "保存素材指派" }));
  expect(await screen.findByText("請先處理已核准交接")).toBeTruthy();
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
