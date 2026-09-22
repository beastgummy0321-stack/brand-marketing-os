/** frontend/src/components/ads/review/PreparePage.test.tsx — F23-I03：`vi.mock` 掉
 * `@/lib/adsReviewApi`／`@/lib/adsTriageApi`，不打真的 API。覆蓋 Done 3：建議卡與預選方向、換方向
 * 重填原因、三種存檔動作（copy/observe/retire）各自的 `decideReview` 呼叫與下一步、已經 completed
 * 的一輪換方向時略過 decide 呼叫、保留卡不可選、錯的步驟轉去看證據頁。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as reviewApi from "@/lib/adsReviewApi";
import type { CommerceEvidence, ReviewPeriod, ReviewRound } from "@/lib/adsReviewApi";
import * as triageApi from "@/lib/adsTriageApi";
import type { QueueItem, QueuePayload, TriageItem } from "@/lib/adsTriageApi";
import { PreparePage } from "./PreparePage";

vi.mock("@/lib/adsReviewApi", async (importOriginal) => ({
  ...(await importOriginal<typeof reviewApi>()),
  getReview: vi.fn(), decideReview: vi.fn(),
}));
vi.mock("@/lib/adsTriageApi", async (importOriginal) => ({
  ...(await importOriginal<typeof triageApi>()),
  getQueue: vi.fn(),
}));

function period(overrides: Partial<ReviewPeriod> = {}): ReviewPeriod {
  return {
    row_count: 14, days_present: 14, days_expected: 14, missing_days: 0,
    series: [{
      metric_scope: "ad", attribution_key: "7d_click:omni_purchase", currency: "TWD", source: "graph",
      row_count: 14, days_present: 14,
      metrics: { spend: 3000, impressions: 100, clicks: 10, purchases: 5, revenue: 4000, ctr: 1, cpc: 1, cpa: 600, roas: 1.3 },
      known_counts: {},
    }],
    result_views: [{
      metric_scope: "ad", currency: "TWD", result_kind: "purchase", result_action: "omni_purchase",
      result_attribution: "7d_click", result_count: 5, cost_per_result: 600, days_present: 14, days_known: 14, reason: null,
    }],
    ...overrides,
  };
}
function commerce(overrides: Partial<CommerceEvidence> = {}): CommerceEvidence {
  return {
    scope: "brand", start: "2026-09-08", end: "2026-09-21",
    order_summary: {
      count: 29, non_void_count: 29, order_net_amount: 24921, paid_net_amount: 18432,
      unknown_payment_count: 9, currency: "TWD", currency_basis: "unknown", coverage: "unknown",
      latest_import_at: null, unknown_amount_count: 0,
    },
    channels: [], limitations: [], attribution: "unavailable",
    ...overrides,
  };
}
function review(overrides: Partial<ReviewRound> = {}): ReviewRound {
  return {
    id: "arv_1", entity_id: "aex_1", window_start: "2026-09-08", window_end: "2026-09-21", previous_id: null,
    status: "ready", evidence_hash: "hash_1", llm_task_id: null, error: null,
    decision: null, reason: null, revisit_at: null, created_at: "2026-09-22T00:00:00Z",
    result_json: {
      recommendations: [{
        id: "rec_1", target_id: "aex_1", recommendation: "adjust",
        evidence_refs: ["current"], hypothesis: "保留圖片，換文案試試。", risks: ["樣本量有限。"], next_step: "先核對素材。",
        suggested_copy: { title: "新標題", body: "新內文" },
      }],
      limitations: [],
    },
    evidence_json: {
      target: { id: "aex_1", name: "撞車1150724", platform: "meta", source_account: "acc_1", native_id: "native_1" },
      window: { start: "2026-09-08", end: "2026-09-21", previous_start: "2026-08-25", previous_end: "2026-09-07", timezone: "Asia/Taipei" },
      current: period(), previous: period(),
      commerce: { current: commerce(), previous: commerce() },
      conditions: { history: "unknown", creative_snapshot: { copy_fields: { title: "舊標題", body: "舊內文" } }, binding_count: 0 },
      previous_review: null, source_review: null,
      limitations: [], waiting_reasons: [], sources: [],
    },
    ...overrides,
  };
}
function triage(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "aex_1", native_id: "native_1", name: "撞車1150724", campaign_id: "cmp_1",
    campaign_name: "【銷售】測試活動", thumbnail_url: null, class: "worse", label: "變差",
    reason_code: "cost_per_result_up",
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

function PrepareRoute() {
  const { brandId, campaignId, reviewId } = useParams<{ brandId: string; campaignId: string; reviewId: string }>();
  return <PreparePage brandId={brandId ?? ""} campaignId={campaignId ?? ""} reviewId={reviewId ?? ""} />;
}
function LocationProbe() {
  return <p data-testid="probe-path">{useLocation().pathname}</p>;
}
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/reviews/:reviewId/prepare" element={<PrepareRoute />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}
const preparePath = (id = "arv_1") => `/brands/brd_1/ads/campaigns/cmp_1/reviews/${id}/prepare`;

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(triageApi.getQueue).mockResolvedValue(queue());
});

describe("PreparePage（F23-I03）建議與預選", () => {
  it("adjust 建議 → 只改文案卡標建議且預選，原因是它的預設值", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(preparePath());
    await screen.findByDisplayValue("採用建議：保留圖片，測試新文案");
    const copyCard = screen.getByRole("button", { name: /只改文案/ });
    expect(copyCard.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("建議")).toBeTruthy();
    expect(screen.getByRole("button", { name: /開始改文案/ })).toBeTruthy();
  });

  it("observe 建議 → 先觀察卡預選，並顯示何時重看", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({
      result_json: { recommendations: [{ id: "rec_1", target_id: "aex_1", recommendation: "observe", evidence_refs: [], hypothesis: "h", risks: [], next_step: "n" }], limitations: [] },
    }));
    renderAt(preparePath());
    await screen.findByDisplayValue("資料量還不夠，先觀察");
    const observeCard = screen.getAllByRole("button", { name: /先觀察/ })
      .find((el) => el.getAttribute("data-slot") === "option-card")!;
    expect(observeCard.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("group", { name: "何時重看" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /保存，先觀察/ })).toBeTruthy();
  });

  it("沒有建議（retain）→ 預選只改文案，不標建議", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({
      result_json: { recommendations: [{ id: "rec_1", target_id: "aex_1", recommendation: "retain", evidence_refs: [], hypothesis: "h", risks: [], next_step: "n" }], limitations: [] },
    }));
    renderAt(preparePath());
    await screen.findByDisplayValue("採用建議：保留圖片，測試新文案");
    const copyCard = screen.getByRole("button", { name: /只改文案/ });
    expect(copyCard.getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByText("建議")).toBeNull();
  });

  it("保留卡（換一張圖／用現成素材）不可選，標接上後開放", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(preparePath());
    await screen.findByRole("button", { name: /只改文案/ });
    const imageCard = screen.getByRole("button", { name: /換一張圖/ }) as HTMLButtonElement;
    expect(imageCard.disabled).toBe(true);
    expect(screen.getAllByText("接上後開放").length).toBeGreaterThan(0);
  });

  it("換方向重填原因為新方向的預設值", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(preparePath());
    await screen.findByDisplayValue("採用建議：保留圖片，測試新文案");
    await user.click(screen.getByRole("button", { name: /停掉這則/ }));
    expect(screen.getByDisplayValue("多次調整仍未改善")).toBeTruthy();
    expect(screen.getByRole("button", { name: /建立暫停提議/ })).toBeTruthy();
  });
});

describe("PreparePage（F23-I03）存檔", () => {
  it("copy：decide completed 後導去改文案", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(reviewApi.decideReview).mockResolvedValue(review({ status: "completed", decision: "completed" }));
    renderAt(preparePath());
    await screen.findByDisplayValue("採用建議：保留圖片，測試新文案");
    await user.click(screen.getByRole("button", { name: /開始改文案/ }));
    await waitFor(() => expect(reviewApi.decideReview).toHaveBeenCalledWith("brd_1", "cmp_1", "arv_1", {
      decision: "completed", reason: "採用建議：保留圖片，測試新文案",
    }));
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1/copy"));
  });

  it("已經 completed 的一輪：換方向存檔時略過 decide 呼叫，直接導頁", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status: "completed", decision: "completed" }));
    renderAt(preparePath());
    await screen.findByDisplayValue("採用建議：保留圖片，測試新文案");
    await user.click(screen.getByRole("button", { name: /停掉這則/ }));
    await user.click(screen.getByRole("button", { name: /建立暫停提議/ }));
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/pause/aex_1"));
    expect(reviewApi.decideReview).not.toHaveBeenCalled();
  });

  it("observe：需要未來的重看時間，deferred 帶 revisit_at 後回看證據頁", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(preparePath());
    await user.click(await screen.findByRole("button", { name: /先觀察/ }));
    await user.click(screen.getByRole("button", { name: "自訂" }));
    const dateInput = screen.getByLabelText("重看日期");
    await user.clear(dateInput);
    await user.type(dateInput, "2020-01-01");
    await user.click(screen.getByRole("button", { name: /保存，先觀察/ }));
    expect(await screen.findByText("請選一個之後的時間。")).toBeTruthy();
    expect(reviewApi.decideReview).not.toHaveBeenCalled();

    await user.clear(dateInput);
    await user.type(dateInput, "2099-01-01");
    vi.mocked(reviewApi.decideReview).mockResolvedValue(review({ status: "deferred", decision: "deferred" }));
    await user.click(screen.getByRole("button", { name: /保存，先觀察/ }));
    await waitFor(() => expect(reviewApi.decideReview).toHaveBeenCalled());
    const call = vi.mocked(reviewApi.decideReview).mock.calls[0][3];
    expect(call.decision).toBe("deferred");
    expect(call.revisit_at?.startsWith("2099-01-01")).toBe(true);
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1"));
  });

  it("retire：decide completed 後導去 F22 停損提議頁", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(reviewApi.decideReview).mockResolvedValue(review({ status: "completed", decision: "completed" }));
    renderAt(preparePath());
    await user.click(await screen.findByRole("button", { name: /停掉這則/ }));
    await user.click(screen.getByRole("button", { name: /建立暫停提議/ }));
    await waitFor(() => expect(reviewApi.decideReview).toHaveBeenCalledWith("brd_1", "cmp_1", "arv_1", {
      decision: "completed", reason: "多次調整仍未改善",
    }));
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/pause/aex_1"));
  });

  it("原因清空不給存", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(preparePath());
    const reasonInput = await screen.findByDisplayValue("採用建議：保留圖片，測試新文案");
    await user.clear(reasonInput);
    await user.click(screen.getByRole("button", { name: /開始改文案/ }));
    expect(await screen.findByText("請填寫原因。")).toBeTruthy();
    expect(reviewApi.decideReview).not.toHaveBeenCalled();
  });
});

describe("PreparePage（F23-I03）錯的步驟", () => {
  it.each(["running", "waiting", "failed", "deferred", "unjudgeable"] as const)("狀態 %s 轉去看證據頁", async (status) => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status }));
    renderAt(preparePath());
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1"));
    expect(screen.queryByRole("button", { name: /只改文案/ })).toBeNull();
  });
});
