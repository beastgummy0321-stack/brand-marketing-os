vi.mock("@/lib/figures", async (actual) => ({ ...await actual<typeof import("@/lib/figures")>(), useFigureBases: () => ({roas_at_cap: {label: "花到上限時", formula: "售價 ÷ 每筆上限", unit: "ratio"}, roas_all_spend: {label: "保守", formula: "營收 ÷ 全部花費", unit: "ratio"}, roas_tracked_spend: {label: "樂觀", formula: "營收 ÷ 有追到營收的那部分花費", unit: "ratio"}}) }));
/** F28-I09: the strategy tab's 「一個上限」 card — own／暫用打平／沒設上限 states, the integer NT$ input saved through
 * `PUT .../target` with the revision guard, the 409 reload path, and the mid ruler fed by triage (none for drafts). */
import { ApiResponseError } from "@/lib/http";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getCampaign, type CampaignDetail } from "@/lib/adsApi";
import {
  getTarget, getTriage, putTarget, type CampaignTarget, type CapView, type TriageItem,
} from "@/lib/adsTriageApi";
import { fetchProductList } from "@/lib/productsApi";
import { CapBlock } from "./CapBlock";

vi.mock("@/lib/adsApi", async () => ({ ...(await vi.importActual<object>("@/lib/adsApi")), getCampaign: vi.fn() }));
vi.mock("@/lib/adsTriageApi", async () => ({
  ...(await vi.importActual<object>("@/lib/adsTriageApi")), getTriage: vi.fn(), getTarget: vi.fn(), putTarget: vi.fn(),
}));
vi.mock("@/lib/productsApi", async () => ({ ...(await vi.importActual<object>("@/lib/productsApi")), fetchProductList: vi.fn() }));

type CampaignCap = CampaignDetail["cap"];
function cap(extra: Partial<CampaignCap>): CampaignCap {
  return {
    value: null, basis: null, own_value: null, break_even: null, price: null, product_id: "prd_1", knowledge_product_id: "kp_1",
    result_kind: "purchase", result_label: "購買", missing: [], revision: 4, ...extra,
  };
}
const OWN = cap({ value: 450, basis: "own", own_value: 450, break_even: 520, price: 1580 });
const BE = cap({ value: 520, basis: "break_even", break_even: 520, price: 1580 });
const NONE = cap({ price: 1280, missing: ["product_cost"] });
/** Only the original same-TWD arithmetic controls declare current source evidence. */
function knownCap(c: CampaignCap): CampaignCap {
  const economics = {basis: "break_even", currency: "TWD", source: "product_economics", unit_basis: "confirmed_product_economics"};
  return {...c, cap_unit: {basis: c.basis, currency: "TWD", source: c.basis === "own" ? "user" : "product_economics", unit_basis: c.basis === "own" ? "manual_ntd_input" : "confirmed_product_economics"}, break_even_unit: economics, price_unit: economics};
}
/** `GET .../target` of the 暫用打平 campaign: 成本含運 1,060 so 售價 1,580 − 1,060 = 打平 520. */
function target(c: CapView, cost: number | null): CampaignTarget {
  return { ...c, campaign_id: "cmp_1", product_ids: ["prd_1"], result_kinds: [{ kind: "purchase", label: "購買" }], cost };
}

function campaign(c: CapView, extra: Partial<CampaignDetail> = {}): CampaignDetail {
  return { id: "cmp_1", status: "live", origin: "internal", cap: c, ...extra } as CampaignDetail;
}

function item(id: string, grade: TriageItem["grade"], spend: number, results: number): TriageItem {
  return {
    entity_id: id, name: `廣告 ${id}`, grade, grade_label: "", thumbnail_url: null,
    current: { spend, result_count: results, cost_per_result: results ? spend / results : null },
  } as unknown as TriageItem;
}

function renderBlock(c: CampaignDetail) {
  const onCampaignChange = vi.fn();
  const view = render(<MemoryRouter><CapBlock brandId="brd_1" campaign={c} onCampaignChange={onCampaignChange} /></MemoryRouter>);
  return {...view, onCampaignChange};
}

