/** frontend/src/components/ads/flow/ConfirmPage.test.tsx — F22-I02／F25-I03：`vi.mock` 掉
 * `@/lib/adsChangeApi`／`@/lib/adsTriageApi`，不打真的 API。覆蓋 Done 4：三種 kind 都能畫、
 * 草稿延遲建立的 payload、核准導去到平台完成、暫緩要未來時間、拒絕、保存沒收到回應時沿用
 * 同一個 operation_id 重試、走錯步驟自動導正、多項變更清單連去既有變更與核對；F25-I03 加了
 * 加預算 propose 路由的完整證據卡、budget 草稿 payload、月預算放不下的 409 不重建。 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as changeApi from "@/lib/adsChangeApi";
import { ChangeRequestRejected, type ChangeItem, type ChangeSet, type MonthlyBudget } from "@/lib/adsChangeApi";
import * as triageApi from "@/lib/adsTriageApi";
import type { PauseView, QueueItem, QueuePayload, QueueScale, TriageItem } from "@/lib/adsTriageApi";
import * as anglesApi from "@/lib/adsAnglesApi";
import { ConfirmPage } from "./ConfirmPage";

vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "u:o", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-09-28" }, orgs: [] } }) }));
vi.mock("@/lib/adsChangeApi", async (importOriginal) => ({
  ...(await importOriginal<typeof changeApi>()),
  getChangeControl: vi.fn(), createChangeSet: vi.fn(), approveChangeSet: vi.fn(),
  decideChangeSet: vi.fn(), getMonthlyBudget: vi.fn(),
}));
vi.mock("@/lib/adsTriageApi", async (importOriginal) => ({
  ...(await importOriginal<typeof triageApi>()),
  getQueue: vi.fn(), getTriage: vi.fn(), getPauseView: vi.fn(),
}));
// F27-I16 Contract C: 每一頁暫停提議都會打一次 `getAngles`（correction 9）——不 mock 會打到真的
// `fetch`，預設先給一個 `ready` 三候選，個別測試需要別的狀態再自己覆寫。
vi.mock("@/lib/adsAnglesApi", async (importOriginal) => ({
  ...(await importOriginal<typeof anglesApi>()),
  getAngles: vi.fn(),
}));

/** F48 Contract R "reason texts" as the backend builds them (`triage_capacity.reason_text`, `triage_scale
 * .scale_reason_text`); the drafts carry them as served. */
const PAUSE_REASON_TEXT = "花了 1420，一筆都沒賣出";
const SCALE_REASON_TEXT = "近期每筆 306 都在上限 450 內，加碼 2 成擴量";

function triage(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "aex_1", native_id: "native_1", name: "1150706 健身情境單圖", campaign_id: "cmp_1",
    campaign_name: "【銷售】測試活動", thumbnail_url: null, class: "stop_loss", label: "停損",
    reason_code: "spend_over_stop_loss",
    grade: "wasted", grade_label: "沒賣出", previous_grade: null, grade_move: null,
    window: { start: "2026-08-25", end: "2026-09-21", days: 9, previous_start: "2026-07-28", previous_end: "2026-08-24", extended_from: null },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 1420, result_count: 0, cost_per_result: null, result_kind: null, result_label: "成果", derived_zero_days: 0, reason: null },
    previous: { spend: null, result_count: null, cost_per_result: null, result_kind: null, result_label: "成果", derived_zero_days: 0, reason: null },
    change_pct: null,
    sample: { gate: false, spend_multiple: null, days_with_events: 0 },
    ...overrides,
  };
}
/** F45-I05 Contract P as `app/ads/triage_pause.py::pause_view` returns it for a running ad of this campaign. */
function pauseView(overrides: Partial<PauseView> = {}): PauseView {
  return {
    state: "active", entity_id: "aex_1", name: "1150706 健身情境單圖", triage: triage(),
    // F48 Contract R: `triage_capacity.reason_text` of this ad's own grade (沒賣出) and spend.
    reason_text: PAUSE_REASON_TEXT,
    closed_at: null, last_read_at: "2026-09-30T16:05:00+00:00", change_set_id: null,
    ...overrides,
  };
}
function queueItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "int_1", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null,
    dedupe_key: "k1", category: "ads_triage_stop_loss", kind: null, severity: "money_loss",
    message: "m", action_url: null, visible_from: null, status: "open",
    created_at: "2026-09-22T00:00:00Z", resolved_at: null, kind_key: "stop_loss",
    triage: triage(), proposal: null, done: false,
    ...overrides,
  };
}
function queue(items: QueueItem[] = []): QueuePayload {
  return { items, counts: { stop_loss: items.length, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 }, total_ads: items.length, kinds_available: ["stop_loss"], kinds_pending: [] };
}
function scale(overrides: Partial<QueueScale> = {}): QueueScale {
  return {
    owner: { id: "aex_owner_G", name: "廣告組 G・廣泛受眾", native_kind: "adset", native_id: "23851", ads_count: 8, currency: "TWD" },
    from: 1000, to: 1200, cost_per_result: 306, previous_cost_per_result: 330,
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    window_days: 14, month: { available: 10000, extra_needed: 1800 },
    reason_text: SCALE_REASON_TEXT,
    ...overrides,
  };
}
function scaleQueueItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return queueItem({
    kind_key: "scale_budget",
    dedupe_key: "ads-triage:scale_budget:aex_owner_G:2026-09-21",
    category: "ads_triage_scale_budget",
    triage: triage({ class: "better", label: "變好" }),
    scale: scale(),
    ...overrides,
  });
}
// F27-I15 Contract F: `QueueKind`/`QueueItem.kind_key` (`adsTriageApi.ts`, out of this issue's
// touch) deliberately hasn't widened to include `"cleanup"` yet (that file's own comment defers
// it to this issue) — same double-assertion workaround `changeFlow.ts::isCleanupKind` documents,
// needed here too since test fixtures are plain `QueueItem`-typed object literals.
const CLEANUP_KIND = "cleanup" as unknown as QueueItem["kind_key"];
function cleanupQueueItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return queueItem({
    kind_key: CLEANUP_KIND,
    dedupe_key: "ads-triage:cleanup:cmp_1:2026-09-21",
    category: "ads_triage_cleanup",
    triage: triage(),
    cleanup: {
      campaign_id: "cmp_1", campaign_name: "【銷售】測試活動", can_support: 3, active_ads: 5,
      ads: [
        { entity_id: "aex_low1", name: "1150701 情境圖 A", thumbnail_url: null, spend_7d: 120, grade: "wasted", cost_per_result: null, spend: 1540, result_count: 0, daily_spend: 120 / 7, rejected_before: null, reason_text: "花了 1540，一筆都沒賣出" },
        { entity_id: "aex_low2", name: "1150702 情境圖 B", thumbnail_url: "https://cdn.example/b.jpg", spend_7d: 340, grade: "over", cost_per_result: 620, spend: 2480, result_count: 4, daily_spend: 340 / 7, rejected_before: null, reason_text: "第 5／5 名，每筆 620 對上限 450（太貴）" },
      ],
      keep: [
        { entity_id: "aex_keep1", name: "晨光隨行杯・日常出發", thumbnail_url: null, spend_7d: 300, grade: "on_target", cost_per_result: 48, spend: 1440, result_count: 30, daily_spend: 300 / 7, rejected_before: null },
        { entity_id: "aex_keep2", name: "健身情境・保冷 12 小時", thumbnail_url: null, spend_7d: 700, grade: "on_target", cost_per_result: 431.25, spend: 3450, result_count: 8, daily_spend: 100, rejected_before: null },
        { entity_id: "aex_keep3", name: "辦公室一角・質感桌面", thumbnail_url: null, spend_7d: 280, grade: "on_target", cost_per_result: 52, spend: 1300, result_count: 25, daily_spend: 40, rejected_before: null },
      ],
      short: 0, daily_saving: 460 / 7, scale_owner_id: null,
    },
    ...overrides,
  });
}
/** `GET …/monthly-budget` as `app/ads/month_budget.py::preflight` shapes it (F40-I01 adds `ongoing_owners`). */
function monthlyBudget(overrides: Partial<MonthlyBudget> = {}): MonthlyBudget {
  return {
    month: "2026-09", currency: "TWD", amount: 60000, revision: 2, known_spend: 22000, ongoing_estimate: 28000,
    reserved_increases: 0, available: 10000, uncertainties: [], can_increase: true, period_end: "2026-09-30", confirmed_at: null, notice: "",
    ongoing_owners: [{ entity_id: "aex_owner_G", name: "廣告組 G・廣泛受眾", daily: 1000, days: 28, commitment: 28000 }],
    ...overrides,
  };
}
function changeItem(overrides: Partial<ChangeItem> = {}): ChangeItem {
  return {
    id: "item_1", kind: "pause", target_id: "aex_1",
    target: { id: "aex_1", name: "1150706 健身情境單圖", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_1" },
    before: { status: "PAUSED" }, after: { status: "PAUSED" }, reason: "花費超過停損線（目標 × 3）仍未達成目標",
    verification_state: "pending", evidence_json: {}, reported_at: null, first_observed_at: null, verified_at: null, platform_url: null,
    ...overrides,
  };
}
function changeSet(overrides: Partial<ChangeSet> = {}): ChangeSet {
  return {
    id: "acs_1", campaign_id: "cmp_1", title: "暫停「1150706 健身情境單圖」", month: "2026-09",
    operation_id: "op_1", content_hash: "hash_1", status: "draft", reason: null, revisit_at: null,
    approval_id: null, created_at: "2026-09-21T00:00:00Z", approved_at: null, items: [changeItem()],
    can_revise: true,
    ...overrides,
  };
}

function ProposeRoute() {
  const { brandId, campaignId, entityId } = useParams<{ brandId: string; campaignId: string; entityId: string }>();
  return <ConfirmPage brandId={brandId ?? ""} campaignId={campaignId ?? ""} entityId={entityId ?? ""} />;
}
function ProposeBudgetRoute() {
  const { brandId, campaignId, entityId } = useParams<{ brandId: string; campaignId: string; entityId: string }>();
  return <ConfirmPage brandId={brandId ?? ""} campaignId={campaignId ?? ""} entityId={entityId ?? ""} proposeKind="budget" />;
}
function ProposeCleanupRoute() {
  const { brandId, campaignId } = useParams<{ brandId: string; campaignId: string }>();
  return <ConfirmPage brandId={brandId ?? ""} campaignId={campaignId ?? ""} proposeKind="cleanup" />;
}
function SetConfirmRoute() {
  const { brandId, campaignId, setId } = useParams<{ brandId: string; campaignId: string; setId: string }>();
  return <ConfirmPage brandId={brandId ?? ""} campaignId={campaignId ?? ""} setId={setId ?? ""} />;
}
function LocationProbe() {
  return <p data-testid="probe-path">{useLocation().pathname}</p>;
}
/** What a row reads on screen: glossary sentences (the hidden `role=tooltip` of each dotted term) are not text. */
function seen(el: Element): string {
  const copy = el.cloneNode(true) as Element;
  copy.querySelectorAll("[role=tooltip]").forEach((tip) => tip.remove());
  return copy.textContent ?? "";
}
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/propose/pause/:entityId" element={<ProposeRoute />} />
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/propose/budget/:entityId" element={<ProposeBudgetRoute />} />
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/propose/cleanup/:cleanupCampaignId" element={<ProposeCleanupRoute />} />
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/changes/:setId/confirm" element={<SetConfirmRoute />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}
const proposePath = "/brands/brd_1/ads/campaigns/cmp_1/propose/pause/aex_1";
const proposeBudgetPath = "/brands/brd_1/ads/campaigns/cmp_1/propose/budget/aex_owner_G";
const proposeCleanupPath = "/brands/brd_1/ads/campaigns/cmp_1/propose/cleanup/cmp_1";
const confirmPath = (id = "acs_1") => `/brands/brd_1/ads/campaigns/cmp_1/changes/${id}/confirm`;

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(triageApi.getQueue).mockResolvedValue(queue());
  vi.mocked(triageApi.getPauseView).mockResolvedValue(pauseView());
  // F28-I11: the cleanup proposal reads the campaign triage for its daily budget only; a failure is tolerated.
  vi.mocked(triageApi.getTriage).mockRejectedValue(new Error("not needed"));
  vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [] });
  // F40-I08: a budget set reads the month budget as soon as the page mounts (it gates 核准), so the default is a
  // month that fits; the three-state tests override it.
  vi.mocked(changeApi.getMonthlyBudget).mockResolvedValue(monthlyBudget());
  vi.mocked(anglesApi.getAngles).mockResolvedValue({ status: "ready", candidates: ["日常出發情境", "辦公室情境", "提問式貼文"], error: null });
});

