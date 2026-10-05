import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as reviews from "@/lib/adsReviewApi";
import * as changes from "@/lib/adsChangeApi";
import type { NativeEntity } from "@/lib/adsExternalApi";
import { apiFetch } from "@/lib/http";
import { ReviewPanel } from "./ReviewPanel";
import { ChangeControl } from "./ChangeControl";
import { RULES_FIXTURE, seedAdsRules } from "./patterns/rulesFixture";

vi.mock("./ManualHandoffPanel", () => ({ ManualHandoffPanel: () => null }));
// F36-I09 (ruling G): the component reads the org clock through `useWorkspace().identity.org`; the
// timezone is mutable so one case can move the org to UTC+14 without re-mocking the module.
let orgTimezone = "Asia/Taipei";
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({
    scope: "user:org", brands: [], brandsLoading: false, brandsError: null, refreshBrands: () => {},
    identity: {
      user: { id: "usr_1", email: "a@example.com" },
      org: { id: "org_test", name: "測試組織", kind: "personal", role: "owner", timezone: orgTimezone, today: "2020-01-01" },
      orgs: [],
    },
  }),
}));
// 2026-02-28 10:30Z: Kiritimati (UTC+14) is already 2026-03-01 00:30; UTC and the test runner zone
// (Asia/Taipei, UTC+8 = 18:30) are still on 2026-02-28. Only `Date` is faked so timers stay real.
const KIRITIMATI_INSTANT = new Date("2026-02-28T10:30:00Z");
function useKiritimati() {
  beforeEach(() => { orgTimezone = "Pacific/Kiritimati"; vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(KIRITIMATI_INSTANT); });
  afterEach(() => { vi.useRealTimers(); orgTimezone = "Asia/Taipei"; });
}
// The v10 timeline above the fold reads its own endpoint; this suite asserts the change-set request is the first `apiFetch`.
vi.mock("./workspace/ChangesTab", () => ({ ChangesTab: () => null }));
vi.mock("./ReviewTracking", () => ({ ReviewTracking: () => null }));
vi.mock("@/lib/auth", () => ({ getOrgId: () => "org_test" }));
vi.mock("@/lib/http", async () => ({ ...(await vi.importActual<typeof import("@/lib/http")>("@/lib/http")), apiFetch: vi.fn() }));
vi.mock("@/lib/adsReviewApi", () => ({
  getReviews: vi.fn(), getReview: vi.fn(), createReview: vi.fn(), decideReview: vi.fn(),
}));
vi.mock("@/lib/adsChangeApi", async importOriginal => ({
  ...await importOriginal<typeof changes>(), getMonthlyBudget: vi.fn(), getChangeControl: vi.fn(),
}));

