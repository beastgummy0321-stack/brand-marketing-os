import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { NewCampaignPage } from "./NewCampaignPage";
import { createCampaign } from "@/lib/adsApi";
import { readDraft } from "./campaignDraft";
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "u:o" }) }));
vi.mock("@/lib/adsApi", () => ({ createCampaign: vi.fn() }));
function view(brandId: string) { return render(<MemoryRouter><NewCampaignPage brandId={brandId} /></MemoryRouter>); }
beforeEach(() => { sessionStorage.clear(); });
describe("campaign draft", () => {
  it("建立頁只保留一次流程說明與必要輸入", () => {
    view("simple");
    expect(screen.getByLabelText("你這次想做到什麼？")).toBeTruthy();
    expect(screen.getByText(/幫你整理投放策略、預算、素材與排程/)).toBeTruthy();
    expect(screen.queryByText("行銷駕駛艙會自動幫你整理")).toBeNull();
  });
  it("restores fields after leaving and isolates another brand", async () => {
    const user = userEvent.setup();
    const first = view("a");
    await user.type(screen.getByLabelText("你這次想做到什麼？"), "秋季新品");
    await user.click(screen.getByRole("button", { name: /預算上限/ }));
    await user.type(screen.getByLabelText("預算上限"), "30000");
    first.unmount();
    const other = view("b");
    expect(screen.getByLabelText("你這次想做到什麼？")).toHaveProperty("value", "");
    other.unmount();
    view("a");
    expect(screen.getByLabelText("你這次想做到什麼？")).toHaveProperty("value", "秋季新品");
    expect(screen.getByLabelText("預算上限")).toHaveProperty("value", "30000");
  });
  it("retains a failed submission and clears only after success", async () => {
    const user = userEvent.setup();
    vi.mocked(createCampaign).mockRejectedValueOnce(new Error("離線"));
    view("save");
    await user.type(screen.getByLabelText("你這次想做到什麼？"), "新品銷售");
    await user.click(screen.getByRole("button", { name: "產生建議" }));
    expect(await screen.findByText("離線")).toBeTruthy();
    expect(readDraft("campaign-draft:u:o:save").goalText).toBe("新品銷售");
    vi.mocked(createCampaign).mockResolvedValue({ id: "draft", parsed: true } as Awaited<ReturnType<typeof createCampaign>>);
    await user.click(screen.getByRole("button", { name: "產生建議" }));
    await waitFor(() => expect(readDraft("campaign-draft:u:o:save").goalText).toBe(""));
  });
});
