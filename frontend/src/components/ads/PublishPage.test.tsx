/** F30-I13: the publish page's URL steps follow `GET …/launch` — no step or a step not open yet redirects to the
 * reported one, earlier steps stay reachable, a stale launch is decided on the platform step (F28 panel), an imported
 * campaign has no publish page, and a failed read is its own state with 重試. Step bodies are covered in
 * `publish/PublishFlow.test.tsx`. */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getCampaign, type CampaignDetail } from "@/lib/adsApi";
import { getHandoff } from "@/lib/adsHandoffApi";
import { fetchChannels, fetchLaunchView, type LaunchStep, type LaunchView } from "@/lib/adsLaunchApi";
import { PublishPage } from "./PublishPage";
// F50 Contract K: the org clock reads the workspace org zone; dates assert Asia/Taipei output, never the runner's.
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-10-01" }, orgs: [] } }) }));

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, getCampaign: vi.fn(), getPublish: vi.fn(() => new Promise(() => {})) };
});
vi.mock("@/lib/adsHandoffApi", () => ({ getHandoff: vi.fn(), reportHandoff: vi.fn() }));
vi.mock("@/lib/adsLaunchApi", () => ({ fetchChannels: vi.fn(), fetchLaunchView: vi.fn() }));
vi.mock("@/lib/auth", () => ({ getOrgId: () => "org_1" }));
vi.mock("./publish/LaunchSettingsCard", () => ({ LaunchSettingsCard: () => <p>投放設定卡</p> }));
vi.mock("./publish/LaunchSettingsCopy", () => ({ LaunchSettingsCopy: () => <p>可複製的投放設定</p> }));
vi.mock("./LaunchStalePanel", () => ({
  LaunchStalePanel: ({ stale, onDecided }: { stale: { diff: unknown[] }; onDecided: (w: unknown, o: { tone: "ok"; text: string }) => void }) => (
    <div><h1>方案改過 {stale.diff.length} 處</h1>
      <button type="button" onClick={() => onDecided({ items: [], launch_stale: null }, { tone: "ok", text: "已用現在的方案重新核准" })}>重新核准</button></div>
  ),
}));

const CAMPAIGN = {
  id: "cmp_1", name: "秋季新色預購", origin: "internal", status: "ready", capabilities: { allowed: [], unavailable: {} },
  cap: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買" }, groups: [], manual_handoff: null,
} as unknown as CampaignDetail;
function view(step: LaunchStep): LaunchView {
  return {
    step, version: step === "list" ? null : 1, approved_at: step === "list" ? null : "2026-09-20T06:05:00Z",
    summary: { campaigns: 1, groups: 0, ads: 0, daily_total: null, start: null, end: null, cap: null, slots_ready: 0, slots_total: 0 },
    items: [{ id: "h1", kind: "campaign", name: "秋季新色預購", parent_name: null, fields: [], state: "todo", mismatches: [], unreadable: [], reason: null, reason_at: null }],
    deferred_ads: [], read_at: step === "verify" ? "2026-09-23T02:52:00Z" : null, settings_readback: null,
  };
}

function Page() {
  const { step } = useParams();
  return <><PublishPage brandId="brd_1" campaignId="cmp_1" step={step} /><p data-testid="where">{useLocation().pathname}</p></>;
}
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="/brands/:b/ads/campaigns/:c/publish/:step?" element={<Page />} /></Routes>
    </MemoryRouter>,
  );
}
const where = () => screen.getByTestId("where").textContent;
const base = "/brands/brd_1/ads/campaigns/cmp_1/publish";

afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getCampaign).mockResolvedValue(CAMPAIGN);
  vi.mocked(fetchChannels).mockResolvedValue([{ key: "meta", label: "Meta", connected: true, state_text: "已接上" }]);
});

it("no step lands on the step the launch reports", async () => {
  vi.mocked(fetchLaunchView).mockResolvedValue(view("platform"));
  renderAt(base);
  await waitFor(() => expect(where()).toBe(`${base}/platform`));
  expect(await screen.findByRole("heading", { name: "到平台完成" })).toBeTruthy();
});