describe("ConfirmPage（F22-I02）三種 kind", () => {
  it("pause／copy／budget 各自畫出對應標題與內容", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [changeSet()] });
    renderAt(confirmPath());
    expect(await screen.findByText("提議：暫停這則廣告")).toBeTruthy();
    expect(screen.getByText("停損")).toBeTruthy();

    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ id: "acs_copy", items: [changeItem({ kind: "copy", before: { title: "舊標題", body: "舊內文" }, after: { title: "新標題", body: "新內文" } })] })],
    });
    renderAt(confirmPath("acs_copy"));
    expect(await screen.findByText("確認變更")).toBeTruthy();
    expect(screen.getByText("舊標題")).toBeTruthy();
    expect(screen.getByText("新標題")).toBeTruthy();

    vi.mocked(changeApi.getMonthlyBudget).mockResolvedValue({
      month: "2026-09", currency: "TWD", amount: 60000, revision: 1, known_spend: 20000, ongoing_estimate: 10000,
      reserved_increases: 0, available: 30000, uncertainties: [], can_increase: true, period_end: "2026-09-30", confirmed_at: null, notice: "",
    });
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ id: "acs_budget", items: [changeItem({ kind: "budget", before: { daily_amount: 1000 }, after: { daily_amount: 1200 } })] })],
    });
    renderAt(confirmPath("acs_budget"));
    expect(await screen.findByText("提議：加預算")).toBeTruthy();
    expect(screen.getByText("可加預算")).toBeTruthy();
  });

  it("改文案清單承接自某一輪檢討：返回鍵是「修改內容」，連回那一輪的改文案頁（F23-I04）", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        id: "acs_copy", review_id: "arv_1", recommendation_id: "rec_1",
        items: [changeItem({ kind: "copy", before: { title: "舊標題", body: "舊內文" }, after: { title: "新標題", body: "新內文" } })],
      })],
    });
    renderAt(confirmPath("acs_copy"));
    await screen.findByText("確認變更");
    const back = screen.getByRole("link", { name: "← 修改內容" }) as HTMLAnchorElement;
    expect(back.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1/copy");
  });

  it("改文案清單沒有承接的檢討：回投放中心的出口是「先不要，回投放中心」（F23-I04；F29-I10 出口取代同去處的返回鍵）", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        id: "acs_copy", items: [changeItem({ kind: "copy", before: { title: "舊標題", body: "舊內文" }, after: { title: "新標題", body: "新內文" } })],
      })],
    });
    renderAt(confirmPath("acs_copy"));
    await screen.findByText("確認變更");
    const exit = screen.getByRole("link", { name: "✕ 先不要，回投放中心" }) as HTMLAnchorElement;
    expect(exit.getAttribute("href")).toBe("/brands/brd_1/ads");
    expect(screen.queryByRole("link", { name: "← 投放中心" })).toBeNull();
  });

  it("已拒絕的改文案清單：即使承接自檢討，出口仍是投放中心（F23-I04；F49：沒有下一件時是主按鈕「← 回投放中心」）", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        id: "acs_copy", review_id: "arv_1", recommendation_id: "rec_1", status: "rejected", reason: "資料還不夠",
        items: [changeItem({ kind: "copy", before: { title: "舊標題", body: "舊內文" }, after: { title: "新標題", body: "新內文" } })],
      })],
    });
    renderAt(confirmPath("acs_copy"));
    await screen.findByText("確認變更");
    const home = screen.getByRole("link", { name: "← 回投放中心" }) as HTMLAnchorElement;
    expect(home.getAttribute("href")).toBe("/brands/brd_1/ads");
    // One way to one place: no second 「← 投放中心」 back link, no 「先不要」 exit on a closed set.
    expect(screen.queryByRole("link", { name: "← 投放中心" })).toBeNull();
    expect(screen.queryByRole("link", { name: /先不要，回投放中心/ })).toBeNull();
  });

  it("多項變更的清單不重新解讀畫面，連去既有變更與核對", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem(), changeItem({ id: "item_2", target_id: "aex_2" })] })],
    });
    renderAt(confirmPath());
    expect(await screen.findByText("這份清單有多項變更")).toBeTruthy();
    const link = screen.getByRole("link", { name: "前往變更與核對" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toContain("tab=changes");
  });
});

describe("ConfirmPage（F22-I02）propose 路由：延遲建立草稿", () => {
  it("第一次核准才建立草稿，payload 照 feature Decisions 的欄位", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
    const draft = changeSet({ status: "approved", items: [changeItem({ verification_state: "pending", reported_at: null })] });
    vi.mocked(changeApi.createChangeSet).mockResolvedValue({ ...draft, status: "draft", approved_at: null });
    vi.mocked(changeApi.approveChangeSet).mockResolvedValue(draft);
    renderAt(proposePath);
    await user.click(await screen.findByRole("button", { name: /核准暫停，接著到平台操作/ }));

    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    const body = vi.mocked(changeApi.createChangeSet).mock.calls[0][2];
    expect(body.operation_id).toMatch(/^triage-pause:aex_1:/);
    expect(body.title).toBe("暫停「1150706 健身情境單圖」");
    expect(body.month).toMatch(/^\d{4}-\d{2}$/);
    expect(body.items).toEqual([{ kind: "pause", target_id: "aex_1", after: { status: "PAUSED" }, reason: PAUSE_REASON_TEXT }]);

    await waitFor(() => expect(changeApi.approveChangeSet).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/handoff"));
  });

  it("既有提議時重用 change_set_id（F45-I06：來自 Contract P），不重新建立草稿", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getPauseView).mockResolvedValue(pauseView({ change_set_id: "acs_existing" }));
    const existing = changeSet({ id: "acs_existing" });
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [existing] });
    vi.mocked(changeApi.approveChangeSet).mockResolvedValue({ ...existing, status: "approved" });
    renderAt(proposePath);
    await user.click(await screen.findByRole("button", { name: /核准暫停，接著到平台操作/ }));
    await waitFor(() => expect(changeApi.approveChangeSet).toHaveBeenCalled());
    expect(changeApi.createChangeSet).not.toHaveBeenCalled();
    expect(vi.mocked(changeApi.approveChangeSet).mock.calls[0][2].id).toBe("acs_existing");
  });
});

describe("ConfirmPage（F27-I16 Contract C/D）這則主打什麼？", () => {
  it("pending：畫骨架佔位，沒有任何 TagToggle", async () => {
    vi.mocked(anglesApi.getAngles).mockReturnValue(new Promise(() => {})); // 永遠不 resolve，停在 pending
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
    renderAt(proposePath);
    await screen.findByText("這則主打什麼？");
    expect(screen.queryByRole("button", { name: "＋ 自訂" })).toBeNull();
    expect(screen.getByText("選一個，暫停後記入品牌學習")).toBeTruthy();
  });

  it("ready：三顆候選＋自訂，選一顆會更新右側文字", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
    renderAt(proposePath);
    const tag = await screen.findByRole("button", { name: "日常出發情境" });
    expect(screen.getByRole("button", { name: "辦公室情境" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "提問式貼文" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "＋ 自訂" })).toBeTruthy();
    expect(screen.getByText("選一個，暫停後記入品牌學習")).toBeTruthy();
    await user.click(tag);
    expect(tag.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("「日常出發情境」對這群受眾無效")).toBeTruthy();
  });

  it("failed：只剩「＋ 自訂」，點開變成輸入框", async () => {
    const user = userEvent.setup();
    vi.mocked(anglesApi.getAngles).mockResolvedValue({ status: "failed", candidates: [], error: "讀取失敗" });
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
    renderAt(proposePath);
    await screen.findByText("這則主打什麼？");
    expect(screen.queryByRole("button", { name: "日常出發情境" })).toBeNull();
    const custom = await screen.findByRole("button", { name: "＋ 自訂" });
    await user.click(custom);
    const input = screen.getByLabelText("自訂主打");
    await user.type(input, "夏季限定");
    expect(screen.getByText("「夏季限定」對這群受眾無效")).toBeTruthy();
  });

  it("選了候選再核准：payload 帶上 angle", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
    const draft = changeSet({ status: "approved", items: [changeItem({ verification_state: "pending", reported_at: null })] });
    vi.mocked(changeApi.createChangeSet).mockResolvedValue({ ...draft, status: "draft", approved_at: null });
    vi.mocked(changeApi.approveChangeSet).mockResolvedValue(draft);
    renderAt(proposePath);
    await user.click(await screen.findByRole("button", { name: "辦公室情境" }));
    await user.click(await screen.findByRole("button", { name: /核准暫停，接著到平台操作/ }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    const body = vi.mocked(changeApi.createChangeSet).mock.calls[0][2];
    expect(body.items).toEqual([{
      kind: "pause", target_id: "aex_1", after: { status: "PAUSED" },
      reason: PAUSE_REASON_TEXT, angle: "辦公室情境",
    }]);
  });

  it("已拒絕／暫緩的清單不再畫這張卡（已經決定完了）", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ status: "rejected", reason: "先觀察" })],
    });
    renderAt(confirmPath());
    await screen.findByText("提議：暫停這則廣告");
    expect(screen.queryByText("這則主打什麼？")).toBeNull();
    expect(anglesApi.getAngles).not.toHaveBeenCalled();
  });
});

