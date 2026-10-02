/** F30-I07: the v10 workspace frame — tab routing (six tabs, `perf` key, `?tab=performance` redirect), the perf tab's
 * 「進階：每日資料、次要指標與舊版檢討」 fold, the two independent reads (campaign, workspace progress) and the step targets. The tab
 * bodies are stubs: each has its own tests. */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { assetHandoff, type Placement } from "@/lib/adsUserAssetsApi";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getCampaign, type CampaignDetail } from "@/lib/adsApi";
import { completeExternalView, existingCampaigns } from "@/lib/adsExternalApi";
import { getCampaignWorkspace, type CampaignWorkspace as WorkspaceRead } from "@/lib/adsWorkspaceApi";
import type { StepTarget } from "./nextStep";
import { CampaignWorkspace } from "./CampaignWorkspace";
import { AssetHandoffPanel } from "./AssetHandoffPanel";
import { currentBudgetMonth } from "./MonthlyBudgetPanel";

// F36-I09 (ruling G): the component reads the org clock through `useWorkspace().identity.org`; the
// timezone is mutable so one case can move the org to UTC+14 without re-mocking the module.
let orgTimezone = "Asia/Taipei";
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({
    scope: "user:org", brands: [], brandsLoading: false, brandsError: null, refreshBrands: () => {},
    identity: {
      user: { id: "usr_1", email: "a@example.com" },
      org: { id: "org_test", name: "測試組織", kind: "personal", role: "owner", timezone: orgTimezone, today: "2020-01-01" },
      orgs: [],
    },
  }),
}));
// 2026-02-28 10:30Z: Kiritimati (UTC+14) is already 2026-03-01 00:30; UTC and the test runner zone
// (Asia/Taipei, UTC+8 = 18:30) are still on 2026-02-28. Only `Date` is faked so timers stay real.
const KIRITIMATI_INSTANT = new Date("2026-02-28T10:30:00Z");
function useKiritimati() {
  beforeEach(() => { orgTimezone = "Pacific/Kiritimati"; vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(KIRITIMATI_INSTANT); });
  afterEach(() => { vi.useRealTimers(); orgTimezone = "Asia/Taipei"; });
}
vi.mock("@/lib/adsApi", () => ({ getCampaign: vi.fn() }));
vi.mock("@/lib/adsWorkspaceApi", () => ({ getCampaignWorkspace: vi.fn() }));
vi.mock("@/lib/adsExternalApi", () => ({ completeExternalView: vi.fn(), syncCampaign: vi.fn(), syncJob: vi.fn(), existingCampaigns: vi.fn() }));
// F36-I09: `AssetHandoffPanel` and `currentBudgetMonth` have no suite of their own; this is the nearest one (issue Done #4).
vi.mock("@/lib/adsUserAssetsApi", async importOriginal => ({ ...await importOriginal<object>(), assetHandoff: vi.fn(), bindingAction: vi.fn(), bindingCandidates: vi.fn(), versionMetrics: vi.fn() }));
vi.mock("./AuthAssetMedia", () => ({ AuthAssetMedia: () => null }));
let go: ((t: StepTarget) => void) | null = null;
vi.mock("./workspace/OverviewBody", () => ({
  capOf: () => null,
  OverviewBody: (p: { onGo: (t: StepTarget) => void; advanced: unknown }) => { go = p.onGo; return <h2>v10 總覽</h2>; },
}));
vi.mock("./OverviewTab", () => ({ OverviewTab: () => <h2>舊總覽內容</h2> }));
vi.mock("./StrategyTab", () => ({ StrategyTab: (p: { launchApproved: boolean | null }) => <h2>共用策略 {String(p.launchApproved)}</h2> }));
vi.mock("./DeliveryTab", () => ({ DeliveryTab: () => <h2>共用結構</h2> }));
vi.mock("./AssetsTab", () => ({ AssetsTab: () => <h2>共用素材</h2> }));
vi.mock("./ChangeControl", () => ({ ChangeControl: () => <h2>共用變更</h2> }));
vi.mock("./ReviewPanel", () => ({ ReviewPanel: () => <h2>單則廣告檢討</h2> }));
vi.mock("./PerformanceTab", () => ({ PerformanceTab: () => <h2>共用成效</h2> }));
vi.mock("./detail/CampaignDetailPage", () => ({
  CampaignPerfBody: ({ advanced }: { advanced: unknown }) => <div><h2>F29 成效本體</h2>{advanced as never}</div>,
}));

