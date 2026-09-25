/** frontend/src/components/ads/flow/CleanupProposal.test.tsx — F28-I11: the cleanup proposal step (prototype v9
 * `stepProp()` for kind `clean`). Fixtures are shaped like the real queue row (`app/ads/triage_capacity.py::
 * cleanup_candidates`): long real names, decimal costs, a 沒賣出 ad with 0 results, unknown capacity, `short > 0` with
 * and without a qualifying `scale_budget` owner. `getTriage` only adds the daily budget and grade words. */
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as triageApi from "@/lib/adsTriageApi";
import type { CampaignTriage, QueueCleanup, QueueCleanupAd, QueueItem, TriageItem } from "@/lib/adsTriageApi";
import { CleanupProposal, rankCleanupAds } from "./CleanupProposal";

vi.mock("@/lib/adsTriageApi", async (importOriginal) => ({
  ...(await importOriginal<typeof triageApi>()),
  getTriage: vi.fn(),
}));

const LONG = "【銷售】1150706 Beast Prime 最高數量｜好攜帶，走到哪都適合（通勤情境單圖・最多數量 1150706）- 複本 3";

function ad(id: string, name: string, grade: QueueCleanupAd["grade"], spend: number | null, results: number | null, cost: number | null = null): QueueCleanupAd {
  return { entity_id: id, name, thumbnail_url: null, spend_7d: null, grade, cost_per_result: cost, spend, result_count: results, daily_spend: null, rejected_before: null };
}

/** Vivian-shaped: 沒賣出 + 太貴 + 偏貴 close, the 4 winners stay; capacity 4. */
const vivian = {
  close: [
    ad("aex_w", LONG, "wasted", 1542.37, 0),
    ad("aex_o", "1150803 圖文簡潔・中秋滿 3000 送月餅禮盒（輪播 5 張・再行銷 30 天）", "over", 2890.5, 4, 722.63),
    ad("aex_v", "撞車1150724・直式 9:16 短影音 - 複本", "watch", 1566.66, 3, 522.22),
  ],
  keep: [
    ad("aex_k1", "晨光隨行杯・日常出發", "on_target", 1440, 30, 48),
    ad("aex_k2", "健身情境・保冷 12 小時", "on_target", 3450, 8, 431.25),
    ad("aex_k3", "開箱 15 秒・單手開蓋", "on_target", 1100.25, 20, 55.01),
    ad("aex_k4", "辦公室一角・質感桌面", "on_target", 1300.5, 25, 52.02),
  ],
};

function cleanup(overrides: Partial<QueueCleanup> = {}): QueueCleanup {
  return {
    campaign_id: "cmp_1", campaign_name: "9/15~9/30廣告日常排程，搭配中秋活動優惠，滿3000送月餅禮盒，到9/30",
    can_support: 4, active_ads: 7, ads: vivian.close, keep: vivian.keep, short: 0, daily_saving: null, scale_owner_id: null,
    ...overrides,
  };
}

function triageItem(entityId: string, gradeLabel: string): TriageItem {
  return {
    entity_id: entityId, native_id: `n_${entityId}`, name: entityId, campaign_id: "cmp_1", campaign_name: "c", thumbnail_url: null,
    class: "flat", label: "持平", reason_code: "x", grade: "insufficient", grade_label: gradeLabel, previous_grade: null, grade_move: null,
    window: { start: "2026-09-10", end: "2026-09-23", days: 14, previous_start: "2026-08-27", previous_end: "2026-09-09", extended_from: null },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 1, result_count: 0, cost_per_result: null, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    previous: { spend: null, result_count: null, cost_per_result: null, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: null, sample: { gate: false, spend_multiple: null, days_with_events: 0 },
  };
}

function campaignTriage(daily: number | null, items: TriageItem[] = []): CampaignTriage {
  return {
    window_days: 14, items,
    closed: { total: 0, paused: 0, archived: 0, other: 0, items: [], truncated: false },
    data: { sync: { state: "fresh" }, coverage: null, missing_days: [], status: { state: "ready", label: "資料已讀齊。", missing_days: [], last_success_at: null }, capacity: { daily_budget: daily, currency: "TWD", target: 450, can_support: 4, active_ads: 7 } },
  } as unknown as CampaignTriage;
}

function row(c: QueueCleanup): QueueItem & { cleanup: QueueCleanup } {
  const t = triageItem("aex_w", "沒賣出");
  return {
    id: "int_1", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: "k", category: "ads_triage_cleanup",
    kind: null, severity: "money_loss", message: "m", action_url: null, visible_from: null, status: "open",
    created_at: "2026-09-23T00:00:00Z", resolved_at: null, kind_key: "cleanup",
    triage: { ...t, target: { ...t.target, break_even: 520 } }, proposal: null, cleanup: c,
  };
}

function renderProposal(c: QueueCleanup) {
  return render(
    <MemoryRouter initialEntries={["/brands/brd_1/ads/campaigns/cmp_1/propose/cleanup/cmp_1"]}>
      <CleanupProposal brandId="brd_1" campaignId="cmp_1" item={row(c)} position={{ pos: 1, total: 2 }} homeHref="/brands/brd_1/ads" />
    </MemoryRouter>,
  );
}

const orderRows = () => within(screen.getByRole("region", { name: "關的順序" })).getAllByRole("listitem");

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(triageApi.getTriage).mockResolvedValue(campaignTriage(1100));
});

