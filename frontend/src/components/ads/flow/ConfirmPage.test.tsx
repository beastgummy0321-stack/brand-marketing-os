/** frontend/src/components/ads/flow/ConfirmPage.test.tsx — F22-I02／F25-I03：`vi.mock` 掉
 * `@/lib/adsChangeApi`／`@/lib/adsTriageApi`，不打真的 API。覆蓋 Done 4：三種 kind 都能畫、
 * 草稿延遲建立的 payload、核准導去到平台完成、暫緩要未來時間、拒絕、保存沒收到回應時沿用
 * 同一個 operation_id 重試、走錯步驟自動導正、多項變更清單連去既有變更與核對；F25-I03 加了
 * 加預算 propose 路由的完整證據卡、budget 草稿 payload、月預算放不下的 409 不重建。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as changeApi from "@/lib/adsChangeApi";
import { ChangeRequestRejected, type ChangeItem, type ChangeSet } from "@/lib/adsChangeApi";
import * as triageApi from "@/lib/adsTriageApi";
import type { QueueItem, QueuePayload, QueueScale, TriageItem } from "@/lib/adsTriageApi";
import * as anglesApi from "@/lib/adsAnglesApi";
import { ConfirmPage } from "./ConfirmPage";

vi.mock("@/lib/adsChangeApi", async (importOriginal) => ({
  ...(await importOriginal<typeof changeApi>()),
  getChangeControl: vi.fn(), createChangeSet: vi.fn(), approveChangeSet: vi.fn(),
  decideChangeSet: vi.fn(), getMonthlyBudget: vi.fn(),
}));
vi.mock("@/lib/adsTriageApi", async (importOriginal) => ({
  ...(await importOriginal<typeof triageApi>()),
  getQueue: vi.fn(),
}));
// F27-I16 Contract C: 每一頁暫停提議都會打一次 `getAngles`（correction 9）——不 mock 會打到真的
// `fetch`，預設先給一個 `ready` 三候選，個別測試需要別的狀態再自己覆寫。
vi.mock("@/lib/adsAnglesApi", async (importOriginal) => ({
  ...(await importOriginal<typeof anglesApi>()),
  getAngles: vi.fn(),
}));

function triage(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "aex_1", native_id: "native_1", name: "1150706 健身情境單圖", campaign_id: "cmp_1",
    campaign_name: "【銷售】測試活動", thumbnail_url: null, class: "stop_loss", label: "停損",
    reason_code: "spend_over_stop_loss",
    window: { start: "2026-08-25", end: "2026-09-21", days: 9, previous_start: "2026-07-28", previous_end: "2026-08-24", extended_from: null },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 1420, result_count: 0, cost_per_result: null, result_kind: null, result_label: "成果", derived_zero_days: 0, reason: null },
    previous: { spend: null, result_count: null, cost_per_result: null, result_kind: null, result_label: "成果", derived_zero_days: 0, reason: null },
    change_pct: null,
    sample: { gate: false, spend_multiple: null, days_with_events: 0 },
    ...overrides,
  };
}
function queueItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "int_1", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null,
    dedupe_key: "k1", category: "ads_triage_stop_loss", kind: null, severity: "money_loss",
    message: "m", action_url: null, visible_from: null, status: "open",
    created_at: "2026-09-22T00:00:00Z", resolved_at: null, kind_key: "stop_loss",
    triage: triage(), proposal: null,
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
        { entity_id: "aex_low1", name: "1150701 情境圖 A", thumbnail_url: null, spend_7d: 120 },
        { entity_id: "aex_low2", name: "1150702 情境圖 B", thumbnail_url: "https://cdn.example/b.jpg", spend_7d: 340 },
      ],
    },
    ...overrides,
  });
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
  vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [] });
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

  it("改文案清單沒有承接的檢討：返回鍵維持「投放中心」（F23-I04）", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        id: "acs_copy", items: [changeItem({ kind: "copy", before: { title: "舊標題", body: "舊內文" }, after: { title: "新標題", body: "新內文" } })],
      })],
    });
    renderAt(confirmPath("acs_copy"));
    await screen.findByText("確認變更");
    const back = screen.getByRole("link", { name: "← 投放中心" }) as HTMLAnchorElement;
    expect(back.getAttribute("href")).toBe("/brands/brd_1/ads");
  });

  it("已拒絕的改文案清單：即使承接自檢討，返回鍵仍是「投放中心」（F23-I04）", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        id: "acs_copy", review_id: "arv_1", recommendation_id: "rec_1", status: "rejected", reason: "資料還不夠",
        items: [changeItem({ kind: "copy", before: { title: "舊標題", body: "舊內文" }, after: { title: "新標題", body: "新內文" } })],
      })],
    });
    renderAt(confirmPath("acs_copy"));
    await screen.findByText("確認變更");
    const back = screen.getByRole("link", { name: "← 投放中心" }) as HTMLAnchorElement;
    expect(back.getAttribute("href")).toBe("/brands/brd_1/ads");
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
    expect(body.items).toEqual([{ kind: "pause", target_id: "aex_1", after: { status: "PAUSED" }, reason: "花費超過停損線（目標 × 3）仍未達成目標" }]);

    await waitFor(() => expect(changeApi.approveChangeSet).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/handoff"));
  });

  it("既有提議時重用 change_set_id，不重新建立草稿", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({
      proposal: { change_set_id: "acs_existing", campaign_id: "cmp_1", kind: "pause", status: "draft", verification_state: "pending", reason: null, revisit_at: null, multi: false },
    })]));
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
    const custom = screen.getByRole("button", { name: "＋ 自訂" });
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
      reason: "花費超過停損線（目標 × 3）仍未達成目標", angle: "辦公室情境",
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

    await user.clear(dateInput);
    await user.type(dateInput, "2099-01-01");
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(changeSet());
    vi.mocked(changeApi.decideChangeSet).mockResolvedValue(changeSet({ status: "deferred", reason: "想再觀察幾天", revisit_at: "2099-01-01T00:00:00Z" }));
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(changeApi.decideChangeSet).toHaveBeenCalled());
    const call = vi.mocked(changeApi.decideChangeSet).mock.calls[0][3];
    expect(call.decision).toBe("deferred");
    expect(call.revisit_at?.startsWith("2099-01-01")).toBe(true);
  });

  it("拒絕不需要重看時間，保存後不帶 revisit_at", async () => {
    const user = userEvent.setup();
    await openSheet(user);
    await user.click(screen.getByRole("button", { name: "拒絕" }));
    expect(screen.queryByLabelText("重看日期")).toBeNull();
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(changeSet());
    vi.mocked(changeApi.decideChangeSet).mockResolvedValue(changeSet({ status: "rejected", reason: "想再觀察幾天" }));
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(changeApi.decideChangeSet).toHaveBeenCalled());
    const call = vi.mocked(changeApi.decideChangeSet).mock.calls[0][3];
    expect(call).toEqual({ decision: "rejected", reason: "想再觀察幾天" });
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
  it("已核准且還沒回報，導去到平台完成", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ status: "approved", approved_at: "2026-09-21T00:00:00Z", items: [changeItem({ verification_state: "pending", reported_at: null })] })],
    });
    renderAt(confirmPath());
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/handoff"));
  });

  it("已核准且已讀回，導去核對結果", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ status: "approved", approved_at: "2026-09-21T00:00:00Z", items: [changeItem({ verification_state: "confirmed", reported_at: "2026-09-21T01:00:00Z" })] })],
    });
    renderAt(confirmPath());
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/verify"));
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
  it("畫出完整證據卡：同組則數、每日預算＋漲幅、購買成本量尺、主力穩定、本月預算放得下", async () => {
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
    expect(screen.getByText(/目標 450/)).toBeTruthy();
    expect(screen.getByText("主力穩定 2 個觀察期")).toBeTruthy();
    expect(screen.getByText("加碼後等 3–5 天再看")).toBeTruthy();
    expect(await screen.findByText("本月預算放得下")).toBeTruthy();
    expect(screen.getByText(/這次加碼/)).toBeTruthy();
    expect(screen.getByText(/TWD 1,800/)).toBeTruthy();
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
    expect(body.items).toEqual([{ kind: "budget", target_id: "aex_owner_G", after: { daily_amount: 1200 }, reason: "近兩期成本都在目標內，加碼 20% 擴量" }]);
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

  it("前提變了的 409（非月預算訊息）：仍照既有規則重建一次再核准", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([scaleQueueItem()]));
    vi.mocked(changeApi.getMonthlyBudget).mockResolvedValue({
      month: "2026-09", currency: "TWD", amount: 60000, revision: 2, known_spend: 22000, ongoing_estimate: 28000,
      reserved_increases: 0, available: 10000, uncertainties: [], can_increase: true, period_end: "2026-09-30", confirmed_at: null, notice: "",
    });
    const draft = changeSet({
      items: [changeItem({ kind: "budget", target_id: "aex_owner_G", before: { daily_amount: 1000 }, after: { daily_amount: 1200 } })],
    });
    vi.mocked(changeApi.createChangeSet).mockResolvedValueOnce(draft).mockResolvedValueOnce({ ...draft, id: "acs_rebuilt" });
    vi.mocked(changeApi.approveChangeSet)
      .mockRejectedValueOnce(new ChangeRequestRejected("這項變更所依據的設定已改變，請依現況重新建立清單。"))
      .mockResolvedValueOnce({ ...draft, id: "acs_rebuilt", status: "approved" });
    renderAt(proposeBudgetPath);
    await user.click(await screen.findByRole("button", { name: /核准加碼，接著到平台操作/ }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalledTimes(2));
    expect(vi.mocked(changeApi.createChangeSet).mock.calls[1][2].supersedes_id).toBe("acs_1");
    await waitFor(() => expect(changeApi.approveChangeSet).toHaveBeenCalledTimes(2));
  });
});

describe("ConfirmPage：重建後仍失敗", () => {
  it("重建的草稿核准又被擋：導到正典網址後錯誤訊息仍在、按鈕不卡在處理中", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([scaleQueueItem()]));
    vi.mocked(changeApi.getMonthlyBudget).mockResolvedValue({
      month: "2026-09", currency: "TWD", amount: 60000, revision: 2, known_spend: 22000, ongoing_estimate: 28000,
      reserved_increases: 0, available: 10000, uncertainties: [], can_increase: true, period_end: "2026-09-30", confirmed_at: null, notice: "",
    });
    const draft = changeSet({
      items: [changeItem({ kind: "budget", target_id: "aex_owner_G", before: { daily_amount: 1000 }, after: { daily_amount: 1200 } })],
    });
    const rebuilt = { ...draft, id: "acs_rebuilt" };
    vi.mocked(changeApi.createChangeSet).mockResolvedValueOnce(draft).mockResolvedValueOnce(rebuilt);
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ change_sets: [rebuilt] } as never);
    // Real latency: the second approve answers after the rebuilt set has already re-rendered the page.
    vi.mocked(changeApi.approveChangeSet).mockImplementation(() => new Promise((_, reject) =>
      setTimeout(() => reject(new ChangeRequestRejected("這個物件已有相同操作待核對，請先處理原清單。")), 50)));
    renderAt(proposeBudgetPath);
    await user.click(await screen.findByRole("button", { name: /核准加碼，接著到平台操作/ }));
    expect(await screen.findByText("這個物件已有相同操作待核對，請先處理原清單。")).toBeTruthy();
    expect(screen.queryByText(/處理中/)).toBeNull();
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

describe("ConfirmPage（F27-I15 Contract F）cleanup propose 路由", () => {
  it("畫出清理卡片：每則廣告的縮圖、名稱與 7 天花費", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    renderAt(proposeCleanupPath);
    expect(await screen.findByText("提議：清理這個活動的廣告")).toBeTruthy();
    expect(screen.getByText("清理")).toBeTruthy();
    expect(screen.getByText("同時在投 5 則・預算約撐得起 3 則")).toBeTruthy();
    expect(screen.getByText("1150701 情境圖 A")).toBeTruthy();
    expect(screen.getByText("1150702 情境圖 B")).toBeTruthy();
    expect(screen.getByText(/7 天花 120/)).toBeTruthy();
    expect(screen.getByText(/7 天花 340/)).toBeTruthy();
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
    renderAt(proposeCleanupPath);
    await user.click(await screen.findByRole("button", { name: /核准清理，接著到平台操作/ }));

    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    const body = vi.mocked(changeApi.createChangeSet).mock.calls[0][2] as unknown as {
      operation_id: string; title: string; items: { kind: string; target_id: string }[]; source?: string;
    };
    expect(body.operation_id).toMatch(/^triage-cleanup:cmp_1:/);
    expect(body.title).toBe("清理「【銷售】測試活動」");
    expect(body.items).toEqual([
      { kind: "pause", target_id: "aex_low1", after: { status: "PAUSED" }, reason: "同時投放的廣告超過預算能撐的則數，先暫停這段時間花費最低的幾則" },
      { kind: "pause", target_id: "aex_low2", after: { status: "PAUSED" }, reason: "同時投放的廣告超過預算能撐的則數，先暫停這段時間花費最低的幾則" },
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
    expect(await screen.findByText("提議：清理這個活動的廣告")).toBeTruthy();
    expect(screen.getByText("1150701 情境圖 A")).toBeTruthy();
    expect(screen.getByText("1150702 情境圖 B")).toBeTruthy();
  });
});