const CAP = { value: 450, basis: "own", own_value: 450, break_even: 520, price: 1580, product_id: null, result_kind: "purchase", result_label: "購買", missing: [], revision: 1 };
function detail(o: Partial<CampaignDetail> = {}): CampaignDetail {
  return { id: "c", name: "日常商品推廣・轉換", objective: "購買", origin: "internal", status: "live", groups: [], cap: CAP,
    start_date: "2026-09-08", end_date: "2026-10-08", capabilities: { allowed: [], unavailable: {} }, ...o } as unknown as CampaignDetail;
}
function ws(o: Partial<WorkspaceRead> = {}): WorkspaceRead {
  return { stage: { key: "decide", done: ["plan", "assets", "launch", "read"] }, pending_count: 2, delivery: "live", daily_budget: 1200, active_ads: 8, can_support: 6,
    next_sync_at: null, missing_days: [], totals: null, draft: null, ...o };
}
function Where() { const l = useLocation(); return <p data-testid="where">{l.search}</p>; }
function renderAt(path = "/brands/b/ads/campaigns/c") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:b/ads/campaigns/:c" element={<><CampaignWorkspace brandId="b" campaignId="c" /><Where /></>} />
        <Route path="/brands/:b/ads/campaigns/:c/publish" element={<h2>發布頁</h2>} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  go = null;
  vi.mocked(getCampaign).mockResolvedValue(detail());
  vi.mocked(getCampaignWorkspace).mockResolvedValue(ws());
  vi.mocked(completeExternalView).mockResolvedValue({ entities: [], observations: [], next_entity_cursor: null, next_observation_cursor: null, window: { start: "2026-08-20", end: "2026-09-18" }, connections: [], sync: {}, coverage: {} });
});

