/** F30-I08: the v10 structure tree (prototype `tabStructure()`) from `GET …/structure` — live grades and costs, a
 * draft's missing material, an imported campaign's platform ad sets, and a failed read. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CampaignDetail } from "@/lib/adsApi";
import { getCampaignStructure, type CampaignStructure, type StructureAd } from "@/lib/adsWorkspaceApi";
import { StructureTab } from "./StructureTab";

vi.mock("@/lib/adsWorkspaceApi", () => ({ getCampaignStructure: vi.fn() }));

function campaign(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    id: "cmp_1", name: "日常商品推廣・轉換", objective: "購買", origin: "app",
    cap: { value: 450, basis: "own", own_value: 450, break_even: 520, price: 1280, product_id: "p1", result_kind: "purchase", result_label: "購買", missing: [], revision: 1 },
    ...overrides,
  } as CampaignDetail;
}

/** `GET …/structure` serves `reason_code` and `sample` beside each grade (F48 Contract R). */
function ad(overrides: Partial<StructureAd> = {}): StructureAd {
  return {
    ad_id: "ad_1", entity_id: "ent_1", name: "晨光隨行杯・日常出發", thumbnail_url: "/t/1.png", spend: 960,
    grade: "on_target", grade_label: "划算", reason_code: null, sample: null, cost_per_result: 48, results: 20, closing: false, missing_material: false,
    ...overrides,
  };
}

const LIVE: CampaignStructure = { groups: [
  { group_id: "g_a", name: "A・廣泛受眾", daily_budget: 400, ads: [
    ad(),
    ad({ ad_id: "ad_2", entity_id: "ent_2", name: "辦公室一角", grade: "watch", grade_label: "偏貴", cost_per_result: 520 }),
    ad({ ad_id: "ad_3", entity_id: "ent_3", name: "開箱 15 秒", grade: "over", grade_label: "太貴", cost_per_result: 617.5 }),
  ] },
  { group_id: "g_b", name: "B・再行銷 30 天", daily_budget: 800, ads: [
    ad({ ad_id: "ad_4", entity_id: "ent_4", name: "秋季新色預告", grade: "wasted", grade_label: "沒賣出", reason_code: "spend_over_target_no_result", cost_per_result: null, results: 0, spend: 1400 }),
    ad({ ad_id: "ad_5", entity_id: "ent_5", name: "健身情境", grade: "insufficient", grade_label: "剛開始、數字還不夠", reason_code: "too_new", cost_per_result: 300, results: 1 }),
    ad({ ad_id: "ad_6", entity_id: "ent_6", name: "提問式貼文", grade: "insufficient", grade_label: "資料不足", reason_code: "result_unknown_days", cost_per_result: null }),
    ad({ ad_id: "ad_7", entity_id: "ent_7", name: "再行銷兩入組", grade: null, grade_label: null, cost_per_result: null, results: null, spend: null }),
    ad({ ad_id: "ad_8", entity_id: "ent_8", name: "關掉的那則", closing: true, grade: "over", grade_label: "太貴", cost_per_result: 700 }),
  ] },
] };

function leaf(name: string) {
  return screen.getByText(name).closest("li") as HTMLElement;
}

