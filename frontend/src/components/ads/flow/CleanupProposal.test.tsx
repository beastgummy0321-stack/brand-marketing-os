/** frontend/src/components/ads/flow/CleanupProposal.test.tsx — F28-I11: the cleanup proposal step (prototype v9
 * `stepProp()` for kind `clean`). Fixtures are shaped like the real queue row (`app/ads/triage_capacity.py::
 * cleanup_candidates`, F48-I02): long real names, decimal costs, a 沒賣出 ad with 0 results, unknown capacity, `short > 0`
 * with and without a qualifying `scale_budget` owner; `ads` and `keep` each in the served rank order with
 * `rank, of, sales, few, verdict, verdict_label, flags, reason_text`. `getTriage` only adds the daily budget and the
 * `reason_code` that splits 剛開始 from 資料不足. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as triageApi from "@/lib/adsTriageApi";
import type { CampaignTriage, QueueCleanup, QueueCleanupAd, QueueItem, TriageItem } from "@/lib/adsTriageApi";
import { CleanupProposal } from "./CleanupProposal";
import { useCleanupPick } from "./cleanupDraft";

vi.mock("@/lib/adsTriageApi", async (importOriginal) => ({
  ...(await importOriginal<typeof triageApi>()),
  getTriage: vi.fn(),
}));

const LONG = "【銷售】1150706 Beast Prime 最高數量｜好攜帶，走到哪都適合（通勤情境單圖・最多數量 1150706）- 複本 3";

const WORD = { on_target: "划算", watch: "偏貴", over: "太貴", wasted: "沒賣出" } as Record<string, string>;

/** One served entry. `place` = [rank, of] in the campaign's ranking (`null` = ungraded, not ranked); `reason_text` is
 * built the way `triage_capacity.reason_text` builds it (cap 450). */
function ad(id: string, name: string, grade: QueueCleanupAd["grade"], spend: number | null, results: number | null, cost: number | null = null,
  place: [number, number] | null = null, label = ""): QueueCleanupAd {
  const sold = place !== null && results !== null && results > 0;
  const verdict = place === null ? null : sold && cost !== null && cost <= 450 ? "keep" : "replace";
  const few = sold && (results as number) < 5;
  const head = place ? `第 ${place[0]}／${place[1]} 名，` : "";
  const per = cost === null ? "" : Math.floor(cost + 0.5).toLocaleString("en-US");
  const reason = place === null ? `這則還沒有分數：${label}`
    : grade === "wasted" ? `花了 ${Math.floor((spend ?? 0) + 0.5).toLocaleString("en-US")}，一筆都沒賣出`
      : grade === "on_target" ? `${head}每筆 ${per} 在上限內（${WORD[grade]}）` : `${head}每筆 ${per} 對上限 450（${WORD[grade]}）`;
  return {
    entity_id: id, name, thumbnail_url: null, spend_7d: null, grade, cost_per_result: cost, spend, result_count: results, daily_spend: null, rejected_before: null,
    rank: place?.[0] ?? null, of: place?.[1] ?? null, sales: place === null ? null : results, few,
    verdict, verdict_label: verdict === null ? null : verdict === "keep" ? "留下" : "換掉", flags: few ? ["樣本少"] : [], reason_text: reason,
  };
}

/** Vivian-shaped: ranked by cost per sale, 沒賣出 last; the 換掉 rows close from the bottom (沒賣出 + the two over the
 * cap), the 4 under the cap stay; capacity 4. Served order: `ads` by rank, `keep` by rank. */