describe("ConfirmPage（F22-I02）拒絕／暫緩 sheet", () => {
  async function openSheet(user: ReturnType<typeof userEvent.setup>) {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
    renderAt(proposePath);
    await user.click(await screen.findByRole("button", { name: "拒絕／暫緩" }));
  }

  it("暫緩要選一個之後的時間，過去的自訂日期不送出", async () => {
    const user = userEvent.setup();
    await openSheet(user);
    await user.click(screen.getByRole("button", { name: "自訂" }));
    const dateInput = screen.getByLabelText("重看日期");
    await user.clear(dateInput);
    await user.type(dateInput, "2020-01-01");
    await user.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("請選一個之後的時間。")).toBeTruthy();
    expect(changeApi.decideChangeSet).not.toHaveBeenCalled();

    expect(changeApi.createChangeSet).not.toHaveBeenCalled();

    await user.clear(dateInput);
    await user.type(dateInput, "2099-01-01");
    // Stored as 00:00 of the chosen day in the org zone (F50 Contract K).
    const deferred = changeSet({ status: "deferred", reason: "想再觀察幾天", revisit_at: "2098-12-31T16:00:00+00:00" });
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(deferred);
    // The page then moves to the set's own confirm URL, which reads the set back.
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [deferred] });
    await user.click(screen.getByRole("button", { name: "保存" }));
    // F47-I07 (drill-10 Q3): no set yet → the draft and the decision are one write.
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalledTimes(1));
    const decide = vi.mocked(changeApi.createChangeSet).mock.calls[0][2].decide;
    expect(decide?.decision).toBe("deferred");
    expect(decide?.revisit_on).toBe("2099-01-01");
    expect(changeApi.decideChangeSet).not.toHaveBeenCalled();
    // drill-10 C3-D: the closed page names the revisit date.
    expect(await screen.findByText("已暫緩・想再觀察幾天・1/1 再看")).toBeTruthy();
  });

  it("F50-I12：「7 天後」從組織的今天起算（10/31 17:00Z 在台北已是 11/1）→ 送 revisit_on 2026-11-08、印「11/8 再看」，不看執行環境時區；選今天本身先擋下", async () => {
    const runnerTz = process.env.TZ;
    process.env.TZ = "America/Los_Angeles"; // the laptop is still on 10/31: a browser-clock pick would send 11/7
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-31T17:00:00Z"));
    try {
      const user = userEvent.setup();
      await openSheet(user);
      await user.click(screen.getByRole("button", { name: "自訂" }));
      const dateInput = screen.getByLabelText("重看日期");
      expect(dateInput.getAttribute("min")).toBe("2026-11-02");
      await user.clear(dateInput);
      await user.type(dateInput, "2026-11-01");
      await user.click(screen.getByRole("button", { name: "保存" }));
      expect(await screen.findByText("請選一個之後的時間。")).toBeTruthy();
      expect(changeApi.createChangeSet).not.toHaveBeenCalled();

      await user.click(screen.getByRole("button", { name: "7 天後" }));
      const deferred = changeSet({ status: "deferred", reason: "想再觀察幾天", revisit_at: "2026-11-07T16:00:00+00:00" });
      vi.mocked(changeApi.createChangeSet).mockResolvedValue(deferred);
      vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [deferred] });
      await user.click(screen.getByRole("button", { name: "保存" }));
      await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalledTimes(1));
      expect(vi.mocked(changeApi.createChangeSet).mock.calls[0][2].decide?.revisit_on).toBe("2026-11-08");
      expect(await screen.findByText("已暫緩・想再觀察幾天・11/8 再看")).toBeTruthy();
    } finally {
      vi.useRealTimers();
      process.env.TZ = runnerTz;
    }
  });

  it("暫緩被拒（例如時間已過）：顯示原因，不留下草稿、也不另外送決定", async () => {
    const user = userEvent.setup();
    await openSheet(user);
    vi.mocked(changeApi.createChangeSet).mockRejectedValue(new changeApi.ChangeRequestRejected("暫緩請選擇未來的重看時間。"));
    await user.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("暫緩請選擇未來的重看時間。")).toBeTruthy();
    expect(changeApi.createChangeSet).toHaveBeenCalledTimes(1);
    expect(changeApi.decideChangeSet).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "保存" })).toBeTruthy();
  });

  it("已經有清單（草稿）時沿用它，用既有的決定 API", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getPauseView).mockResolvedValue(pauseView({ change_set_id: "acs_existing" }));
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [changeSet({ id: "acs_existing" })] });
    vi.mocked(changeApi.decideChangeSet).mockResolvedValue(changeSet({ id: "acs_existing", status: "rejected", reason: "想再觀察幾天" }));
    await openSheet(user);
    await user.click(screen.getByRole("button", { name: "拒絕" }));
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(changeApi.decideChangeSet).toHaveBeenCalled());
    expect(vi.mocked(changeApi.decideChangeSet).mock.calls[0][2]).toBe("acs_existing");
    expect(changeApi.createChangeSet).not.toHaveBeenCalled();
  });

  it("拒絕不需要重看時間，保存後不帶 revisit_at", async () => {
    const user = userEvent.setup();
    await openSheet(user);
    await user.click(screen.getByRole("button", { name: "拒絕" }));
    expect(screen.queryByLabelText("重看日期")).toBeNull();
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(changeSet({ status: "rejected", reason: "想再觀察幾天" }));
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    expect(vi.mocked(changeApi.createChangeSet).mock.calls[0][2].decide).toEqual({ decision: "rejected", reason: "想再觀察幾天" });
  });
});

describe("ConfirmPage（F22-I02）沒收到伺服器回應", () => {
  it("保存失敗沿用同一個 operation_id 重試，不重複建立", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
    vi.mocked(changeApi.createChangeSet)
      .mockRejectedValueOnce(new Error("未收到伺服器回應，結果尚未確認。請沿用原操作重試，不要重做平台操作。"))
      .mockResolvedValueOnce(changeSet());
    vi.mocked(changeApi.approveChangeSet).mockResolvedValue(changeSet({ status: "approved" }));
    renderAt(proposePath);
    await user.click(await screen.findByRole("button", { name: /核准暫停，接著到平台操作/ }));
    expect(await screen.findByText(/未收到伺服器回應/)).toBeTruthy();
    const firstBody = vi.mocked(changeApi.createChangeSet).mock.calls[0][2];

    await user.click(screen.getByRole("button", { name: /核准暫停，接著到平台操作/ }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalledTimes(2));
    expect(vi.mocked(changeApi.createChangeSet).mock.calls[1][2]).toEqual(firstBody);
    await waitFor(() => expect(changeApi.approveChangeSet).toHaveBeenCalled());
  });
});

describe("ConfirmPage（F22-I02）步驟導正", () => {
  // F47-I07 (drill-10 C3-E): 「回到確認」 on a later step lands here and stays — read-only, one link forward.
  it("已核准且還沒回報：從確認網址打開就留在確認頁，唯讀，連到到平台完成", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ status: "approved", approved_at: "2026-09-21T00:00:00Z", items: [changeItem({ verification_state: "pending", reported_at: null })] })],
    });
    renderAt(confirmPath());
    expect(await screen.findByText("已核准")).toBeTruthy();
    expect(screen.queryByTestId("probe-path")).toBeNull();
    expect(screen.getByRole("link", { name: "接著到平台完成 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/handoff");
    expect(screen.queryByRole("button", { name: "拒絕／暫緩" })).toBeNull();
    expect(screen.queryByRole("button", { name: /核准暫停/ })).toBeNull();
    expect(screen.queryByText("這則主打什麼？")).toBeNull();
    expect(anglesApi.getAngles).not.toHaveBeenCalled();
  });

  it("已核准且已讀回：留在確認頁，連到核對結果", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ status: "approved", approved_at: "2026-09-21T00:00:00Z", items: [changeItem({ verification_state: "confirmed", reported_at: "2026-09-21T01:00:00Z" })] })],
    });
    renderAt(confirmPath());
    expect(await screen.findByRole("link", { name: "看核對結果 →" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "看核對結果 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/verify");
    expect(screen.queryByTestId("probe-path")).toBeNull();
  });

  it("草稿在確認頁核准後照舊往前到到平台完成", async () => {
    const user = userEvent.setup();
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [changeSet()] });
    vi.mocked(changeApi.approveChangeSet).mockResolvedValue(changeSet({ status: "approved", approved_at: "2026-09-21T00:00:00Z" }));
    renderAt(confirmPath());
    await user.click(await screen.findByRole("button", { name: /核准暫停，接著到平台操作/ }));
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/handoff"));
  });

  it("已拒絕的清單留在確認頁，顯示關閉狀態", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ status: "rejected", reason: "資料還不夠" })],
    });
    renderAt(confirmPath());
    expect(await screen.findByText("已拒絕・資料還不夠")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "拒絕／暫緩" })).toBeNull();
  });
});