it("six tabs in prototype order; each tab mounts its body (structure, assets, changes are slots)", async () => {
  renderAt();
  await screen.findByText("v10 總覽");
  const tabs = screen.getByRole("group", { name: "活動分頁" });
  expect([...tabs.querySelectorAll("button")].map((b) => b.textContent)).toEqual(["總覽2", "策略", "投放結構", "素材", "成效", "變更與核對"]);
  for (const [label, content] of [["策略", "共用策略 false"], ["投放結構", "共用結構"], ["素材", "共用素材"], ["變更與核對", "共用變更"], ["成效", "F29 成效本體"]]) {
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${label}`) }));
    expect(await screen.findByText(content)).toBeTruthy();
  }
  expect(screen.getByTestId("where").textContent).toBe("?tab=perf");
  expect(completeExternalView).not.toHaveBeenCalled();
});

it("an unknown pending count shows no number on 總覽 — never 0", async () => {
  vi.mocked(getCampaignWorkspace).mockResolvedValue(ws({ pending_count: null }));
  renderAt();
  await screen.findByText("v10 總覽");
  expect(screen.getByRole("button", { name: "總覽" }).textContent).toBe("總覽");
});

it("?tab=performance lands on perf keeping ?ad=; the old review and platform charts fold opens for it", async () => {
  renderAt("/brands/b/ads/campaigns/c?tab=performance&ad=ad_1");
  await screen.findByText("F29 成效本體");
  expect(screen.getByTestId("where").textContent).toBe("?tab=perf&ad=ad_1");
  expect(screen.getByRole("button", { name: "進階：每日資料、次要指標與舊版檢討" }).getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByText("單則廣告檢討")).toBeTruthy();
  expect(screen.getByText("共用成效")).toBeTruthy();
});

it("perf without ?ad= or ?review= keeps the old review and platform charts folded (and unread)", async () => {
  renderAt("/brands/b/ads/campaigns/c?tab=perf");
  await screen.findByText("F29 成效本體");
  expect(screen.getByRole("button", { name: "進階：每日資料、次要指標與舊版檢討" }).getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByText("單則廣告檢討")).toBeNull();
});

it("imported campaigns read the complete platform view once and use the same tabs", async () => {
  vi.mocked(getCampaign).mockResolvedValue(detail({ origin: "imported" }));
  renderAt();
  await screen.findByText("v10 總覽");
  fireEvent.click(screen.getByRole("button", { name: "素材" }));
  expect(await screen.findByText("共用素材")).toBeTruthy();
  expect(completeExternalView).toHaveBeenCalledTimes(1);
});

it("offers retry when complete native data cannot be loaded", async () => {
  vi.mocked(getCampaign).mockResolvedValue(detail({ origin: "imported" }));
  vi.mocked(completeExternalView).mockRejectedValueOnce(new Error("第二頁讀取失敗"));
  renderAt();
  await screen.findByText("第二頁讀取失敗");
  fireEvent.click(screen.getByRole("button", { name: "重新載入" }));
  await screen.findByText("v10 總覽");
});

it("the progress read fails on its own: the head says so with 重試, the tabs keep working, the old overview stays reachable", async () => {
  vi.mocked(getCampaignWorkspace).mockRejectedValueOnce(new Error("伺服器忙碌"));
  renderAt();
  expect(await screen.findByText(/活動進度讀不到：伺服器忙碌/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "進階：更多活動資訊" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "策略" }));
  expect(await screen.findByText("共用策略 null")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "重試" }));
  expect(await screen.findByRole("navigation", { name: "活動進度" })).toBeTruthy();
  expect(getCampaignWorkspace).toHaveBeenCalledTimes(2);
});

it("step targets: the old 'performance' key opens perf (a draft's empty perf keeps the old fold); 'publish' goes to the publish page's URL", async () => {
  vi.mocked(getCampaign).mockResolvedValue(detail({ status: "draft" }));
  vi.mocked(getCampaignWorkspace).mockResolvedValue(ws({ stage: { key: "plan", done: [] }, pending_count: 0, draft: { cap_set: false, budget_set: false, slots_ready: 0, slots_total: 3, launch_checked: 0, launch_total: 0 } }));
  renderAt();
  await screen.findByText("v10 總覽");
  go!("performance");
  expect(await screen.findByText("還沒上架，沒有成效")).toBeTruthy();
  expect(screen.getByRole("button", { name: "進階：每日資料、次要指標與舊版檢討" })).toBeTruthy(); // the comparison plan stays reachable on a draft
  expect(screen.getByTestId("where").textContent).toBe("?tab=perf");
  fireEvent.click(screen.getByRole("button", { name: "確認上架清單 →" }));
  expect(await screen.findByText("發布頁")).toBeTruthy();
  expect(screen.queryByRole("group", { name: "活動分頁" })).toBeNull();
});

it("'publish' on a campaign that cannot publish (imported) opens the assets tab instead", async () => {
  vi.mocked(getCampaign).mockResolvedValue(detail({ origin: "imported" }));
  renderAt();
  await screen.findByText("v10 總覽");
  go!("publish");
  expect(await screen.findByText("共用素材")).toBeTruthy();
  expect(screen.getByTestId("where").textContent).toBe("?tab=assets");
});

describe("F36-I09 組織時鐘：交接面板與月預算月份", () => {
  useKiritimati();
  const placement: Placement = { id: "p1", revision: 1, is_current: true, asset_id: "asset1", filename: "p1.png", mime_type: "image/png", asset_status: "ready", asset_error: null, copy_fields: { headline: "原標題" }, suggested_copy: {}, purpose: "產品介紹", destination_entity_id: null, start_date: null, end_date: null, status: "pending", pending_reason: "尚待確認安排", required: true, confirmed_at: null, suggestion_batch_id: null };
  it("版本成效日期預設是組織的最近 30 天（UTC+14 已是 3/1），不再是 UTC 的今天", async () => {
    vi.mocked(existingCampaigns).mockResolvedValue({ sources: [] } as unknown as Awaited<ReturnType<typeof existingCampaigns>>);
    vi.mocked(assetHandoff).mockResolvedValue({ original_copy: {}, suggested_copy: {}, effective_copy: {}, tracking_name: "MOS-p1-v1", notice: "內部確認不代表已上架", destination_entity_id: null, download_url: "/api/private", purpose: "產品介紹", start_date: null, end_date: null, bindings: [] });
    render(<MemoryRouter><AssetHandoffPanel brandId="b" campaignId="c" placement={placement} readOnly={false} /></MemoryRouter>);
    await screen.findByText("內部確認不代表已上架");
    expect((screen.getByLabelText("版本成效開始日") as HTMLInputElement).value).toBe("2026-01-31");
    expect((screen.getByLabelText("版本成效結束日") as HTMLInputElement).value).toBe("2026-03-01");
  });
  it("currentBudgetMonth 依組織時區取月份：UTC+14 已是 2026-03，台北還在 2026-02", () => {
    expect(currentBudgetMonth("Pacific/Kiritimati")).toBe("2026-03");
    expect(currentBudgetMonth("Asia/Taipei")).toBe("2026-02");
    expect(currentBudgetMonth()).toBe("2026-02");
  });
});