it("a step not open yet (or an unknown one) redirects to the reported step", async () => {
  vi.mocked(fetchLaunchView).mockResolvedValue(view("list"));
  renderAt(`${base}/verify`);
  await waitFor(() => expect(where()).toBe(`${base}/list`));
  cleanup();
  renderAt(`${base}/nope`);
  await waitFor(() => expect(where()).toBe(`${base}/list`));
  expect(await screen.findByRole("heading", { name: "確認上架清單" })).toBeTruthy();
});

it("earlier steps stay reachable: from 讀回核對 the platform step opens as it is", async () => {
  vi.mocked(fetchLaunchView).mockResolvedValue(view("verify"));
  renderAt(`${base}/platform`);
  expect(await screen.findByRole("heading", { name: "到平台完成" })).toBeTruthy();
  expect(where()).toBe(`${base}/platform`);
  expect(screen.getByRole("link", { name: "回到「確認上架清單」" }).getAttribute("href")).toBe(`${base}/list`);
});

it("a stale launch is decided on the platform step; the decision reads the launch again", async () => {
  vi.mocked(fetchLaunchView).mockResolvedValueOnce(view("stale")).mockResolvedValue(view("platform"));
  vi.mocked(getHandoff).mockResolvedValue({ items: [], launch_stale: { diff: [{}, {}] } } as never);
  renderAt(`${base}/verify`);
  await waitFor(() => expect(where()).toBe(`${base}/platform`));
  expect(await screen.findByRole("heading", { name: "方案改過 2 處" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "重新核准" }));
  expect(await screen.findByRole("heading", { name: "到平台完成" })).toBeTruthy();
  expect(screen.getByText("已用現在的方案重新核准")).toBeTruthy();
  expect(fetchLaunchView).toHaveBeenCalledTimes(2);
});

it("an imported campaign has no publish page: it points to its own material handoff", async () => {
  vi.mocked(getCampaign).mockResolvedValue({ ...CAMPAIGN, origin: "imported" } as CampaignDetail);
  vi.mocked(fetchLaunchView).mockReturnValue(new Promise(() => {}));
  renderAt(`${base}/list`);
  expect((await screen.findByRole("link", { name: "前往自帶素材安排" })).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1?tab=assets");
});

it("a failed launch read shows ReadFailed with 重試 — never an empty list", async () => {
  vi.mocked(fetchLaunchView).mockRejectedValueOnce(new Error("伺服器忙碌")).mockResolvedValue(view("list"));
  renderAt(`${base}/list`);
  expect((await screen.findByRole("alert")).textContent).toContain("上架清單讀不到：伺服器忙碌");
  fireEvent.click(screen.getByRole("button", { name: "重試" }));
  expect(await screen.findByRole("heading", { name: "確認上架清單" })).toBeTruthy();
});

it("the campaign read fails on its own: the list still shows, the settings block says so and approval waits", async () => {
  vi.mocked(getCampaign).mockRejectedValue(new Error("活動讀取逾時"));
  vi.mocked(fetchLaunchView).mockResolvedValue(view("list"));
  renderAt(`${base}/list`);
  expect(await screen.findByText(/活動資料讀不到：活動讀取逾時/)).toBeTruthy();
  expect(screen.getByRole("region", { name: "清單" })).toBeTruthy();
  expect((screen.getByRole("button", { name: "核准上架清單 →" }) as HTMLButtonElement).disabled).toBe(true);
});

it("F47-I06: the crumb says 首次上架 only for a first launch — a later period or a re-approved version is named from the data", async () => {
  vi.mocked(fetchLaunchView).mockResolvedValue(view("list"));
  renderAt(`${base}/list`);
  expect(await screen.findByText("首次上架", { exact: true })).toBeTruthy();
  cleanup();
  vi.mocked(getCampaign).mockResolvedValue({ ...CAMPAIGN, context_json: { field_sources: { cap: "copied", product: "user" } } } as unknown as CampaignDetail);
  renderAt(`${base}/list`);
  expect(await screen.findByText("這一期上架", { exact: true })).toBeTruthy();
  cleanup();
  vi.mocked(fetchLaunchView).mockResolvedValue({ ...view("platform"), version: 2 });
  renderAt(`${base}/platform`);
  expect(await screen.findByText("第 2 版上架", { exact: true })).toBeTruthy();
});
