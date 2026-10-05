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
import type { ChangeItem, ChangeSet } from "@/lib/adsChangeApi";
import { CopyPage } from "./CopyPage";
import { RULES_FIXTURE, seedAdsRules } from "../patterns/rulesFixture";

vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "u:o", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-09-28" }, orgs: [] } }) }));
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
  getChangeControl: vi.fn(),
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
      window: { start: "2026-09-08", end: "2026-09-21", previous_start: "2026-08-25", previous_end: "2026-09-07", timezone: "Asia/Taipei", missing_days: [] },
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
    triage: triage(), proposal: null, done: false,
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
function changeItem(overrides: Partial<ChangeItem> = {}): ChangeItem {
  return {
    id: "adx_1", kind: "copy", target_id: "aex_1", after: {}, reason: "文案偏離",
    target: { id: "aex_1", name: "晨光隨行杯・隨時有你", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_1" },
    before: {}, verification_state: "deviated", evidence_json: {}, reported_at: null,
    first_observed_at: null, verified_at: null, platform_url: null,
    ...overrides,
  };
}
// F27-I13：真實回應（動態素材 `copy_editable.mode==="variants"`，真的打過本機後端 GET 一輪已存在
// 檢討，見 `.harness/scratch/F27/F27-I13/real-review.json`——campaign `adc_01M2T370NSGZDS0YXWTATKCN3T`
// 的每一則廣告都是 dynamic）確認 `copy_fields` 缺陣列時就是空陣列，不是報錯；這裡另外放兩個非空
// 版本做差異標記／清單編輯的行為測試，跟真實回應一樣走同一組鍵、只是內容非空。
function variantsReview(overrides: Partial<ReviewRound> = {}): ReviewRound {
  const base = review();
  return review({
    evidence_json: {
      ...base.evidence_json,
      conditions: {
        ...base.evidence_json.conditions,
        // `adsReviewApi.ts` 的 `copy_fields` 型別還是舊的 `Record<string, string | null>`（不在這張
        // 票的 touch 內，跟 `CopyPage.tsx` 的 `CopyFields` 就地放寬同一個理由）——真實回應（contract
        // B）動態素材是 `{titles,bodies}` 陣列，這裡照真實形狀就地放寬型別，不改到那支檔案。
        creative_snapshot: {
          kind: "dynamic",
          copy_fields: { titles: ["標題A", "標題B"], bodies: ["內文A 第一行\n內文A 第二行", "內文B"] } as unknown as Record<string, string | null>,
        },
        copy_editable: { ok: true, mode: "variants", reason: null },
      },
    },
    ...overrides,
  });
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
    expect(screen.getByText("讀取於 09/19 22:40")).toBeTruthy();
    expect(screen.queryByText("沒有可承接的建議，這份清單不會連回這輪檢討。")).toBeNull();
  });

  it("沒有 adjust 建議（F30-I02）：新版從平台現在的文案開始，目的行說 AI 沒給新版", async () => {
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
    expect(await screen.findByDisplayValue("每天的隨行杯")).toBeTruthy();
    expect((screen.getByLabelText("新內文") as HTMLTextAreaElement).value).toBe(review().evidence_json.conditions.creative_snapshot.copy_fields?.body);
    expect(screen.getByText("AI 沒給新版，從現在的文案直接改")).toBeTruthy();
    expect(screen.queryByText("圖片不變，只換文字")).toBeNull();
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

describe("CopyPage（F27-I13）variants 模式：copy_editable.mode===\"variants\"", () => {
  it("目前依標題／內文分兩組列每一則變體；新版是留白的清單編輯器（各一列可打字）", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(variantsReview());
    renderAt(copyPath());
    await screen.findByText("標題（2 則）");
    expect(screen.getByText("內文（2 則）")).toBeTruthy();
    expect(screen.getByText("標題A")).toBeTruthy();
    expect(screen.getByText("標題B")).toBeTruthy();
    // 新版沒有 prefill、也沒有可用的 variants 建議（`suggested_copy` 只有單一模式的形狀）→ 各一列空白。
    expect((screen.getByLabelText("新標題 1") as HTMLInputElement).value).toBe("");
    expect((screen.getByLabelText("新內文 1") as HTMLTextAreaElement).value).toBe("");
    // 這一輪本來就有 adjust 建議（只是沒有 variants 的形狀），新版照舊留白，不從現在的文案開始。
  });

  it("新版沿用其中一則標題，另一則沒被沿用 → 目前卡片只標記沒被沿用的那一則（整段每一行）", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(variantsReview());
    renderAt(copyPath());
    await screen.findByText("標題A");
    await user.type(screen.getByLabelText("新標題 1"), "標題A");
    const kept = screen.getByText("標題A");
    expect(kept.tagName).not.toBe("MARK");
    const dropped = screen.getByText("標題B");
    expect(dropped.tagName).toBe("MARK");
    // 內文沒被沿用（新版內文欄還是空的）→ 多行變體的每一行都標記。
    const droppedLine1 = screen.getByText("內文A 第一行");
    const droppedLine2 = screen.getByText("內文A 第二行");
    expect(droppedLine1.tagName).toBe("MARK");
    expect(droppedLine2.tagName).toBe("MARK");
  });

  it("新增／刪除標題列：滿 5 則（served `limits.copy_items_max`）停用新增，刪除後重新開放", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(variantsReview());
    renderAt(copyPath());
    await screen.findByLabelText("新標題 1");
    const addTitle = screen.getByRole("button", { name: "+ 新增標題" });
    for (let i = 0; i < 4; i++) await user.click(addTitle);
    expect(screen.getByLabelText("新標題 5")).toBeTruthy();
    expect((addTitle as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "刪除標題 5" }));
    expect(screen.queryByLabelText("新標題 5")).toBeNull();
    expect((addTitle as HTMLButtonElement).disabled).toBe(false);
  });

  it("F50 Contract I: the per-list cap and 「（最多 N 則）」 are the served `limits.copy_items_max` (a changed fixture changes both)", async () => {
    const user = userEvent.setup();
    expect(RULES_FIXTURE.limits.copy_items_max).toBe(5);
    seedAdsRules({ ...RULES_FIXTURE, limits: { ...RULES_FIXTURE.limits, copy_items_max: 3 } });
    try {
      vi.mocked(reviewApi.getReview).mockResolvedValue(variantsReview());
      renderAt(copyPath());
      expect(await screen.findByText("標題（最多 3 則）")).toBeTruthy();
      expect(screen.getByText("內文（最多 3 則）")).toBeTruthy();
      const addTitle = screen.getByRole("button", { name: "+ 新增標題" });
      for (let i = 0; i < 2; i++) await user.click(addTitle);
      expect(screen.getByLabelText("新標題 3")).toBeTruthy();
      expect((addTitle as HTMLButtonElement).disabled).toBe(true);
    } finally { seedAdsRules(RULES_FIXTURE); }
  });

  it("F50: while the rules load the headings print without a number", async () => {
    seedAdsRules(null);
    try {
      vi.mocked(reviewApi.getReview).mockResolvedValue(variantsReview());
      renderAt(copyPath());
      await screen.findByLabelText("新標題 1");
      expect(screen.queryByText(/最多 \d+ 則/)).toBeNull();
      expect(screen.getAllByRole("heading", { name: "標題" }).length).toBeGreaterThan(0);
    } finally { seedAdsRules(RULES_FIXTURE); }
  });

  it("保存：after 只送非空、去頭尾空白的 titles/bodies，附 review_id／recommendation_id", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(variantsReview());
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(changeSet());
    renderAt(copyPath());
    await screen.findByLabelText("新標題 1");
    await user.type(screen.getByLabelText("新標題 1"), "  新標題1  ");
    await user.click(screen.getByRole("button", { name: "+ 新增標題" }));
    // 第二列留白：保存時濾掉，不送空字串。
    await user.type(screen.getByLabelText("新內文 1"), "新內文1");
    await user.click(screen.getByRole("button", { name: /加入變更清單/ }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    const body = vi.mocked(changeApi.createChangeSet).mock.calls[0][2];
    expect(body.items).toEqual([{
      kind: "copy", target_id: "aex_1",
      after: { titles: ["新標題1"], bodies: ["新內文1"] },
      reason: "測試新的文案訴求",
    }]);
    expect(body.review_id).toBe("arv_1");
    expect(body.recommendation_id).toBe("rec_1");
  });

  it("標題與內文都留白（或整段空白字元）不給存", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(variantsReview());
    renderAt(copyPath());
    await screen.findByLabelText("新標題 1");
    await user.type(screen.getByLabelText("新內文 1"), "   ");
    await user.click(screen.getByRole("button", { name: /加入變更清單/ }));
    expect(await screen.findByText("請至少填寫一則標題或內文。")).toBeTruthy();
    expect(changeApi.createChangeSet).not.toHaveBeenCalled();
  });
});

