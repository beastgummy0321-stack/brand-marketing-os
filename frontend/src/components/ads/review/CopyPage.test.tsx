/** frontend/src/components/ads/review/CopyPage.test.tsx — F23-I04：`vi.mock` 掉
 * `@/lib/adsReviewApi`／`@/lib/adsTriageApi`／`@/lib/adsChangeApi`，不打真的 API。覆蓋 Done 3/4：
 * 承接 adjust 建議的 suggested_copy（沒有 adjust 建議就留白並一行說明）、目前→新版的即時行差異
 * 標記、保存只送非空欄位並附 `review_id`/`recommendation_id`（有 adjust 建議才附）、保存失敗兩種
 * 分流（`ChangeRequestRejected` 顯示後端訊息保留草稿／沒收到回應顯示 banner 且主按鈕停用、banner
 * 自己的按鈕沿用同一份草稿重試）、走錯步驟轉去看證據頁、`ready`（還沒決定）一樣能畫這頁。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as reviewApi from "@/lib/adsReviewApi";
import type { CommerceEvidence, ReviewPeriod, ReviewRound } from "@/lib/adsReviewApi";
import * as triageApi from "@/lib/adsTriageApi";
import type { QueueItem, QueuePayload, TriageItem } from "@/lib/adsTriageApi";
import * as changeApi from "@/lib/adsChangeApi";
import type { ChangeSet } from "@/lib/adsChangeApi";
import { formatSyncTime } from "@/lib/format";
import { CopyPage } from "./CopyPage";

vi.mock("@/lib/adsReviewApi", async (importOriginal) => ({
  ...(await importOriginal<typeof reviewApi>()),
  getReview: vi.fn(),
}));
vi.mock("@/lib/adsTriageApi", async (importOriginal) => ({
  ...(await importOriginal<typeof triageApi>()),
  getQueue: vi.fn(),
}));
vi.mock("@/lib/adsChangeApi", async (importOriginal) => ({
  ...(await importOriginal<typeof changeApi>()),
  createChangeSet: vi.fn(),
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
    decision: null, reason: null, revisit_at: null, created_at: "2026-09-19T14:40:00Z",
    result_json: {
      recommendations: [{
        id: "rec_1", target_id: "aex_1", recommendation: "adjust",
        evidence_refs: ["current"], hypothesis: "保留圖片，換文案試試。", risks: ["樣本量有限。"], next_step: "先核對素材。",
        suggested_copy: { title: "輕鬆帶走，每天剛剛好", body: "帶著晨光出發\n好咖啡・好心情，每一段旅程都值得。\n現在官網兩入組 NT$1,580 免運，再送原廠杯刷。\n👉 前往官網看更多顏色" },
      }],
      limitations: [],
    },
    evidence_json: {
      target: { id: "aex_1", name: "晨光隨行杯・隨時有你", platform: "meta", source_account: "acc_1", native_id: "native_1" },
      window: { start: "2026-09-08", end: "2026-09-21", previous_start: "2026-08-25", previous_end: "2026-09-07", timezone: "Asia/Taipei" },
      current: period(), previous: period(),
      commerce: { current: commerce(), previous: commerce() },
      conditions: {
        history: "unknown",
        creative_snapshot: {
          copy_fields: {
            title: "每天的隨行杯",
            body: "一杯剛剛好的溫度，陪你走過每一個日常。\n通勤、開會、健身、接小孩，晨光隨行杯 12 小時保溫保冷，單手開蓋不滴漏，杯身只有 280 公克。\n現在官網兩入組 NT$1,580 免運，再送原廠杯刷。\n👉 前往官網看更多顏色",
          },
        },
        binding_count: 0,
      },
      previous_review: null, source_review: null,
      limitations: [], waiting_reasons: [], sources: [],
    },
    ...overrides,
  };
}
function triage(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "aex_1", native_id: "native_1", name: "晨光隨行杯・隨時有你", campaign_id: "cmp_1",
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
function changeSet(overrides: Partial<ChangeSet> = {}): ChangeSet {
  return {
    id: "acs_1", campaign_id: "cmp_1", title: "改文案「晨光隨行杯・隨時有你」", month: "2026-09",
    operation_id: "op_1", content_hash: "hash_1", status: "draft", reason: null, revisit_at: null,
    approval_id: null, created_at: "2026-09-22T00:00:00Z", approved_at: null, items: [],
    ...overrides,
  };
}

function CopyRoute() {
  const { brandId, campaignId, reviewId } = useParams<{ brandId: string; campaignId: string; reviewId: string }>();
  return <CopyPage brandId={brandId ?? ""} campaignId={campaignId ?? ""} reviewId={reviewId ?? ""} />;
}
function LocationProbe() {
  return <p data-testid="probe-path">{useLocation().pathname}</p>;
}
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/reviews/:reviewId/copy" element={<CopyRoute />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}
const copyPath = (id = "arv_1") => `/brands/brd_1/ads/campaigns/cmp_1/reviews/${id}/copy`;

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(triageApi.getQueue).mockResolvedValue(queue());
});

describe("CopyPage（F23-I04）承接與差異標記", () => {
  it("有 adjust 建議：新版承接 suggested_copy，目前讀取時間來自 created_at", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(copyPath());
    expect(await screen.findByDisplayValue("輕鬆帶走，每天剛剛好")).toBeTruthy();
    expect((screen.getByLabelText("新內文") as HTMLTextAreaElement).value).toBe(
      "帶著晨光出發\n好咖啡・好心情，每一段旅程都值得。\n現在官網兩入組 NT$1,580 免運，再送原廠杯刷。\n👉 前往官網看更多顏色",
    );
    expect(screen.getByText(`讀取於 ${formatSyncTime("2026-09-19T14:40:00Z")}`)).toBeTruthy();
    expect(screen.queryByText("沒有可承接的建議，這份清單不會連回這輪檢討。")).toBeNull();
  });

  it("沒有 adjust 建議：新版留白，一行說明不會連回檢討", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({
      result_json: {
        recommendations: [{
          id: "rec_1", target_id: "aex_1", recommendation: "observe",
          evidence_refs: [], hypothesis: "h", risks: [], next_step: "n", suggested_copy: {},
        }],
        limitations: [],
      },
    }));
    renderAt(copyPath());
    await screen.findByText("目前");
    expect((screen.getByLabelText("新標題") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("新內文") as HTMLTextAreaElement).value).toBe("");
    expect(screen.getByText("沒有可承接的建議，這份清單不會連回這輪檢討。")).toBeTruthy();
  });

  it("目前卡片標記新版刪掉的行；還留著的行不標記", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(copyPath());
    await screen.findByDisplayValue("輕鬆帶走，每天剛剛好");
    // 舊標題整段改了 → 標記；「現在官網兩入組…」在新版一字不差保留 → 不標記。
    const droppedTitle = screen.getByText("每天的隨行杯");
    expect(droppedTitle.tagName).toBe("B");
    expect(droppedTitle.className).toContain("bg-warning/30");
    const kept = screen.getAllByText(/現在官網兩入組/).find((el) => el.tagName !== "TEXTAREA")!;
    expect(kept.tagName).not.toBe("MARK");
  });
});

describe("CopyPage（F23-I04）保存", () => {
  it("保存：只送非空欄位，附 review_id／recommendation_id，成功後導去確認變更頁", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(changeSet());
    renderAt(copyPath());
    await screen.findByDisplayValue("輕鬆帶走，每天剛剛好");
    await user.click(screen.getByRole("button", { name: /加入變更清單/ }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    const [brand, campaign, body] = vi.mocked(changeApi.createChangeSet).mock.calls[0];
    expect(brand).toBe("brd_1");
    expect(campaign).toBe("cmp_1");
    expect(body.operation_id).toMatch(/^review-copy:arv_1:/);
    expect(body.items).toEqual([{
      kind: "copy", target_id: "aex_1",
      after: { title: "輕鬆帶走，每天剛剛好", body: "帶著晨光出發\n好咖啡・好心情，每一段旅程都值得。\n現在官網兩入組 NT$1,580 免運，再送原廠杯刷。\n👉 前往官網看更多顏色" },
      reason: "測試新的文案訴求",
    }]);
    expect(body.review_id).toBe("arv_1");
    expect(body.recommendation_id).toBe("rec_1");
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/confirm"));
  });

  it("沒有 adjust 建議時，保存的草稿不附 review_id／recommendation_id", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({
      result_json: {
        recommendations: [{ id: "rec_1", target_id: "aex_1", recommendation: "observe", evidence_refs: [], hypothesis: "h", risks: [], next_step: "n", suggested_copy: {} }],
        limitations: [],
      },
    }));
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(changeSet());
    renderAt(copyPath());
    await screen.findByText("目前");
    await user.type(screen.getByLabelText("新內文"), "新的內文");
    await user.click(screen.getByRole("button", { name: /加入變更清單/ }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    const body = vi.mocked(changeApi.createChangeSet).mock.calls[0][2];
    expect(body.review_id).toBeUndefined();
    expect(body.recommendation_id).toBeUndefined();
  });

  it("新內文清空不給存", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(copyPath());
    // 先等預填內容到位再清空：預填是讀到檢討後才寫進 textarea，太早清會被預填蓋回去。
    await screen.findByDisplayValue("輕鬆帶走，每天剛剛好");
    const bodyInput = screen.getByLabelText("新內文");
    await user.clear(bodyInput);
    await user.click(screen.getByRole("button", { name: /加入變更清單/ }));
    expect(await screen.findByText("請填寫新內文。")).toBeTruthy();
    expect(changeApi.createChangeSet).not.toHaveBeenCalled();
  });

  it("原因清空不給存", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(copyPath());
    await screen.findByDisplayValue("輕鬆帶走，每天剛剛好");
    const reasonInput = screen.getByDisplayValue("測試新的文案訴求");
    await user.clear(reasonInput);
    await user.click(screen.getByRole("button", { name: /加入變更清單/ }));
    expect(await screen.findByText("請填寫原因。")).toBeTruthy();
    expect(changeApi.createChangeSet).not.toHaveBeenCalled();
  });
});

describe("CopyPage（F23-I04）保存失敗", () => {
  it("4xx（ChangeRequestRejected）：顯示後端訊息、保留草稿，主按鈕不停用", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(changeApi.createChangeSet).mockRejectedValue(new changeApi.ChangeRequestRejected("這則廣告已超過 30 天，請重新檢討。"));
    renderAt(copyPath());
    await screen.findByDisplayValue("輕鬆帶走，每天剛剛好");
    await user.click(screen.getByRole("button", { name: /加入變更清單/ }));
    expect(await screen.findByText("這則廣告已超過 30 天，請重新檢討。")).toBeTruthy();
    expect(screen.queryByText("上次保存沒收到回應")).toBeNull();
    expect((screen.getByRole("button", { name: /加入變更清單/ }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByDisplayValue("輕鬆帶走，每天剛剛好")).toBeTruthy();
  });

  it("沒收到回應：顯示 banner、主按鈕停用，banner 按鈕沿用同一份草稿重試", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(changeApi.createChangeSet)
      .mockRejectedValueOnce(new Error("未收到伺服器回應，結果尚未確認。請沿用原操作重試，不要重做平台操作。"))
      .mockResolvedValueOnce(changeSet());
    renderAt(copyPath());
    await screen.findByDisplayValue("輕鬆帶走，每天剛剛好");
    await user.click(screen.getByRole("button", { name: /加入變更清單/ }));
    expect(await screen.findByText("上次保存沒收到回應")).toBeTruthy();
    expect((screen.getByRole("button", { name: /加入變更清單/ }) as HTMLButtonElement).disabled).toBe(true);

    const firstBody = vi.mocked(changeApi.createChangeSet).mock.calls[0][2];
    await user.click(screen.getByRole("button", { name: /再核對一次/ }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalledTimes(2));
    expect(vi.mocked(changeApi.createChangeSet).mock.calls[1][2]).toEqual(firstBody);
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/confirm"));
  });
});

describe("CopyPage（F23-I04）錯的步驟／狀態", () => {
  it("completed 一樣能畫這頁", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status: "completed", decision: "completed" }));
    renderAt(copyPath());
    await screen.findByDisplayValue("輕鬆帶走，每天剛剛好");
    expect(screen.getByRole("button", { name: /加入變更清單/ })).toBeTruthy();
  });

  it.each(["running", "waiting", "failed", "deferred", "unjudgeable"] as const)("狀態 %s 轉去看證據頁", async (status) => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ status }));
    renderAt(copyPath());
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1"));
    expect(screen.queryByRole("button", { name: /加入變更清單/ })).toBeNull();
  });
});