describe("ConfirmPage（F25-I03）propose/budget 路由", () => {
  it("畫出完整證據卡：同組則數、每日預算＋漲幅、購買成本量尺、後端給的加碼理由、本月預算放得下", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([scaleQueueItem()]));
    vi.mocked(changeApi.getMonthlyBudget).mockResolvedValue({
      month: "2026-09", currency: "TWD", amount: 60000, revision: 2, known_spend: 22000, ongoing_estimate: 28000,
      reserved_increases: 0, available: 10000, uncertainties: [], can_increase: true, period_end: "2026-09-30", confirmed_at: null, notice: "",
    });
    renderAt(proposeBudgetPath);
    expect(await screen.findByText("提議：加預算")).toBeTruthy();
    expect(screen.getByText("可加預算")).toBeTruthy();
    expect(screen.getByText("廣告組 G・廣泛受眾・同組 8 則一起受影響")).toBeTruthy();
    expect(screen.getByText(/1,000/)).toBeTruthy();
    expect(screen.getByText(/1,200/)).toBeTruthy();
    expect(screen.getByText("+20%")).toBeTruthy();
    expect(screen.getByText(/購買成本 306/)).toBeTruthy();
    expect(screen.getByText("上限 450")).toBeTruthy();
    // F48-I11: the reason is `scale.reason_text` as served; no fixed 「主力穩定 N 期」／「等 N–M 天」 words.
    expect(screen.getByText(SCALE_REASON_TEXT)).toBeTruthy();
    expect(screen.getByText("核准後會排一次檢查")).toBeTruthy();
    expect(screen.queryByText(/主力穩定|3–5 天/)).toBeNull();
    expect(await screen.findByText("本月預算放得下")).toBeTruthy();
    expect(screen.getByText(/這次要花 1,800/)).toBeTruthy();
    expect(screen.getByText(/還剩 8,200/)).toBeTruthy();
  });

  it("找不到這個 owner 的加預算提議：不誤用暫停提議的措辭", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue());
    renderAt(proposeBudgetPath);
    expect(await screen.findByText("找不到這個投放組的加預算提議")).toBeTruthy();
  });

  it("第一次核准才建立 budget 草稿，payload 照 feature Decisions 的欄位", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([scaleQueueItem()]));
    vi.mocked(changeApi.getMonthlyBudget).mockResolvedValue({
      month: "2026-09", currency: "TWD", amount: 60000, revision: 2, known_spend: 22000, ongoing_estimate: 28000,
      reserved_increases: 0, available: 10000, uncertainties: [], can_increase: true, period_end: "2026-09-30", confirmed_at: null, notice: "",
    });
    const draft = changeSet({
      title: "加碼「廣告組 G・廣泛受眾」",
      items: [changeItem({ kind: "budget", target_id: "aex_owner_G", before: { daily_amount: 1000 }, after: { daily_amount: 1200 } })],
    });
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(draft);
    vi.mocked(changeApi.approveChangeSet).mockResolvedValue({ ...draft, status: "approved" });
    renderAt(proposeBudgetPath);
    await user.click(await screen.findByRole("button", { name: /核准加碼，接著到平台操作/ }));

    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    const body = vi.mocked(changeApi.createChangeSet).mock.calls[0][2];
    expect(body.operation_id).toMatch(/^triage-budget:aex_owner_G:/);
    expect(body.title).toBe("加碼「廣告組 G・廣泛受眾」");
    expect(body.items).toEqual([{ kind: "budget", target_id: "aex_owner_G", after: { daily_amount: 1200 }, reason: SCALE_REASON_TEXT }]);
    await waitFor(() => expect(changeApi.approveChangeSet).toHaveBeenCalled());
  });

  it("月預算放不下的 409：顯示後端訊息，不重建草稿", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([scaleQueueItem()]));
    vi.mocked(changeApi.getMonthlyBudget).mockResolvedValue({
      month: "2026-09", currency: "TWD", amount: 60000, revision: 2, known_spend: 22000, ongoing_estimate: 28000,
      reserved_increases: 0, available: 10000, uncertainties: [], can_increase: true, period_end: "2026-09-30", confirmed_at: null, notice: "",
    });
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(changeSet({
      items: [changeItem({ kind: "budget", target_id: "aex_owner_G", before: { daily_amount: 1000 }, after: { daily_amount: 1200 } })],
    }));
    vi.mocked(changeApi.approveChangeSet).mockRejectedValue(
      new ChangeRequestRejected("這份變更超過本月總額；尚未讀回完成的降額不能先釋放額度。"),
    );
    renderAt(proposeBudgetPath);
    await user.click(await screen.findByRole("button", { name: /核准加碼，接著到平台操作/ }));
    expect(await screen.findByText("這份變更超過本月總額；尚未讀回完成的降額不能先釋放額度。")).toBeTruthy();
    expect(changeApi.createChangeSet).toHaveBeenCalledTimes(1);
  });

  it("前提變了的 409（非月預算訊息，暫停提議）：仍照既有規則靜默重建一次再核准", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
    const draft = changeSet();
    vi.mocked(changeApi.createChangeSet).mockResolvedValueOnce(draft).mockResolvedValueOnce({ ...draft, id: "acs_rebuilt" });
    vi.mocked(changeApi.approveChangeSet)
      .mockRejectedValueOnce(new ChangeRequestRejected("這項變更所依據的設定已改變，請依現況重新建立清單。"))
      .mockResolvedValueOnce({ ...draft, id: "acs_rebuilt", status: "approved" });
    renderAt(proposePath);
    await user.click(await screen.findByRole("button", { name: /核准暫停，接著到平台操作/ }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalledTimes(2));
    expect(vi.mocked(changeApi.createChangeSet).mock.calls[1][2].supersedes_id).toBe("acs_1");
    await waitFor(() => expect(changeApi.approveChangeSet).toHaveBeenCalledTimes(2));
  });
});

describe("ConfirmPage（F40-I08）本月預算放得下：三個狀態", () => {
  const budgetDraft = () => changeSet({
    title: "加碼「廣告組 G・廣泛受眾」",
    items: [changeItem({ kind: "budget", target_id: "aex_owner_G", before: { daily_amount: 1000 }, after: { daily_amount: 1200 } })],
  });
  const card = () => screen.getByRole("region", { name: "本月預算放得下" });

  it("(i) 放得下：算式標題、四段圖例、預留說明點名還在跑的投放組；核准可按、旁邊沒有原因", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([scaleQueueItem()]));
    vi.mocked(changeApi.getMonthlyBudget).mockResolvedValue(monthlyBudget({
      amount: 10500, known_spend: 0, ongoing_estimate: 7500, reserved_increases: 0, available: 3000,
      ongoing_owners: [{ entity_id: "aex_prev", name: "9 月活動", daily: 1500, days: 5, commitment: 7500 }],
    }));
    renderAt(proposeBudgetPath);
    expect(await screen.findByText("9 月還能花 3,000")).toBeTruthy();
    const text = seen(card());
    expect(text).toContain("放得下");
    expect(text).toContain("（月預算 10,500 − 已花 0 − 預留 7,500）");
    expect(text).toContain("已花 0");
    expect(text).toContain("預留 7,500");
    expect(text).toContain("這次要花 1,800");
    expect(text).toContain("還剩 1,200");
    expect(text).toContain("預留＝9 月活動 還有 5 天沒跑完，每天 1,500 先留著；跑完就還回來。");
    // The word 預留 carries its definition (hidden until hover／focus), not printed as running text.
    expect(card().querySelector("[data-slot=term] [role=tooltip]")?.textContent).toContain("跑完就還回來");
    const approve = screen.getByRole("button", { name: "核准加碼，接著到平台操作 →" });
    expect((approve as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText(/⚠/)).toBeNull();
  });

  it("(i) 幾個投放組都在跑：依承諾金額排序、最多點名三個、其餘算「等 N 項」", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([scaleQueueItem()]));
    vi.mocked(changeApi.getMonthlyBudget).mockResolvedValue(monthlyBudget({
      ongoing_owners: [
        { entity_id: "a", name: "小的", daily: 100, days: 2, commitment: 200 },
        { entity_id: "b", name: "最大", daily: 1500, days: 5, commitment: 7500 },
        { entity_id: "c", name: "第二", daily: 800, days: 4, commitment: 3200 },
        { entity_id: "d", name: "第三", daily: 300, days: 3, commitment: 900 },
      ],
    }));
    renderAt(proposeBudgetPath);
    expect(await screen.findByText("預留＝最大 還有 5 天沒跑完，每天 1,500；第二 還有 4 天沒跑完，每天 800；第三 還有 3 天沒跑完，每天 300等 4 項 先留著；跑完就還回來。")).toBeTruthy();
  });

  it("(ii) 還沒設月預算：標題、「設定 N 月月預算 →」連去投放中心的月預算表單（帶 return＝這一頁），核准灰掉、旁邊寫原因", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([scaleQueueItem()]));
    vi.mocked(changeApi.getMonthlyBudget).mockResolvedValue(monthlyBudget({
      amount: null, known_spend: null, ongoing_estimate: null, available: null, can_increase: false, ongoing_owners: [],
      uncertainties: ["尚未設定 2026-09 的月總額。"],
    }));
    renderAt(proposeBudgetPath);
    expect(await screen.findByText("9 月還沒設月預算")).toBeTruthy();
    const text = seen(card());
    expect(text).toContain("還沒設月預算");
    expect(text).toContain("，算不出放不放得下");
    expect(text).toContain("尚未設定 2026-09 的月總額。");
    expect(text).not.toContain("還能花");
    // F49 Contract Q (drill-11 Q4): the link carries this page's own path, so the home budget editor offers
    // 「← 回到剛才的核准」 after saving.
    expect(screen.getByRole("link", { name: "設定 9 月月預算 →" }).getAttribute("href"))
      .toBe(`/brands/brd_1/ads?budget=edit&return=${encodeURIComponent(proposeBudgetPath)}`);
    expect(screen.getByText("⚠ 要先設 9 月月預算")).toBeTruthy();
    expect((screen.getByRole("button", { name: "核准加碼，接著到平台操作 →" }) as HTMLButtonElement).disabled).toBe(true);
    expect(changeApi.createChangeSet).not.toHaveBeenCalled();
  });

  it("(iii) 核准被「前提變了」擋下：標題＋「重新檢查」，核准灰掉、旁邊寫原因；重新檢查才重建草稿（帶 supersedes_id），不自動再核准", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([scaleQueueItem()]));
    const draft = budgetDraft();
    const rebuilt = { ...draft, id: "acs_rebuilt" };
    vi.mocked(changeApi.createChangeSet).mockResolvedValueOnce(draft).mockResolvedValueOnce(rebuilt);
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [rebuilt] });
    vi.mocked(changeApi.approveChangeSet).mockRejectedValueOnce(new ChangeRequestRejected("這項變更所依據的設定已改變，請依現況重新建立清單。"));
    renderAt(proposeBudgetPath);
    await user.click(await screen.findByRole("button", { name: /核准加碼，接著到平台操作/ }));

    expect(await screen.findByText("計畫、素材或月份已改變")).toBeTruthy();
    const text = seen(card());
    expect(text).toContain("要重新檢查");
    expect(text).toContain("，這批內容要重新對一次");
    expect(text).not.toContain("還能花");
    expect(screen.getByText("⚠ 內容變了，先按「重新檢查」")).toBeTruthy();
    expect((screen.getByRole("button", { name: "核准加碼，接著到平台操作 →" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(changeApi.createChangeSet).toHaveBeenCalledTimes(1);
    expect(changeApi.approveChangeSet).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "重新檢查" }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalledTimes(2));
    expect(vi.mocked(changeApi.createChangeSet).mock.calls[1][2].supersedes_id).toBe("acs_1");
    // The rebuilt draft takes over the page on its own confirm URL (the set route reads it back); 核准 is the
    // user's next press, not automatic.
    await waitFor(() => expect(changeApi.getChangeControl).toHaveBeenCalled());
    expect(await screen.findByText("9 月還能花 10,000")).toBeTruthy();
    expect((screen.getByRole("button", { name: "核准加碼，接著到平台操作 →" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText(/⚠/)).toBeNull();
    expect(changeApi.approveChangeSet).toHaveBeenCalledTimes(1);
  });

  it("(iii) 重新檢查後再被擋：照舊顯示後端訊息，不再無限提供重新檢查、按鈕不卡在處理中", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([scaleQueueItem()]));
    const draft = budgetDraft();
    const rebuilt = { ...draft, id: "acs_rebuilt" };
    vi.mocked(changeApi.createChangeSet).mockResolvedValueOnce(draft).mockResolvedValueOnce(rebuilt);
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [rebuilt] });
    // Real latency: the answer lands after the page has re-rendered.
    vi.mocked(changeApi.approveChangeSet).mockImplementation(() => new Promise((_, reject) =>
      setTimeout(() => reject(new ChangeRequestRejected("這個物件已有相同操作待核對，請先處理原清單。")), 50)));
    renderAt(proposeBudgetPath);
    await user.click(await screen.findByRole("button", { name: /核准加碼，接著到平台操作/ }));
    await user.click(await screen.findByRole("button", { name: "重新檢查" }));
    // Wait for the rebuilt set's own page (it reads the set back) before pressing 核准 there.
    await waitFor(() => expect(changeApi.getChangeControl).toHaveBeenCalled());
    expect(await screen.findByText("9 月還能花 10,000")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "核准加碼，接著到平台操作 →" }));
    expect(await screen.findByText("這個物件已有相同操作待核對，請先處理原清單。")).toBeTruthy();
    expect(screen.queryByText(/處理中/)).toBeNull();
    expect(screen.queryByRole("button", { name: "重新檢查" })).toBeNull();
    expect(changeApi.createChangeSet).toHaveBeenCalledTimes(2);
  });
});