describe("CopyPage（F27-I13）?prefill=observed&set= 從偏離項目的平台現況預填新版", () => {
  it("variants 模式：從指定清單裡對到這則廣告的項目讀 evidence_json.observed，覆蓋原本的留白", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(variantsReview());
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [],
      change_sets: [changeSet({
        id: "acs_9",
        items: [changeItem({
          target_id: "aex_1",
          evidence_json: { observed: { titles: ["觀察到的標題"], bodies: ["觀察到的內文"] } },
        })],
      })],
    });
    renderAt(`${copyPath()}?prefill=observed&set=acs_9`);
    await waitFor(() => expect(changeApi.getChangeControl).toHaveBeenCalledWith("brd_1", "cmp_1", expect.any(AbortSignal)));
    expect(await screen.findByDisplayValue("觀察到的標題")).toBeTruthy();
    expect((screen.getByLabelText("新內文 1") as HTMLTextAreaElement).value).toBe("觀察到的內文");
  });

  it("single 模式：一樣從 evidence_json.observed 覆蓋預設的 adjust 建議", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [],
      change_sets: [changeSet({
        id: "acs_9",
        items: [changeItem({
          target_id: "aex_1",
          evidence_json: { observed: { title: "平台現在的標題", body: "平台現在的內文" } },
        })],
      })],
    });
    renderAt(`${copyPath()}?prefill=observed&set=acs_9`);
    expect(await screen.findByDisplayValue("平台現在的標題")).toBeTruthy();
    expect((screen.getByLabelText("新內文") as HTMLTextAreaElement).value).toBe("平台現在的內文");
  });

  it("讀取變更清單失敗（F29-I10）：說讀取失敗＋重試，不偷偷改用 AI 建議；重試成功後預填平台現況", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(changeApi.getChangeControl).mockRejectedValueOnce(new Error("網路錯誤")).mockResolvedValueOnce({
      targets: [],
      change_sets: [changeSet({
        id: "acs_9",
        items: [changeItem({ target_id: "aex_1", evidence_json: { observed: { title: "平台現在的標題", body: "平台現在的內文" } } })],
      })],
    });
    renderAt(`${copyPath()}?prefill=observed&set=acs_9`);
    expect(await screen.findByText(/平台上現在的文案讀不到/)).toBeTruthy();
    expect(screen.queryByDisplayValue("輕鬆帶走，每天剛剛好")).toBeNull();
    expect((screen.getByRole("button", { name: "加入變更清單 →" }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByDisplayValue("平台現在的標題")).toBeTruthy();
    expect(screen.queryByText(/平台上現在的文案讀不到/)).toBeNull();
    expect(changeApi.getChangeControl).toHaveBeenCalledTimes(2);
  });
});