const target: NativeEntity = {
  id: "ad_a", platform: "fixture", source_account: "account_a", native_id: "native_a",
  native_kind: "ad", native_label: "廣告", name: "虛構品牌 A 廣告", parent_native_id: "group_a",
  native_status: "ACTIVE", start_date: null, end_date: null, budget_amount: null,
  budget_type: "unknown", budget_raw: {}, currency: null, last_success_at: null, sync_error: null,
  creative: { kind: "image", fields: { body: "保留的原始內文", title: "保留的原始標題" } },
};
function commerce(): reviews.CommerceEvidence {
  return {
    scope: "brand", start: "2026-09-01", end: "2026-09-07", attribution: "unavailable",
    order_summary: {
      count: 8, non_void_count: 7, order_net_amount: 4567, paid_net_amount: null,
      unknown_payment_count: 3, currency: null, currency_basis: "unknown", coverage: "unknown",
      latest_import_at: null, unpaid_count: 2, void_count: 1, refunded_count: 1,
    },
    channels: [{ channel: "website", currency: null, amount: 4567, row_count: 8,
      source_type: "order_mirror", source: "easystore_xlsx" }],
    limitations: ["來源幣別尚未確認，不得把商城金額分配至單則廣告。"],
  };
}
function period(): reviews.ReviewPeriod {
  return {
    row_count: 6, days_present: 6, days_expected: 7, missing_days: 1,
    series: [{ metric_scope: "ad", attribution_key: "7d_click", currency: null, source: "platform",
      row_count: 6, days_present: 6, known_counts: { spend: 6, purchases: 0 },
      metrics: { spend: 1234, impressions: 4000, clicks: 20, purchases: null,
        revenue: null, ctr: 0.5, cpc: 61.7, cpa: null, roas_platform: null } }],
  };
}
function round(status: reviews.ReviewStatus = "waiting"): reviews.ReviewRound {
  return {
    id: "review_a", entity_id: target.id, window_start: "2026-09-01", window_end: "2026-09-07",
    previous_id: null, status, evidence_hash: "hash_a", llm_task_id: null, error: null,
    decision: null, reason: null, revisit_at: null, created_at: "2026-09-08T00:00:00Z",
    result_json: {}, evidence_json: {
      target,
      window: { start: "2026-09-01", end: "2026-09-07", previous_start: "2026-08-25",
        previous_end: "2026-08-31", timezone: null, missing_days: [] },
      current: period(), previous: { row_count: 0, days_present: 0, days_expected: 7,
        missing_days: 7, series: [] },
      commerce: { current: commerce(), previous: { ...commerce(), order_summary: {
        ...commerce().order_summary, count: 0, non_void_count: 0, order_net_amount: null,
      } } },
      conditions: { history: "unknown", creative_snapshot: { kind: "image", copy_fields: {
        body: "保留的原始內文",
      } }, binding_count: 1 },
      previous_review: null, limitations: ["未讀到完整報表。"],
      waiting_reasons: status === "waiting" ? ["購買與付款證據尚未齊全。"] : [],
      sources: [{ id: "source_a", text: "已收平台報表，缺購買指標。" }],
    },
  };
}
function data(value = round()): reviews.ReviewsData {
  return { reviews: [value], targets: [target], reviews_truncated: false, targets_truncated: false };
}
const onGoal = vi.fn();
function page(brandId = "brand_a") {
  return <MemoryRouter><ReviewPanel brandId={brandId} campaignId="campaign_a" onGoal={onGoal} /></MemoryRouter>;
}
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear();
  vi.mocked(reviews.getReviews).mockResolvedValue(data());
});

