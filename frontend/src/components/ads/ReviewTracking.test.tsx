import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import * as api from "@/lib/adsRuntimeApi";
import { ReviewTracking } from "./ReviewTracking";
import { RULES_FIXTURE, seedAdsRules } from "./patterns/rulesFixture";
// F50 Contract K: the org clock reads the workspace org zone; dates assert Asia/Taipei output, never the runner's.
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-10-01" }, orgs: [] } }) }));

vi.mock("@/lib/adsRuntimeApi", () => ({ getRuntime: vi.fn(), saveMonitor: vi.fn() }));
vi.mock("@/lib/auth", () => ({ getOrgId: () => "org" }));
function sample(): api.RuntimeData {
  return { monitors: [{ id: "m", entity_id: "ad", entity_name: "原 B", revision: 1, enabled: true, window_days: 7, cadence_days: 7, state: "waiting", next_check_at: "2026-09-20T00:00:00Z", last_checked_at: null, reason: "缺少完整日期，等待回補", review_id: "r", window: { start: "2026-09-10", end: "2026-09-16", previous_id: null } }], sources: [{ platform: "測試平台", source_account: "account", status: "partial", last_attempt_at: null, last_success_at: null, coverage: null, error: "權限已失效，請修復連線" }], health: [{ code: "budget_unknown", severity: "unknown", message: "目前餘額仍不確定", observed_at: null }], last_checked_at: null, last_bootstrap_at: null, budget: null, notice: "本機停機時無法追蹤，平台仍可能花費。" };
}
function page(brandId = "brand", entityId = "ad") { return <MemoryRouter><ReviewTracking brandId={brandId} campaignId="c" entityId={entityId} refreshKey="r" /></MemoryRouter>; }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(api.getRuntime).mockResolvedValue(sample()); });
it("將缺漏與下一步放在主要畫面，來源和設定收合", async () => {
  const user = userEvent.setup(); render(page());
  expect(await screen.findByText("缺少完整日期，等待回補")).toBeTruthy();
  expect(screen.getByText("目前餘額仍不確定")).toBeTruthy();
  expect(screen.queryByText("權限已失效，請修復連線")).toBeNull();
  await user.click(screen.getByRole("button", { name: "查看同步、恢復與追蹤設定" }));
  expect(screen.getByText("權限已失效，請修復連線")).toBeTruthy();
  expect(api.saveMonitor).not.toHaveBeenCalled();
});
it("保存後必須讀回，暫停檢討不假稱已停止投放", async () => {
  const user = userEvent.setup(); render(page());
  await screen.findByText("缺少完整日期，等待回補");
  await user.click(screen.getByRole("button", { name: "查看同步、恢復與追蹤設定" }));
  const updated = sample(); updated.monitors[0] = { ...updated.monitors[0], revision: 2, enabled: false, state: "paused" };
  vi.mocked(api.saveMonitor).mockResolvedValue({ monitor: updated.monitors[0] });
  vi.mocked(api.getRuntime).mockResolvedValue(updated);
  await user.click(screen.getByRole("button", { name: "暫停自動檢討" }));
  expect(await screen.findByText("追蹤條件已保存並重新讀回。")).toBeTruthy();
  expect(api.getRuntime).toHaveBeenCalledTimes(2);
  expect(api.saveMonitor).toHaveBeenCalledWith("brand", "c", "ad", { expected_revision: 1, enabled: false, window_days: 7, cadence_days: 7, reset_window: false }, expect.any(AbortSignal));
  expect(screen.getByText(/都不會停止平台花費/)).toBeTruthy();
});
it("回應遺失沒有假成功或自動重送，保留輸入供讀回處理", async () => {
  const user = userEvent.setup(); render(page()); await screen.findByText("缺少完整日期，等待回補");
  await user.click(screen.getByRole("button", { name: "查看同步、恢復與追蹤設定" }));
  await user.click(screen.getByRole("button", { name: "調整觀察與檢討天數" }));
  const input = screen.getByRole("spinbutton", { name: "觀察天數" }); await user.clear(input); await user.type(input, "10");
  vi.mocked(api.saveMonitor).mockRejectedValue(new Error("保存結果尚未確認，請先重新讀取。"));
  await user.click(screen.getByRole("button", { name: "保存追蹤條件" }));
  expect((await screen.findByRole("alert")).textContent).toContain("尚未確認");
  expect(screen.queryByText("追蹤條件已保存並重新讀回。")).toBeNull();
  expect((input as HTMLInputElement).value).toBe("10"); expect(api.saveMonitor).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: "讀取已保存版本（保留輸入）" }));
  await waitFor(() => expect(api.getRuntime).toHaveBeenCalledTimes(2));
  expect((input as HTMLInputElement).value).toBe("10"); expect(api.saveMonitor).toHaveBeenCalledTimes(1);
});
it("品牌切換不保留上一品牌的資料與操作對象", async () => {
  const { rerender } = render(page()); await screen.findByText("缺少完整日期，等待回補");
  vi.mocked(api.getRuntime).mockResolvedValue({ ...sample(), monitors: [], sources: [], health: [] });
  rerender(page("brand-other", "ad-other"));
  await waitFor(() => expect(screen.queryByText("缺少完整日期，等待回補")).toBeNull());
  expect(api.getRuntime).toHaveBeenLastCalledWith("brand-other", "c", expect.any(AbortSignal));
  expect(api.saveMonitor).not.toHaveBeenCalled();
});
// F50 Contract I (decision 11): the day range is the served `limits.review_days`, never a copy here.
async function typeWindow(value: string) {
  const user = userEvent.setup(); render(page()); await screen.findByText("缺少完整日期，等待回補");
  await user.click(screen.getByRole("button", { name: "查看同步、恢復與追蹤設定" }));
  await user.click(screen.getByRole("button", { name: "調整觀察與檢討天數" }));
  const input = screen.getByLabelText("觀察天數");
  await user.clear(input); await user.type(input, value);
  await user.click(screen.getByRole("button", { name: "保存追蹤條件" }));
}
it("an out-of-range day count prints the served range (a changed fixture changes the words)", async () => {
  await typeWindow("40");
  expect(await screen.findByText("觀察期與檢討間隔請填 1 至 31 天。")).toBeTruthy();
  expect(api.saveMonitor).not.toHaveBeenCalled();
});
it("the range follows the served limits", async () => {
  seedAdsRules({ ...RULES_FIXTURE, limits: { ...RULES_FIXTURE.limits, review_days: { min: 3, max: 14 } } });
  try {
    await typeWindow("20");
    expect(await screen.findByText("觀察期與檢討間隔請填 3 至 14 天。")).toBeTruthy();
    expect((screen.getByLabelText("觀察天數") as HTMLInputElement).max).toBe("14");
    expect(api.saveMonitor).not.toHaveBeenCalled();
  } finally { seedAdsRules(RULES_FIXTURE); }
});
it("before the rules load nothing is checked here: the typed value goes and the server's sentence comes back", async () => {
  seedAdsRules(null);
  vi.mocked(api.saveMonitor).mockRejectedValue(new Error("觀察窗與重看間隔請選一至三十一日。"));
  try {
    await typeWindow("40");
    expect(await screen.findByText("觀察窗與重看間隔請選一至三十一日。")).toBeTruthy();
    expect(api.saveMonitor).toHaveBeenCalledWith("brand", "c", "ad", expect.objectContaining({ window_days: 40 }), expect.any(AbortSignal));
  } finally { seedAdsRules(RULES_FIXTURE); }
});
