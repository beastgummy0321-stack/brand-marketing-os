/** frontend/src/components/ads/review/PreparePage.test.tsx — F23-I03／F27-I12：`vi.mock` 掉
 * `@/lib/adsReviewApi`／`@/lib/adsTriageApi`，不打真的 API。覆蓋 Done 3：建議依 `ladder.step`
 * 預選（除非第一個 AI 建議是 observe）、換方向重填原因、五種存檔動作（copy/image/existing/
 * observe/retire）各自的 `decideReview` 呼叫與下一步、已經 completed 的一輪換方向時略過 decide
 * 呼叫、`copy_editable.ok === false` 時只改文案停用且顯示原因、錯的步驟轉去看證據頁。 */
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
      window: { start: "2026-09-08", end: "2026-09-21", previous_start: "2026-08-25", previous_end: "2026-09-07", timezone: "Asia/Taipei", missing_days: [] },
      current: period(), previous: period(),
      commerce: { current: commerce(), previous: commerce() },
      conditions: {
        history: "unknown", creative_snapshot: { copy_fields: { title: "舊標題", body: "舊內文" } }, binding_count: 0,
        copy_editable: { ok: true, mode: "single", reason: null },
      },
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
    ladder: { step: 0, copy_changes: 0, image_changes: 0, lineage_from: null },
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