// F29-I10 Contract K: the queue is context on this step — a failed read is said out loud with 重試 and the step
// still works; the open step flow has one exit back to 投放中心.
describe("CopyPage（F29-I10）佇列讀取失敗與出口", () => {
  it("佇列讀取失敗：只多一塊讀取失敗，這一步照舊；重試重讀佇列後補回「第幾件」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    vi.mocked(triageApi.getQueue).mockReset();
    vi.mocked(triageApi.getQueue).mockRejectedValueOnce(new Error("queue down")).mockResolvedValueOnce(queue());
    renderAt(copyPath());
    expect(await screen.findByText(/待決定清單讀不到/)).toBeTruthy();
    expect(screen.getByLabelText("新內文")).toBeTruthy();
    expect(screen.queryByText("第 1 件／共 1 件")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText("第 1 件／共 1 件")).toBeTruthy();
    expect(screen.queryByText(/待決定清單讀不到/)).toBeNull();
    expect(triageApi.getQueue).toHaveBeenCalledTimes(2);
  });

  it("開著的決定有「✕ 先不要，回投放中心」", async () => {
    vi.mocked(reviewApi.getReview).mockResolvedValue(review());
    renderAt(copyPath());
    const exit = await screen.findByRole("link", { name: "✕ 先不要，回投放中心" });
    expect(exit.getAttribute("href")).toBe("/brands/brd_1/ads");
  });
});