describe("StructureTab (F30-I08)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("live: campaign → groups (每日・N 則) → ads with grade chip, cost and money tag; 0 筆, thin label, —; 關閉中 dimmed; legend once", async () => {
    vi.mocked(getCampaignStructure).mockResolvedValue(LIVE);
    render(<StructureTab brandId="brd_1" campaign={campaign()} planKey="k" />);

    expect(await screen.findByText("A・廣泛受眾")).toBeTruthy();
    expect(getCampaignStructure).toHaveBeenCalledWith("brd_1", "cmp_1", expect.anything());
    expect(screen.getByRole("heading", { name: "活動 → 廣告組 → 廣告" })).toBeTruthy();
    expect(screen.getByText("每則右邊是每賣一筆花多少")).toBeTruthy();
    expect(screen.getByText("每日 1,200・購買")).toBeTruthy();
    expect(screen.getByText("每日 400・3 則")).toBeTruthy();
    expect(screen.getByText("每日 800・5 則")).toBeTruthy();

    const ok = leaf("晨光隨行杯・日常出發");
    expect(within(ok).getByText("划算").closest("[data-slot=chip]")?.getAttribute("data-tone")).toBe("ok");
    expect(ok.textContent).toContain("48 元");
    expect(ok.querySelector("[data-slot=money-tag]")?.getAttribute("data-variant")).toBe("gain");
    expect(ok.querySelector("img")?.getAttribute("src")).toBe("/t/1.png");
    expect(leaf("辦公室一角").querySelector("[data-slot=money-tag]")?.getAttribute("data-variant")).toBe("even");
    expect(leaf("開箱 15 秒").querySelector("[data-slot=money-tag]")?.getAttribute("data-variant")).toBe("loss");
    expect(leaf("開箱 15 秒").textContent).toContain("618 元");

    const wasted = leaf("秋季新色預告");
    expect(within(wasted).getByText("沒賣出")).toBeTruthy();
    expect(wasted.textContent).toContain("0 筆");
    // A thin sample prints its label (a glossary term) instead of a cost, even when a cost exists.
    const thin = leaf("健身情境");
    expect(within(thin).getAllByText("剛開始、數字還不夠")).toHaveLength(2);
    expect(thin.textContent).not.toContain("300 元");
    expect(within(leaf("提問式貼文")).getAllByText("資料不足")).toHaveLength(2);
    // F48: 剛開始 vs 資料不足 is the served reason_code, not the label: only too_new carries the 剛開始 glossary term.
    expect(within(thin).getAllByText("剛開始、數字還不夠").filter((el) => el.dataset.slot === "term")).toHaveLength(2);
    expect(within(leaf("提問式貼文")).getAllByText("資料不足").filter((el) => el.dataset.slot === "term")).toHaveLength(0);
    // Not judged and no cost: 未判斷 and —, never 0.
    const unknown = leaf("再行銷兩入組");
    expect(within(unknown).getByText("未判斷")).toBeTruthy();
    expect(unknown.textContent).toContain("—");
    expect(unknown.textContent).not.toContain("0 元");

    const closing = leaf("關掉的那則");
    expect(closing.getAttribute("data-variant")).toBe("dimmed");
    expect(within(closing).getByText("關閉中")).toBeTruthy();
    expect(within(closing).queryByText("太貴")).toBeNull();

    expect(document.querySelectorAll("[data-slot=grade-rules]")).toHaveLength(1);
  });

  it("draft (F49 Contract T): each planned ad's material cell is its served slot_label; no grade or cost; missing_material is never read", async () => {
    const planned = (o: Partial<StructureAd>) => ad({ entity_id: null, grade: null, grade_label: null, cost_per_result: null, spend: null, results: null, ...o });
    vi.mocked(getCampaignStructure).mockResolvedValue({ groups: [
      { group_id: "g_a", name: "A・廣泛受眾", daily_budget: 500, ads: [
        // `missing_material` is stale on purpose: the screen prints the slot state, not the compatibility key.
        planned({ ad_id: "ad_1", name: "晨光隨行杯（秋季新色）", thumbnail_url: "/t/1.png", slot_state: "ready", slot_label: "已確認", missing_material: true }),
        planned({ ad_id: "ad_2", name: "第四則", thumbnail_url: null, slot_state: "missing", slot_label: "缺", missing_material: true }),
        planned({ ad_id: "ad_3", name: "訓練前不用配水", thumbnail_url: null, slot_state: "waiting", slot_label: "等你", missing_material: true }),
        planned({ ad_id: "ad_4", name: "訓練前免沖泡優惠價", thumbnail_url: "/t/4.png", slot_state: "blocked", slot_label: "卡住", missing_material: true }),
        planned({ ad_id: "ad_5", name: "段考前一次備妥", thumbnail_url: null, slot_state: "failed", slot_label: "失敗", missing_material: true }),
        // The slot read failed: no state served — the name alone, never a guessed word.
        planned({ ad_id: "ad_6", name: "讀不到格子的那則", thumbnail_url: null, slot_state: null, slot_label: null, missing_material: false }),
      ] },
    ] });
    render(<StructureTab brandId="brd_1" campaign={campaign({ name: "秋季新色預購", cap: { ...campaign().cap, value: null, basis: null } })} planKey="k" />);

    const chipOf = (name: string) => leaf(name).querySelector("[data-slot=chip]") as HTMLElement | null;
    const ready = (await screen.findByText("晨光隨行杯（秋季新色）")).closest("li") as HTMLElement;
    expect(ready.getAttribute("data-variant")).toBe("ad");
    expect(ready.querySelector("img")?.getAttribute("src")).toBe("/t/1.png");
    expect([chipOf("晨光隨行杯（秋季新色）")?.textContent, chipOf("晨光隨行杯（秋季新色）")?.dataset.tone]).toEqual(["已確認", "ok"]);
    // Not ready without a picture: the dashed tile beside the ad's own name, and the served chip.
    expect(leaf("第四則").getAttribute("data-variant")).toBe("missing");
    expect([chipOf("第四則")?.textContent, chipOf("第四則")?.dataset.tone]).toEqual(["缺", "warn"]);
    expect([chipOf("訓練前不用配水")?.textContent, chipOf("訓練前不用配水")?.dataset.tone]).toEqual(["等你", "warn"]);
    expect([chipOf("段考前一次備妥")?.textContent, chipOf("段考前一次備妥")?.dataset.tone]).toEqual(["失敗", "bad"]);
    // Not ready with a picture: the picture stays, the chip says why it is not ready.
    expect(leaf("訓練前免沖泡優惠價").querySelector("img")?.getAttribute("src")).toBe("/t/4.png");
    expect([chipOf("訓練前免沖泡優惠價")?.textContent, chipOf("訓練前免沖泡優惠價")?.dataset.tone]).toEqual(["卡住", "bad"]);
    expect(chipOf("讀不到格子的那則")).toBeNull();
    expect(screen.queryByText("缺素材")).toBeNull();
    expect(screen.getByText("每日 500・6 則")).toBeTruthy();
    expect(screen.getByText("每日 500・購買")).toBeTruthy();
    expect(screen.queryByText("未判斷")).toBeNull();
  });

  it("imported: platform ad sets; an unknown group daily budget makes the campaign daily unknown; a lead objective names its result", async () => {
    vi.mocked(getCampaignStructure).mockResolvedValue({ groups: [
      { group_id: null, name: "Meta 廣告組 1", daily_budget: null, ads: [ad({ ad_id: null, entity_id: "ent_9", name: "平台廣告" })] },
      { group_id: null, name: "Meta 廣告組 2", daily_budget: 300, ads: [] },
    ] });
    render(<StructureTab brandId="brd_1" campaign={campaign({ origin: "imported", objective: "名單", cap: { ...campaign().cap, result_kind: "lead", result_label: "名單" } })} planKey="k" />);

    expect(await screen.findByText("Meta 廣告組 1")).toBeTruthy();
    expect(screen.getByText("每日 —・1 則")).toBeTruthy();
    expect(screen.getByText("每日 300・0 則")).toBeTruthy();
    expect(screen.getByText("每日 —・名單")).toBeTruthy();
    expect(screen.getByText("每則右邊是每一筆名單花多少")).toBeTruthy();
    expect(within(leaf("平台廣告")).getByText("划算")).toBeTruthy();
  });

  it("imported with no ad sets read yet says so (not an empty tree)", async () => {
    vi.mocked(getCampaignStructure).mockResolvedValue({ groups: [] });
    render(<StructureTab brandId="brd_1" campaign={campaign({ origin: "imported" })} planKey="k" />);
    expect(await screen.findByText("還沒讀回平台上的廣告組。")).toBeTruthy();
    expect(document.querySelector("[data-slot=tree-rows]")).toBeNull();
  });

  it("a failed read is ReadFailed with 重試 (no tree, no legend); 重試 reads again", async () => {
    const user = userEvent.setup();
    vi.mocked(getCampaignStructure).mockRejectedValueOnce(new Error("讀取投放結構失敗。")).mockResolvedValueOnce(LIVE);
    render(<StructureTab brandId="brd_1" campaign={campaign()} planKey="k" />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("讀取投放結構失敗。");
    expect(document.querySelector("[data-slot=tree-rows]")).toBeNull();
    expect(document.querySelector("[data-slot=grade-rules]")).toBeNull();
    await user.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText("A・廣泛受眾")).toBeTruthy();
    expect(getCampaignStructure).toHaveBeenCalledTimes(2);
  });

  it("a new planKey re-reads the tree", async () => {
    vi.mocked(getCampaignStructure).mockResolvedValue(LIVE);
    const view = render(<StructureTab brandId="brd_1" campaign={campaign()} planKey="a" />);
    await screen.findByText("A・廣泛受眾");
    view.rerender(<StructureTab brandId="brd_1" campaign={campaign()} planKey="b" />);
    await screen.findByText("A・廣泛受眾");
    expect(getCampaignStructure).toHaveBeenCalledTimes(2);
  });
});