function PrepareRoute() {
  const { brandId, campaignId, reviewId } = useParams<{ brandId: string; campaignId: string; reviewId: string }>();
  return <PreparePage brandId={brandId ?? ""} campaignId={campaignId ?? ""} reviewId={reviewId ?? ""} />;
}
function LocationProbe() {
  const loc = useLocation();
  return <p data-testid="probe-path">{loc.pathname}{loc.search}</p>;
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

describe("PreparePage（F27-I12）建議與預選", () => {
  it("ladder.step 0 → 只改文案卡標建議且預選，原因是它的預設值", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({ triage: triage({ ladder: { step: 0, copy_changes: 0, image_changes: 0, lineage_from: null } }) })]));
    renderAt(preparePath());
    await screen.findByDisplayValue("採用建議：保留圖片，測試新文案");
    const copyCard = screen.getByRole("button", { name: /只改文案/ });
    expect(copyCard.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("建議")).toBeTruthy();
    expect(screen.getByRole("button", { name: /開始改文案/ })).toBeTruthy();
  });

  it("ladder.step 1 → 換一張圖卡標建議且預選，原因是它的預設值", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({ triage: triage({ ladder: { step: 1, copy_changes: 1, image_changes: 0, lineage_from: null } }) })]));
    renderAt(preparePath());
    await screen.findByDisplayValue("文案改過仍未改善，換圖");
    const imageCard = screen.getByRole("button", { name: /換一張圖/ }) as HTMLButtonElement;
    expect(imageCard.disabled).toBe(false);
    expect(imageCard.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("建議")).toBeTruthy();
    expect(screen.getByRole("button", { name: /準備新圖/ })).toBeTruthy();
  });

  it("ladder.step 2 → 停掉這則卡標建議且預選", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({ triage: triage({ ladder: { step: 2, copy_changes: 1, image_changes: 1, lineage_from: null } }) })]));
    renderAt(preparePath());
    await screen.findByDisplayValue("多次調整仍未改善");
    const retireCard = screen.getByRole("button", { name: /停掉這則/ });
    expect(retireCard.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("建議")).toBeTruthy();
    expect(screen.getByRole("button", { name: /建立暫停提議/ })).toBeTruthy();
  });

  it("第一個 AI 建議是 observe → 先觀察卡預選並標建議，蓋過 ladder 步驟，並顯示何時重看", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({
      result_json: { recommendations: [{ id: "rec_1", target_id: "aex_1", recommendation: "observe", evidence_refs: [], hypothesis: "h", risks: [], next_step: "n" }], limitations: [] },
    }));
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({ triage: triage({ ladder: { step: 1, copy_changes: 1, image_changes: 0, lineage_from: null } }) })]));
    renderAt(preparePath());
    await screen.findByDisplayValue("資料量還不夠，先觀察");
    const observeCard = screen.getAllByRole("button", { name: /先觀察/ })
      .find((el) => el.getAttribute("data-slot") === "option-card")!;
    expect(observeCard.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("group", { name: "何時重看" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /保存，先觀察/ })).toBeTruthy();
    // ladder 步驟本來會指到換一張圖，蓋過去後那張卡不標建議。
    const imageCard = screen.getByRole("button", { name: /換一張圖/ });
    expect(imageCard.textContent?.includes("建議")).toBe(false);
  });

  it("找不到對應的 queue 項目（ladder 不明）→ 預選只改文案，不標建議", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({
      result_json: { recommendations: [{ id: "rec_1", target_id: "aex_1", recommendation: "retain", evidence_refs: [], hypothesis: "h", risks: [], next_step: "n" }], limitations: [] },
    }));
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([]));
    renderAt(preparePath());
    await screen.findByDisplayValue("採用建議：保留圖片，測試新文案");
    const copyCard = screen.getByRole("button", { name: /只改文案/ });
    expect(copyCard.getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByText("建議")).toBeNull();
  });

  it("copy_editable.ok=false → 只改文案卡停用並顯示原因，建議挪到換一張圖", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({
      evidence_json: {
        ...review().evidence_json,
        conditions: {
          history: "unknown", creative_snapshot: { copy_fields: { title: "舊標題", body: "舊內文" } }, binding_count: 0,
          copy_editable: { ok: false, mode: null, reason: "商品目錄素材沒有可改的文字" },
        },
      },
    }));
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({ triage: triage({ ladder: { step: 0, copy_changes: 0, image_changes: 0, lineage_from: null } }) })]));
    renderAt(preparePath());
    await screen.findByDisplayValue("文案改過仍未改善，換圖");
    const copyCard = screen.getByRole("button", { name: /只改文案/ }) as HTMLButtonElement;
    expect(copyCard.disabled).toBe(true);
    const imageCard = screen.getByRole("button", { name: /換一張圖/ });
    expect(imageCard.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getAllByText(/商品目錄素材沒有可改的文字/).length).toBeGreaterThan(0);
  });

  it("換方向重填原因為新方向的預設值", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(preparePath());
    await screen.findByDisplayValue("採用建議：保留圖片，測試新文案");
    await user.click(screen.getByRole("button", { name: /換一張圖/ }));
    expect(screen.getByDisplayValue("文案改過仍未改善，換圖")).toBeTruthy();
    expect(screen.getByRole("button", { name: /準備新圖/ })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /用現成素材/ }));
    expect(screen.getByDisplayValue("改用現成素材")).toBeTruthy();
    expect(screen.getByRole("button", { name: /上傳素材/ })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /停掉這則/ }));
    expect(screen.getByDisplayValue("多次調整仍未改善")).toBeTruthy();
    expect(screen.getByRole("button", { name: /建立暫停提議/ })).toBeTruthy();
  });
});

describe("PreparePage（F23-I03／F27-I12）存檔", () => {
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

  it("image：decide completed 後導去素材頁，mode=workbench_image", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(reviewApi.decideReview).mockResolvedValue(review({ status: "completed", decision: "completed" }));
    renderAt(preparePath());
    await user.click(await screen.findByRole("button", { name: /換一張圖/ }));
    await user.click(screen.getByRole("button", { name: /準備新圖/ }));
    await waitFor(() => expect(reviewApi.decideReview).toHaveBeenCalledWith("brd_1", "cmp_1", "arv_1", {
      decision: "completed", reason: "文案改過仍未改善，換圖",
    }));
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1/material?mode=workbench_image"));
  });

  it("existing：decide completed 後導去素材頁，mode=existing", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(reviewApi.decideReview).mockResolvedValue(review({ status: "completed", decision: "completed" }));
    renderAt(preparePath());
    await user.click(await screen.findByRole("button", { name: /用現成素材/ }));
    await user.click(screen.getByRole("button", { name: /上傳素材/ }));
    await waitFor(() => expect(reviewApi.decideReview).toHaveBeenCalledWith("brd_1", "cmp_1", "arv_1", {
      decision: "completed", reason: "改用現成素材",
    }));
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1/material?mode=existing"));
  });

  it("已經 completed 的一輪：換方向存檔時略過 decide 呼叫，直接導頁", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status: "completed", decision: "completed" }));
    renderAt(preparePath());
    await screen.findByDisplayValue("採用建議：保留圖片，測試新文案");
    await user.click(screen.getByRole("button", { name: /停掉這則/ }));
    await user.click(screen.getByRole("button", { name: /建立暫停提議/ }));
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/pause/aex_1?from=review&ref=arv_1"));
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
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/pause/aex_1?from=review&ref=arv_1"));
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

