/** frontend/src/components/ads/review/MaterialStepPage.test.tsx — F27-I14：`vi.mock` 掉
 * `@/lib/adsReviewApi`／`@/lib/adsTriageApi`／`@/lib/adsApi`／`@/lib/adsHandoffApi`，不打真的 API；
 * `../MaterialTasksPanel`／`../UserAssetPlacements` 換成 stub（同 `AssetsTab.test.tsx` 的既有作法，
 * 這頁只驗證自己的組裝與「建立新廣告提議」邏輯，不重覆那兩支自己的測試）。覆蓋 Done 1：依 `mode`
 * 顯示的標題／說明、走錯步驟轉去看證據頁、correction 5（只有這輪有 `new_test` 建議才把
 * `review`／`recommendation` 帶進 URL、新廣告交接才附 `review_id`／`recommendation_id`）、目的地
 * 投放組自動判斷（找不到就停用、不猜）、`replaces_entity_id` 固定是這則廣告、成功後導去
 * `changes/:id/confirm`。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as reviewApi from "@/lib/adsReviewApi";
import type { ReviewRound } from "@/lib/adsReviewApi";
import * as triageApi from "@/lib/adsTriageApi";
import type { QueueItem, QueuePayload, TriageItem } from "@/lib/adsTriageApi";
import * as adsApi from "@/lib/adsApi";
import type { CampaignDetail } from "@/lib/adsApi";
import * as handoffApi from "@/lib/adsHandoffApi";
import type { ChangeSet } from "@/lib/adsChangeApi";
import { MaterialStepPage } from "./MaterialStepPage";

vi.mock("@/lib/adsReviewApi", async (importOriginal) => ({
  ...(await importOriginal<typeof reviewApi>()),
  getReview: vi.fn(),
}));
vi.mock("@/lib/adsTriageApi", async (importOriginal) => ({
  ...(await importOriginal<typeof triageApi>()),
  getQueue: vi.fn(),
}));
vi.mock("@/lib/adsApi", async (importOriginal) => ({
  ...(await importOriginal<typeof adsApi>()),
  getCampaign: vi.fn(),
}));
vi.mock("@/lib/adsHandoffApi", async (importOriginal) => ({
  ...(await importOriginal<typeof handoffApi>()),
  getHandoff: vi.fn(),
  createNewAdHandoff: vi.fn(),
}));
vi.mock("../MaterialTasksPanel", () => ({
  MaterialTasksPanel: () => <p>素材任務入口</p>,
}));
vi.mock("../UserAssetPlacements", () => ({
  UserAssetPlacements: () => <div>自帶素材安排</div>,
}));

function review(overrides: Partial<ReviewRound> = {}): ReviewRound {
  return {
    id: "arv_1", entity_id: "aex_1", window_start: "2026-09-08", window_end: "2026-09-21", previous_id: null,
    status: "ready", evidence_hash: "hash_1", llm_task_id: null, error: null,
    decision: "completed", reason: null, revisit_at: null, created_at: "2026-09-19T14:40:00Z",
    result_json: { recommendations: [], limitations: [] },
    evidence_json: {
      target: { id: "aex_1", name: "晨光隨行杯・隨時有你", platform: "meta", source_account: "acc_1", native_id: "native_1" },
      window: { start: "2026-09-08", end: "2026-09-21", previous_start: "2026-08-25", previous_end: "2026-09-07", timezone: "Asia/Taipei" },
      current: { row_count: 0, days_present: 0, days_expected: 0, missing_days: 0, series: [] },
      previous: { row_count: 0, days_present: 0, days_expected: 0, missing_days: 0, series: [] },
      commerce: {
        current: { scope: "brand", start: "2026-09-08", end: "2026-09-21", order_summary: { count: 0, non_void_count: 0, order_net_amount: null, paid_net_amount: null, unknown_payment_count: 0, currency: null, currency_basis: "unknown", coverage: "unknown", latest_import_at: null }, channels: [], limitations: [], attribution: "unavailable" },
        previous: { scope: "brand", start: "2026-08-25", end: "2026-09-07", order_summary: { count: 0, non_void_count: 0, order_net_amount: null, paid_net_amount: null, unknown_payment_count: 0, currency: null, currency_basis: "unknown", coverage: "unknown", latest_import_at: null }, channels: [], limitations: [], attribution: "unavailable" },
      },
      conditions: { history: "unknown", creative_snapshot: {}, binding_count: 0 },
      previous_review: null, source_review: null, limitations: [], waiting_reasons: [], sources: [],
    },
    ...overrides,
  };
}
function newTestReview(overrides: Partial<ReviewRound> = {}): ReviewRound {
  return review({
    result_json: {
      recommendations: [{
        id: "rec_1", target_id: "aex_1", recommendation: "new_test",
        evidence_refs: [], hypothesis: "換一張圖再試", risks: [], next_step: "準備新素材",
      }],
      limitations: [],
    },
    ...overrides,
  });
}
function triage(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "aex_1", native_id: "native_1", name: "晨光隨行杯・隨時有你", campaign_id: "cmp_1",
    campaign_name: "【銷售】測試活動", thumbnail_url: null, class: "worse", label: "變差",
    reason_code: "cost_per_result_up",
    grade: "over", grade_label: "太貴", previous_grade: "on_target", grade_move: { from: "on_target", to: "over" },
    window: { start: "2026-09-08", end: "2026-09-21", days: 14, previous_start: "2026-08-25", previous_end: "2026-09-07", extended_from: null },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 3000, result_count: 5, cost_per_result: 600, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    previous: { spend: 2000, result_count: 8, cost_per_result: 250, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: 1.4,
    sample: { gate: true, spend_multiple: 6.6, days_with_events: 14 },
    ...overrides,
  };
}
function queueItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "int_1", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null,
    dedupe_key: "k1", category: "ads_triage_worse", kind: null, severity: "rule_warning",
    message: "m", action_url: null, visible_from: null, status: "open",
    created_at: "2026-09-22T00:00:00Z", resolved_at: null, kind_key: "worse",
    triage: triage(), proposal: null,
    ...overrides,
  };
}
function queue(items: QueueItem[] = [queueItem()]): QueuePayload {
  return { items, counts: { stop_loss: 0, worse: items.length, better: 0, flat: 0, insufficient: 0, no_target: 0 }, total_ads: items.length, kinds_available: ["worse"], kinds_pending: [] };
}
function campaign(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    id: "cmp_1", origin: "imported", capabilities: { allowed: [], unavailable: {} },
    external_view: {
      entities: [
        { id: "aex_1", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_1", native_label: "廣告", name: "晨光隨行杯・隨時有你", parent_native_id: "adset_native_1", native_status: "ACTIVE", start_date: null, end_date: null, budget_amount: null, budget_type: "unknown", budget_raw: {}, currency: "TWD", last_success_at: null, sync_error: null, creative: {} },
        { id: "aes_1", platform: "meta", source_account: "acc_1", native_kind: "adset", native_id: "adset_native_1", native_label: "廣告組", name: "既有投放組", parent_native_id: "campaign_native_1", native_status: "ACTIVE", start_date: null, end_date: null, budget_amount: 500, budget_type: "daily", budget_raw: {}, currency: "TWD", last_success_at: null, sync_error: null, creative: {} },
      ],
      observations: [], next_entity_cursor: null, next_observation_cursor: null,
      window: { start: "2026-09-08", end: "2026-09-21" }, connections: [], sync: {}, coverage: {},
    },
    name: "測試活動", goal_text: null, objective: "銷售", cap: { value: null, basis: null, own_value: null, break_even: null, price: null, product_id: null, result_kind: "purchase", result_label: "購買", missing: ["product"], revision: 0 },
    start_date: null, end_date: null, status: "live", budget_planned: null, budget_scenario: null, budget_basis_json: {}, budget_total: null,
    context_json: {}, constraints_json: {}, verdict: null, verdict_json: {}, closed_at: null, created_by: null, created_at: "2026-01-01",
    groups: [], actions: [], outcome: { spend: null, purchases: null, revenue: null }, asset_readiness: { total: 0, ready_count: 0 },
    external_id: null, external_name: null, external_status: null, local_state: "unbound", bound_at: null,
    ...overrides,
  };
}
function handoff(overrides: Partial<handoffApi.HandoffWorkspace> = {}): handoffApi.HandoffWorkspace {
  return {
    items: [], items_truncated: false, ready_placements: [], destinations: [], destinations_truncated: false,
    launch_stale: null, notice: "物件存在、設定相符與素材核對分別記錄；人工交接不代表平台已投遞。",
    ...overrides,
  };
}
function changeSet(overrides: Partial<ChangeSet> = {}): ChangeSet {
  return {
    id: "acs_new", campaign_id: "cmp_1", title: "新廣告", month: "2026-09",
    operation_id: "op_1", content_hash: "hash_1", status: "draft", reason: null, revisit_at: null,
    approval_id: null, created_at: "2026-09-22T00:00:00Z", approved_at: null, items: [],
    ...overrides,
  };
}

function MaterialRoute() {
  const { brandId, campaignId, reviewId } = useParams<{ brandId: string; campaignId: string; reviewId: string }>();
  return <MaterialStepPage brandId={brandId ?? ""} campaignId={campaignId ?? ""} reviewId={reviewId ?? ""} />;
}
function LocationProbe() {
  return <p data-testid="probe-path">{useLocation().pathname}</p>;
}
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/reviews/:reviewId/material" element={<MaterialRoute />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}
const materialPath = (mode: string, id = "arv_1") => `/brands/brd_1/ads/campaigns/cmp_1/reviews/${id}/material?mode=${mode}`;

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(triageApi.getQueue).mockResolvedValue(queue());
  vi.mocked(adsApi.getCampaign).mockResolvedValue(campaign());
  vi.mocked(handoffApi.getHandoff).mockResolvedValue(handoff());
});

describe("MaterialStepPage（F27-I14）組裝與走錯步驟", () => {
  it("走錯步驟（尚未判讀完）轉去看證據頁", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status: "waiting" }));
    renderAt(materialPath("workbench_image"));
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe(
      "/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1",
    ));
  });

  it("mode=workbench_image：標題與說明承接 materialModes「請工作台準備新圖」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(materialPath("workbench_image"));
    expect(await screen.findByRole("heading", { name: "請工作台準備新圖" })).toBeTruthy();
    expect(screen.getByText("承接這次需求，準備圖片提示詞，再帶到外部工具生圖。")).toBeTruthy();
    expect(screen.getByText("素材任務入口")).toBeTruthy();
    expect(screen.getByText("自帶素材安排")).toBeTruthy();
  });

  it("mode=existing：標題與說明承接 materialModes「使用已有成品」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(materialPath("existing"));
    expect(await screen.findByRole("heading", { name: "使用已有成品" })).toBeTruthy();
    expect(screen.getByText("上傳圖片或影片，直接安排使用。")).toBeTruthy();
  });
});

describe("MaterialStepPage（F27-I14）建立新廣告提議", () => {
  it("沒有已就緒成品：只顯示提示，不畫表單", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(materialPath("workbench_image"));
    expect(await screen.findByText("還沒有已確認、就緒的成品；請先在上方準備素材並確認安排。")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /建立新廣告提議/ })).toBeNull();
  });

  it("沒有 new_test 建議：只送 replaces_entity_id，不附 review_id／recommendation_id", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(handoffApi.getHandoff).mockResolvedValue(handoff({
      ready_placements: [{ id: "plc_1", revision: 2, filename: "新圖.png", purpose: "產品介紹", destination_entity_id: null }],
    }));
    vi.mocked(handoffApi.createNewAdHandoff).mockResolvedValue(changeSet());
    renderAt(materialPath("workbench_image"));
    await user.click(await screen.findByLabelText(/新圖\.png/));
    await user.click(screen.getByRole("button", { name: /建立新廣告提議/ }));
    await waitFor(() => expect(handoffApi.createNewAdHandoff).toHaveBeenCalled());
    const [brand, camp, body] = vi.mocked(handoffApi.createNewAdHandoff).mock.calls[0];
    expect(brand).toBe("brd_1");
    expect(camp).toBe("cmp_1");
    expect(body.placement_id).toBe("plc_1");
    expect(body.revision).toBe(2);
    expect(body.destination_entity_id).toBe("aes_1");
    expect(body.replaces_entity_id).toBe("aex_1");
    expect(body.review_id).toBeUndefined();
    expect(body.recommendation_id).toBeUndefined();
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe(
      "/brands/brd_1/ads/campaigns/cmp_1/changes/acs_new/confirm",
    ));
  });

  it("有 new_test 建議：附 review_id／recommendation_id，且把兩者帶進網址供素材任務承接", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(newTestReview());
    vi.mocked(handoffApi.getHandoff).mockResolvedValue(handoff({
      ready_placements: [{ id: "plc_2", revision: 1, filename: "候選圖.png", purpose: "", destination_entity_id: null }],
    }));
    vi.mocked(handoffApi.createNewAdHandoff).mockResolvedValue(changeSet());
    renderAt(materialPath("existing"));
    await user.click(await screen.findByLabelText(/候選圖\.png/));
    await user.click(screen.getByRole("button", { name: /建立新廣告提議/ }));
    await waitFor(() => expect(handoffApi.createNewAdHandoff).toHaveBeenCalled());
    const body = vi.mocked(handoffApi.createNewAdHandoff).mock.calls[0][2];
    expect(body.review_id).toBe("arv_1");
    expect(body.recommendation_id).toBe("rec_1");
  });

  it("找不到這則廣告所屬投放組：警示文字，按鈕停用", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(adsApi.getCampaign).mockResolvedValue(campaign({ external_view: { entities: [], observations: [], next_entity_cursor: null, next_observation_cursor: null, window: { start: "2026-09-08", end: "2026-09-21" }, connections: [], sync: {}, coverage: {} } }));
    vi.mocked(handoffApi.getHandoff).mockResolvedValue(handoff({
      ready_placements: [{ id: "plc_1", revision: 1, filename: "新圖.png", purpose: "", destination_entity_id: null }],
    }));
    renderAt(materialPath("workbench_image"));
    expect(await screen.findByText("找不到這則廣告目前所屬的投放組，請重新整理再試；仍可先確認素材安排。")).toBeTruthy();
    expect((screen.getByRole("button", { name: /建立新廣告提議/ }) as HTMLButtonElement).disabled).toBe(true);
  });
});

// F29-I10 Contract K: the queue is context on this step — a failed read is said out loud with 重試 and the step
// still works; the open step flow has one exit back to 投放中心.
describe("MaterialStepPage（F29-I10）佇列讀取失敗與出口", () => {
  it("佇列讀取失敗：只多一塊讀取失敗，這一步照舊；重試重讀佇列後補回「第幾件」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(triageApi.getQueue).mockReset();
    vi.mocked(triageApi.getQueue).mockRejectedValueOnce(new Error("queue down")).mockResolvedValueOnce(queue());
    renderAt(materialPath("workbench_image"));
    expect(await screen.findByText(/待決定清單讀不到/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "請工作台準備新圖" })).toBeTruthy();
    expect(screen.queryByText("第 1 件／共 1 件")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText("第 1 件／共 1 件")).toBeTruthy();
    expect(screen.queryByText(/待決定清單讀不到/)).toBeNull();
    expect(triageApi.getQueue).toHaveBeenCalledTimes(2);
  });

  it("開著的決定有「✕ 先不要，回投放中心」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(materialPath("workbench_image"));
    const exit = await screen.findByRole("link", { name: "✕ 先不要，回投放中心" });
    expect(exit.getAttribute("href")).toBe("/brands/brd_1/ads");
  });
});

describe("MaterialStepPage（F29-I10）已就緒成品讀取失敗", () => {
  it("讀不到交接工作區：不說「還沒有就緒的成品」，顯示讀取失敗；重試後出現成品", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(handoffApi.getHandoff).mockReset();
    vi.mocked(handoffApi.getHandoff).mockRejectedValueOnce(new Error("handoff down")).mockResolvedValueOnce(handoff({
      ready_placements: [{ id: "plc_1", revision: 2, filename: "新圖.png", purpose: "產品介紹", destination_entity_id: null }],
    }));
    renderAt(materialPath("workbench_image"));
    expect(await screen.findByText(/已就緒的成品讀不到/)).toBeTruthy();
    expect(screen.queryByText("還沒有已確認、就緒的成品；請先在上方準備素材並確認安排。")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByLabelText(/新圖\.png/)).toBeTruthy();
    expect(handoffApi.getHandoff).toHaveBeenCalledTimes(2);
  });
});