describe("廣告檢討的證據與使用者決定", () => {
  it("通知或來源連結可讀回不在最近清單內的歷史檢討", async () => {
    const old = { ...round("completed"), id: "older_review", reason: "歷史假設需要重新確認" };
    vi.mocked(reviews.getReview).mockResolvedValue(old);
    render(<MemoryRouter initialEntries={["/?tab=performance&review=older_review"]}><ReviewPanel brandId="brand_a" campaignId="campaign_a" onGoal={onGoal} /></MemoryRouter>);
    await screen.findByText("本次檢討完成");
    expect(reviews.getReview).toHaveBeenCalledWith("brand_a", "campaign_a", "older_review", expect.any(AbortSignal));
    expect(screen.queryByText("資料不足，等待補齊")).toBeNull();
    expect(reviews.createReview).not.toHaveBeenCalled();
  });

  it("商城與平台分區呈現，未知付款、幣別與缺資料不顯示成功或補零", async () => {
    const user = userEvent.setup();
    render(page());
    const platform = within(await screen.findByRole("region", { name: "單則廣告成效" }));
    const shop = within(screen.getByRole("region", { name: "商城與通路證據" }));
    expect(platform.getByText("1,234")).toBeTruthy();
    expect(platform.queryByText("4,567")).toBeNull();
    expect(shop.getByText("4,567")).toBeTruthy();
    expect(shop.queryByText("1,234")).toBeNull();
    const purchases = platform.getByRole("row", { name: /平台回報購買/ });
    expect(within(purchases).getAllByRole("cell").map(cell => cell.textContent))
      .toEqual(["平台回報購買", "尚待確認", "尚待確認"]);
    const paid = shop.getByRole("row", { name: /明確付款訂單淨額/ });
    expect(within(paid).getAllByRole("cell").map(cell => cell.textContent))
      .toEqual(["明確付款訂單淨額", "尚待確認", "尚待確認"]);
    expect(shop.getByText("3 筆")).toBeTruthy();
    expect(shop.getByText(/原始來源未確認/)).toBeTruthy();
    expect(platform.getByText(/幣別待確認.*6 \/ 7/)).toBeTruthy();
    expect(screen.getByText("資料不足，等待補齊")).toBeTruthy();
    expect(screen.queryByText("建議已備妥")).toBeNull();
    expect(screen.queryByRole("button", { name: "完成本次檢討" })).toBeNull();
    await user.click(shop.getByRole("button", { name: "查看通路來源與資料限制" }));
    expect(shop.getByText(/由訂單同步，不與訂單再次相加/)).toBeTruthy();
  });

  it("waiting 只讀取資料與開啟補件入口，明確提交前不重新建立檢討", async () => {
    const user = userEvent.setup();
    vi.mocked(reviews.createReview).mockResolvedValue(round());
    render(page());
    await user.click(await screen.findByRole("button", { name: "檢視活動目標" }));
    expect(onGoal).toHaveBeenCalledTimes(1);
    expect(reviews.createReview).not.toHaveBeenCalled();
    expect(reviews.getReview).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "重新檢查本期資料" }));
    await waitFor(() => expect(reviews.createReview).toHaveBeenCalledTimes(1));
    expect(reviews.createReview).toHaveBeenCalledWith("brand_a", "campaign_a",
      { entity_id: "ad_a", start: "2026-09-01", end: "2026-09-07" }, expect.any(AbortSignal));
  });

  it("觀察建議的空文案不顯示修改入口", async () => {
    const value = round("ready");
    value.result_json.recommendations = [{ id: "observe", target_id: target.id, recommendation: "observe",
      evidence_refs: ["current"], hypothesis: "等待更完整證據", risks: ["資料仍不足"], next_step: "補齊來源", suggested_copy: {} }];
    vi.mocked(reviews.getReviews).mockResolvedValue(data(value));
    render(page());
    await screen.findByText("等待更完整證據");
    expect(screen.queryByRole("link", { name: "只改文案，保留圖片" })).toBeNull();
  });

  it("承接上一回與核對紀錄，提交下一回時保留 previous_id", async () => {
    const user = userEvent.setup();
    const completed = round("completed");
    completed.previous_id = "review_before";
    completed.evidence_json.previous_review = { id: "review_before", result_json: {},
      decision: "completed", reason: "上一回選擇保留圖片，再觀察新內文", actions: [{ state: "confirmed" }] };
    vi.mocked(reviews.getReviews).mockResolvedValue(data(completed));
    vi.mocked(reviews.createReview).mockResolvedValue({ ...round(), id: "review_next", previous_id: "review_a" });
    render(page());
    await user.click(await screen.findByRole("button", { name: "查看完整判讀依據、缺漏與上一輪結果" }));
    expect(screen.getByText("上一回選擇保留圖片，再觀察新內文")).toBeTruthy();
    expect(screen.getByText(/已帶入 1 項操作核對紀錄/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "暫緩本次檢討" })).toBeNull();
    expect(screen.queryByRole("button", { name: "記錄無法判定" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "準備下一次檢討" }));
    expect(screen.getByText(/承接上一輪判讀與操作紀錄/)).toBeTruthy();
    expect(reviews.createReview).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "開始本次檢討" }));
    expect(reviews.createReview).toHaveBeenCalledWith("brand_a", "campaign_a",
      expect.objectContaining({ previous_id: completed.id }), expect.any(AbortSignal));
  });

  it("同一天可改選另一則廣告開始第一次檢討，不承接上一則的紀錄", async () => {
    const user = userEvent.setup();
    const completed = round("completed");
    completed.window_end = "2999-01-01";
    const other = { ...target, id: "entity_other", name: "另一則廣告" };
    vi.mocked(reviews.getReviews).mockResolvedValue({ ...data(completed), targets: [target, other] });
    vi.mocked(reviews.createReview).mockResolvedValue({ ...round(), id: "review_other", entity_id: other.id });
    render(page());
    await user.click(await screen.findByRole("button", { name: "檢討另一則廣告" }));
    const select = screen.getByLabelText("檢討廣告") as HTMLSelectElement;
    expect(select.disabled).toBe(false);
    expect(select.value).toBe(other.id);
    await user.click(screen.getByRole("button", { name: "開始本次檢討" }));
    const body = vi.mocked(reviews.createReview).mock.calls[0][2];
    expect(body.entity_id).toBe(other.id);
    expect("previous_id" in body).toBe(false);
  });

  it("切品牌清掉舊證據，延遲回應不能把前一品牌資料帶回", async () => {
    let resolveOld: (value: reviews.ReviewsData) => void = () => {};
    vi.mocked(reviews.getReviews).mockImplementation(brand => brand === "brand_a"
      ? new Promise(resolve => { resolveOld = resolve; })
      : Promise.resolve({ reviews: [], targets: [], reviews_truncated: false, targets_truncated: false }));
    const view = render(page());
    await waitFor(() => expect(reviews.getReviews).toHaveBeenCalledTimes(1));
    const oldSignal = vi.mocked(reviews.getReviews).mock.calls[0][2];
    view.rerender(page("brand_b"));
    await screen.findByText("先帶入正在投放的廣告");
    await act(async () => { resolveOld(data()); });
    expect(oldSignal?.aborted).toBe(true);
    expect(screen.queryByText(target.name!)).toBeNull();
    expect(screen.queryByRole("region", { name: "商城與通路證據" })).toBeNull();
    expect(reviews.createReview).not.toHaveBeenCalled();
  });

  it("已顯示的舊品牌證據在切換後立即移除", async () => {
    const view = render(page());
    await screen.findByText(target.name!);
    vi.mocked(reviews.getReviews).mockImplementation(() => new Promise(() => {}));
    view.rerender(page("brand_b"));
    expect(screen.queryByText(target.name!)).toBeNull();
    expect(screen.queryByRole("region", { name: "商城與通路證據" })).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("正在讀取");
  });

  it("建議連到文案清單，使用者修改後 POST 保留檢討與建議識別", async () => {
    const user = userEvent.setup();
    const ready = round("ready");
    ready.result_json = { recommendations: [{ id: "recommendation_a", target_id: target.id,
      recommendation: "adjust", evidence_refs: ["source_a"], hypothesis: "測試不同訴求，尚未證明改善",
      risks: ["目前購買資料不足"], next_step: "保留圖片，測試新的文案",
      suggested_copy: { title: "建議新標題", body: "建議新內文" } }] };
    vi.mocked(reviews.getReviews).mockResolvedValue(data(ready));
    vi.mocked(reviews.getReview).mockResolvedValue(ready);
    vi.mocked(changes.getChangeControl).mockResolvedValue({ targets: [target], change_sets: [] });
    vi.mocked(changes.getMonthlyBudget).mockResolvedValue({ month: "2026-09", currency: null,
      amount: null, revision: 0, known_spend: null, ongoing_estimate: null, reserved_increases: 0,
      available: null, uncertainties: ["資料待確認"], can_increase: false, period_end: "2026-09-30",
      confirmed_at: null, notice: "尚待確認" });
    const saved: changes.ChangeSet = { id: "change_a", campaign_id: "campaign_a", title: "文案測試",
      month: "2026-09", operation_id: "op_a", content_hash: "hash_a", status: "draft",
      reason: null, revisit_at: null, approval_id: null, created_at: "2026-09-19T00:00:00Z",
      approved_at: null, review_id: ready.id, recommendation_id: "recommendation_a", items: [{
        id: "item_a", kind: "copy", target_id: target.id, target,
        before: { title: "保留的原始標題", body: "保留的原始內文" },
        after: { title: "建議新標題", body: "使用者修訂後的測試內文" },
        reason: "測試不同訴求，尚未證明改善", verification_state: "pending", evidence_json: {},
        reported_at: null, first_observed_at: null, verified_at: null, platform_url: null,
      }],
    };
    vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ change_set: saved }), { status: 200 }));
    function Flow() {
      const [search] = useSearchParams();
      return search.get("tab") === "changes"
        ? <ChangeControl brandId="brand_a" campaignId="campaign_a" />
        : <ReviewPanel brandId="brand_a" campaignId="campaign_a" onGoal={onGoal} />;
    }
    render(<MemoryRouter><Flow /></MemoryRouter>);
    const link = await screen.findByRole("link", { name: "只改文案，保留圖片" });
    expect(link.getAttribute("href")).toContain("review=review_a&recommendation=recommendation_a");
    await user.click(link);
    expect(await screen.findByDisplayValue("建議新內文")).toBeTruthy();
    expect(screen.getByDisplayValue("建議新標題")).toBeTruthy();
    expect(apiFetch).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText("變更 1 新內文"));
    await user.type(screen.getByLabelText("變更 1 新內文"), "使用者修訂後的測試內文");
    await user.click(screen.getByRole("button", { name: "保存清單，檢視並核准" }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(1));
    const [url, options] = vi.mocked(apiFetch).mock.calls[0];
    expect(url).toContain("/brands/brand_a/campaigns/campaign_a/change-sets");
    expect(options?.method).toBe("POST");
    expect(typeof options?.body).toBe("string");
    const body = JSON.parse(String(options?.body));
    expect(body).toMatchObject({ review_id: "review_a", recommendation_id: "recommendation_a",
      items: [{ kind: "copy", target_id: "ad_a", after: {
        title: "建議新標題", body: "使用者修訂後的測試內文",
      } }] });
    expect(body.operation_id).toEqual(expect.any(String));
    expect(reviews.createReview).not.toHaveBeenCalled();
    await screen.findByRole("button", { name: "核准這份變更清單" });
    expect(screen.getByText("使用者修訂後的測試內文")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "保存清單，檢視並核准" })).toBeNull();
  });
});