describe("ConfirmPage（F27-I15）new_ad kind", () => {
  function newAdItem(overrides: Partial<ChangeItem> = {}): ChangeItem {
    return changeItem({
      id: "item_new", kind: "new_ad", target_id: "plc_1",
      target: { id: "plc_1", name: "1150710 夏季新裝（新廣告）", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "" },
      before: {}, after: { daily_amount: 0 }, reason: "新測試建議",
      handoff_snapshot: {
        filename: "1150710.mp4", revision: 1,
        copy: { headline: "夏季新裝上市", body: "限時 79 折，今天就試穿" },
        destination: { native_id: "23900", name: "廣告組 H・興趣受眾" },
        budget_owner: { budget_amount: 1000, currency: "TWD" },
      },
      ...overrides,
    });
  }
  it("確認新廣告提議：畫出創意預覽、加入的投放組與核准文案", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [changeSet({ items: [newAdItem()] })] });
    renderAt(confirmPath());
    expect(await screen.findByText("確認新廣告提議")).toBeTruthy();
    expect(screen.getByText("1150710 夏季新裝（新廣告）")).toBeTruthy();
    expect(screen.getByText("廣告組 H・興趣受眾")).toBeTruthy();
    expect(screen.getByText("夏季新裝上市")).toBeTruthy();
    expect(screen.getByText("限時 79 折，今天就試穿")).toBeTruthy();
    expect(screen.getByRole("button", { name: /核准新廣告，接著到平台操作/ })).toBeTruthy();
  });
});

describe("ConfirmPage（F27-I15 Contract F／F28-I11）cleanup propose 路由", () => {
  it("先是提議步驟，下一步到確認：關的清單有等級、成本與「不會新增花費」，不再寫「花費最低」", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    renderAt(proposeCleanupPath);
    expect(await screen.findByRole("heading", { name: "關 2 則、留 3 則" })).toBeTruthy();
    expect(screen.getByText("關的順序")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /核准清理/ })).toBeNull();
    expect(changeApi.createChangeSet).not.toHaveBeenCalled();

    await user.click(screen.getByRole("link", { name: "下一步：確認 →" }));
    expect(await screen.findByRole("heading", { name: "確認清理" })).toBeTruthy();
    expect(screen.getByText("清理")).toBeTruthy();
    expect(screen.getByText("關 2 則、留 3 則")).toBeTruthy();
    expect(screen.getByText("✓ 不會新增花費")).toBeTruthy();
    const rows = screen.getAllByRole("listitem").filter((li) => seen(li).endsWith("關"));
    expect(rows.map(seen)).toEqual(["1150701 情境圖 A花了 1540，一筆都沒賣出沒賣出購買0 筆關", "1150702 情境圖 B第 5／5 名，每筆 620 對上限 450（太貴）太貴每賣一筆620 元關"]);
    // v10: the grade words are glossary terms and the legend (grade rules + money rule) sits under the card.
    expect(document.querySelector("[data-slot=grade-rules]")).toBeTruthy();
    expect(screen.queryByText(/花費最低/)).toBeNull();
    expect(screen.getByRole("link", { name: "← 提議" }).getAttribute("href")).toBe(proposeCleanupPath);
    expect(changeApi.createChangeSet).not.toHaveBeenCalled();
  });

  it("找不到這個活動的清理提議", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue());
    renderAt(proposeCleanupPath);
    expect(await screen.findByText("找不到這個活動的清理提議")).toBeTruthy();
  });

  it("第一次核准才建立草稿：每則廣告一個 pause item，並帶上 source=cleanup", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    const draft = changeSet({
      status: "approved",
      items: [
        changeItem({ id: "item_low1", target_id: "aex_low1", verification_state: "pending", reported_at: null }),
        changeItem({ id: "item_low2", target_id: "aex_low2", verification_state: "pending", reported_at: null }),
      ],
    });
    vi.mocked(changeApi.createChangeSet).mockResolvedValue({ ...draft, status: "draft", approved_at: null });
    vi.mocked(changeApi.approveChangeSet).mockResolvedValue(draft);
    renderAt(`${proposeCleanupPath}?step=confirm`);
    await user.click(await screen.findByRole("button", { name: "核准清理（關 2 則） →" }));

    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    const body = vi.mocked(changeApi.createChangeSet).mock.calls[0][2] as unknown as {
      operation_id: string; title: string; items: { kind: string; target_id: string }[]; source?: string;
    };
    expect(body.operation_id).toMatch(/^triage-cleanup:cmp_1:/);
    expect(body.title).toBe("清理「【銷售】測試活動」");
    expect(body.items).toEqual([
      { kind: "pause", target_id: "aex_low1", after: { status: "PAUSED" }, reason: "花了 1540，一筆都沒賣出" },
      { kind: "pause", target_id: "aex_low2", after: { status: "PAUSED" }, reason: "第 5／5 名，每筆 620 對上限 450（太貴）" },
    ]);
    expect(body.source).toBe("cleanup");
    await waitFor(() => expect(changeApi.approveChangeSet).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/handoff"));
  });

  it("既有清理清單：畫出多列廣告，核准後有下一件可看", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        items: [
          changeItem({ id: "item_low1", target_id: "aex_low1", verification_state: "pending", reported_at: null }),
          changeItem({ id: "item_low2", target_id: "aex_low2", verification_state: "pending", reported_at: null }),
        ],
      })],
    });
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem({
      proposal: { kind: "cleanup", change_set_id: "acs_1", campaign_id: "cmp_1", status: "draft", verification_state: "pending", reason: null, revisit_at: null, multi: true },
    })]));
    renderAt(confirmPath());
    expect(await screen.findByRole("heading", { name: "確認清理" })).toBeTruthy();
    expect(screen.getByText("1150701 情境圖 A")).toBeTruthy();
    expect(screen.getByText("1150702 情境圖 B")).toBeTruthy();
    expect(screen.getByText("關 2 則、留 3 則")).toBeTruthy();
    // The draft's own items are the close list; the proposal step is one link back.
    expect(screen.getByRole("link", { name: "回到「提議」" }).getAttribute("href")).toBe(proposeCleanupPath);
  });
});

