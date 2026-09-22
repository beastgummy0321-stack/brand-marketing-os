/** frontend/src/components/ads/AdsHomePage.test.tsx — F19-I02：v7 首頁版面重寫，取代 F04-I09
 * 的舊版判斷帶／時間軸／建檔檢查表斷言（issue 授權）。首頁只負責讀 `refreshQueue`（header 件數
 * ＋ `DecisionQueue`），`CampaignCards`／`BudgetCard`／`ChangeAttention` 各自打自己的 API——
 * review repair (b)：一塊讀取失敗不拖累另外兩塊，這裡驗證三塊真的互相獨立。
 *
 * F27-I17：頁首「最近同步・N 項待處理」晶片搬到頂欄（F27-I20），這支移除了三則原本斷言它的
 * 測試，換成頁首自己新讀的 `getRecovery`（恢復期橫幅、往下傳給 `DecisionQueue` 的
 * `recovering`）。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CampaignCard } from "@/lib/adsApi";
import { listCampaigns } from "@/lib/adsApi";
import type {
  QueueKind, QueuePayload, QueueProposal, QueueRefresh, QueueReviewProposal, QueueScale, TriageItem,
} from "@/lib/adsTriageApi";
import { refreshQueue } from "@/lib/adsTriageApi";
import { getChangeControlSummary, getMonthlyBudget, type MonthlyBudget } from "@/lib/adsChangeApi";
import { getRecovery, type AdsRecovery } from "@/lib/adsStatusApi";
import { AdsHomePage } from "./AdsHomePage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, listCampaigns: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, refreshQueue: vi.fn() };
});
vi.mock("@/lib/adsChangeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsChangeApi")>("@/lib/adsChangeApi");
  return { ...actual, getChangeControlSummary: vi.fn(), getMonthlyBudget: vi.fn() };
});
vi.mock("@/lib/adsStatusApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsStatusApi")>("@/lib/adsStatusApi");
  return { ...actual, getRecovery: vi.fn() };
});

function notRecovering(): AdsRecovery {
  return { recovering: false, gap: null, steps: [] };
}

// 跟元件自己的 `formatHM` 同一套換算（瀏覽器／測試執行環境的本地時區）——不直接寫死
// 「09:10」這種字面值，避免測試機時區跟元件算出來的不一樣。
function hm(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function unknownBudget(overrides: Partial<MonthlyBudget> = {}): MonthlyBudget {
  return {
    month: "2026-09", currency: "TWD", amount: null, revision: 0,
    known_spend: null, ongoing_estimate: null, reserved_increases: 0,
    available: null, uncertainties: ["待補資料"], can_increase: false,
    period_end: "2026-09-30", confirmed_at: null, notice: "餘額未知",
    ...overrides,
  };
}

function triageItem(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "ad_1", native_id: "native_1", name: "晨光隨行杯・日常出發", campaign_id: "cmp_1",
    campaign_name: "晨光隨行杯上市", thumbnail_url: null,
    class: "stop_loss", label: "停損", reason_code: "spend_over_stop_loss",
    window: { start: "2026-09-01", end: "2026-09-07", days: 7, previous_start: "2026-08-25", previous_end: "2026-08-31", extended_from: null },
    target: { value: 450, basis: "break_even", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 5200, result_count: 0, cost_per_result: null, result_kind: "purchase", result_label: "購買", derived_zero_days: 7, reason: null },
    previous: { spend: 4900, result_count: 15, cost_per_result: 326.7, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: null, sample: { gate: true, spend_multiple: 3.2, days_with_events: 7 },
    ...overrides,
  };
}

// F25-I02: `extra` carries the scale_budget／refresh_creative-only fields — `kind_key` defaults to
// mirroring `triage.class` (stop_loss／worse-only tests never need to pass it, same precedent as
// `DecisionQueue.test.tsx`'s `queueItem`), but scale_budget／refresh_creative fixtures always
// override it explicitly since their `triage.class` is the *ad's* own class (e.g. `better`),
// never one of the two row kinds.
function queueItem(
  id: string,
  overrides: Partial<TriageItem> = {},
  proposal: QueueProposal | null = null,
  extra: { kind_key?: QueueKind; scale?: QueueScale; refresh?: QueueRefresh; action_url?: string } = {},
) {
  const triage = triageItem(overrides);
  return {
    id, org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: `k_${id}`,
    category: "ads_triage_stop_loss", kind: null, severity: "rule_warning" as const,
    message: `廣告「${overrides.name ?? "晨光隨行杯・日常出發"}」停損，待決定`,
    action_url: extra.action_url ?? `/brands/brd_1/ads/campaigns/cmp_1?tab=performance`, visible_from: null,
    status: "open", created_at: "2026-09-19T00:00:00Z", resolved_at: null,
    kind_key: extra.kind_key ?? (triage.class === "worse" ? "worse" : "stop_loss"),
    triage, proposal, scale: extra.scale, refresh: extra.refresh,
  };
}

function scaleOwner(overrides: Partial<QueueScale["owner"]> = {}): QueueScale["owner"] {
  return { id: "adset_1", name: "晨光隨行杯・投放組", native_kind: "adset", native_id: "native_adset_1", ads_count: 3, currency: "TWD", ...overrides };
}
function scale(overrides: Partial<QueueScale> = {}): QueueScale {
  return {
    owner: scaleOwner(), from: 500, to: 600,
    cost_per_result: 300, previous_cost_per_result: 310,
    target: { value: 450, basis: "break_even", result_kind: "purchase", result_label: "購買", missing: [] },
    window_days: 7, month: { available: 12000, extra_needed: 700 },
    ...overrides,
  };
}
function refresh(overrides: Partial<QueueRefresh> = {}): QueueRefresh {
  return {
    campaign_id: "cmp_1", campaign_name: "晨光隨行杯上市",
    readable_count: 2, classified_count: 5, thumbnails: [null, null],
    ...overrides,
  };
}

function queue(overrides: Partial<QueuePayload> = {}): QueuePayload {
  return {
    items: [], counts: { stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 },
    // F25-I01: all four kinds are live now, `kinds_pending` is always empty.
    total_ads: 0, kinds_available: ["stop_loss", "worse", "scale_budget", "refresh_creative"], kinds_pending: [],
    ...overrides,
  };
}

function campaignCard(overrides: Partial<CampaignCard> = {}): CampaignCard {
  return {
    id: "cmp_1", name: "測試 Campaign", status: "live",
    start_date: "2026-01-01", end_date: "2026-01-31", objective: "conversion",
    created_at: "2026-01-01T00:00:00Z", created_by: null,
    budget_planned: null, budget_total: null,
    budget_progress: { spent: null, total: null, pct: null },
    judgment: { tone: "neutral", text: "投放中", detail: "還沒有花費資料" },
    outcome: { spend: 0, purchases: 0, revenue: 0 },
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AdsHomePage brandId="brd_1" />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  // 重置每個 mock 的呼叫紀錄，讓「refreshQueue 每次掛載只呼叫一次」這類斷言不受測試順序影響。
  vi.clearAllMocks();
  vi.mocked(getChangeControlSummary).mockResolvedValue({ pending_count: 0, items: [], truncated: false });
  vi.mocked(getMonthlyBudget).mockResolvedValue(unknownBudget());
  vi.mocked(listCampaigns).mockResolvedValue([]);
  vi.mocked(getRecovery).mockResolvedValue(notRecovering());
});

describe("AdsHomePage（F19-I02，v7 首頁版面）", () => {
  it("header 件數：多件時印出「N 件」（含 refreshQueue 每次掛載只呼叫一次）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(
      queue({ items: [queueItem("q1"), queueItem("q2", { name: "晨光隨行杯・辦公室一角" }), queueItem("q3", { name: "晨光隨行杯・隨時有你" })] }),
    );

    renderPage();

    expect(await screen.findByText("3 件・由上往下處理就好")).toBeTruthy();
    expect(vi.mocked(refreshQueue).mock.calls.length).toBe(1);
  });

  it("header 件數：已核對的停損列不算開著的——一件已完成、一件還開著只印「1 件」（F22-I05 rescope）", async () => {
    const doneProposal: QueueProposal = {
      change_set_id: "set_1", campaign_id: "cmp_1", kind: "pause",
      status: "approved", verification_state: "confirmed",
      reason: null, revisit_at: null, multi: false,
    };
    vi.mocked(refreshQueue).mockResolvedValue(
      queue({
        items: [
          queueItem("q1", { name: "已核對的廣告" }, doneProposal),
          queueItem("q2", { name: "還沒處理的廣告" }),
        ],
      }),
    );

    renderPage();

    expect(await screen.findByText("1 件・由上往下處理就好")).toBeTruthy();
  });

  it("header 件數：已暫緩的變差列不算開著的——`isQueueItemDone` 的 review 分支（F23-I05），一件已暫緩、一件還開著只印「1 件」", async () => {
    const deferredProposal: QueueReviewProposal = {
      kind: "review", review_id: "arv_1", status: "deferred", decision: "deferred",
      reason: null, revisit_at: "2026-10-03T02:00:00Z", recommendation_id: null,
      change_set_id: null, change_set_status: null, verification_state: null, multi: false,
    };
    vi.mocked(refreshQueue).mockResolvedValue(
      queue({
        items: [
          queueItem("q1", { class: "worse", label: "變差", name: "已暫緩的廣告" }, deferredProposal),
          queueItem("q2", { class: "worse", label: "變差", name: "還沒處理的廣告" }),
        ],
      }),
    );

    renderPage();

    expect(await screen.findByText("1 件・由上往下處理就好")).toBeTruthy();
  });

  it("header 件數：可加預算列算跟停損列一樣——已核對不算開著，沒有提案還開著（feature Decisions「header count counts scale rows like pause rows」）", async () => {
    const confirmedBudget: QueueProposal = {
      kind: "budget", change_set_id: "set_9", campaign_id: "cmp_1",
      status: "approved", verification_state: "confirmed",
      reason: null, revisit_at: null, multi: false,
    };
    vi.mocked(refreshQueue).mockResolvedValue(
      queue({
        items: [
          queueItem("q1", { class: "better", label: "變好", name: "已核對的加碼" }, confirmedBudget, {
            kind_key: "scale_budget", scale: scale({ owner: scaleOwner({ id: "adset_done" }) }),
          }),
          queueItem("q2", { class: "flat", label: "持平", name: "還沒處理的加碼" }, null, {
            kind_key: "scale_budget", scale: scale({ owner: scaleOwner({ id: "adset_open" }) }),
          }),
        ],
      }),
    );

    renderPage();

    expect(await screen.findByText("1 件・由上往下處理就好")).toBeTruthy();
  });

  it("header 件數：補素材列永遠算開著——沒有提案、也沒有「完成」狀態可言（feature Decisions「refresh rows never count as done」）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(
      queue({
        items: [
          queueItem("q1", { class: "flat", label: "持平", name: "素材不足的活動" }, null, {
            kind_key: "refresh_creative", refresh: refresh(), action_url: "/brands/brd_1/ads/campaigns/cmp_1?tab=assets&material_new=1",
          }),
        ],
      }),
    );

    renderPage();

    expect(await screen.findByText("1 件・由上往下處理就好")).toBeTruthy();
  });

  it("空佇列：header 印「都處理完了」（誠實空狀態句由 DecisionQueue 的佔位列自己扛，這支只管頁首）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());

    renderPage();

    expect(await screen.findByText("都處理完了")).toBeTruthy();
  });

  it("佇列列真的照 payload 渲染（分類、名稱、連結）——列的細節斷言在 DecisionQueue.test.tsx，這支只驗頁面接得到資料", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue({ items: [queueItem("q1")] }));

    renderPage();

    expect(await screen.findByText("晨光隨行杯・日常出發")).toBeTruthy();
    expect(screen.getByText("停損")).toBeTruthy();
    // 停損列沒有 proposal（F22-I05）：按鈕走提議頁。F25-I02：home 這一列的字樣是「看提議」，
    // 不是 detail 頁那顆「去處理」（feature Decisions "Home rows"："detail-page 「去處理」
    // unchanged"）。
    expect(screen.getByRole("link", { name: "看提議" })).toBeTruthy();
  });

  it("變差列不看 action_url——F23-I05 接上 proposalAction 後，就算 action_url 是 null 也照樣給「看證據」", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(
      queue({ items: [{ ...queueItem("q1", { class: "worse", label: "變差" }), action_url: null }] }),
    );

    renderPage();

    expect(await screen.findByText("晨光隨行杯・日常出發")).toBeTruthy();
    const link = screen.getByRole("link", { name: "看證據" });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/review/ad_1");
  });

  it("每月回顧是真的連結（F24-I02 接上 /month）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());

    renderPage();

    const link = await screen.findByRole("link", { name: "每月回顧" });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/month");
  });

  it("月預算未知：金額顯示「尚待確認」（逐欄核對，不用籠統的 no-0 regex）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());
    vi.mocked(getMonthlyBudget).mockResolvedValue(unknownBudget());

    renderPage();

    const region = await screen.findByRole("region", { name: "本月可新增承諾" });
    await waitFor(() => expect(region.textContent).toContain("尚待確認"));
    expect(region.textContent).toContain("已花 尚待確認");
    expect(region.textContent).toContain("預留 尚待確認");
    expect(region.textContent).toContain("可用 尚待確認");
  });

  it("月預算已知：分段長條可見（不是灰色佔位條）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());
    vi.mocked(getMonthlyBudget).mockResolvedValue(
      unknownBudget({ amount: 60000, known_spend: 22000, ongoing_estimate: 28000, available: 10000, can_increase: true }),
    );

    renderPage();

    const region = await screen.findByRole("region", { name: "本月可新增承諾" });
    await waitFor(() => expect(region.textContent).toContain("TWD 10,000"));
    expect(region.textContent).toContain("已花 TWD 22,000");
    expect(region.textContent).toContain("預留 TWD 28,000");
  });

  it("兩個插槽都掛上：佇列列與活動卡同時出現", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue({ items: [queueItem("q1")] }));
    vi.mocked(listCampaigns).mockResolvedValue([campaignCard()]);

    renderPage();

    expect(await screen.findByText("晨光隨行杯・日常出發")).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "測試 Campaign" })).toBeTruthy();
    expect(screen.getByTestId("campaign-grid")).toBeTruthy();
  });

  it("活動卡只列未結案的 Campaign，已結案的靠「查看全部活動」連結", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCard({ id: "cmp_live", name: "進行中活動" }),
      campaignCard({ id: "cmp_closed", name: "已結案活動", status: "closed" }),
    ]);

    renderPage();

    expect(await screen.findByRole("heading", { name: "進行中活動" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "已結案活動" })).toBeNull();
    expect(screen.getByRole("link", { name: "查看全部活動 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns");
  });

  it("活動卡讀取失敗不拖累佇列卡（三塊各自獨立）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue({ items: [queueItem("q1")] }));
    vi.mocked(listCampaigns).mockRejectedValue(new Error("活動讀取失敗，請稍後再試。"));

    renderPage();

    expect(await screen.findByText("晨光隨行杯・日常出發")).toBeTruthy();
    expect(await screen.findByText("活動讀取失敗，請稍後再試。")).toBeTruthy();
  });

  it("佇列讀取失敗：顯示錯誤與重試，不拖累月預算卡或活動卡；按下重試後恢復", async () => {
    vi.mocked(refreshQueue).mockRejectedValueOnce(new Error("讀取失敗，請稍後再試。"));
    vi.mocked(getMonthlyBudget).mockResolvedValue(unknownBudget({ amount: 60000, known_spend: 1000, ongoing_estimate: 0, available: 59000 }));
    vi.mocked(listCampaigns).mockResolvedValue([campaignCard()]);

    renderPage();

    expect(await screen.findByText("讀取失敗，請稍後再試。")).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "測試 Campaign" })).toBeTruthy();
    expect(await screen.findByRole("region", { name: "本月可新增承諾" })).toBeTruthy();

    const retry = screen.getByRole("button", { name: "重新讀取" });
    vi.mocked(refreshQueue).mockResolvedValue(queue());
    await userEvent.click(retry);

    expect(await screen.findByText("都處理完了")).toBeTruthy();
  });

  it("F27-I17：頁首不再印「最近同步・N 項待處理」晶片（搬到頂欄，F27-I20）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());
    vi.mocked(listCampaigns).mockResolvedValue([
      campaignCard({ id: "cmp_never", name: "從沒同步過" }),
    ]);

    renderPage();

    await screen.findByRole("heading", { name: "從沒同步過" });
    expect(screen.queryByText("尚未同步")).toBeNull();
    expect(screen.queryByRole("link", { name: /最近同步/ })).toBeNull();
  });

  describe("F27-I17：系統剛恢復（getRecovery）", () => {
    it("recovering 為 false：不印恢復橫幅", async () => {
      vi.mocked(refreshQueue).mockResolvedValue(queue());
      vi.mocked(getRecovery).mockResolvedValue(notRecovering());

      renderPage();

      await screen.findByText("都處理完了");
      expect(screen.queryByText(/系統暫停了/)).toBeNull();
    });

    it("recovering 為 true：印橫幅（時數／分鐘、缺口時間、warn chip、RecoverSteps），佇列列的按鈕換成佔位", async () => {
      vi.mocked(refreshQueue).mockResolvedValue(queue({ items: [queueItem("q1")] }));
      vi.mocked(getRecovery).mockResolvedValue({
        recovering: true,
        gap: { start: "2026-09-22T09:10:00Z", end: "2026-09-22T11:30:00Z", minutes: 140 },
        steps: [
          { key: "reconnect", label: "重新連線", state: "done" },
          { key: "auth", label: "確認讀取權限", state: "done" },
          { key: "resync", label: "補 2 小時的資料", state: "active" },
          { key: "requeue", label: "重新判斷廣告", state: "todo" },
          { key: "verify", label: "核對你回報的操作", state: "todo" },
        ],
      });

      renderPage();

      expect(await screen.findByText("系統暫停了 2 小時 20 分，正在補資料")).toBeTruthy();
      const gapStart = hm("2026-09-22T09:10:00Z");
      const gapEnd = hm("2026-09-22T11:30:00Z");
      expect(screen.getByText(`${gapStart} – ${gapEnd} 沒有檢查・下面的數字補完後會更新`)).toBeTruthy();
      expect(screen.getByText("這段時間平台可能照常花費")).toBeTruthy();
      expect(screen.getByText("重新判斷廣告")).toBeTruthy();
      // 佇列列的按鈕在恢復期間換成同一顆佔位（`DecisionQueue`／`QueueRow` 的斷面，這裡只驗證
      // 頁面真的把 `recovering` 傳下去）。
      expect(screen.queryByRole("link", { name: "看提議" })).toBeNull();
      expect(screen.getByText("補完資料後更新")).toBeTruthy();
    });

    it("getRecovery 讀取失敗：不擋頁面其他部分（review repair 同一條規則）", async () => {
      vi.mocked(refreshQueue).mockResolvedValue(queue());
      vi.mocked(getRecovery).mockRejectedValue(new Error("讀取系統恢復狀態失敗。"));

      renderPage();

      expect(await screen.findByText("都處理完了")).toBeTruthy();
      expect(screen.queryByText(/系統暫停了/)).toBeNull();
    });
  });

  it("移除的舊區塊不再出現（判斷帶／時間軸／建檔檢查表）", async () => {
    vi.mocked(refreshQueue).mockResolvedValue(queue());

    renderPage();

    await screen.findByText("都處理完了");
    expect(screen.queryByRole("heading", { name: "進行中的活動" })).toBeNull();
    expect(screen.queryByRole("button", { name: "查看歷史操作紀錄" })).toBeNull();
    expect(screen.queryByRole("button", { name: "查看新活動的建檔準備" })).toBeNull();
  });
});
