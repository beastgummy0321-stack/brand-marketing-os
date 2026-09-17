import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ManualSettings } from "./ManualSettings";
import { saveManualSettings } from "@/lib/adsLaunchApi";

vi.mock("@/lib/adsLaunchApi", () => ({ saveManualSettings: vi.fn() }));
vi.mock("@/lib/adsApi", () => ({ getCampaign: vi.fn() }));

it("keeps entered audience settings visible on save failure and sends the right group", async () => {
  vi.mocked(saveManualSettings).mockRejectedValueOnce(new Error("連線中斷，請重試"));
  render(<ManualSettings brandId="b1" campaign={{ id: "c1", status: "ready", manual_handoff: {
    fields: [{ key: "audience_source", label: "受眾來源", section: "受眾", required: true }],
    pending_count: 1, groups: [{ id: "g1", name: "再行銷", status: "待補設定", values: {},
      missing: ["受眾来源"], saved_at: null, saved_by: null, ads: [] }],
  } }} onSaved={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "人工上架設定與平台對應" }));
  await userEvent.click(screen.getByRole("button", { name: "再行銷 · 待補設定" }));
  await userEvent.type(screen.getByRole("textbox", { name: "受眾來源 *" }), "網站訪客30天");
  await userEvent.click(screen.getByRole("button", { name: "儲存這組設定" }));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.getByDisplayValue("網站訪客30天")).toBeTruthy();
  expect(saveManualSettings).toHaveBeenCalledWith("b1", "c1", "g1", { audience_source: "網站訪客30天" });
});