describe("CapBlock", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTriage).mockResolvedValue({ window_days: 14, items: [], closed: { groups: [], total: 0, items: [], truncated: false } });
    vi.mocked(getTarget).mockResolvedValue(target(BE, 1060));
  });

  it.each(["USD", null])("never compares/fills a %s break-even into the manual TWD input", async (currency) => {
    const user = userEvent.setup();
    const c = knownCap(OWN);
    c.break_even_unit = {basis: "break_even", currency, source: "product_economics", unit_basis: currency ? "confirmed_product_economics" : null};
    c.price_unit = c.break_even_unit;
    const {container} = renderBlock(campaign(c));
    expect(container.textContent).not.toContain("ROAS");
    expect(screen.getByText(`・打平 520 ${currency ?? "幣別未知"}・售價、打平線與上限的幣別不同或尚未核實，暫時不能比較。`)).toBeTruthy();
    await user.click(screen.getByRole("button", {name: "修改"}));
    await user.type(screen.getByLabelText("每賣一筆最多花多少（上限）"), "450");
    expect(screen.getByRole("button", {name: `用打平 520 ${currency ?? "幣別未知"}`}).hasAttribute("disabled")).toBe(true);
    expect(container.textContent).not.toContain("比打平");
    expect(container.textContent).not.toContain("ROAS");
    expect(putTarget).not.toHaveBeenCalled();
  });

  it.each(["TWD", "USD"])("confirmed %s price without break-even only divides by a same-unit cap", async (currency) => {
    const c = knownCap(cap({value: 450, basis: "own", own_value: 450, price: 620, break_even: null, missing: ["product_cost"]}));
    c.break_even_unit = {basis: "break_even", currency: null, source: "product_economics", unit_basis: null};
    c.price_unit = {basis: "break_even", currency, source: "product_economics", unit_basis: "confirmed_product_economics"};
    const {container} = renderBlock(campaign(c));
    expect(await screen.findByText("450 TWD")).toBeTruthy();
    if (currency === "TWD") expect(container.textContent).toContain("ROAS 1.38x");
    else {
      expect(container.textContent).not.toContain("ROAS");
      expect(container.textContent).toContain("售價、打平線與上限的幣別不同或尚未核實，暫時不能比較。");
    }
    expect(container.textContent).not.toContain("打平 0");
    expect(putTarget).not.toHaveBeenCalled();
  });

  it("does not assign a unit to a legacy own cap while retaining its known scalar", async () => {
    renderBlock(campaign(OWN));
    expect(await screen.findByText("450 幣別未知")).toBeTruthy();
    expect(screen.queryByText("450 TWD")).toBeNull();
  });

  it("own cap: value, 自己填, ROAS 參考 = price ÷ cap and 打平; 修改 opens the input", async () => {
    const user = userEvent.setup();
    renderBlock(campaign(knownCap(OWN)));
    expect(await screen.findByText("450 TWD")).toBeTruthy();
    expect(screen.getByText("自己填")).toBeTruthy();
    expect(screen.getByText(textIs("ROAS 3.51x 花到上限時・打平 520 TWD"))).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "修改" }));
    expect(screen.getByLabelText("每賣一筆最多花多少（上限）")).toBeTruthy();
    expect(screen.getByRole("button", { name: "取消" })).toBeTruthy();
  });

  it("the chip reads the stored cap source: copied → 沿用上一期, break_even → 打平線, user → 自己填", async () => {
    const withSource = (source: string) =>
      campaign(OWN, { context_json: { field_sources: { cap: source } } } as unknown as Partial<CampaignDetail>);
    const { unmount } = render(<MemoryRouter><CapBlock brandId="brd_1" campaign={withSource("copied")} onCampaignChange={vi.fn()} /></MemoryRouter>);
    expect(await screen.findByText("沿用上一期")).toBeTruthy();
    expect(screen.queryByText("自己填")).toBeNull();
    unmount();
    const be = render(<MemoryRouter><CapBlock brandId="brd_1" campaign={withSource("break_even")} onCampaignChange={vi.fn()} /></MemoryRouter>);
    expect(await screen.findByText("打平線")).toBeTruthy();
    be.unmount();
    renderBlock(withSource("user"));
    expect(await screen.findByText("自己填")).toBeTruthy();
  });

  it("a cap the model read from the 一句話 sentence (parsed) is a guess, never 自己填 (F50)", async () => {
    renderBlock(campaign(OWN, { context_json: { field_sources: { cap: "parsed" } } } as unknown as Partial<CampaignDetail>));
    expect(await screen.findByText("猜的，請確認")).toBeTruthy();
    expect(screen.queryByText("自己填")).toBeNull();
  });

  it("an own cap equal to break-even reads 打平值", async () => {
    renderBlock(campaign(knownCap(cap({ value: 520, basis: "own", own_value: 520, break_even: 520, price: 1580 }))));
    expect(await screen.findByText("打平值")).toBeTruthy();
  });

  it("does not call equal scalar TWD own / USD break-even amounts a break-even value", async () => {
    const c = knownCap(cap({value: 450, basis: "own", own_value: 450, break_even: 450, price: 620}));
    c.break_even_unit = {...c.break_even_unit!, currency: "USD"};
    renderBlock(campaign(c));
    expect(screen.queryByText("打平值")).toBeNull();
    expect(screen.getByText("自己填")).toBeTruthy();
  });

  it("typing previews against break-even and saves the integer as the own cap with the revision guard", async () => {
    const user = userEvent.setup();
    const reread = campaign(cap({ value: 460, basis: "own", own_value: 460, break_even: 520, price: 1580, revision: 5 }));
    vi.mocked(putTarget).mockResolvedValue({} as CampaignTarget);
    vi.mocked(getCampaign).mockResolvedValue(reread);
    const { onCampaignChange } = renderBlock(campaign(knownCap(OWN)));
    await user.click(await screen.findByRole("button", { name: "修改" }));
    await user.type(screen.getByLabelText("每賣一筆最多花多少（上限）"), "460");
    expect(screen.getByText(textIs("比打平 520 TWD 低 60・ROAS 3.43x 花到上限時"))).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "儲存上限" }));
    expect(putTarget).toHaveBeenCalledWith("brd_1", "cmp_1", { basis: "own", value: 460, expected_revision: 4 });
    expect(onCampaignChange).toHaveBeenCalledWith(reread);
  });

  it.each(["0", "4.5", "-3"])("rejects %s: error shown, nothing saved", async (typed) => {
    const user = userEvent.setup();
    renderBlock(campaign(NONE));
    await user.type(await screen.findByLabelText("每賣一筆最多花多少（上限）"), typed);
    expect(screen.getByText("請填大於 0 的整數金額")).toBeTruthy();
    expect(screen.getByRole("button", { name: "儲存上限" }).hasAttribute("disabled")).toBe(true);
    expect(putTarget).not.toHaveBeenCalled();
  });

  it("暫用打平: 就用 saves break-even as the user's own cap only when pressed", async () => {
    const user = userEvent.setup();
    vi.mocked(putTarget).mockResolvedValue({} as CampaignTarget);
    vi.mocked(getCampaign).mockResolvedValue(campaign(OWN));
    vi.mocked(getTarget).mockResolvedValue(target(knownCap(BE), 1060));
    renderBlock(campaign(knownCap(BE)));
    expect(await screen.findByText("暫用打平")).toBeTruthy();
    expect(await screen.findByText(textIs("打平線 520 TWD・售價 1,580 TWD − 成本含運 1,060 TWD・ROAS 3.04x 花到上限時"))).toBeTruthy();
    expect(getTarget).toHaveBeenCalledWith("brd_1", "cmp_1");
    expect(putTarget).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "就用 520 TWD" }));
    expect(putTarget).toHaveBeenCalledWith("brd_1", "cmp_1", { basis: "own", value: 520, expected_revision: 4 });
  });

  it("暫用打平 without a known cost, or when the target read fails: price and ROAS only, never a made-up cost", async () => {
    vi.mocked(getTarget).mockResolvedValue(target(knownCap(BE), null));
    const { unmount } = render(<MemoryRouter><CapBlock brandId="brd_1" campaign={campaign(knownCap(BE))} onCampaignChange={vi.fn()} /></MemoryRouter>);
    await waitFor(() => expect(getTarget).toHaveBeenCalled());
    expect(screen.getByText(textIs("打平線 520 TWD・售價 1,580 TWD・ROAS 3.04x 花到上限時"))).toBeTruthy();
    expect(screen.queryByText(/成本含運/)).toBeNull();
    unmount();
    vi.mocked(getTarget).mockRejectedValue(new Error("逾時"));
    renderBlock(campaign(knownCap(BE)));
    await waitFor(() => expect(getTarget).toHaveBeenCalledTimes(2));
    expect(screen.getByText(textIs("打平線 520 TWD・售價 1,580 TWD・ROAS 3.04x 花到上限時"))).toBeTruthy();
  });

  it("an own cap never reads the target for the 打平線 line", async () => {
    renderBlock(campaign(knownCap(OWN)));
    expect(await screen.findByText("450 TWD")).toBeTruthy();
    expect(getTarget).not.toHaveBeenCalled();
  });

  it("暫用打平: 設定自己的上限 opens the input with a 用打平 fill", async () => {
    const user = userEvent.setup();
    renderBlock(campaign(knownCap(BE)));
    await user.click(await screen.findByRole("button", { name: "設定自己的上限" }));
    await user.click(screen.getByRole("button", { name: "用打平 520 TWD" }));
    expect((screen.getByLabelText("每賣一筆最多花多少（上限）") as HTMLInputElement).value).toBe("520");
    expect(screen.getByText(textIs("比打平 520 TWD 高 0・ROAS 3.04x 花到上限時"))).toBeTruthy();
  });

  it("no cap and no product cost: the input is open, 沒有商品成本 links to the product's 賣法與價格 step, the ruler is empty", async () => {
    renderBlock(campaign(NONE, { status: "draft" }));
    expect(await screen.findByText("填一個整數金額")).toBeTruthy();
    expect(screen.getByText("沒有商品成本")).toBeTruthy();
    // F43-I16: the sell-way's knowledge product (not the sell-way row), onboarding step 4.
    expect(screen.getByRole("link", { name: "去填商品成本" }).getAttribute("href")).toBe("/brands/brd_1/products/kp_1/onboarding?step=4");
    expect(screen.queryByRole("button", { name: /用打平/ })).toBeNull();
    expect(screen.getByRole("img", { name: "沒設上限，先不分等級" })).toBeTruthy();
    expect(getTriage).not.toHaveBeenCalled();
  });

  it("去填商品成本 without a knowledge product (null, or an older payload without the field) opens the products page", async () => {
    for (const c of [cap({ price: 1280, missing: ["product_cost"], knowledge_product_id: null }), cap({ price: 1280, missing: ["product_cost"], knowledge_product_id: undefined })]) {
      const view = render(<MemoryRouter><CapBlock brandId="brd_1" campaign={campaign(c, { status: "draft" })} onCampaignChange={vi.fn()} /></MemoryRouter>);
      expect((await screen.findByRole("link", { name: "去填商品成本" })).getAttribute("href")).toBe("/brands/brd_1/products");
      view.unmount();
    }
  });

  it("409 target_conflict: says so and offers a re-read, never a silent overwrite", async () => {
    const user = userEvent.setup();
    vi.mocked(putTarget).mockRejectedValue(new ApiResponseError("目標設定已被更新", 409, {}, { code: "target_conflict" }));
    vi.mocked(getCampaign).mockResolvedValue(campaign(OWN));
    const { onCampaignChange } = renderBlock(campaign(NONE));
    await user.type(await screen.findByLabelText("每賣一筆最多花多少（上限）"), "300");
    await user.click(screen.getByRole("button", { name: "儲存上限" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("上限剛被更新");
    expect(onCampaignChange).not.toHaveBeenCalled();
    await user.click(within(alert).getByRole("button", { name: "重新讀取" }));
    expect(getCampaign).toHaveBeenCalledWith("brd_1", "cmp_1");
    expect(onCampaignChange).toHaveBeenCalled();
  });

  it("the mid ruler places the campaign's graded ads from triage", async () => {
    vi.mocked(getTriage).mockResolvedValue({
      window_days: 14, closed: { groups: [], total: 0, items: [], truncated: false },
      items: [item("a1", "on_target", 3600, 20), item("a2", "over", 6200, 10), item("a3", "wasted", 1600, 0)].map((row) => ({...row, current: {...row.current, currency: "TWD"}, cap_comparison: {basis: "own", currency: "TWD", reason: null, message: null}})),
    });
    renderBlock(campaign(knownCap(OWN)));
    expect(await screen.findByRole("button", { name: "廣告 a1｜每筆 180 TWD｜划算" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "廣告 a3｜花 1,600 TWD・0 筆購買｜沒賣出" })).toBeTruthy();
  });

  it("a failed triage read leaves the cap usable and offers a retry", async () => {
    vi.mocked(getTriage).mockRejectedValue(new Error("逾時"));
    renderBlock(campaign(OWN));
    expect((await screen.findByRole("alert")).textContent).toContain("廣告讀取失敗：逾時");
    expect(screen.getByRole("button", { name: "修改" })).toBeTruthy();
  });

  it("no product: the fold picks one and sends only the product (a derived result kind is never re-sent)", async () => {
    const user = userEvent.setup();
    vi.mocked(getTarget).mockResolvedValue({
      ...cap({ missing: ["product"], product_id: null }), campaign_id: "cmp_1", product_ids: [],
      result_kinds: [{ kind: "purchase", label: "購買" }, { kind: "lead", label: "名單" }], cost: null,
    });
    vi.mocked(fetchProductList).mockResolvedValue([
      { id: "prd_1", name: "晨光隨行杯", status: "active", kind: "knowledge", fact_count: 0, pending_fact_count: 0, economics_status: "none" },
      { id: "prd_9", name: "晨光隨行杯 500ml 通勤款", status: "active", kind: "sell_way", fact_count: 0, pending_fact_count: 0, economics_status: "confirmed" },
    ]);
    vi.mocked(putTarget).mockResolvedValue({} as CampaignTarget);
    vi.mocked(getCampaign).mockResolvedValue(campaign(BE));
    renderBlock(campaign(cap({ missing: ["product"], product_id: null }), { status: "draft" }));
    await user.click(await screen.findByRole("button", { name: "選商品與成果（算打平要用）" }));
    expect((await screen.findByRole("button", { name: "購買" })).getAttribute("aria-pressed")).toBe("true");
    // F50 Contract R: only sell-ways are offered (money lives there); the knowledge product is not.
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["請選擇商品", "晨光隨行杯 500ml 通勤款"]);
    await user.selectOptions(screen.getByRole("combobox"), "prd_9");
    await user.click(screen.getByRole("button", { name: "儲存" }));
    expect(putTarget).toHaveBeenCalledWith("brd_1", "cmp_1", { expected_revision: 4, product_id: "prd_9" });
  });
});

function textIs(wanted: string) {
  const plain = (el: Element) => {const copy = el.cloneNode(true) as Element; copy.querySelectorAll("button,[role=tooltip]").forEach(n => n.remove()); return (copy.textContent ?? "").replace(/\s+/g, "");};
  return (_: string, el: Element | null) => !!el && plain(el) === wanted.replace(/\s+/g, "") && ![...el.children].some(c => plain(c) === wanted.replace(/\s+/g, ""));
}
