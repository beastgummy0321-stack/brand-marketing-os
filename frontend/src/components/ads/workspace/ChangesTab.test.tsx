import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "@/lib/adsWorkspaceApi";
import { ChangesTab } from "./ChangesTab";
// F50 Contract K: the org clock reads the workspace org zone; dates assert Asia/Taipei output, never the runner's.
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-10-01" }, orgs: [] } }) }));

vi.mock("@/lib/adsWorkspaceApi", async (importOriginal) => ({
  ...await importOriginal<typeof api>(), getCampaignTimeline: vi.fn(),
}));

// Real-shaped rows (Contract E `timeline.rows`), newest first, one per state.
function row(overrides: Partial<api.TimelineRow>): api.TimelineRow {
  return { change_set_id: "cs_x", title: "改文案：晨光隨行杯・日常出發", at: "2026-09-21T08:30:00Z", state: "verified",
    reason: null, checked: 1, total: 1, version: null, ...overrides };
}
const ROWS: api.TimelineRow[] = [
  row({ change_set_id: "cs_draft", title: "暫停「提問式貼文・早晨版」", at: "2026-09-23T02:10:00Z", state: "draft", checked: 0, total: 1 }),
  row({ change_set_id: "cs_platform", title: "加預算：廣告組 A 每日 300 → 400", at: "2026-09-22T06:05:00Z", state: "platform", checked: 0, total: 2 }),
  row({ change_set_id: "cs_check", title: "清理：關 3 則", at: "2026-09-22T03:00:00Z", state: "check", checked: 1, total: 3 }),
  row({ change_set_id: "cs_verified", title: "改文案：晨光隨行杯・日常出發", at: "2026-09-21T08:30:00Z", state: "verified", checked: 1, total: 1 }),
  row({ change_set_id: "cs_rejected", title: "清理：關 1 則（再行銷・兩入組）", at: "2026-09-15T02:20:00Z", state: "rejected", reason: "兩入組還在檔期", checked: 0, total: 1 }),
  row({ change_set_id: "cs_launch", title: "首次上架", at: "2026-09-08T01:40:00Z", state: "stale", checked: 4, total: 11, version: 2 }),
];

function page(props: Partial<Parameters<typeof ChangesTab>[0]> = {}) {
  return <MemoryRouter><ChangesTab brandId="brd_a" campaignId="cmp_1" {...props} /></MemoryRouter>;
}
const item = (title: string) => screen.getByText(title, { selector: "b" }).closest("li") as HTMLElement;
const base = "/brands/brd_a/ads/campaigns/cmp_1/changes";

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.getCampaignTimeline).mockResolvedValue({ rows: ROWS, truncated: false });
});

describe("ChangesTab 變更紀錄", () => {
  it("六種狀態各有自己的字、進度與去處", async () => {
    render(page());
    await screen.findByRole("list", { name: "變更紀錄" });
    expect(screen.getAllByRole("listitem").map((li) => li.getAttribute("data-variant")))
      .toEqual(["draft", "platform", "check", "verified", "rejected", "stale"]);

    const draft = within(item("暫停「提問式貼文・早晨版」"));
    expect(draft.getByText("還沒核准")).toBeTruthy();
    expect(draft.getByRole("link", { name: /打開/ }).getAttribute("href")).toBe(`${base}/cs_draft/confirm`);
    expect(draft.getByText("0／1 已核對")).toBeTruthy();

    const platform = within(item("加預算：廣告組 A 每日 300 → 400"));
    expect(platform.getByText("等你到平台完成")).toBeTruthy();
    expect(platform.getByRole("link", { name: /打開/ }).getAttribute("href")).toBe(`${base}/cs_platform/handoff`);

    const check = within(item("清理：關 3 則"));
    expect(check.getByText("等核對")).toBeTruthy();
    expect(check.getByText("1／3 已核對")).toBeTruthy();
    expect(check.getByRole("link", { name: /去核對/ }).getAttribute("href")).toBe(`${base}/cs_check/verify`);
    expect(item("清理：關 3 則").querySelectorAll('[data-slot="progress-segments"] i[data-state="ok"]')).toHaveLength(1);

    const verified = within(item("改文案：晨光隨行杯・日常出發"));
    expect(verified.getByText("✓ 已核對")).toBeTruthy();
    expect(verified.getByText("09/21 16:30")).toBeTruthy();
    expect(verified.getByRole("link", { name: /打開/ }).getAttribute("href")).toBe(`${base}/cs_verified/verify`);

    const rejected = within(item("清理：關 1 則（再行銷・兩入組）"));
    expect(rejected.getByText("已拒絕・不用處理")).toBeTruthy();
    expect(rejected.getByText("原因：兩入組還在檔期")).toBeTruthy();
    expect(rejected.queryByText(/已核對$/)).toBeNull();
    expect(rejected.queryByRole("link")).toBeNull();
    expect(rejected.queryByRole("button")).toBeNull();

    const stale = within(item("首次上架"));
    expect(stale.getByText("核准後方案改過")).toBeTruthy();
    expect(stale.getByText("4／11 已核對")).toBeTruthy();
    expect(item("首次上架").querySelectorAll('i[data-state="changed"]')).toHaveLength(7);
    expect(screen.queryByText(/更早的變更沒有顯示/)).toBeNull();
  });

  it("步驟頁畫不出的清單（上架、多項）在進階區打開", async () => {
    const user = userEvent.setup();
    const onOpenInFold = vi.fn();
    render(page({ inFold: (r) => r.version !== null, onOpenInFold }));
    await user.click(await within(await screen.findByRole("list", { name: "變更紀錄" })).findByRole("button", { name: "打開：首次上架" }));
    expect(onOpenInFold).toHaveBeenCalledWith(expect.objectContaining({ change_set_id: "cs_launch" }));
    expect(within(item("清理：關 3 則")).getByRole("link", { name: /去核對/ })).toBeTruthy();
  });

  it("超過上限時說只列出最近幾批", async () => {
    vi.mocked(api.getCampaignTimeline).mockResolvedValue({ rows: ROWS.slice(0, 2), truncated: true });
    render(page());
    expect(await screen.findByText("只列出最近 2 批，更早的變更沒有顯示。")).toBeTruthy();
  });

  it("讀取失敗是讀取失敗，不是空的紀錄；重試再讀一次", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getCampaignTimeline).mockRejectedValueOnce(new Error("讀取變更紀錄失敗。"));
    render(page());
    const failed = await screen.findByRole("alert");
    expect(within(failed).getByText("讀取失敗")).toBeTruthy();
    expect(screen.queryByText("這個活動還沒有變更")).toBeNull();
    await user.click(within(failed).getByRole("button", { name: "重試" }));
    expect(await screen.findByRole("list", { name: "變更紀錄" })).toBeTruthy();
    expect(api.getCampaignTimeline).toHaveBeenCalledTimes(2);
  });

  it("沒有任何變更時說「這個活動還沒有變更」", async () => {
    vi.mocked(api.getCampaignTimeline).mockResolvedValue({ rows: [], truncated: false });
    render(page());
    expect(await screen.findByText("這個活動還沒有變更")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "變更紀錄" })).toBeNull();
  });

  it("呼叫端改過東西後重讀，舊的紀錄留在畫面上", async () => {
    const view = render(page({ refreshKey: 0 }));
    await screen.findByRole("list", { name: "變更紀錄" });
    view.rerender(page({ refreshKey: 1 }));
    expect(screen.getByRole("list", { name: "變更紀錄" })).toBeTruthy();
    await vi.waitFor(() => expect(api.getCampaignTimeline).toHaveBeenCalledTimes(2));
  });
});