describe("ConfirmPage（F28-I15）清理草稿與最新提議不同", () => {
  const draftProposal = (id = "acs_old") => ({
    kind: "cleanup" as const, change_set_id: id, campaign_id: "cmp_1", status: "draft" as const,
    verification_state: "pending" as const, reason: null, revisit_at: null, multi: true,
  });
  // The dev-DB shape the user hit: the draft closes one ad the proposal still closes plus one it no longer does;
  // the proposal now also closes a second ad.
  const outdatedDraft = (overrides: Partial<ChangeSet> = {}) => changeSet({
    id: "acs_old", title: "清理「【銷售】測試活動」",
    items: [
      changeItem({ id: "item_low1", target_id: "aex_low1", reason: "花費最低" }),
      changeItem({
        id: "item_keep1", target_id: "aex_keep1", reason: "花費最低",
        target: { id: "aex_keep1", name: "晨光隨行杯・日常出發", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "n_k1" },
      }),
    ],
    ...overrides,
  });

  it("畫出差異（新增／不關），不給核准清理；改用最新提議帶 supersedes_id 建新清單並導去新清單的確認頁", async () => {
    const user = userEvent.setup();
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [outdatedDraft()] });
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem({ proposal: draftProposal() })]));
    renderAt(confirmPath("acs_old"));

    expect(await screen.findByRole("heading", { name: "確認清理" })).toBeTruthy();
    expect(screen.getByText("提議已更新")).toBeTruthy();
    expect(screen.getByText("關 2 則、留 3 則")).toBeTruthy();
    const rows = screen.getAllByRole("listitem").filter((li) => li.hasAttribute("data-mark"));
    expect(rows.map((r) => [r.getAttribute("data-mark"), seen(r)])).toEqual([
      ["close", "1150701 情境圖 A花了 1540，一筆都沒賣出沒賣出購買0 筆關"],
      ["added", "1150702 情境圖 B新增第 5／5 名，每筆 620 對上限 450（太貴）太貴每賣一筆620 元關"],
      ["dropped", "晨光隨行杯・日常出發划算每賣一筆48 元不關"],
    ]);
    expect(screen.queryByRole("button", { name: /核准清理/ })).toBeNull();
    expect(screen.queryByText("核准不會改動平台")).toBeNull();

    const rebuilt = changeSet({
      id: "acs_new", title: "清理「【銷售】測試活動」",
      items: [
        changeItem({ id: "item_n1", target_id: "aex_low1" }),
        changeItem({ id: "item_n2", target_id: "aex_low2" }),
      ],
    });
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(rebuilt);
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [rebuilt, outdatedDraft({ status: "superseded" })],
    });
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem({ proposal: draftProposal("acs_new") })]));
    await user.click(screen.getByRole("button", { name: "改用最新提議 →" }));

    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalledTimes(1));
    const body = vi.mocked(changeApi.createChangeSet).mock.calls[0][2] as unknown as {
      operation_id: string; title: string; supersedes_id?: string; source?: string; items: { target_id: string }[];
    };
    expect(body.supersedes_id).toBe("acs_old");
    expect(body.source).toBe("cleanup");
    expect(body.title).toBe("清理「【銷售】測試活動」");
    expect(body.operation_id).toMatch(/^triage-cleanup-adopt:acs_old:/);
    expect(body.items.map((i) => i.target_id)).toEqual(["aex_low1", "aex_low2"]);
    // The new set matches the proposal: the ordinary confirm page with 核准清理.
    expect(await screen.findByRole("button", { name: "核准清理（關 2 則） →" })).toBeTruthy();
    expect(screen.queryByText("提議已更新")).toBeNull();
    expect(changeApi.approveChangeSet).not.toHaveBeenCalled();
  });

  it("草稿與提議一致：頁面照舊，有核准清理、沒有差異標記", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        items: [
          changeItem({ id: "item_low2", target_id: "aex_low2" }),
          changeItem({ id: "item_low1", target_id: "aex_low1" }),
        ],
      })],
    });
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem({ proposal: draftProposal("acs_1") })]));
    renderAt(confirmPath());
    expect(await screen.findByRole("button", { name: "核准清理（關 2 則） →" })).toBeTruthy();
    expect(screen.getByText("核准不會改動平台")).toBeTruthy();
    expect(screen.queryByText("提議已更新")).toBeNull();
    expect(screen.queryByRole("button", { name: /改用最新提議/ })).toBeNull();
    expect(screen.getAllByRole("listitem").every((li) => li.getAttribute("data-mark") === null)).toBe(true);
  });

  it("佇列讀取失敗：不提供改用最新提議，也不當掉", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [outdatedDraft()] });
    vi.mocked(triageApi.getQueue).mockRejectedValue(new Error("queue down"));
    renderAt(confirmPath("acs_old"));
    await waitFor(() => expect(screen.queryByRole("heading", { level: 1 }) ?? screen.queryByText("這份清單有多項變更")).toBeTruthy());
    expect(screen.queryByRole("button", { name: /改用最新提議/ })).toBeNull();
    expect(screen.queryByText("提議已更新")).toBeNull();
    expect(changeApi.createChangeSet).not.toHaveBeenCalled();
  });

  it("已拒絕的清單不走這條重建", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [outdatedDraft({ status: "rejected", reason: "先不要" })],
    });
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem({ proposal: { ...draftProposal(), status: "rejected" } })]));
    renderAt(confirmPath("acs_old"));
    expect(await screen.findByText(/已拒絕・先不要/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /改用最新提議/ })).toBeNull();
    expect(screen.queryByText("提議已更新")).toBeNull();
  });

  it("propose 路由的確認步驟遇到既有草稿：導去那份草稿自己的確認頁（在那裡比對）", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [outdatedDraft()] });
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem({ proposal: draftProposal() })]));
    renderAt(`${proposeCleanupPath}?step=confirm`);
    expect(await screen.findByText("提議已更新")).toBeTruthy();
    expect(screen.getByRole("button", { name: "改用最新提議 →" })).toBeTruthy();
    expect(changeApi.createChangeSet).not.toHaveBeenCalled();
  });
});

// F29-I14: the user's own pick on the cleanup proposal (`?keep=` = the proposed ads they unticked). The confirm step
// lists only the ticked ads; 核准 creates the set with them and `declined_ids` (F29-I01 Contract B).
describe("ConfirmPage（F29-I14）清理：自己挑要關哪幾則", () => {
  const draftProposal = (id = "acs_1") => ({
    kind: "cleanup" as const, change_set_id: id, campaign_id: "cmp_1", status: "draft" as const,
    verification_state: "pending" as const, reason: null, revisit_at: null, multi: true,
  });
  const bodyOf = (call = 0) => vi.mocked(changeApi.createChangeSet).mock.calls[call][2] as unknown as {
    items: { target_id: string }[]; declined_ids?: string[]; source?: string; supersedes_id?: string;
    decide?: { decision: string; reason: string; revisit_at?: string };
  };

  it("全部取消勾選：確認頁說一則都沒勾，核准不能按，拒絕還在", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    renderAt(`${proposeCleanupPath}?step=confirm&keep=aex_low1,aex_low2`);
    expect(await screen.findByRole("heading", { name: "確認清理" })).toBeTruthy();
    expect(screen.getByText("關 0 則、留 5 則")).toBeTruthy();
    expect(screen.getByText("一則都沒勾。回提議勾選，或按拒絕")).toBeTruthy();
    expect((screen.getByRole("button", { name: "核准清理（關 0 則） →" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("一則都沒勾，沒有可核准的")).toBeTruthy();
    expect(screen.getByRole("button", { name: "拒絕／暫緩" })).toBeTruthy();
    // 提議 keeps the ticks when the user goes back.
    expect(screen.getByRole("link", { name: "← 提議" }).getAttribute("href")).toBe(`${proposeCleanupPath}?keep=aex_low1%2Caex_low2`);
  });

  it("取消勾一則：只列勾的那則；核准建立的草稿只有它，沒勾的送 declined_ids", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    const draft = changeSet({ items: [changeItem({ id: "item_low1", target_id: "aex_low1" })] });
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(draft);
    vi.mocked(changeApi.approveChangeSet).mockResolvedValue({ ...draft, status: "approved" });
    renderAt(`${proposeCleanupPath}?step=confirm&keep=aex_low2`);
    expect(await screen.findByText("關 1 則、留 4 則")).toBeTruthy();
    const rows = screen.getAllByRole("listitem").filter((li) => seen(li).endsWith("關"));
    expect(rows.map(seen)).toEqual(["1150701 情境圖 A花了 1540，一筆都沒賣出沒賣出購買0 筆關"]);
    await user.click(screen.getByRole("button", { name: "核准清理（關 1 則） →" }));

    await waitFor(() => expect(changeApi.approveChangeSet).toHaveBeenCalled());
    expect(bodyOf().items.map((i) => i.target_id)).toEqual(["aex_low1"]);
    expect(bodyOf().declined_ids).toEqual(["aex_low2"]);
    expect(bodyOf().source).toBe("cleanup");
  });

  it("拒絕是拒絕整個提議：草稿帶全部提議的廣告、不帶 declined_ids", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    const draft = changeSet({ items: [changeItem({ id: "i1", target_id: "aex_low1" }), changeItem({ id: "i2", target_id: "aex_low2" })] });
    vi.mocked(changeApi.createChangeSet).mockResolvedValue({ ...draft, status: "rejected", reason: "還在檔期" });
    renderAt(`${proposeCleanupPath}?step=confirm&keep=aex_low1,aex_low2`);
    await user.click(await screen.findByRole("button", { name: "拒絕／暫緩" }));
    await user.click(screen.getByRole("button", { name: "拒絕" }));
    await user.click(screen.getByRole("button", { name: "保存" }));
    // F47-I07: the cleanup draft and its rejection are one write.
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    expect(bodyOf().items.map((i) => i.target_id)).toEqual(["aex_low1", "aex_low2"]);
    expect(bodyOf().declined_ids).toBeUndefined();
    expect(bodyOf().source).toBe("cleanup");
    expect(bodyOf().decide?.decision).toBe("rejected");
    expect(changeApi.decideChangeSet).not.toHaveBeenCalled();
  });

  it("F28-I15 仍成立：使用者自己挑的子集（declined_ids）不算過期草稿，照常可以核准", async () => {
    const subset = { ...changeSet({ items: [changeItem({ id: "item_low1", target_id: "aex_low1" })] }), plan_json: { declined_ids: ["aex_low2"] } } as ChangeSet;
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [subset] });
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem({ proposal: draftProposal("acs_1") })]));
    renderAt(confirmPath());
    expect(await screen.findByRole("button", { name: "核准清理（關 1 則） →" })).toBeTruthy();
    expect(screen.getByText("關 1 則、留 4 則")).toBeTruthy();
    expect(screen.queryByText("提議已更新")).toBeNull();
    expect(screen.queryByRole("button", { name: /改用最新提議/ })).toBeNull();
  });

  it("同一份子集但沒有 declined_ids（舊草稿）：仍是過期草稿，只給改用最新提議", async () => {
    const legacy = changeSet({ items: [changeItem({ id: "item_low1", target_id: "aex_low1" })] });
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [legacy] });
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem({ proposal: draftProposal("acs_1") })]));
    renderAt(confirmPath());
    expect(await screen.findByText("提議已更新")).toBeTruthy();
    expect(screen.getByRole("button", { name: "改用最新提議 →" })).toBeTruthy();
  });

  it("帶著自己的勾選到確認：不被導去既有草稿；核准時以新勾選取代那份草稿", async () => {
    const user = userEvent.setup();
    const old = changeSet({ items: [changeItem({ id: "i1", target_id: "aex_low1" }), changeItem({ id: "i2", target_id: "aex_low2" })] });
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [old] });
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem({ proposal: draftProposal("acs_1") })]));
    const picked = changeSet({ id: "acs_2", items: [changeItem({ id: "i3", target_id: "aex_low2" })] });
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(picked);
    vi.mocked(changeApi.approveChangeSet).mockResolvedValue({ ...picked, status: "approved" });
    renderAt(`${proposeCleanupPath}?step=confirm&keep=aex_low1`);
    await user.click(await screen.findByRole("button", { name: "核准清理（關 1 則） →" }));
    await waitFor(() => expect(changeApi.approveChangeSet).toHaveBeenCalled());
    expect(bodyOf().supersedes_id).toBe("acs_1");
    expect(bodyOf().items.map((i) => i.target_id)).toEqual(["aex_low2"]);
    expect(bodyOf().declined_ids).toEqual(["aex_low1"]);
  });

  it("上次拒絕過、變更差才回來的廣告在確認清單裡也說出來", async () => {
    const item = cleanupQueueItem();
    const ads = item.cleanup!.ads.map((ad, i) => (i === 1
      ? { ...ad, rejected_before: { grade: "watch" as const, grade_label: "偏貴", at: "2026-09-15T10:20:00Z", reason: null, change_set_id: "acs_x" } }
      : ad));
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([{ ...item, cleanup: { ...item.cleanup!, ads } }]));
    renderAt(`${proposeCleanupPath}?step=confirm`);
    expect(await screen.findByText("上次你拒絕時是偏貴，現在變太貴")).toBeTruthy();
  });
});