const vivian = {
  close: [
    ad("aex_v", "撞車1150724・直式 9:16 短影音 - 複本", "watch", 1566.66, 3, 522.22, [5, 7]),
    ad("aex_o", "1150803 圖文簡潔・中秋滿 3000 送月餅禮盒（輪播 5 張・再行銷 30 天）", "over", 2890.5, 4, 722.63, [6, 7]),
    ad("aex_w", LONG, "wasted", 1542.37, 0, null, [7, 7]),
  ],
  keep: [
    ad("aex_k1", "晨光隨行杯・日常出發", "on_target", 1440, 30, 48, [1, 7]),
    ad("aex_k4", "辦公室一角・質感桌面", "on_target", 1300.5, 25, 52.02, [2, 7]),
    ad("aex_k3", "開箱 15 秒・單手開蓋", "on_target", 1100.25, 20, 55.01, [3, 7]),
    ad("aex_k2", "健身情境・保冷 12 小時", "on_target", 3450, 8, 431.25, [4, 7]),
  ],
};

function cleanup(overrides: Partial<QueueCleanup> = {}): QueueCleanup {
  return {
    campaign_id: "cmp_1", campaign_name: "9/15~9/30廣告日常排程，搭配中秋活動優惠，滿3000送月餅禮盒，到9/30",
    can_support: 4, active_ads: 7, ads: vivian.close, keep: vivian.keep, short: 0, daily_saving: null, scale_owner_id: null,
    ...overrides,
  };
}

function triageItem(entityId: string, reasonCode: string, gradeLabel = ""): TriageItem {
  return {
    entity_id: entityId, native_id: `n_${entityId}`, name: entityId, campaign_id: "cmp_1", campaign_name: "c", thumbnail_url: null,
    class: "flat", label: "持平", reason_code: reasonCode, grade: "insufficient", grade_label: gradeLabel, previous_grade: null, grade_move: null,
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
  const t = triageItem("aex_w", "spend_over_target_no_result", "沒賣出");
  return {
    id: "int_1", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: "k", category: "ads_triage_cleanup",
    kind: null, severity: "money_loss", message: "m", action_url: null, visible_from: null, status: "open",
    created_at: "2026-09-23T00:00:00Z", resolved_at: null, kind_key: "cleanup",
    triage: { ...t, target: { ...t.target, break_even: 520 } }, proposal: null, done: false, cleanup: c,
  };
}

function Harness({ c }: { c: QueueCleanup }) {
  const pick = useCleanupPick(c);
  const location = useLocation();
  return (
    <>
      <CleanupProposal brandId="brd_1" campaignId="cmp_1" item={row(c)} position={{ pos: 1, total: 2 }} homeHref="/brands/brd_1/ads" pick={pick} />
      <span data-testid="probe-search">{location.search}</span>
    </>
  );
}

function renderProposal(c: QueueCleanup, search = "") {
  return render(
    <MemoryRouter initialEntries={[`/brands/brd_1/ads/campaigns/cmp_1/propose/cleanup/cmp_1${search}`]}>
      <Harness c={c} />
    </MemoryRouter>,
  );
}

/** What the row reads on screen: glossary sentences (the hidden `role=tooltip` of each dotted term) are not text. */
function seen(el: Element): string {
  const copy = el.cloneNode(true) as Element;
  copy.querySelectorAll("[role=tooltip]").forEach((tip) => tip.remove());
  return copy.textContent ?? "";
}

const orderRows = () => within(screen.getByRole("region", { name: "關的順序" })).getAllByRole("listitem");

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(triageApi.getTriage).mockResolvedValue(campaignTriage(1100));
});

