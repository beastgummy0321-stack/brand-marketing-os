import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { ToolsStep } from "./ToolsStep";
import { fetchMetaAccounts } from "@/lib/metaApi";

vi.mock("@/lib/intakeApi", () => ({
  fetchIntakeTools: vi.fn().mockResolvedValue({ conversion_goal: "purchase", conversion_goal_options: [{ key: "purchase", label: "購買" }], bound_account_ids: ["bound"] }),
  saveConversionGoal: vi.fn(),
}));
vi.mock("@/lib/metaApi", () => ({
  fetchMetaAccounts: vi.fn().mockResolvedValue({ token_tail: "fixture", accounts: [{ id: "bound", name: "已連線測試帳戶" }] }),
  bindMetaAccount: vi.fn(), connectMetaToken: vi.fn(), fetchMetaBackfillStatus: vi.fn(), startMetaBackfill: vi.fn(),
}));

it("reuses the saved account and goal, lets the user start a plan, and only continues research on request", async () => {
  const next = vi.fn();
  render(<MemoryRouter><ToolsStep brandId="cold" onNext={next} /></MemoryRouter>);
  expect((await screen.findByRole("link", { name: "先建立投放計畫" })).getAttribute("href")).toBe("/brands/cold/ads/new");
  expect(screen.getByRole("radio", { name: "購買" })).toHaveProperty("checked", true);
  expect(screen.getByText(/已指定給這個品牌：已連線測試帳戶/)).toBeTruthy();
  expect(next).not.toHaveBeenCalled();
  expect(screen.queryByPlaceholderText("貼上 Meta 存取權杖")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "繼續品牌研究（選用）" }));
  expect(next).toHaveBeenCalledTimes(1);
});

it("keeps drafting available when account lookup fails without claiming connection is confirmed", async () => {
  vi.mocked(fetchMetaAccounts).mockRejectedValueOnce(new Error("權限已失效"));
  const next = vi.fn();
  render(<MemoryRouter><ToolsStep brandId="cold" onNext={next} /></MemoryRouter>);
  expect((await screen.findByRole("link", { name: "先建立投放計畫" })).getAttribute("href")).toBe("/brands/cold/ads/new");
  expect(screen.getByText("權限已失效")).toBeTruthy();
  expect(screen.getByText(/目前無法確認帳戶與目標設定/)).toBeTruthy();
  expect(screen.queryByText(/已指定給這個品牌/)).toBeNull();
  expect(next).not.toHaveBeenCalled();
});