// F29-I10 Contract K: a failed read is its own state (ReadFailed + 重試), never "no proposal" or a silent fallback;
// the step flow's one exit shows only while the decision is open.
describe("ConfirmPage（F29-I10）讀取失敗與出口", () => {
  it("暫停提議頁自己的讀取（Contract P）失敗：顯示讀取失敗、不說「找不到」；重試後照常（F45-I06）", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getPauseView).mockReset();
    vi.mocked(triageApi.getPauseView).mockRejectedValueOnce(new Error("pause down")).mockResolvedValueOnce(pauseView());
    renderAt(proposePath);
    expect((await screen.findByRole("alert")).textContent).toContain("讀取失敗");
    expect(screen.queryByText(/找不到這則廣告/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByRole("heading", { name: "提議：暫停這則廣告" })).toBeTruthy();
    expect(triageApi.getPauseView).toHaveBeenCalledTimes(2);
  });

  it("暫停提議頁的佇列讀取失敗：頁面照常、只少了「第幾件」，不擋核准（F45-I06）", async () => {
    vi.mocked(triageApi.getQueue).mockRejectedValue(new Error("queue down"));
    renderAt(proposePath);
    expect(await screen.findByRole("heading", { name: "提議：暫停這則廣告" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "核准暫停，接著到平台操作 →" })).toBeTruthy();
    expect(screen.queryByText(/第 \d+ 件／共/)).toBeNull();
    expect(screen.queryByText(/待決定清單讀不到/)).toBeNull();
  });

  it("清單路由的佇列讀取失敗：只有這一塊說失敗，變更內容與核准照舊；重試重讀", async () => {
    const user = userEvent.setup();
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [changeSet()] });
    vi.mocked(triageApi.getQueue).mockReset();
    vi.mocked(triageApi.getQueue).mockRejectedValueOnce(new Error("queue down")).mockResolvedValueOnce(queue([queueItem({ kind_key: "worse" })]));
    renderAt(confirmPath());
    expect(await screen.findByText(/待決定清單讀不到/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "提議：暫停這則廣告" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "核准暫停，接著到平台操作 →" })).toBeTruthy();
    await user.click(screen.getAllByRole("button", { name: "重試" })[0]);
    await waitFor(() => expect(screen.queryByText(/待決定清單讀不到/)).toBeNull());
    expect(screen.getByText("第 1 件／共 1 件")).toBeTruthy();
  });

  it("清理清單自己帶 source: cleanup：佇列讀不到也畫清理，不誤判成「多項變更」", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        source: "cleanup",
        items: [changeItem({ id: "item_low1", target_id: "aex_low1" }), changeItem({ id: "item_low2", target_id: "aex_low2" })],
      })],
    });
    vi.mocked(triageApi.getQueue).mockRejectedValue(new Error("queue down"));
    renderAt(confirmPath());
    expect(await screen.findByRole("heading", { name: "確認清理" })).toBeTruthy();
    expect(screen.queryByText("這份清單有多項變更")).toBeNull();
    expect(screen.getByText(/待決定清單讀不到/)).toBeTruthy();
  });

  it("主打候選讀取失敗：讀取失敗＋重試，「＋ 自訂」照樣可用；重試後出現候選", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
    vi.mocked(anglesApi.getAngles).mockReset();
    vi.mocked(anglesApi.getAngles)
      .mockRejectedValueOnce(new Error("angles down"))
      .mockResolvedValueOnce({ status: "ready", candidates: ["日常出發情境"], error: null });
    renderAt(proposePath);
    expect(await screen.findByText(/AI 整理的主打讀不到/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "＋ 自訂" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByRole("button", { name: "日常出發情境" })).toBeTruthy();
    expect(screen.queryByText(/AI 整理的主打讀不到/)).toBeNull();
    expect(anglesApi.getAngles).toHaveBeenCalledTimes(2);
  });

  it("開著的決定有「✕ 先不要，回投放中心」且取代同去處的返回鍵；已暫緩的清單沒有", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
    const view = renderAt(proposePath);
    const exit = await screen.findByRole("link", { name: "✕ 先不要，回投放中心" });
    expect(exit.getAttribute("href")).toBe("/brands/brd_1/ads");
    expect(screen.queryByRole("link", { name: "← 投放中心" })).toBeNull();
    view.unmount();

    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ status: "deferred", reason: "再看看", revisit_at: "2099-01-01T00:00:00Z" })],
    });
    renderAt(confirmPath());
    expect(await screen.findByText(/已暫緩・再看看/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: /先不要，回投放中心/ })).toBeNull();
    expect(screen.getByRole("link", { name: "← 回投放中心" })).toBeTruthy();
  });

  it("加預算的月預算讀取失敗：說失敗、核准內容照舊，重試重讀月預算", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([scaleQueueItem()]));
    vi.mocked(changeApi.getMonthlyBudget).mockRejectedValueOnce(new Error("x")).mockResolvedValueOnce({
      month: "2026-09", currency: "TWD", amount: 30000, revision: 1, known_spend: 12000, ongoing_estimate: 3000, reserved_increases: 0,
      available: 15000, uncertainties: [], can_increase: true, period_end: "2026-09-30", confirmed_at: null, notice: "",
    });
    renderAt(proposeBudgetPath);
    expect(await screen.findByText("月預算暫時讀取不到，不影響上面的核准內容。")).toBeTruthy();
    expect(screen.getByRole("button", { name: "核准加碼，接著到平台操作 →" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText(/還剩 /)).toBeTruthy();
    expect(changeApi.getMonthlyBudget).toHaveBeenCalledTimes(2);
  });
});

