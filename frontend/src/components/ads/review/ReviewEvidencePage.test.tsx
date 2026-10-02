/** frontend/src/components/ads/review/ReviewEvidencePage.test.tsx — F23-I02：`vi.mock` 掉
 * `@/lib/adsReviewApi`／`@/lib/adsTriageApi`，不打真的 API。覆蓋 Done 4：running/waiting/failed/
 * ready/deferred/unjudgeable/completed 各自的卡片與 bar，completed 導去正確的下一步；暫緩要未來
 * 時間、無法判定不用；entry route 沿用既有 proposal 或即時建立一輪並轉導。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as reviewApi from "@/lib/adsReviewApi";
import type { CommerceEvidence, ReviewPeriod, ReviewRound } from "@/lib/adsReviewApi";
import * as triageApi from "@/lib/adsTriageApi";
import type { QueueItem, QueuePayload, TriageItem } from "@/lib/adsTriageApi";
import { ReviewEvidencePage } from "./ReviewEvidencePage";

vi.mock("@/lib/adsReviewApi", async (importOriginal) => ({
  ...(await importOriginal<typeof reviewApi>()),
  getReview: vi.fn(), createReview: vi.fn(), decideReview: vi.fn(), retryReview: vi.fn(),
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
        id: "rec_1", target_id: "aex_1", recommendation: "observe",
        evidence_refs: ["current"], hypothesis: "花費持平但購買下降。", risks: ["樣本量有限。"], next_step: "先觀察一段時間。",
      }],
      limitations: [],
    },
    evidence_json: {
      target: { id: "aex_1", name: "撞車1150724", platform: "meta", source_account: "acc_1", native_id: "native_1" },
      window: { start: "2026-09-08", end: "2026-09-21", previous_start: "2026-08-25", previous_end: "2026-09-07", timezone: "Asia/Taipei", missing_days: [] },
      current: period(), previous: period({ series: [{ metric_scope: "ad", attribution_key: "7d_click:omni_purchase", currency: "TWD", source: "graph", row_count: 14, days_present: 14, metrics: { spend: 2000, impressions: 80, clicks: 8, purchases: 8, revenue: 5000, ctr: 1, cpc: 1, cpa: 250, roas: 2.5 }, known_counts: {} }], result_views: [{ metric_scope: "ad", currency: "TWD", result_kind: "purchase", result_action: "omni_purchase", result_attribution: "7d_click", result_count: 8, cost_per_result: 250, days_present: 14, days_known: 14, reason: null }] }),
      commerce: { current: commerce(), previous: commerce({ order_summary: { ...commerce().order_summary, count: 65, order_net_amount: 61700, paid_net_amount: 60645 } }) },
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
    grade: "over", grade_label: "太貴", previous_grade: "on_target", grade_move: { from: "on_target", to: "over" },
    window: { start: "2026-09-08", end: "2026-09-21", days: 14, previous_start: "2026-08-25", previous_end: "2026-09-07", extended_from: null },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 3000, result_count: 5, cost_per_result: 600, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    previous: { spend: 2000, result_count: 8, cost_per_result: 250, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: 1.4,
    sample: { gate: true, spend_multiple: 6.6, days_with_events: 14 },
    // F27-I11 Contract A: live ladder + history default (step 1 = 改過一次文案) — the sales-variant
    // tests below never assert on these, only the new non-sales test overrides them.
    ladder: { step: 1, copy_changes: 1, image_changes: 0, lineage_from: null },
    history: [{
      change_set_id: "acs_hist_1", kind: "copy",
      approved_at: "2026-09-06T12:00:00Z", verified_at: "2026-09-13T12:00:00Z",
      cost_before: 500, cost_after: 450,
    }],
    ...overrides,
  };
}
function queueItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "int_1", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null,
    dedupe_key: "k1", category: "ads_triage_worse", kind: null, severity: "rule_warning",
    message: "m", action_url: null, visible_from: null, status: "open",
    created_at: "2026-09-22T00:00:00Z", resolved_at: null, kind_key: "worse",
    triage: triage(), proposal: null, done: false,
    ...overrides,
  };
}
function queue(items: QueueItem[] = [queueItem()]): QueuePayload {
  return { items, counts: { stop_loss: 0, worse: items.length, better: 0, flat: 0, insufficient: 0, no_target: 0 }, total_ads: items.length, kinds_available: ["worse"], kinds_pending: [] };
}

function EntryRoute() {
  const { brandId, campaignId, entityId } = useParams<{ brandId: string; campaignId: string; entityId: string }>();
  return <ReviewEvidencePage brandId={brandId ?? ""} campaignId={campaignId ?? ""} entityId={entityId ?? ""} />;
}
function RoundRoute() {
  const { brandId, campaignId, reviewId } = useParams<{ brandId: string; campaignId: string; reviewId: string }>();
  return <ReviewEvidencePage brandId={brandId ?? ""} campaignId={campaignId ?? ""} reviewId={reviewId ?? ""} />;
}
function LocationProbe() {
  return <p data-testid="probe-path">{useLocation().pathname}</p>;
}
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/review/:entityId" element={<EntryRoute />} />
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/reviews/:reviewId" element={<RoundRoute />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}
const entryPath = "/brands/brd_1/ads/campaigns/cmp_1/review/aex_1";
const roundPath = (id = "arv_1") => `/brands/brd_1/ads/campaigns/cmp_1/reviews/${id}`;

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(triageApi.getQueue).mockResolvedValue(queue());
});

describe("ReviewEvidencePage（F23-I02）各狀態的卡片與 bar", () => {
  it("running：只有整理證據卡片，bar 只有返回", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status: "running" }));
    renderAt(roundPath());
    expect(await screen.findByText("AI 正在整理證據")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "暫緩" })).toBeNull();
    expect(screen.queryByRole("link", { name: /選擇處理方向/ })).toBeNull();
  });

  it("waiting：列出 waiting_reasons，只有先不決定沒有選擇處理方向", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status: "waiting", evidence_json: { ...review().evidence_json, waiting_reasons: ["缺 9/17 的資料"] } }));
    renderAt(roundPath());
    expect(await screen.findByText("資料還不夠，這回先不判")).toBeTruthy();
    expect(screen.getByText("缺 9/17 的資料")).toBeTruthy();
    expect(screen.getByRole("button", { name: "暫緩" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /選擇處理方向/ })).toBeNull();
  });

  it("failed：顯示 error 訊息，沒有重試按鈕", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status: "failed", error: "模型逾時" }));
    renderAt(roundPath());
    expect(await screen.findByText("本次未完成")).toBeTruthy();
    expect(screen.getByText("模型逾時")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "重試" })).toBeNull();
    expect(screen.getByRole("button", { name: "暫緩" })).toBeTruthy();
  });

  it("ready：AI 建議、這則廣告（花費用 series 加總、不是 ROAS）、商城訂單、完整 bar、活的處理階梯", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(roundPath());
    expect(await screen.findByText("先觀察一段時間")).toBeTruthy();
    expect(screen.getByText("花費持平但購買下降。")).toBeTruthy();
    expect(screen.getByText("這則廣告")).toBeTruthy();
    expect(screen.getByText("3,000")).toBeTruthy(); // 花費（series 加總，不是 series[0] 的任意選取）
    expect(screen.queryByText(/ROAS/)).toBeNull(); // 沒有可信的單則 ROAS 存取器，三行不是四行
    expect(screen.getByText("商城訂單")).toBeTruthy();
    expect(screen.queryByText("這條素材的紀錄")).toBeNull(); // 銷售活動不顯示非銷售的紀錄卡
    expect(screen.getByRole("button", { name: "暫緩" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "無法判定" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /選擇處理方向/ })).toBeTruthy();
    // F27-I11 Contract A：`ladder.step` 帶進活的處理階梯，不再是 F23 那個一律灰階的 placeholder。
    expect(screen.getByLabelText("處理階梯")).toBeTruthy();
    expect(screen.queryByLabelText("處理階梯（接上後開放）")).toBeNull();
  });

  it("F47-I06：麵包屑用這一列自己的種類；沒有對應的列就寫「檢討」，不是固定的「變貴」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    const first = renderAt(roundPath());
    expect(await screen.findByText(/^變貴・/)).toBeTruthy();
    first.unmount();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({ kind_key: "stop_loss" })]));
    const second = renderAt(roundPath());
    expect(await screen.findByText(/^停損・/)).toBeTruthy();
    second.unmount();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([]));
    renderAt(roundPath());
    expect(await screen.findByText(/^檢討・/)).toBeTruthy();
    expect(screen.queryByText(/^變貴・/)).toBeNull();
  });

  it("ready：非銷售活動（target.result_kind 不是 purchase）顯示「這條素材的紀錄」，不顯示商城訂單", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({
      triage: triage({
        campaign_name: "【名單】測試活動",
        target: { value: 300, basis: "own", result_kind: "lead", result_label: "名單", missing: [] },
        ladder: { step: 1, copy_changes: 1, image_changes: 0, lineage_from: null },
        history: [{
          change_set_id: "acs_hist_2", kind: "copy",
          approved_at: "2026-09-06T12:00:00Z", verified_at: "2026-09-13T12:00:00Z",
          cost_before: 2.0, cost_after: 3.1,
        }],
      }),
    })]));
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(roundPath());
    expect(await screen.findByText("這條素材的紀錄")).toBeTruthy();
    expect(screen.queryByText("商城訂單")).toBeNull();
    expect(screen.getByText("已處理 1 次")).toBeTruthy();
    expect(screen.getByText("9/6 改過文案")).toBeTruthy();
    expect(screen.getByText("之後 7 天・每次名單成本 2 → 3.1")).toBeTruthy();
    expect(screen.getByText("這個活動看名單，不看商城訂單")).toBeTruthy();
  });

  it("deferred：closed chip、bar 只有先不決定按鈕與提示，沒有選擇處理方向", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status: "deferred", decision: "deferred", reason: "等資料更完整", revisit_at: "2099-01-07T12:00:00Z" }));
    renderAt(roundPath());
    expect(await screen.findByText(/1\/7 再看・等資料更完整/)).toBeTruthy();
    expect(screen.getByText("要改文案請等下一回證據")).toBeTruthy();
    expect(screen.getByRole("button", { name: "暫緩" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /選擇處理方向/ })).toBeNull();
  });

  it("unjudgeable：closed chip 是「無法判定」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status: "unjudgeable", decision: "unjudgeable", reason: "資料缺漏" }));
    renderAt(roundPath());
    expect(await screen.findByText(/無法判定・資料缺漏/)).toBeTruthy();
  });

  it("completed：沒有比對到佇列的 review proposal 時，連去選方向；比對到時走佇列的下一步", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status: "completed", decision: "completed" }));
    renderAt(roundPath());
    const link = await screen.findByRole("link", { name: /選擇處理方向/ });
    expect((link as HTMLAnchorElement).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1/prepare");
    expect(screen.queryByRole("button", { name: "暫緩" })).toBeNull();

    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({
      proposal: {
        kind: "review", review_id: "arv_1", status: "completed", decision: "completed", reason: null, revisit_at: null,
        recommendation_id: "rec_1", change_set_id: "acs_1", change_set_status: "draft", verification_state: "pending", multi: false,
      },
    })]));
    renderAt(roundPath());
    const changeLink = await screen.findByRole("link", { name: /等你核准/ });
    expect((changeLink as HTMLAnchorElement).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/confirm");
  });
});

describe("ReviewEvidencePage（F23-I02）先不決定 sheet", () => {
  it("暫緩要選一個之後的時間，過去的自訂日期不送出", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(roundPath());
    await user.click(await screen.findByRole("button", { name: "暫緩" }));
    await user.click(screen.getByRole("button", { name: "自訂" }));
    const dateInput = screen.getByLabelText("重看日期");
    await user.clear(dateInput);
    await user.type(dateInput, "2020-01-01");
    await user.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("請選一個之後的時間。")).toBeTruthy();
    expect(reviewApi.decideReview).not.toHaveBeenCalled();

    await user.clear(dateInput);
    await user.type(dateInput, "2099-01-01");
    vi.mocked(reviewApi.decideReview).mockResolvedValue(review({ status: "deferred", decision: "deferred", reason: "等資料更完整", revisit_at: "2099-01-01T00:00:00Z" }));
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(reviewApi.decideReview).toHaveBeenCalled());
    const call = vi.mocked(reviewApi.decideReview).mock.calls[0][3];
    expect(call.decision).toBe("deferred");
    expect(call.revisit_at?.startsWith("2099-01-01")).toBe(true);
  });

  it("無法判定不需要重看時間", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(roundPath());
    await user.click(await screen.findByRole("button", { name: "無法判定" }));
    expect(screen.queryByLabelText("重看日期")).toBeNull();
    vi.mocked(reviewApi.decideReview).mockResolvedValue(review({ status: "unjudgeable", decision: "unjudgeable", reason: "資料缺漏，無法比較" }));
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(reviewApi.decideReview).toHaveBeenCalled());
    const call = vi.mocked(reviewApi.decideReview).mock.calls[0][3];
    expect(call).toEqual({ decision: "unjudgeable", reason: "資料缺漏，無法比較" });
  });
});

describe("ReviewEvidencePage（F23-I02）entry route", () => {
  it("佇列列已有 proposal.review_id 時直接轉導，不建立新的一輪", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({
      proposal: {
        kind: "review", review_id: "arv_existing", status: "ready", decision: null, reason: null, revisit_at: null,
        recommendation_id: null, change_set_id: null, change_set_status: null, verification_state: null, multi: false,
      },
    })]));
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ id: "arv_existing" }));
    renderAt(entryPath);
    // `reviews/:reviewId` 也在 renderAt 的路由表裡，轉導後直接掛載 round 模式，不落到 catch-all——
    // 用實際讀到的回合內容證明轉導對象正確，同時確認沒有多送一次建立請求。
    await screen.findByText("先觀察一段時間");
    expect(reviewApi.getReview).toHaveBeenCalledWith("brd_1", "cmp_1", "arv_existing");
    expect(reviewApi.createReview).not.toHaveBeenCalled();
  });

  it("沒有既有提議時，用佇列列的觀察窗建立一輪並轉導", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
    vi.mocked(reviewApi.createReview).mockResolvedValue(review({ id: "arv_new" }));
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ id: "arv_new" }));
    renderAt(entryPath);
    await waitFor(() => expect(reviewApi.createReview).toHaveBeenCalled());
    const body = vi.mocked(reviewApi.createReview).mock.calls[0][2];
    expect(body).toEqual({ entity_id: "aex_1", start: "2026-09-08", end: "2026-09-21" });
    await screen.findByText("先觀察一段時間");
    expect(reviewApi.getReview).toHaveBeenCalledWith("brd_1", "cmp_1", "arv_new");
  });

  it("建立失敗顯示後端訊息，並提供回投放中心", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
    vi.mocked(reviewApi.createReview).mockRejectedValue(new Error("活動已結案，本回未送出。"));
    renderAt(entryPath);
    expect(await screen.findByText("活動已結案，本回未送出。")).toBeTruthy();
    const link = screen.getByRole("link", { name: "回投放中心" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads");
  });
});

// F29-I10 Contract K: the queue is context on this step — a failed read is said out loud with 重試 and the step
// still works; the open step flow has one exit back to 投放中心.
describe("ReviewEvidencePage（F29-I10）佇列讀取失敗與出口", () => {
  it("佇列讀取失敗：只多一塊讀取失敗，這一步照舊；重試重讀佇列後補回「第幾件」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(triageApi.getQueue).mockReset();
    vi.mocked(triageApi.getQueue).mockRejectedValueOnce(new Error("queue down")).mockResolvedValueOnce(queue());
    renderAt(roundPath());
    expect(await screen.findByText(/待決定清單讀不到/)).toBeTruthy();
    // Without the queue row there is no grade move to name: the headline stays neutral (no guess).
    expect(screen.getByRole("heading", { name: "看看這則廣告的數字" })).toBeTruthy();
    expect(screen.queryByText("第 1 件／共 1 件")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText("第 1 件／共 1 件")).toBeTruthy();
    expect(screen.queryByText(/待決定清單讀不到/)).toBeNull();
    expect(triageApi.getQueue).toHaveBeenCalledTimes(2);
  });

  it("開著的決定有「✕ 先不要，回投放中心」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(roundPath());
    const exit = await screen.findByRole("link", { name: "✕ 先不要，回投放中心" });
    expect(exit.getAttribute("href")).toBe("/brands/brd_1/ads");
  });
});

describe("ReviewEvidencePage（F29-I10）讀取失敗與已關閉的決定", () => {
  it("round 模式佇列讀取失敗：素材紀錄說讀取失敗，不說「還沒有處理紀錄」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(triageApi.getQueue).mockRejectedValue(new Error("queue down"));
    renderAt(roundPath());
    expect(await screen.findByText("讀取失敗，按上方重試後再看。")).toBeTruthy();
    expect(screen.queryByText("這則廣告還沒有處理紀錄。")).toBeNull();
  });

  it("entry 模式佇列讀取失敗：讀取失敗＋重試，不說「沒有這回的檢討提議」；重試後照常建立並導去正典網址", async () => {
    vi.mocked(triageApi.getQueue).mockReset();
    vi.mocked(triageApi.getQueue).mockRejectedValueOnce(new Error("queue down")).mockResolvedValue(queue());
    vi.mocked(reviewApi.createReview).mockResolvedValue(review({ id: "arv_new" }));
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ id: "arv_new" }));
    renderAt(entryPath);
    expect((await screen.findByRole("alert")).textContent).toContain("讀取失敗");
    expect(screen.queryByText("沒有這回的檢討提議")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    await waitFor(() => expect(reviewApi.createReview).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("heading", { name: "這則從划算變太貴" })).toBeTruthy();
  });

  it("已暫緩的一回沒有「先不要」出口，只剩返回投放中心", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status: "deferred", decision: "deferred", reason: "等資料更完整", revisit_at: "2099-01-07T12:00:00Z" }));
    renderAt(roundPath());
    expect(await screen.findByRole("link", { name: "← 投放中心" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /先不要，回投放中心/ })).toBeNull();
  });
});

// F29-I14 (v10 `stepEv()`): the 變貴 headline is the grade move against the campaign's own cap (Contract A
// `grade_move`); the cost carries its money tag; the ▲▼ against the previous window is only a reference.
describe("ReviewEvidencePage（F29-I14）變貴的標題與上限", () => {
  it("有 grade_move：標題說從哪一級變哪一級，目的說跟哪個活動的上限比；成本旁有有賺／在虧，前後升降只當參考", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({
      triage: triage({
        campaign_name: "日常商品推廣・轉換", grade: "watch", grade_label: "偏貴", grade_move: { from: "on_target", to: "watch" },
        target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [], break_even: 520 },
      }),
    })]));
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(roundPath());
    expect(await screen.findByRole("heading", { name: "這則從划算變偏貴" })).toBeTruthy();
    expect(screen.getByText("跟日常商品推廣的上限比，先看數字，再決定")).toBeTruthy();
    // 600 per purchase against break-even 520 → 在虧; the cap chip says 上限, never 目標.
    expect(document.querySelector("[data-slot=money-tag]")?.getAttribute("data-variant")).toBe("loss");
    expect(screen.getByText("在虧")).toBeTruthy();
    expect(screen.getAllByText("上限").length).toBeGreaterThan(0);
    expect(screen.queryByText(/目標/)).toBeNull();
    expect(screen.getByText(/前後升降只當參考/)).toBeTruthy();
  });

  it("grade_move 是 null：標題中性，不從趨勢猜「變差」", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({ triage: triage({ previous_grade: null, grade_move: null }) })]));
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(roundPath());
    expect(await screen.findByRole("heading", { name: "看看這則廣告的數字" })).toBeTruthy();
    expect(screen.queryByText(/變差|變貴了/)).toBeNull();
    // No break-even known → no money tag at all (never a guess).
    expect(document.querySelector("[data-slot=money-tag]")).toBeNull();
  });
});

// F30-I02 (v10 ai-blocked `aiBlockedCard()`, Contract A): the fact check rejected the model text — the round is
// `ready` with no recommendation; the numbers show as usual and the AI card is the dashed 「沒採用」 card with one retry.
describe("ReviewEvidencePage（F30-I02）AI 說明被擋下與再請 AI 看一次", () => {
  const rejectedRound = (overrides: Partial<ReviewRound> = {}) => review({
    result_json: { recommendations: [], limitations: ["歸因不可用"], rejected: { reason: "模型包含未允許的數字或因果斷言；請依原始證據人工判讀。" } },
    ...overrides,
  });

  it("rejected：數字照常，AI 卡變成「這次的說明沒採用」＋再請 AI 看一次，選方向照樣可以往下", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(rejectedRound());
    renderAt(roundPath());
    expect(await screen.findByText("✦ AI 這次的說明沒採用")).toBeTruthy();
    // Prototype `adIdent()`: the ad's grade and name head the page in their own card (no AI column).
    expect(screen.getByText("太貴").getAttribute("data-grade")).toBe("over");
    expect(screen.getByText("這則廣告")).toBeTruthy();
    expect(screen.getByText("3,000")).toBeTruthy();
    expect(screen.getByText("商城訂單")).toBeTruthy();
    // No stand-in AI text: neither the 「沒有給出建議」 fallback nor the limitations list.
    expect(screen.queryByText("AI 沒有給出建議")).toBeNull();
    expect(screen.queryByText("歸因不可用")).toBeNull();
    expect(screen.queryByText("✦ AI 建議")).toBeNull();
    expect(screen.getByRole("button", { name: "再請 AI 看一次" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /選擇處理方向/ }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1/prepare");
  });

  it("rejected：再請 AI 看一次 → 同一份證據重送，轉到新一輪的網址，新一輪顯示整理中", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockImplementation(async (_b, _c, id) => (id === "arv_2" ? review({ id: "arv_2", status: "queued", result_json: {} }) : rejectedRound()));
    vi.mocked(reviewApi.retryReview).mockResolvedValue({ review: review({ id: "arv_2", status: "queued", result_json: {} }), monitor: null });
    renderAt(roundPath());
    await user.click(await screen.findByRole("button", { name: "再請 AI 看一次" }));
    expect(reviewApi.retryReview).toHaveBeenCalledWith("brd_1", "cmp_1", "arv_1");
    expect(await screen.findByText("AI 正在整理證據")).toBeTruthy();
    expect(reviewApi.getReview).toHaveBeenLastCalledWith("brd_1", "cmp_1", "arv_2");
  });

  it("重送被拒（409）：留在這一頁，說出後端的原因，數字與選方向都還在", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(rejectedRound());
    vi.mocked(reviewApi.retryReview).mockRejectedValue(new Error("只有尚未決定、失敗或 AI 說明被擋下的檢討可以再請 AI 看一次。"));
    renderAt(roundPath());
    await user.click(await screen.findByRole("button", { name: "再請 AI 看一次" }));
    expect((await screen.findByRole("alert")).textContent).toBe("只有尚未決定、失敗或 AI 說明被擋下的檢討可以再請 AI 看一次。");
    expect(screen.getByText("這則廣告")).toBeTruthy();
    expect(screen.getByRole("link", { name: /選擇處理方向/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "再請 AI 看一次" })).toBeTruthy();
  });

  it("failed：訊息旁有再請 AI 看一次，按下轉到新一輪", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockImplementation(async (_b, _c, id) => (id === "arv_2" ? review({ id: "arv_2", status: "running", result_json: {} }) : review({ status: "failed", error: "模型未完成；保留已知證據，不自動重送。", result_json: {} })));
    vi.mocked(reviewApi.retryReview).mockResolvedValue({ review: review({ id: "arv_2", status: "running", result_json: {} }), monitor: null });
    renderAt(roundPath());
    expect(await screen.findByText("本次未完成")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "再請 AI 看一次" }));
    expect(await screen.findByText("AI 正在整理證據")).toBeTruthy();
    expect(reviewApi.retryReview).toHaveBeenCalledTimes(1);
  });

  it("unknown（結果未確認）與已決定的一輪都不給重送", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status: "unknown", error: null, result_json: {} }));
    renderAt(roundPath());
    expect(await screen.findByText("本次未完成")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "再請 AI 看一次" })).toBeNull();
  });

  it("已決定（completed）的 rejected 一輪：還是說沒採用，但不給重送", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(rejectedRound({ status: "completed", decision: "completed" }));
    renderAt(roundPath());
    expect(await screen.findByText("✦ AI 這次的說明沒採用")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "再請 AI 看一次" })).toBeNull();
  });
});
