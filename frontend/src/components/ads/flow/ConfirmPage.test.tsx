/** frontend/src/components/ads/flow/ConfirmPage.test.tsx — F22-I02：`vi.mock` 掉
 * `@/lib/adsChangeApi`／`@/lib/adsTriageApi`，不打真的 API。覆蓋 Done 4：三種 kind 都能畫、
 * 草稿延遲建立的 payload、核准導去到平台完成、暫緩要未來時間、拒絕、保存沒收到回應時沿用
 * 同一個 operation_id 重試、走錯步驟自動導正、多項變更清單連去既有變更與核對。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as changeApi from "@/lib/adsChangeApi";
import type { ChangeItem, ChangeSet } from "@/lib/adsChangeApi";
import * as triageApi from "@/lib/adsTriageApi";
import type { QueueItem, QueuePayload, TriageItem } from "@/lib/adsTriageApi";
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
    created_at: "2026-09-22T00:00:00Z", resolved_at: null, triage: triage(), proposal: null,
    ...overrides,
  };
}
function queue(items: QueueItem[] = []): QueuePayload {
  return { items, counts: { stop_loss: items.length, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 }, total_ads: items.length, kinds_available: ["stop_loss"], kinds_pending: [] };
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
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/changes/:setId/confirm" element={<SetConfirmRoute />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}
const proposePath = "/brands/brd_1/ads/campaigns/cmp_1/propose/pause/aex_1";
const confirmPath = (id = "acs_1") => `/brands/brd_1/ads/campaigns/cmp_1/changes/${id}/confirm`;

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(triageApi.getQueue).mockResolvedValue(queue());
  vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [] });
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