describe("CleanupProposal（F28-I11）", () => {
  it("Vivian 形狀：關 3 則、留 4 則，照後端給的排名順序印（名次、成交、樣本少、原因句），不在前端重排", async () => {
    renderProposal(cleanup());
    expect(await screen.findByText("每日 1,100 撐 4 則")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "關 3 則、留 4 則" })).toBeTruthy();
    const rows = orderRows();
    expect(rows).toHaveLength(7);
    // Every cost carries its money tag against break-even 520 (v10 `mt(a)`), within 2 % is 剛好打平.
    expect(rows.map(seen)).toEqual([
      "5／7撞車1150724・直式 9:16 短影音 - 複本第 5／7 名，每筆 522 對上限 450（偏貴）偏貴樣本少522 元・剛好打平（打平 520）成交 3 筆關",
      "6／71150803 圖文簡潔・中秋滿 3000 送月餅禮盒（輪播 5 張・再行銷 30 天）第 6／7 名，每筆 723 對上限 450（太貴）太貴樣本少723 元・在虧（打平 520）成交 4 筆關",
      `7／7${LONG}花了 1,542，一筆都沒賣出沒賣出0 筆關`,
      "1／7晨光隨行杯・日常出發第 1／7 名，每筆 48 在上限內（划算）划算48 元・有賺（打平 520）成交 30 筆留",
      "2／7辦公室一角・質感桌面第 2／7 名，每筆 52 在上限內（划算）划算52 元・有賺（打平 520）成交 25 筆留",
      "3／7開箱 15 秒・單手開蓋第 3／7 名，每筆 55 在上限內（划算）划算55 元・有賺（打平 520）成交 20 筆留",
      "4／7健身情境・保冷 12 小時第 4／7 名，每筆 431 在上限內（划算）划算431 元・有賺（打平 520）成交 8 筆留",
    ]);
    expect(screen.getByText("照每筆成本排名；換掉的從最後一名往前關，留下的不關")).toBeTruthy();
    // The advanced fold is closed by default and lists only the proposed ads, all ticked.
    const fold = screen.getByText("進階：自己挑要關哪幾則").closest("details") as HTMLDetailsElement;
    expect(fold.open).toBe(false);
    expect(within(fold).getAllByRole("checkbox").map((b) => (b as HTMLInputElement).checked)).toEqual([true, true, true]);
    // Capacity dots: 4 kept before the line, 3 closed after it.
    expect(screen.getByRole("img", { name: "留 4 則、關 3 則" })).toBeTruthy();
    // No 「剩下的都划算」 banner while nothing stays over capacity.
    expect(screen.queryByText(/剩下的都划算/)).toBeNull();
    // The grade legend (grade rules + money rule) sits under the ruler, as in the prototype.
    expect(document.querySelector("[data-slot=grade-rules]")).toBeTruthy();
    // The ruler badges exactly the three closing ads.
    expect(screen.getAllByText("關", { selector: "em" })).toHaveLength(3);
    expect(screen.getByRole("link", { name: "下一步：確認 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/cleanup/cmp_1?step=confirm");
  });

  it("只有沒賣出、撐幾則不知道：只關沒賣出，不印 null", async () => {
    vi.mocked(triageApi.getTriage).mockResolvedValue(campaignTriage(null));
    const wasted = ad("aex_w", LONG, "wasted", 1542.37, 0, null, [3, 3]);
    const { container } = renderProposal(cleanup({
      can_support: null, active_ads: 3, ads: [wasted],
      keep: [ad("aex_k1", "晨光隨行杯・日常出發", "on_target", 1440, 30, 48, [1, 3]), ad("aex_k4", "辦公室一角・質感桌面", "on_target", 1300.5, 25, 52.02, [2, 3])],
    }));
    expect(await screen.findByText("預算撐幾則還不知道")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "關 1 則、留 2 則" })).toBeTruthy();
    expect(seen(orderRows()[0])).toBe(`3／3${LONG}花了 1,542，一筆都沒賣出沒賣出0 筆關`);
    expect(container.textContent).not.toMatch(/null|NaN|undefined/);
  });

  it("剩下的都划算、還超過預算：提示改提議加預算並連到該擁有者的加預算提議", async () => {
    renderProposal(cleanup({ can_support: 2, active_ads: 5, ads: [vivian.close[2]], keep: vivian.keep, short: 2, scale_owner_id: "aex_owner_A" }));
    expect(await screen.findByText("剩下的都划算，不關；改提議加預算")).toBeTruthy();
    expect(screen.getByRole("link", { name: "看加預算提議" }).getAttribute("href"))
      .toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/budget/aex_owner_A");
  });

  it("還超過預算但沒有可加預算的列：只說不關，不給連結", async () => {
    renderProposal(cleanup({ can_support: 2, active_ads: 5, ads: [vivian.close[2]], keep: vivian.keep, short: 2, scale_owner_id: null }));
    expect(await screen.findByText("剩下的都划算，不關")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "看加預算提議" })).toBeNull();
  });

  it("成本未知的列：太貴但成本未知印「未知」，資料不足／剛開始照 reason_code 的字，沒賣出筆數未知印「未知」", async () => {
    vi.mocked(triageApi.getTriage).mockResolvedValue(campaignTriage(1100, [triageItem("aex_n1", "result_unknown_days"), triageItem("aex_n2", "too_new")]));
    const unknown = (x: QueueCleanupAd): QueueCleanupAd => ({ ...x, reason_text: null });
    const { container } = renderProposal(cleanup({
      ads: [unknown(ad("aex_w", "沒賣出但筆數未知", "wasted", 1480, null, null, [1, 2])), unknown(ad("aex_o", "太貴但成本未知", "over", 2000, null, null, [2, 2]))],
      keep: [ad("aex_n1", "中秋限定・月光藍開箱", "insufficient", 120, null, null, null, "資料不足"), ad("aex_n2", "送禮提案・長輩也會用的保溫杯", "insufficient", 180, 0, null, null, "剛開始、數字還不夠")],
    }));
    expect(await screen.findByText((_, el) => el?.getAttribute("data-slot") === "chip" && seen(el) === "資料不足")).toBeTruthy();
    const rows = orderRows();
    expect(seen(rows[0])).toBe("1／2沒賣出但筆數未知沒賣出未知關");
    // An unknown cost prints 未知 and no money tag (never a guess).
    expect(seen(rows[1])).toBe("2／2太貴但成本未知太貴未知關");
    // Ungraded ads have no place (「—」) and keep the served reason sentence.
    expect(seen(rows[2])).toBe("—中秋限定・月光藍開箱這則還沒有分數：資料不足資料不足資料不足留");
    expect(seen(rows[3])).toBe("—送禮提案・長輩也會用的保溫杯這則還沒有分數：剛開始、數字還不夠剛開始、數字還不夠剛開始、數字還不夠留");
    expect(container.textContent).not.toMatch(/null|NaN|undefined/);
  });

  it("排序照 payload：較便宜的太貴排在偏貴前面也不重排", async () => {
    const over = ad("aex_o2", "太貴但比較便宜", "over", 1100, 2, 550, [2, 3]);
    const watch = ad("aex_v2", "偏貴但比較貴", "watch", 1600, 3, 533.33, [1, 3]);
    renderProposal(cleanup({ can_support: 1, active_ads: 3, ads: [over, watch, vivian.close[2]], keep: [] }));
    await screen.findByText("每日 1,100 撐 1 則");
    expect(orderRows().map((li) => li.getAttribute("data-ad"))).toEqual(["aex_o2", "aex_v2", "aex_w"]);
    const fold = screen.getByText("進階：自己挑要關哪幾則").closest("details") as HTMLDetailsElement;
    expect(within(fold).getAllByRole("checkbox").map((b) => b.getAttribute("aria-label"))).toEqual([
      "關掉「太貴但比較便宜」", "關掉「偏貴但比較貴」", `關掉「${LONG}」`,
    ]);
  });

  it("讀不到活動 triage 時仍顯示撐幾則（只少了每日預算），並說讀取失敗；重試重讀後補上每日預算（F29-I10）", async () => {
    vi.mocked(triageApi.getTriage).mockRejectedValueOnce(new Error("網路錯誤")).mockResolvedValueOnce(campaignTriage(1100));
    renderProposal(cleanup());
    expect(await screen.findByText("預算撐 4 則")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "關 3 則、留 4 則" })).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("每日預算與等級說明讀不到");
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText("每日 1,100 撐 4 則")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(triageApi.getTriage).toHaveBeenCalledTimes(2);
  });

  it("提議步驟是開著的決定：「✕ 先不要，回投放中心」取代同去處的「← 投放中心」（F29-I10）", async () => {
    renderProposal(cleanup());
    const exit = await screen.findByRole("link", { name: "✕ 先不要，回投放中心" });
    expect(exit.getAttribute("href")).toBe("/brands/brd_1/ads");
    expect(screen.queryByRole("link", { name: "← 投放中心" })).toBeNull();
  });

  it("進階：取消勾一則 → 標題、容量點、關的順序跟著勾選走，網址記住，全部照建議關復原（F29-I14）", async () => {
    const user = userEvent.setup();
    renderProposal(cleanup());
    await screen.findByText("每日 1,100 撐 4 則");
    await user.click(screen.getByText("進階：自己挑要關哪幾則"));
    await user.click(screen.getByRole("checkbox", { name: "關掉「撞車1150724・直式 9:16 短影音 - 複本」" }));

    expect(screen.getByRole("heading", { name: "關 2 則、留 5 則" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "留 5 則、關 2 則" })).toBeTruthy();
    expect(screen.getByText("你留下了 1 則")).toBeTruthy();
    expect(seen(orderRows()[0])).toBe("5／7撞車1150724・直式 9:16 短影音 - 複本第 5／7 名，每筆 522 對上限 450（偏貴）偏貴樣本少522 元・剛好打平（打平 520）成交 3 筆留・你改的");
    expect(screen.getAllByText("關", { selector: "em" })).toHaveLength(2);
    // Keeping it leaves 5 ads on a budget that carries 4: said on the page, not blocked.
    expect(screen.getByText("留 5 則，每日 1,100 只撐得起 4 則")).toBeTruthy();
    expect(screen.getByText("每則分到的錢變少，要更久才看得出好壞")).toBeTruthy();
    // The pick lives in the URL, so the confirm step (and a reload) see the same ticks.
    expect(screen.getByTestId("probe-search").textContent).toBe("?keep=aex_v");
    expect(screen.getByRole("link", { name: "下一步：確認 →" }).getAttribute("href"))
      .toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/cleanup/cmp_1?step=confirm&keep=aex_v");

    await user.click(screen.getByRole("button", { name: "全部照建議關" }));
    expect(screen.getByRole("heading", { name: "關 3 則、留 4 則" })).toBeTruthy();
    expect(screen.queryByText(/你留下了/)).toBeNull();
    expect(screen.queryByText(/只撐得起/)).toBeNull();
    expect(screen.getByTestId("probe-search").textContent).toBe("");
  });

  it("帶著勾選回到提議：摺疊自己打開，未知的 id 不算（F29-I14）", async () => {
    renderProposal(cleanup(), "?keep=aex_w,aex_gone");
    expect(await screen.findByRole("heading", { name: "關 2 則、留 5 則" })).toBeTruthy();
    const fold = screen.getByText("進階：自己挑要關哪幾則").closest("details") as HTMLDetailsElement;
    expect(fold.open).toBe(true);
    expect((screen.getByRole("checkbox", { name: `關掉「${LONG}」` }) as HTMLInputElement).checked).toBe(false);
    expect(screen.getByText("你留下了 1 則")).toBeTruthy();
  });

  it("上次拒絕過、這次變更差才回來的廣告：說出上次與這次的等級（F29-I01 Contract B）", async () => {
    const back = { ...vivian.close[1], rejected_before: { grade: "watch" as const, grade_label: "偏貴", at: "2026-09-15T10:20:00Z", reason: "兩入組還在檔期", change_set_id: "acs_old" } };
    renderProposal(cleanup({ ads: [vivian.close[0], back, vivian.close[2]] }));
    expect(await screen.findByText("上次你拒絕時是偏貴，現在變太貴")).toBeTruthy();
  });
});