describe("F36-I09 組織時鐘：觀察期間預設", () => {
  useKiritimati();
  it("結束日是組織的昨天（UTC+14 已是 3/1），不是瀏覽器的；下一輪門檻也用同一個今天", async () => {
    const user = userEvent.setup();
    const completed = round("completed");
    // Browser clock (2/28) would refuse: 2/27 >= 2/27. The org clock (3/1) allows it: 2/27 < 2/28.
    completed.window_end = "2026-02-27";
    vi.mocked(reviews.getReviews).mockResolvedValue(data(completed));
    render(page());
    await user.click(await screen.findByRole("button", { name: "準備下一次檢討" }));
    expect(screen.queryByText(/目前還沒有晚於本次觀察期的完整日期/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "調整觀察期間" }));
    expect((screen.getByLabelText("開始日期") as HTMLInputElement).value).toBe("2026-02-22");
    expect((screen.getByLabelText("結束日期") as HTMLInputElement).value).toBe("2026-02-28");
  });
});

describe("F50 Contract I (decision 11): the served limits", () => {
  const firstReview = () => vi.mocked(reviews.getReviews).mockResolvedValue({ ...data(), reviews: [] });
  const openRange = () => userEvent.setup().click(screen.getByRole("button", { name: "調整觀察期間" }));

  it("prints the served cadence default and day range (a changed fixture changes the words)", async () => {
    firstReview();
    const { unmount } = render(page());
    expect(await screen.findByText(/開始後預設每 7 天自動檢查這則廣告/)).toBeTruthy();
    await openRange();
    expect(screen.getByText(/一次最多 31 天；/)).toBeTruthy();
    unmount();
    seedAdsRules({ ...RULES_FIXTURE, limits: { ...RULES_FIXTURE.limits, review_cadence_default: 5, review_days: { min: 2, max: 20 } } });
    try {
      render(page());
      expect(await screen.findByText(/開始後預設每 5 天自動檢查這則廣告/)).toBeTruthy();
      await openRange();
      expect(screen.getByText(/一次最多 20 天；/)).toBeTruthy();
    } finally { seedAdsRules(RULES_FIXTURE); }
  });

  it("while the rules load the sentences print without a number", async () => {
    firstReview();
    seedAdsRules(null);
    try {
      render(page());
      expect(await screen.findByText(/開始後預設定期自動檢查這則廣告/)).toBeTruthy();
      await openRange();
      expect(screen.getByText(/後端依組織日期確認範圍/)).toBeTruthy();
      expect(screen.queryByText(/一次最多/)).toBeNull();
    } finally { seedAdsRules(RULES_FIXTURE); }
  });
});