// F45-I06 (ads.md §6.49): the pause page reads the ad itself (Contract P); every entry lands on a working page.
describe("ConfirmPage（F45-I06）暫停提議頁讀廣告本身", () => {
  it("一般提議：這則廣告自己的數字＋量尺＋主打卡；不在佇列裡就沒有「第幾件」；草稿用 Contract P 建立", async () => {
    const user = userEvent.setup();
    const draft = changeSet({ status: "approved", items: [changeItem({ verification_state: "pending", reported_at: null })] });
    vi.mocked(changeApi.createChangeSet).mockResolvedValue({ ...draft, status: "draft", approved_at: null });
    vi.mocked(changeApi.approveChangeSet).mockResolvedValue(draft);
    renderAt(`${proposePath}?from=perf`);
    expect(await screen.findByRole("heading", { name: "提議：暫停這則廣告" })).toBeTruthy();
    const card = document.querySelector("[data-state=active]") as HTMLElement;
    expect(seen(card)).toContain("花費NT$ 1,420");
    expect(seen(card)).toContain("成交0 筆");
    expect(seen(card)).toContain("每筆成本—");
    expect(within(card).getByText("沒賣出", { selector: "[data-slot=chip]" }).getAttribute("data-grade")).toBe("wasted");
    expect(seen(card)).toContain("花到 NT$ 1,350 還一筆都沒賣，就算「沒賣出」（上限 × 3）");
    expect(screen.getByText("這則廣告自己的數字・08/25～09/21・9 天")).toBeTruthy();
    expect(seen(card)).toContain(`原因：${PAUSE_REASON_TEXT}`);
    expect(screen.getByText("✓ 不會新增花費")).toBeTruthy();
    expect(screen.getByText("這則主打什麼？")).toBeTruthy();
    expect(screen.queryByText(/第 \d+ 件／共/)).toBeNull();
    expect(triageApi.getPauseView).toHaveBeenCalledWith("brd_1", "cmp_1", "aex_1", expect.anything());
    expect(screen.getByRole("link", { name: "← 成效" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1?tab=perf");
    expect(screen.getByRole("link", { name: "✕ 先不要，回投放中心" })).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /核准暫停，接著到平台操作/ }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    const body = vi.mocked(changeApi.createChangeSet).mock.calls[0][2];
    expect(body.title).toBe("暫停「1150706 健身情境單圖」");
    expect(body.items).toEqual([{ kind: "pause", target_id: "aex_1", after: { status: "PAUSED" }, reason: PAUSE_REASON_TEXT }]);
  });

  it("有成交的廣告：每筆成本對照上限；這則在佇列裡時多「第幾件」", async () => {
    vi.mocked(triageApi.getPauseView).mockResolvedValue(pauseView({ triage: triage({
      grade: "over", grade_label: "太貴",
      current: { spend: 3380, result_count: 5, cost_per_result: 676, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    }) }));
    // F47-I07: 「第幾件」 counts the open home decisions (here two 變貴 rows), by the rows' own done.
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({ id: "int_0", kind_key: "worse", triage: triage({ entity_id: "aex_0" }) }), queueItem({ kind_key: "worse" })]));
    renderAt(proposePath);
    expect(await screen.findByText("第 2 件／共 2 件")).toBeTruthy();
    const card = document.querySelector("[data-state=active]") as HTMLElement;
    expect(seen(card)).toContain("成交5 筆");
    expect(seen(card)).toContain("每筆成本NT$ 676");
    expect(seen(card)).toContain("每筆 NT$ 676");
    expect(seen(card)).toContain("上限 NT$ 450");
    expect(within(card).getByText("太貴")).toBeTruthy();
  });

  it("F48-I11（drill 11 c3-09）：太貴的廣告用它自己的理由建草稿，不再是「花到上限 3 倍…沒賣出」", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getPauseView).mockResolvedValue(pauseView({
      triage: triage({
        grade: "over", grade_label: "太貴",
        current: { spend: 2588, result_count: 2, cost_per_result: 1294, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
      }),
      reason_text: "每筆 1294 對上限 450（太貴）",
    }));
    const draft = changeSet({ status: "approved", items: [changeItem({ verification_state: "pending", reported_at: null })] });
    vi.mocked(changeApi.createChangeSet).mockResolvedValue({ ...draft, status: "draft", approved_at: null });
    vi.mocked(changeApi.approveChangeSet).mockResolvedValue(draft);
    renderAt(proposePath);
    expect(await screen.findByRole("heading", { name: "提議：暫停這則廣告" })).toBeTruthy();
    const card = document.querySelector("[data-state=active]") as HTMLElement;
    expect(seen(card)).toContain("原因：每筆 1294 對上限 450（太貴）");
    expect(seen(card)).not.toContain("沒賣出");
    await user.click(screen.getByRole("button", { name: /核准暫停，接著到平台操作/ }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    expect(vi.mocked(changeApi.createChangeSet).mock.calls[0][2].items[0].reason).toBe("每筆 1294 對上限 450（太貴）");
  });

  it("F48-I11：沒有理由句（還沒有分數）時照實說「這則還沒有分數」＋後端給的評級字", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getPauseView).mockResolvedValue(pauseView({
      triage: triage({ grade: "insufficient", grade_label: "剛開始、數字還不夠", reason_code: "too_new" }),
      reason_text: null,
    }));
    const draft = changeSet({ status: "approved", items: [changeItem({ verification_state: "pending", reported_at: null })] });
    vi.mocked(changeApi.createChangeSet).mockResolvedValue({ ...draft, status: "draft", approved_at: null });
    vi.mocked(changeApi.approveChangeSet).mockResolvedValue(draft);
    renderAt(proposePath);
    expect(await screen.findByRole("heading", { name: "提議：暫停這則廣告" })).toBeTruthy();
    const card = document.querySelector("[data-state=active]") as HTMLElement;
    expect(seen(card)).toContain("原因：這則還沒有分數：剛開始、數字還不夠");
    await user.click(screen.getByRole("button", { name: /核准暫停，接著到平台操作/ }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    expect(vi.mocked(changeApi.createChangeSet).mock.calls[0][2].items[0].reason).toBe("這則還沒有分數：剛開始、數字還不夠");
  });

  it("已經停了：「這則已經停了」、已暫停・日期、只有一顆回上一頁（覆盤）；不問主打、不能核准", async () => {
    vi.mocked(triageApi.getPauseView).mockResolvedValue(pauseView({ state: "closed", closed_at: "2026-10-01T03:12:00+00:00" }));
    renderAt(`${proposePath}?from=review&ref=arv_1`);
    expect(await screen.findByRole("heading", { name: "這則已經停了" })).toBeTruthy();
    expect(screen.getByText("平台上這則廣告已經是關閉狀態，不用再暫停")).toBeTruthy();
    expect(screen.getByText("已暫停・10/01在平台上關掉")).toBeTruthy();
    expect(screen.queryByText("✓ 不會新增花費")).toBeNull();
    expect(screen.queryByText("這則主打什麼？")).toBeNull();
    expect(screen.queryByRole("button", { name: /核准/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "拒絕／暫緩" })).toBeNull();
    const links = within(document.querySelector("[data-slot=action-bar]") as HTMLElement).getAllByRole("link");
    expect(links.map((l) => [l.textContent, l.getAttribute("href")]))
      .toEqual([["← 回上一頁（覆盤）", "/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1/prepare"]]);
    expect(anglesApi.getAngles).not.toHaveBeenCalled();
  });

  it("已經停了但不知道何時關的：日期省略；從核對結果進來回那份清單的核對結果", async () => {
    vi.mocked(triageApi.getPauseView).mockResolvedValue(pauseView({ state: "closed", closed_at: null }));
    renderAt(`${proposePath}?from=verify&ref=acs_9`);
    expect(await screen.findByText("已暫停・在平台上關掉")).toBeTruthy();
    expect(screen.getByRole("link", { name: "← 回上一頁（核對結果）" }).getAttribute("href"))
      .toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_9/verify");
  });

  it("找不到（平台上已刪除）：說為什麼、最後一次讀到的日期、回投放中心", async () => {
    vi.mocked(triageApi.getPauseView).mockResolvedValue(pauseView({ state: "gone", name: "睡前一顆・直式影片", triage: null }));
    renderAt(`${proposePath}?from=review&ref=arv_1`);
    expect(await screen.findByRole("heading", { name: "找不到這則廣告" })).toBeTruthy();
    expect(screen.getByText("「睡前一顆・直式影片」在平台上已經刪除，系統讀不到它，沒有東西可以暫停。（最後一次讀到是 10/01）")).toBeTruthy();
    expect(screen.getByRole("link", { name: "回投放中心" }).getAttribute("href")).toBe("/brands/brd_1/ads");
    expect(screen.queryByRole("button", { name: /核准/ })).toBeNull();
    expect(anglesApi.getAngles).not.toHaveBeenCalled();
  });

  it("找不到、沒有名稱也沒讀過：「這則廣告」，不印日期", async () => {
    vi.mocked(triageApi.getPauseView).mockResolvedValue(pauseView({ state: "gone", name: null, triage: null, last_read_at: null }));
    renderAt(proposePath);
    expect(await screen.findByText("這則廣告在平台上已經刪除，系統讀不到它，沒有東西可以暫停。")).toBeTruthy();
  });

  it("返回鍵依 from：沒有或不認得的 from、缺 ref 都回投放中心（只剩出口）", async () => {
    for (const query of ["", "?from=nope", "?from=review"]) {
      const view = renderAt(`${proposePath}${query}`);
      expect(await screen.findByRole("heading", { name: "提議：暫停這則廣告" })).toBeTruthy();
      expect(screen.queryByRole("link", { name: /^← / })).toBeNull();
      expect(screen.getByRole("link", { name: "✕ 先不要，回投放中心" }).getAttribute("href")).toBe("/brands/brd_1/ads");
      view.unmount();
    }
    renderAt(`${proposePath}?from=verify&ref=acs_9`);
    expect((await screen.findByRole("link", { name: "← 核對結果" })).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_9/verify");
  });

  it("加預算的 propose 路由不讀 Contract P", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([scaleQueueItem()]));
    renderAt(proposeBudgetPath);
    expect(await screen.findByText("提議：加預算")).toBeTruthy();
    expect(triageApi.getPauseView).not.toHaveBeenCalled();
  });
});

// F49 Contract Q (drill-11 R4 H4): 下一件 on a closed set is the open decision row with the lowest served position —
// never a notice row (資料不足 on the campaign row) — and an ended campaign's closeout row opens its closeout.
describe("ConfirmPage（F49-I11）下一件跟著 served position", () => {
  const deferredSet = () => changeSet({ status: "deferred", reason: "再看看", revisit_at: "2099-01-01T00:00:00Z" });
  const notice = () => queueItem({
    id: "int_gap", kind_key: "insufficient_data", decision: false, position: null,
    action_url: "/brands/brd_1/ads/campaigns/cmp_2/wait", triage: triage({ entity_id: "aex_gap", campaign_id: "cmp_2" }),
  });

  it("skips the notice row and the handled row, follows position over list order", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [deferredSet()] });
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([
      notice(),
      queueItem({ id: "int_3", triage: triage({ entity_id: "aex_3", campaign_id: "cmp_3" }), decision: true, position: 3 }),
      queueItem({ id: "int_done", triage: triage({ entity_id: "aex_d", campaign_id: "cmp_d" }), decision: true, position: null, done: true }),
      queueItem({ id: "int_2", triage: triage({ entity_id: "aex_2", campaign_id: "cmp_2" }), decision: true, position: 2 }),
    ]));
    renderAt(confirmPath());
    const next = await screen.findByRole("link", { name: "下一件 →" });
    expect(next.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_2/propose/pause/aex_2");
  });

  it("only a notice row left: no 下一件, the forward exit is 「← 回投放中心」", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [deferredSet()] });
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([notice()]));
    renderAt(confirmPath());
    expect((await screen.findByRole("link", { name: "← 回投放中心" })).getAttribute("href")).toBe("/brands/brd_1/ads");
    expect(screen.queryByRole("link", { name: /下一件|去處理/ })).toBeNull();
  });

  it("a closeout row next: 「結案這一期 →」 opens the campaign's closeout", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [deferredSet()] });
    vi.mocked(triageApi.getQueue).mockResolvedValue({
      ...queue([notice()]),
      closeouts: [{
        id: "int_close", dedupe_key: "ads-triage:closeout:cmp_9", category: "ads_triage_closeout", severity: "rule_warning",
        message: "「秋季檔期」已結束，待結案", action_url: "/brands/brd_1/ads/campaigns/cmp_9?tab=perf&close=1", visible_from: null,
        status: "open", created_at: "2026-10-10T00:00:00Z", campaign_id: "cmp_9", decision: true, position: 1, done: false,
        closeout: { campaign_id: "cmp_9", campaign_name: "秋季檔期", end_date: "2026-10-09", running: { count: 0, read_at: null } },
      }],
    });
    renderAt(confirmPath());
    const close = await screen.findByRole("link", { name: "結案這一期 →" });
    expect(close.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_9?tab=perf&close=1");
  });
});