describe("CleanupProposal（F28-I11）", () => {
  it("Vivian 形狀：關 3 則、留 4 則，關的順序沒賣出 → 太貴 → 偏貴 → 划算（同級最貴的先）", async () => {
    renderProposal(cleanup());
    expect(await screen.findByText("每日 1,100 撐 4 則")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "關 3 則、留 4 則" })).toBeTruthy();
    const rows = orderRows();
    expect(rows).toHaveLength(7);
    expect(rows.map((r) => r.textContent)).toEqual([
      `1${LONG}沒賣出0 筆關`,
      "21150803 圖文簡潔・中秋滿 3000 送月餅禮盒（輪播 5 張・再行銷 30 天）太貴722.63 元關",
      "3撞車1150724・直式 9:16 短影音 - 複本偏貴522.22 元關",
      "4健身情境・保冷 12 小時划算431.25 元留",
      "5開箱 15 秒・單手開蓋划算55.01 元留",
      "6辦公室一角・質感桌面划算52.02 元留",
      "7晨光隨行杯・日常出發划算48 元留",
    ]);
    // Capacity dots: 4 kept before the line, 3 closed after it.
    expect(screen.getByRole("img", { name: "留 4 則、關 3 則" })).toBeTruthy();
    // No 「剩下的都划算」 banner while nothing stays over capacity.
    expect(screen.queryByText(/剩下的/)).toBeNull();
    // The ruler badges exactly the three closing ads.
    expect(screen.getAllByText("關", { selector: "em" })).toHaveLength(3);
    expect(screen.getByRole("link", { name: "下一步：確認 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/cleanup/cmp_1?step=confirm");
  });

  it("只有沒賣出、撐幾則不知道：只關沒賣出，不印 null", async () => {
    vi.mocked(triageApi.getTriage).mockResolvedValue(campaignTriage(null));
    const { container } = renderProposal(cleanup({ can_support: null, active_ads: 3, ads: [vivian.close[0]], keep: vivian.keep.slice(0, 2) }));
    expect(await screen.findByText("預算撐幾則還不知道")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "關 1 則、留 2 則" })).toBeTruthy();
    expect(orderRows()[0].textContent).toBe(`1${LONG}沒賣出0 筆關`);
    expect(container.textContent).not.toMatch(/null|NaN|undefined/);
  });

  it("剩下的都划算、還超過預算：提示改提議加預算並連到該擁有者的加預算提議", async () => {
    renderProposal(cleanup({ can_support: 2, active_ads: 5, ads: [vivian.close[0]], keep: vivian.keep, short: 2, scale_owner_id: "aex_owner_A" }));
    expect(await screen.findByText("剩下的都划算，不關；改提議加預算")).toBeTruthy();
    expect(screen.getByRole("link", { name: "看加預算提議" }).getAttribute("href"))
      .toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/budget/aex_owner_A");
  });

  it("還超過預算但沒有可加預算的列：只說不關，不給連結", async () => {
    renderProposal(cleanup({ can_support: 2, active_ads: 5, ads: [vivian.close[0]], keep: vivian.keep, short: 2, scale_owner_id: null }));
    expect(await screen.findByText("剩下的都划算，不關")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "看加預算提議" })).toBeNull();
  });

  it("成本未知的列：太貴但成本未知印「未知」，資料不足／剛開始照後端的字，沒賣出筆數未知印「未知」", async () => {
    vi.mocked(triageApi.getTriage).mockResolvedValue(campaignTriage(1100, [triageItem("aex_n1", "資料不足"), triageItem("aex_n2", "剛開始、數字還不夠")]));
    const { container } = renderProposal(cleanup({
      ads: [ad("aex_w", "沒賣出但筆數未知", "wasted", 1480, null), ad("aex_o", "太貴但成本未知", "over", 2000, null)],
      keep: [ad("aex_n1", "中秋限定・月光藍開箱", "insufficient", 120, null), ad("aex_n2", "送禮提案・長輩也會用的保溫杯", "insufficient", 180, 1, 180)],
    }));
    expect(await screen.findByText("資料不足", { selector: "[data-slot=chip]" })).toBeTruthy();
    const rows = orderRows();
    expect(rows[0].textContent).toBe("1沒賣出但筆數未知沒賣出未知關");
    expect(rows[1].textContent).toBe("2太貴但成本未知太貴未知關");
    expect(rows[2].textContent).toBe("3中秋限定・月光藍開箱資料不足資料不足留");
    expect(rows[3].textContent).toBe("4送禮提案・長輩也會用的保溫杯剛開始、數字還不夠剛開始、數字還不夠留");
    expect(container.textContent).not.toMatch(/null|NaN|undefined/);
  });

  it("讀不到活動 triage 時仍顯示撐幾則（只少了每日預算）", async () => {
    vi.mocked(triageApi.getTriage).mockRejectedValue(new Error("網路錯誤"));
    renderProposal(cleanup());
    expect(await screen.findByText("預算撐 4 則")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "關 3 則、留 4 則" })).toBeTruthy();
  });

  it("rankCleanupAds：同級成本高的先，成本未知排最前，再比花費", () => {
    const ranked = rankCleanupAds([
      ad("a", "a", "on_target", 10, 1, 10), ad("b", "b", "over", 10, 1, 600), ad("c", "c", "over", 10, 1, 700),
      ad("d", "d", "wasted", 100, 0), ad("e", "e", "wasted", 300, 0), ad("f", "f", "insufficient", 5, null), ad("g", "g", "watch", 10, 1, 500),
    ]);
    expect(ranked.map((x) => x.entity_id)).toEqual(["e", "d", "c", "b", "g", "a", "f"]);
  });
});