// F29-I10 Contract K: the queue is context on this step — a failed read is said out loud with 重試 and the step
// still works; the open step flow has one exit back to 投放中心.
describe("PreparePage（F29-I10）佇列讀取失敗與出口", () => {
  it("佇列讀取失敗：只多一塊讀取失敗，這一步照舊；重試重讀佇列後補回「第幾件」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(triageApi.getQueue).mockReset();
    vi.mocked(triageApi.getQueue).mockRejectedValueOnce(new Error("queue down")).mockResolvedValueOnce(queue());
    renderAt(preparePath());
    expect(await screen.findByText(/待決定清單讀不到/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /只改文案/ })).toBeTruthy();
    expect(screen.queryByText("第 1 件／共 1 件")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText("第 1 件／共 1 件")).toBeTruthy();
    expect(screen.queryByText(/待決定清單讀不到/)).toBeNull();
    expect(triageApi.getQueue).toHaveBeenCalledTimes(2);
  });

  it("開著的決定有「✕ 先不要，回投放中心」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(preparePath());
    const exit = await screen.findByRole("link", { name: "✕ 先不要，回投放中心" });
    expect(exit.getAttribute("href")).toBe("/brands/brd_1/ads");
  });
});

// F30-I02 (v10 ai-blocked `stepDir()`, Contract A): the fact check rejected the model text — no AI recommendation,
// so the ladder's pick is labelled 照順序先試 (neutral), never 建議, and the step works as usual.
describe("PreparePage（F30-I02）AI 說明被擋下：照順序先試", () => {
  const rejected = { recommendations: [], limitations: [], rejected: { reason: "模型包含未允許的數字或因果斷言；請依原始證據人工判讀。" } };

  it("ladder.step 0：只改文案預選、標「照順序先試」不標建議；原因不寫採用建議；存檔後導去改文案", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ result_json: rejected }));
    vi.mocked(reviewApi.decideReview).mockResolvedValue(review({ status: "completed", decision: "completed", result_json: rejected }));
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({ triage: triage({ ladder: { step: 0, copy_changes: 0, image_changes: 0, lineage_from: null } }) })]));
    renderAt(preparePath());
    await screen.findByDisplayValue("照順序先試：保留圖片，測試新文案");
    const chip = screen.getByText("照順序先試");
    expect(chip.getAttribute("data-tone")).toBe("neutral");
    expect(screen.queryByText("建議")).toBeNull();
    expect(screen.getByRole("button", { name: /只改文案/ }).getAttribute("aria-pressed")).toBe("true");
    await user.click(screen.getByRole("button", { name: /開始改文案/ }));
    await waitFor(() => expect(reviewApi.decideReview).toHaveBeenCalledWith("brd_1", "cmp_1", "arv_1", {
      decision: "completed", reason: "照順序先試：保留圖片，測試新文案",
    }));
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1/copy"));
  });

  it("ladder.step 1：換一張圖標「照順序先試」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ result_json: rejected }));
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem({ triage: triage({ ladder: { step: 1, copy_changes: 1, image_changes: 0, lineage_from: null } }) })]));
    renderAt(preparePath());
    await screen.findByDisplayValue("文案改過仍未改善，換圖");
    expect(screen.getByRole("button", { name: /換一張圖/ }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: /換一張圖/ }).textContent).toContain("照順序先試");
  });
});