// F30-I02 (v10 ai-blocked `stepCopy()`, Contract A): the fact check rejected the model text — no AI version, so
// the new version starts from the platform's current copy, and an untouched draft is not a change.
describe("CopyPage（F30-I02）AI 說明被擋下：從現在的文案直接改", () => {
  const rejected = { recommendations: [], limitations: [], rejected: { reason: "模型包含未允許的數字或因果斷言；請依原始證據人工判讀。" } };

  it("single：新版＝目前、沒有標記；沒改過不給存；改一行後存，不附 review_id／recommendation_id", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(review({ result_json: rejected }));
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(changeSet());
    renderAt(copyPath());
    expect(await screen.findByDisplayValue("每天的隨行杯")).toBeTruthy();
    expect(screen.getByText("AI 沒給新版，從現在的文案直接改")).toBeTruthy();
    expect(document.querySelector("[data-slot=copy-block] mark")).toBeNull();

    await user.click(screen.getByRole("button", { name: /加入變更清單/ }));
    expect(await screen.findByText("新版跟現在的文案一樣，改過再加入。")).toBeTruthy();
    expect(changeApi.createChangeSet).not.toHaveBeenCalled();

    const title = screen.getByLabelText("新標題");
    await user.clear(title);
    await user.type(title, "兩入組免運，今天下單");
    expect(screen.getByText("每天的隨行杯").className).toContain("bg-warning/30");
    await user.click(screen.getByRole("button", { name: /加入變更清單/ }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    const body = vi.mocked(changeApi.createChangeSet).mock.calls[0][2];
    expect(body.items[0].after).toEqual({ title: "兩入組免運，今天下單", body: review().evidence_json.conditions.creative_snapshot.copy_fields?.body });
    expect(body.review_id).toBeUndefined();
    expect(body.recommendation_id).toBeUndefined();
  });

  it("variants：新版每一列從現在的標題／內文開始；沒改過不給存，刪掉一則後存", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.getReview).mockResolvedValue(variantsReview({ result_json: rejected }));
    vi.mocked(changeApi.createChangeSet).mockResolvedValue(changeSet());
    renderAt(copyPath());
    expect(await screen.findByDisplayValue("標題B")).toBeTruthy();
    expect((screen.getByLabelText("新標題 1") as HTMLInputElement).value).toBe("標題A");
    expect((screen.getByLabelText("新內文 1") as HTMLTextAreaElement).value).toBe("內文A 第一行\n內文A 第二行");
    expect((screen.getByLabelText("新內文 2") as HTMLTextAreaElement).value).toBe("內文B");
    expect(screen.getByText("AI 沒給新版，從現在的文案直接改")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: /加入變更清單/ }));
    expect(await screen.findByText("新版跟現在的文案一樣，改過再加入。")).toBeTruthy();
    expect(changeApi.createChangeSet).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "刪除標題 2" }));
    await user.click(screen.getByRole("button", { name: /加入變更清單/ }));
    await waitFor(() => expect(changeApi.createChangeSet).toHaveBeenCalled());
    const body = vi.mocked(changeApi.createChangeSet).mock.calls[0][2];
    expect(body.items[0].after).toEqual({ titles: ["標題A"], bodies: ["內文A 第一行\n內文A 第二行", "內文B"] });
    expect(body.review_id).toBeUndefined();
  });
});
