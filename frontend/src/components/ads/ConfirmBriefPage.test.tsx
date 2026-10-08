import { CapBlock } from "./strategy/CapBlock";
vi.mock("@/lib/figures", async (actual) => ({ ...await actual<typeof import("@/lib/figures")>(), useFigureBases: () => ({roas_at_cap: {label: "花到上限時", formula: "售價 ÷ 每筆上限", unit: "ratio"}, roas_all_spend: {label: "保守", formula: "營收 ÷ 全部花費", unit: "ratio"}, roas_tracked_spend: {label: "樂觀", formula: "營收 ÷ 有追到營收的那部分花費", unit: "ratio"}}) }));
/** ConfirmBriefPage (F30-I05): wizard v10 step 2 「系統這樣理解」 — six fields, guessed ones marked, in-place edits
 * that PATCH one field, independent read failures, and 產生策略 as the only model call.
 * F36-I04: the optional seventh chip 「每賣一筆最多花」 — empty by default with break-even as hint only, saved through
 * `putTarget {basis:"own"}`, the campaign re-read afterwards. */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { CampaignDetail } from "@/lib/adsApi";
import type { CampaignFieldSources } from "@/lib/adsCampaignTypes";
import { generateStrategy, getCampaign, patchCampaign } from "@/lib/adsApi";
import { fetchChannels } from "@/lib/adsLaunchApi";
import { putTarget, type CapView } from "@/lib/adsTriageApi";
import { getWizardOptions, type WizardOptions } from "@/lib/adsWizardApi";
import { ConfirmBriefPage } from "./ConfirmBriefPage";

vi.mock("@/lib/adsApi", async (original) => ({ ...await original<object>(), getCampaign: vi.fn(), patchCampaign: vi.fn(), generateStrategy: vi.fn() }));
vi.mock("@/lib/adsLaunchApi", async (original) => ({ ...await original<object>(), fetchChannels: vi.fn() }));
vi.mock("@/lib/adsTriageApi", async (original) => ({ ...await original<object>(), putTarget: vi.fn() }));
vi.mock("@/lib/adsWizardApi", () => ({ getWizardOptions: vi.fn() }));

const LONG = "Beast Gummy咖啡因機能軟糖・終極組合包(T-shirt+12盒)";
const GROUPS = [{ id: "grp_1", who: "加班提神的上班族" }, { id: "grp_2", who: "考前衝刺的學生" }];
const options: WizardOptions = {
  products: [
    { id: "prd_1", name: LONG, display_name: LONG, kind: "bundle", knowledge_product_id: "kp_1", knowledge_product_name: "咖啡因機能軟糖",
      price: 3000, currency: "TWD", thumbnail_url: null, has_cost: false, break_even: null, cap_per_sale: null, derived_fields: [], offer_labels: ["組合價"],
      customer_groups: GROUPS, landing_url: "https://beastgummy.tw/shop",
      previous: { campaign_id: "cmp_0", campaign_name: "組合包・09/19～10/01", platform: "meta", cap: 450, budget: 30000, spend: 9781 },
      learned: { campaigns: [{ id: "cmp_0", name: "組合包・09/19～10/01" }], keep: 2, replace: 1 } },
    { id: "prd_2", name: "Beast Gummy咖啡因機能軟糖・試用包", display_name: "試用包", kind: "single", knowledge_product_id: "kp_1", knowledge_product_name: "咖啡因機能軟糖",
      price: 100, currency: "TWD", thumbnail_url: null, has_cost: true, break_even: 40, cap_per_sale: 40, derived_fields: [], offer_labels: [], customer_groups: [], landing_url: null,
      previous: null, learned: null },
  ],
  default_platform: "meta",
  objectives: [
    { key: "購買", label: "購買", description: "看每賣一筆花多少", available: true, platforms: {} },
    { key: "名單", label: "名單", description: "看每筆名單成本", available: true, platforms: {} },
    { key: "互動", label: "互動", description: "看每次互動成本", available: false, platforms: {} },
  ],
  default_objective: "購買",
};

function sources(overrides: Partial<CampaignFieldSources> = {}): CampaignFieldSources {
  return { product: "user", objective: "user", platform: "user", budget: "user", dates: "user", audience: "system", ...overrides };
}
function campaign(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    id: "cmp_1", name: "測試 Campaign", goal_text: "推商品", objective: "購買",
    cap: { value: null, basis: null, own_value: null, break_even: null, price: null, product_id: null, result_kind: "purchase", result_label: "購買", missing: ["product"], revision: 0 },
    start_date: "2026-10-01", end_date: "2026-10-31", status: "draft", budget_planned: null, budget_scenario: null, budget_basis_json: {}, budget_total: null,
    context_json: { product_ids: ["prd_1"], audience_hint: "25–40 歲上班族", field_sources: sources() },
    constraints_json: { platform: "meta", budget: 30000 },
    verdict: null, verdict_json: {}, closed_at: null, created_by: null, created_at: "2026-01-01T00:00:00Z", groups: [], actions: [],
    outcome: { spend: null, purchases: null, revenue: null }, asset_readiness: { ready_count: 0, total: 0 },
    external_id: null, external_name: null, external_status: null, local_state: "unbound", bound_at: null,
    ...overrides,
  };
}
const field = (key: string) => document.querySelector(`[data-field="${key}"]`) as HTMLElement;
/** The prototype's numbers: a product with economics (售價 999, 打平 559), the cap not yet stated. */
function capView(overrides: Partial<CapView> = {}): CapView {
  return {
    value: 559, basis: "break_even", own_value: null, break_even: 559, price: 999, product_id: "prd_2",
    result_kind: "purchase", result_label: "購買", missing: [], revision: 3,
    cap_unit: {basis: "break_even", currency: "TWD", source: "product_economics", unit_basis: "confirmed_product_economics"},
    break_even_unit: {basis: "break_even", currency: "TWD", source: "product_economics", unit_basis: "confirmed_product_economics"},
    price_unit: {basis: "break_even", currency: "TWD", source: "product_economics", unit_basis: "confirmed_product_economics"},
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/brands/brd_1/ads/new/cmp_1"]}>
      <Routes>
        <Route path="/brands/:b/ads/new/:c" element={<ConfirmBriefPage brandId="brd_1" campaignId="cmp_1" />} />
        <Route path="/brands/:b/ads/campaigns/:c" element={<p>策略頁</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getCampaign).mockResolvedValue(campaign());
  vi.mocked(getWizardOptions).mockResolvedValue(options);
  vi.mocked(fetchChannels).mockResolvedValue([{ key: "meta", label: "Meta", connected: true, state_text: "" }, { key: "google_ads", label: "Google Ads", connected: false, state_text: "" }]);
});

describe("ConfirmBriefPage after adoption (F48-I07 lead note)", () => {
  it("a campaign that is no longer a draft goes to its strategy tab — the locked brief is never shown or patched", async () => {
    vi.mocked(getCampaign).mockResolvedValue(campaign({ status: "ready" }));
    render(
      <MemoryRouter initialEntries={["/brands/brd_1/ads/new/cmp_1"]}>
        <Routes>
          <Route path="/brands/:b/ads/new/:c" element={<ConfirmBriefPage brandId="brd_1" campaignId="cmp_1" />} />
          <Route path="/brands/:b/ads/campaigns/:c" element={<SearchProbe />} />
        </Routes>
      </MemoryRouter>,
    );
    expect((await screen.findByTestId("landed")).textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1?tab=strategy");
    expect(screen.queryByText("系統這樣理解")).toBeNull();
    expect(patchCampaign).not.toHaveBeenCalled();
  });
});

function SearchProbe() {
  const location = useLocation();
  return <p data-testid="landed">{location.pathname + location.search}</p>;
}

describe("ConfirmBriefPage (F30-I05)", () => {
  it("shows the six understood fields and the optional cap chip with their values; 主打／素材 are not shown before the strategy", async () => {
    renderPage();
    expect(await screen.findByText(LONG)).toBeTruthy();
    for (const label of ["商品", "結果", "期間", "預算上限", "平台", "受眾", "每賣一筆最多花"]) expect(screen.getByText(label)).toBeTruthy();
    expect(within(field("objective")).getByText("購買")).toBeTruthy();
    expect(within(field("dates")).getByText("10/01 – 10/31")).toBeTruthy();
    expect(within(field("budget")).getByText("30,000 TWD")).toBeTruthy();
    expect(await within(field("platform")).findByText("Meta")).toBeTruthy();
    expect(within(field("audience")).getByText("25–40 歲上班族")).toBeTruthy();
    expect(screen.queryByText("主打")).toBeNull();
    expect(screen.queryByText("素材")).toBeNull();
  });

  it("marks only fields the system guessed with 「猜的，請確認」 and counts them in the bar", async () => {
    vi.mocked(getCampaign).mockResolvedValue(campaign({ context_json: { product_ids: ["prd_1"], audience_hint: null, field_sources: sources({ dates: "system" }) } }));
    renderPage();
    await screen.findByText(LONG);
    expect(within(field("dates")).getByText("猜的，請確認")).toBeTruthy();
    expect(within(field("audience")).getByText("猜的，請確認")).toBeTruthy();
    expect(within(field("audience")).getByText("未設定")).toBeTruthy();
    expect(within(field("product")).queryByText("猜的，請確認")).toBeNull();
    expect(screen.getByText("有 2 項是猜的")).toBeTruthy();
  });

  it("F50 (R6 B1): a field the model read from the sentence (`parsed`) renders exactly like `system` — dashed, 「猜的，請確認」", async () => {
    vi.mocked(getCampaign).mockResolvedValue(campaign({
      context_json: { product_ids: ["prd_1"], audience_hint: "a", field_sources: sources({ budget: "parsed", platform: "parsed", audience: "user" }) },
    }));
    renderPage();
    await screen.findByText(LONG);
    for (const key of ["budget", "platform"]) {
      expect(within(field(key)).getByText("猜的，請確認")).toBeTruthy();
      expect(field(key).className).toContain("border-dashed");
      expect(field(key).querySelector("[data-slot=source-tag]")).toBeNull();
    }
    expect(field("product").className).not.toContain("border-dashed");
    // The sentence path's platform default (filled by the backend) is printed like any other value.
    expect(within(field("platform")).getByText("Meta")).toBeTruthy();
    expect(screen.getByText("有 2 項是猜的")).toBeTruthy();
  });

  it("F50: a cap the model read from the sentence (`parsed`) is a guess too, counted in the bar", async () => {
    vi.mocked(getCampaign).mockResolvedValue(campaign({
      cap: capView({ value: 450, basis: "own", own_value: 450 }),
      context_json: { product_ids: ["prd_1"], audience_hint: "a", field_sources: { ...sources({ audience: "user" }), cap: "parsed" } },
    }));
    renderPage();
    await screen.findByText(LONG);
    expect(within(field("cap")).getByText("450 TWD")).toBeTruthy();
    expect(within(field("cap")).getByText("猜的，請確認")).toBeTruthy();
    expect(field("cap").className).toContain("border-dashed");
    expect(screen.getByText("有 1 項是猜的")).toBeTruthy();
  });

  it("F46-I08: a value the create filled by rule shows its tag instead of 「猜的，請確認」; system keeps the guess", async () => {
    vi.mocked(getCampaign).mockResolvedValue(campaign({
      context_json: { product_ids: ["prd_1"], audience_hint: null, field_sources: sources({ platform: "copied", budget: "copied", dates: "system" }) },
    }));
    const view = renderPage();
    await screen.findByText(LONG);
    const tag = (key: string) => field(key).querySelector("[data-slot=source-tag]");
    expect(tag("platform")?.textContent).toBe("沿用上一期");
    expect(tag("platform")?.getAttribute("title")).toBe("上一期：組合包・09/19～10/01");
    expect(tag("budget")?.textContent).toBe("沿用上一期");
    expect(within(field("platform")).queryByText("猜的，請確認")).toBeNull();
    expect(within(field("dates")).getByText("猜的，請確認")).toBeTruthy();
    expect(tag("dates")).toBeNull();
    expect(tag("product")).toBeNull(); // the user's own pick carries no tag
    expect(screen.getByText("有 2 項是猜的")).toBeTruthy(); // dates + audience
    view.unmount();
    vi.mocked(getCampaign).mockResolvedValue(campaign({ context_json: { product_ids: ["prd_2"], audience_hint: "a", field_sources: sources({ platform: "brand" }) } }));
    renderPage();
    await screen.findByText("Beast Gummy咖啡因機能軟糖・試用包");
    expect(tag("platform")?.textContent).toBe("已接上的帳戶");
  });

  it("prints the cap as a number or unset, never NaN", async () => {
    vi.mocked(getCampaign).mockResolvedValue(campaign({ constraints_json: { budget: "NT$ 30,000" } }));
    const view = renderPage();
    await screen.findByText("預算上限");
    expect(within(field("budget")).getByText("NT$ 30,000")).toBeTruthy();
    view.unmount();
    vi.mocked(getCampaign).mockResolvedValue(campaign({ constraints_json: {} }));
    renderPage();
    await screen.findByText("預算上限");
    expect(within(field("budget")).getByText("未設定")).toBeTruthy();
    expect(screen.queryByText(/NaN/)).toBeNull();
  });

  it("edits the objective in place from the available catalog and closes only after the server confirmed", async () => {
    let resolve!: (c: CampaignDetail) => void;
    vi.mocked(patchCampaign).mockReturnValue(new Promise((r) => { resolve = r; }));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    await user.click(screen.getByRole("button", { name: "改結果" }));
    const select = within(field("objective")).getByRole("combobox");
    expect(within(select).queryByRole("option", { name: "互動" })).toBeNull();
    await user.selectOptions(select, "名單");
    await user.click(within(field("objective")).getByRole("button", { name: "完成" }));
    expect(patchCampaign).toHaveBeenCalledWith("brd_1", "cmp_1", { objective: "名單" });
    expect(within(field("objective")).getByRole("combobox")).toBeTruthy();
    resolve(campaign({ objective: "名單" }));
    expect(await within(field("objective")).findByText("名單")).toBeTruthy();
    expect(within(field("objective")).queryByRole("combobox")).toBeNull();
  });

  it("keeps the editor open with the error when a save fails", async () => {
    vi.mocked(patchCampaign).mockRejectedValue(new Error("這個目標尚未開放，請選其他目標。"));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    await user.click(screen.getByRole("button", { name: "改結果" }));
    await user.selectOptions(within(field("objective")).getByRole("combobox"), "名單");
    await user.click(within(field("objective")).getByRole("button", { name: "完成" }));
    expect(await screen.findByText("這個目標尚未開放，請選其他目標。")).toBeTruthy();
    expect(within(field("objective")).getByRole("combobox")).toBeTruthy();
  });

  it("an old campaign without customer groups still reads its free-text audience", async () => {
    renderPage();
    await screen.findByText(LONG);
    expect(within(field("audience")).getByText("25–40 歲上班族")).toBeTruthy();
  });

  it("the audience row names the picked customer groups (F43-I15) and edits them with the same select; an owned unchanged field just closes", async () => {
    const withGroups = (ids: string[], source: "sell_way" | "user") => campaign({ context_json: { product_ids: ["prd_1"], customer_group_ids: ids, field_sources: sources({ audience: source }) } });
    vi.mocked(getCampaign).mockResolvedValue(withGroups(["grp_1", "grp_2"], "sell_way"));
    vi.mocked(patchCampaign).mockResolvedValueOnce(withGroups(["grp_2"], "user")).mockResolvedValueOnce(withGroups(["grp_1", "grp_2"], "sell_way"));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    expect(await within(field("audience")).findByText("2 群都投（加班提神的上班族、考前衝刺的學生）")).toBeTruthy();
    expect(within(field("audience")).queryByText("猜的，請確認")).toBeNull();
    expect(screen.queryByText("25–40 歲上班族")).toBeNull();
    await user.click(screen.getByRole("button", { name: "改受眾" }));
    const select = within(field("audience")).getByRole("combobox");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["2 群都投", "只投：加班提神的上班族", "只投：考前衝刺的學生"]);
    await user.selectOptions(select, "grp_2");
    await user.click(within(field("audience")).getByRole("button", { name: "完成" }));
    expect(patchCampaign).toHaveBeenCalledWith("brd_1", "cmp_1", { customer_group_ids: ["grp_2"] });
    expect(await within(field("audience")).findByText("考前衝刺的學生")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "改受眾" }));
    await user.selectOptions(within(field("audience")).getByRole("combobox"), "all");
    await user.click(within(field("audience")).getByRole("button", { name: "完成" }));
    expect(patchCampaign).toHaveBeenLastCalledWith("brd_1", "cmp_1", { customer_group_ids: [] });
    expect(await within(field("audience")).findByText(/2 群都投/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "改期間" }));
    await user.click(within(field("dates")).getByRole("button", { name: "完成" }));
    expect(patchCampaign).toHaveBeenCalledTimes(2);
    expect(within(field("dates")).getByText("10/01 – 10/31")).toBeTruthy();
  });

  it("F47-I06: 改期間 完成 greyed out says which field is wrong", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    await user.click(screen.getByRole("button", { name: "改期間" }));
    const end = within(field("dates")).getByLabelText("結束日期");
    await user.clear(end);
    await user.type(end, "2026-09-01");
    const done = within(field("dates")).getByRole("button", { name: "完成" });
    expect((done as HTMLButtonElement).disabled).toBe(true);
    expect(within(field("dates")).getByText("結束日不能早於開始日")).toBeTruthy();
    await user.clear(end);
    expect(within(field("dates")).getByText("結束日期還沒填")).toBeTruthy();
  });

  it("a sell-way with fewer than two customer groups has no audience choice", async () => {
    vi.mocked(getCampaign).mockResolvedValue(campaign({ context_json: { product_ids: ["prd_2"], customer_group_ids: [], field_sources: sources({ audience: "system" }) } }));
    renderPage();
    await screen.findByText("Beast Gummy咖啡因機能軟糖・試用包");
    expect(screen.queryByRole("button", { name: "改受眾" })).toBeNull();
    expect(within(field("audience")).getByText("未設定")).toBeTruthy();
  });

  it("saves a new cap as a number in the campaign's constraints", async () => {
    vi.mocked(patchCampaign).mockResolvedValue(campaign({ constraints_json: { platform: "meta", budget: 45000 } }));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    await user.click(screen.getByRole("button", { name: "改預算上限" }));
    const input = within(field("budget")).getByLabelText("預算上限");
    await user.clear(input);
    await user.type(input, "45000");
    await user.click(within(field("budget")).getByRole("button", { name: "完成" }));
    expect(patchCampaign).toHaveBeenCalledWith("brd_1", "cmp_1", { constraints_json: { platform: "meta", budget: 45000 } });
    expect(await within(field("budget")).findByText("45,000 TWD")).toBeTruthy();
  });

  it("a failed channel list shows ReadFailed with 重試; the platform is not editable, the rest still is", async () => {
    vi.mocked(fetchChannels).mockRejectedValueOnce(new Error("讀取通路清單失敗。"));
    const user = userEvent.setup();
    renderPage();
    expect(await screen.findByText(/平台清單讀不到/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "改平台" })).toBeNull();
    expect(within(field("platform")).getByText("meta")).toBeTruthy();
    expect(screen.getByRole("button", { name: "改結果" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByRole("button", { name: "改平台" })).toBeTruthy();
    expect(screen.queryByText(/平台清單讀不到/)).toBeNull();
  });

  it("a failed campaign read shows ReadFailed, not empty fields", async () => {
    vi.mocked(getCampaign).mockRejectedValueOnce(new Error("讀取 Campaign 失敗。"));
    renderPage();
    expect(await screen.findByText(/這個活動讀不到/)).toBeTruthy();
    expect(screen.queryByText("未設定")).toBeNull();
  });

  it("產生策略 calls the strategy once (not on load) and lands on the strategy tab", async () => {
    vi.mocked(generateStrategy).mockResolvedValue(campaign());
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    expect(generateStrategy).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "產生策略 →" }));
    expect(await screen.findByText("策略頁")).toBeTruthy();
    expect(generateStrategy).toHaveBeenCalledTimes(1);
    expect(generateStrategy).toHaveBeenCalledWith("brd_1", "cmp_1");
  });

  it("上一步 and the done step go back to step 1 of this campaign, and the asset route stays under 進階", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    expect(screen.getByRole("link", { name: "← 上一步" }).getAttribute("href")).toBe("/brands/brd_1/ads/new?created=cmp_1");
    expect(screen.getByRole("link", { name: "回到「建立活動」" }).getAttribute("href")).toBe("/brands/brd_1/ads/new?created=cmp_1");
    await user.click(screen.getByRole("button", { name: "進階" }));
    expect(screen.getByRole("link", { name: "先處理自帶素材與手動交接" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1?tab=assets");
  });
});

describe("ConfirmBriefPage cap chip 「每賣一筆最多花」 (F36-I04)", () => {
  it("F46-I08／F47-I06: the cap's tag is its stored source — 沿用上一期／打平線 from the create, none once the user changed it", async () => {
    const capSources = (cap: "copied" | "break_even" | "user") => ({ product_ids: ["prd_1"], audience_hint: "a", field_sources: { ...sources(), cap } });
    vi.mocked(getCampaign).mockResolvedValue(campaign({ cap: capView({ value: 450, basis: "own", own_value: 450 }), context_json: capSources("copied") }));
    const first = renderPage();
    await screen.findByText(LONG);
    expect(within(field("cap")).getByText("450 TWD")).toBeTruthy();
    expect(field("cap").querySelector("[data-slot=source-tag]")?.textContent).toBe("沿用上一期");
    expect(within(field("cap")).queryByText("猜的，請確認")).toBeNull();
    expect(screen.queryByText(/上限沒填會先用打平/)).toBeNull();
    first.unmount();
    vi.mocked(getCampaign).mockResolvedValue(campaign({ cap: capView({ value: 559, basis: "own", own_value: 559 }), context_json: capSources("break_even") }));
    const second = renderPage();
    await screen.findByText(LONG);
    expect(field("cap").querySelector("[data-slot=source-tag]")?.textContent).toBe("打平線");
    second.unmount();
    // Changed afterwards through the target writer: the writer stores `field_sources.cap = "user"`, so no tag.
    vi.mocked(getCampaign).mockResolvedValue(campaign({ cap: capView({ value: 600, basis: "own", own_value: 600 }), context_json: capSources("user") }));
    renderPage();
    await screen.findByText(LONG);
    expect(within(field("cap")).getByText("600 TWD")).toBeTruthy();
    expect(field("cap").querySelector("[data-slot=source-tag]")).toBeNull();
  });

  it("is empty by default with break-even as a hint only, not marked as a guess; the bar says the cap falls back to break-even", async () => {
    vi.mocked(getCampaign).mockResolvedValue(campaign({ cap: capView() }));
    renderPage();
    await screen.findByText(LONG);
    const chip = field("cap");
    expect(within(chip).getByText("還沒填（選填）")).toBeTruthy();
    expect(within(chip).getByText("先不填就用打平 559 TWD：售價 999 TWD 扣成本、運費後的一筆利潤")).toBeTruthy();
    expect(within(chip).queryByText("猜的，請確認")).toBeNull();
    expect(chip.className).toContain("border-dashed");
    expect(chip.className).not.toContain("border-grade-watch");
    expect(screen.getByText("有 1 項是猜的・上限沒填會先用打平")).toBeTruthy();
    expect(screen.getByRole("button", { name: "產生策略 →" }).hasAttribute("disabled")).toBe(false);
  });

  it("完成 saves through putTarget with basis own; the campaign is re-read and the chip shows the saved value", async () => {
    vi.mocked(getCampaign)
      .mockResolvedValueOnce(campaign({ cap: capView() }))
      .mockResolvedValueOnce(campaign({ cap: capView({ value: 600, basis: "own", own_value: 600, revision: 4 }) }));
    vi.mocked(putTarget).mockResolvedValue({} as never);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    await user.click(screen.getByRole("button", { name: "改每賣一筆最多花" }));
    const chip = field("cap");
    expect(chip.className).toContain("md:col-span-2");
    expect(within(chip).getByText("填一個整數金額；留空＝先用打平 559 TWD")).toBeTruthy();
    await user.type(within(chip).getByLabelText("每賣一筆最多花"), "600");
    expect(within(chip).getByText(textIs("比打平 559 TWD 高 41・ROAS 1.67x 花到上限時"))).toBeTruthy();
    await user.click(within(chip).getByRole("button", { name: "完成" }));
    expect(putTarget).toHaveBeenCalledWith("brd_1", "cmp_1", { basis: "own", value: 600, expected_revision: 3 });
    expect(await within(field("cap")).findByText("600 TWD")).toBeTruthy();
    expect(within(field("cap")).getByText(textIs("比打平 559 TWD 高 41・ROAS 1.67x 花到上限時"))).toBeTruthy();
    expect(getCampaign).toHaveBeenCalledTimes(2);
    expect(screen.getByText("有 1 項是猜的")).toBeTruthy();
    expect(screen.queryByText(/上限沒填會先用打平/)).toBeNull();
  });

  it("「用打平」 fills the input with break-even; Enter saves it; a lower value reads 低", async () => {
    vi.mocked(getCampaign)
      .mockResolvedValueOnce(campaign({ cap: capView() }))
      .mockResolvedValueOnce(campaign({ cap: capView({ value: 559, basis: "own", own_value: 559, revision: 4 }) }));
    vi.mocked(putTarget).mockResolvedValue({} as never);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    await user.click(screen.getByRole("button", { name: "改每賣一筆最多花" }));
    const input = within(field("cap")).getByLabelText("每賣一筆最多花") as HTMLInputElement;
    await user.type(input, "500");
    expect(within(field("cap")).getByText(textIs("比打平 559 TWD 低 59・ROAS 2.00x 花到上限時"))).toBeTruthy();
    await user.click(within(field("cap")).getByRole("button", { name: "用打平 559 TWD" }));
    expect(input.value).toBe("559");
    await user.type(input, "{Enter}");
    expect(putTarget).toHaveBeenCalledWith("brd_1", "cmp_1", { basis: "own", value: 559, expected_revision: 3 });
    expect(await within(field("cap")).findByText("559 TWD")).toBeTruthy();
  });

  it("an invalid amount disables 完成 with the message; Escape cancels without saving; an empty 完成 keeps the old value", async () => {
    vi.mocked(getCampaign).mockResolvedValue(campaign({ cap: capView({ value: 600, basis: "own", own_value: 600 }) }));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    await user.click(screen.getByRole("button", { name: "改每賣一筆最多花" }));
    const input = within(field("cap")).getByLabelText("每賣一筆最多花") as HTMLInputElement;
    expect(input.value).toBe("600");
    await user.clear(input);
    await user.type(input, "0");
    expect(within(field("cap")).getByText("請填大於 0 的整數金額")).toBeTruthy();
    expect(within(field("cap")).getByRole("button", { name: "完成" }).hasAttribute("disabled")).toBe(true);
    await user.clear(input);
    await user.click(within(field("cap")).getByRole("button", { name: "完成" }));
    expect(putTarget).not.toHaveBeenCalled();
    expect(within(field("cap")).getByText("600 TWD")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "改每賣一筆最多花" }));
    await user.type(within(field("cap")).getByLabelText("每賣一筆最多花"), "{Escape}");
    expect(putTarget).not.toHaveBeenCalled();
    expect(within(field("cap")).queryByRole("textbox")).toBeNull();
    await user.click(screen.getByRole("button", { name: "改每賣一筆最多花" }));
    await user.click(within(field("cap")).getByRole("button", { name: "取消" }));
    expect(within(field("cap")).queryByRole("textbox")).toBeNull();
  });

  it("without a break-even there is no hint, no 用打平 button and no bar suffix; the ROAS part still shows with a price", async () => {
    vi.mocked(getCampaign).mockResolvedValue(campaign({ cap: capView({ value: null, basis: null, break_even: null, price: 999, missing: ["product_cost"] }) }));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    expect(within(field("cap")).getByText("還沒填（選填）")).toBeTruthy();
    expect(within(field("cap")).queryByText(/先不填就用打平/)).toBeNull();
    expect(screen.getByText("有 1 項是猜的")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "改每賣一筆最多花" }));
    expect(within(field("cap")).queryByRole("button", { name: /用打平/ })).toBeNull();
    expect(within(field("cap")).getByText("填一個整數金額；留空保留目前設定")).toBeTruthy();
    await user.type(within(field("cap")).getByLabelText("每賣一筆最多花"), "500");
    expect(within(field("cap")).getByText(textIs("ROAS 2.00x 花到上限時"))).toBeTruthy();
  });

  it("keeps the editor open with the error when the target save fails", async () => {
    vi.mocked(getCampaign).mockResolvedValue(campaign({ cap: capView() }));
    vi.mocked(putTarget).mockRejectedValue(new Error("這個活動的上限剛被更新。"));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    await user.click(screen.getByRole("button", { name: "改每賣一筆最多花" }));
    await user.type(within(field("cap")).getByLabelText("每賣一筆最多花"), "600{Enter}");
    expect(await screen.findByText("這個活動的上限剛被更新。")).toBeTruthy();
    expect(within(field("cap")).getByRole("textbox")).toBeTruthy();
    expect(getCampaign).toHaveBeenCalledTimes(1);
  });
});

/** F40-I12 (drill-7 #10): the campaign-level landing URL sits in the main block, tagged with its source (F43-I15), and
 * edits go through the campaign PATCH's `landing_url` (F40-I04 2b); the 追蹤 tab keeps its per-group values. */
describe("ConfirmBriefPage landing URL (F40-I12)", () => {
  const URL = "https://beastgummy.tw/shop";
  const withUrl = (landing_url: string | null) => campaign({ context_json: { product_ids: ["prd_1"], audience_hint: "上班族", landing_url, field_sources: sources({ landing_url: landing_url ? "copied" : "system" }) } });

  it("shows the URL with its tag in the main block, blank as 還沒填（選填）, never as a guess", async () => {
    vi.mocked(getCampaign).mockResolvedValue(withUrl(URL));
    const view = renderPage();
    await screen.findByText(LONG);
    expect(within(field("landing_url")).getByText("落地頁")).toBeTruthy();
    expect(within(field("landing_url")).getByText("照上一期")).toBeTruthy();
    expect(within(field("landing_url")).getByText(URL)).toBeTruthy();
    expect(within(field("landing_url")).queryByText("猜的，請確認")).toBeNull();
    expect(screen.getByText("有 1 項是猜的")).toBeTruthy(); // the audience only; the landing URL is never counted
    view.unmount();
    vi.mocked(getCampaign).mockResolvedValue(withUrl(null));
    renderPage();
    await screen.findByText(LONG);
    expect(within(field("landing_url")).getByText("還沒填（選填）")).toBeTruthy();
    expect(within(field("landing_url")).queryByText("猜的，請確認")).toBeNull();
    expect(within(field("landing_url")).queryByText("照上一期")).toBeNull();
  });

  it("names the sell-way's landing 「來自賣法」 and the user's own 「你填的」 (F43-I15)", async () => {
    const tagged = (source: "sell_way" | "user") => campaign({ context_json: { product_ids: ["prd_1"], landing_url: URL, field_sources: sources({ landing_url: source }) } });
    vi.mocked(getCampaign).mockResolvedValue(tagged("sell_way"));
    const view = renderPage();
    await screen.findByText(LONG);
    expect(within(field("landing_url")).getByText("來自賣法")).toBeTruthy();
    view.unmount();
    vi.mocked(getCampaign).mockResolvedValue(tagged("user"));
    renderPage();
    await screen.findByText(LONG);
    expect(within(field("landing_url")).getByText("你填的")).toBeTruthy();
  });

  it("an edit PATCHes landing_url and shows the saved value; blank clears with null; an unchanged value just closes", async () => {
    vi.mocked(getCampaign).mockResolvedValue(withUrl(URL));
    vi.mocked(patchCampaign).mockResolvedValue(withUrl("https://beastgummy.tw/new"));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    await user.click(screen.getByRole("button", { name: "改落地頁" }));
    const input = within(field("landing_url")).getByLabelText("落地頁");
    expect(input).toHaveProperty("value", URL);
    await user.clear(input);
    await user.type(input, "https://beastgummy.tw/new{Enter}");
    expect(patchCampaign).toHaveBeenCalledWith("brd_1", "cmp_1", { landing_url: "https://beastgummy.tw/new" });
    expect(await within(field("landing_url")).findByText("https://beastgummy.tw/new")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "改落地頁" }));
    await user.click(within(field("landing_url")).getByRole("button", { name: "完成" }));
    expect(patchCampaign).toHaveBeenCalledTimes(1);
    expect(within(field("landing_url")).getByText("https://beastgummy.tw/new")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "改落地頁" }));
    await user.clear(within(field("landing_url")).getByLabelText("落地頁"));
    await user.click(within(field("landing_url")).getByRole("button", { name: "完成" }));
    expect(patchCampaign).toHaveBeenLastCalledWith("brd_1", "cmp_1", { landing_url: null });
  });

  it("keeps the editor open with the server's message when the URL is refused", async () => {
    vi.mocked(getCampaign).mockResolvedValue(withUrl(URL));
    vi.mocked(patchCampaign).mockRejectedValue(new Error("落地頁請填完整的 http 或 https 網址，不可包含密碼。"));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText(LONG);
    await user.click(screen.getByRole("button", { name: "改落地頁" }));
    await user.type(within(field("landing_url")).getByLabelText("落地頁"), "x{Enter}");
    expect(await screen.findByText("落地頁請填完整的 http 或 https 網址，不可包含密碼。")).toBeTruthy();
    expect(within(field("landing_url")).getByLabelText("落地頁")).toBeTruthy();
    await user.click(within(field("landing_url")).getByRole("button", { name: "取消" }));
    expect(within(field("landing_url")).getByText(URL)).toBeTruthy();
  });
});

function textIs(wanted: string) {
  const plain = (el: Element) => {const copy = el.cloneNode(true) as Element; copy.querySelectorAll("button,[role=tooltip]").forEach(n => n.remove()); return (copy.textContent ?? "").replace(/\s+/g, "");};
  return (_: string, el: Element | null) => !!el && plain(el) === wanted.replace(/\s+/g, "") && ![...el.children].some(c => plain(c) === wanted.replace(/\s+/g, ""));
}


it("cap ROAS uses identical rounding on the brief and strategy, with independent help and edit controls", async () => {
  const c = campaign({cap: capView({value: 500, own_value: 500, basis: "own", price: 1002.5})});
  vi.mocked(getCampaign).mockResolvedValue(c);
  renderPage();
  await screen.findByText("2.01x");
  const help = within(field("cap")).getByRole("button", {name: /花到上限時怎麼算/});
  expect(help.parentElement?.closest("button")).toBeNull();
  await userEvent.click(help);
  expect(within(field("cap")).queryByLabelText("每賣一筆最多花")).toBeNull();
  render(<MemoryRouter><CapBlock brandId="brd_1" campaign={c} onCampaignChange={vi.fn()} /></MemoryRouter>);
  expect(screen.getAllByText("2.01x")).toHaveLength(2);
  expect(screen.getAllByText("花到上限時")).toHaveLength(2);
});

it.each([undefined, null, "USD"])("rejects foreign or unverified price/break-even units in brief previews: %s", async currency => {
  const c = campaign({cap: capView({value: 600, own_value: 600, basis: "own",
    price_unit: currency === undefined ? undefined : {basis: "break_even", currency},
    break_even_unit: currency === undefined ? undefined : {basis: "break_even", currency}})});
  vi.mocked(getCampaign).mockResolvedValue(c);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText(LONG);
  const capField = field("cap");
  expect(within(capField).queryByText(/ROAS|比打平/)).toBeNull();
  expect(within(capField).getByText(/幣別不同或尚未核實/)).toBeTruthy();
  await user.click(screen.getByRole("button", {name: "改每賣一筆最多花"}));
  const fill = within(capField).getByRole("button", {name: /用打平/});
  expect(fill.hasAttribute("disabled")).toBe(true);
  await user.click(fill);
  const input = within(capField).getByLabelText("每賣一筆最多花") as HTMLInputElement;
  expect(input.value).toBe("600");
  await user.clear(input);
  await user.type(input, "500");
  expect(within(capField).queryByText(/ROAS|比打平/)).toBeNull();
  await user.type(input, "{Escape}");
  expect(putTarget).not.toHaveBeenCalled();
  expect(within(capField).getByText("600 TWD")).toBeTruthy();
});

it.each([undefined, null, "USD"])("does not relabel an unchanged stored own cap as a new TWD input: %s", async currency => {
  const c = campaign({cap: capView({value: 600, own_value: 600, basis: "own",
    cap_unit: currency === undefined ? undefined : {basis: "own", currency}})});
  vi.mocked(getCampaign).mockResolvedValue(c);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText(LONG);
  expect(within(field("cap")).getByText(`600 ${currency ?? "幣別未知"}`)).toBeTruthy();
  expect(within(field("cap")).queryByText(/ROAS|比打平/)).toBeNull();
  await user.click(screen.getByRole("button", {name: "改每賣一筆最多花"}));
  const input = within(field("cap")).getByLabelText("每賣一筆最多花") as HTMLInputElement;
  expect(field("cap").querySelector('[data-slot="money-input"] span')?.textContent).toBe(currency ?? "幣別未知");
  expect(within(field("cap")).queryByText(/ROAS|比打平/)).toBeNull();
  await user.type(input, "{Enter}");
  expect(putTarget).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", {name: "改每賣一筆最多花"}));
  const same = within(field("cap")).getByLabelText("每賣一筆最多花") as HTMLInputElement;
  await user.clear(same);
  await user.type(same, "600");
  expect(field("cap").querySelector('[data-slot="money-input"] span')?.textContent).toBe(currency ?? "幣別未知");
  await user.click(within(field("cap")).getByRole("button", {name: "完成"}));
  expect(putTarget).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", {name: "改每賣一筆最多花"}));
  const edited = within(field("cap")).getByLabelText("每賣一筆最多花") as HTMLInputElement;
  await user.clear(edited);
  await user.type(edited, "500");
  expect(field("cap").querySelector('[data-slot="money-input"] span')?.textContent).toBe("TWD");
  expect(within(field("cap")).getByText(textIs("比打平 559 TWD 低 59・ROAS 2.00x 花到上限時"))).toBeTruthy();
  await user.clear(edited);
  await user.click(within(field("cap")).getByRole("button", {name: "完成"}));
  expect(putTarget).not.toHaveBeenCalled();
  expect(within(field("cap")).getByText(`600 ${currency ?? "幣別未知"}`)).toBeTruthy();
});

it.each([null, "USD"])("a failed new manual cap preserves the stored %s source until a successful server read", async currency => {
  const original = campaign({cap: capView({value: 600, own_value: 600, basis: "own",
    cap_unit: {basis: "own", currency}})});
  vi.mocked(getCampaign).mockResolvedValueOnce(original).mockResolvedValueOnce(campaign({
    cap: capView({value: 500, own_value: 500, basis: "own", revision: 4,
      cap_unit: {basis: "own", currency: "TWD", source: "user", unit_basis: "manual_ntd_input"}})}));
  vi.mocked(putTarget).mockRejectedValueOnce(new Error("上限儲存失敗")).mockResolvedValueOnce({} as never);
  const user = userEvent.setup();
  renderPage();
  await screen.findByText(LONG);
  await user.click(screen.getByRole("button", {name: "改每賣一筆最多花"}));
  const input = within(field("cap")).getByLabelText("每賣一筆最多花") as HTMLInputElement;
  await user.clear(input);
  await user.type(input, "500{Enter}");
  expect(await screen.findByText("上限儲存失敗")).toBeTruthy();
  expect(input.value).toBe("500");
  expect(field("cap").querySelector('[data-slot="money-input"] span')?.textContent).toBe("TWD");
  expect(getCampaign).toHaveBeenCalledTimes(1);
  expect(original.cap.cap_unit?.currency).toBe(currency);
  await user.click(within(field("cap")).getByRole("button", {name: "取消"}));
  expect(within(field("cap")).getByText(`600 ${currency ?? "幣別未知"}`)).toBeTruthy();
  await user.click(screen.getByRole("button", {name: "改每賣一筆最多花"}));
  const retry = within(field("cap")).getByLabelText("每賣一筆最多花");
  await user.clear(retry);
  await user.type(retry, "500{Enter}");
  expect(await within(field("cap")).findByText("500 TWD")).toBeTruthy();
  expect(putTarget).toHaveBeenLastCalledWith("brd_1", "cmp_1", {basis: "own", value: 500, expected_revision: 3});
  expect(getCampaign).toHaveBeenCalledTimes(2);
});

it("compares a known USD read in USD but refuses using its break-even as a manual TWD value", async () => {
  const c = campaign({cap: capView({value: 500, own_value: 500, basis: "own", price: 1002.5,
    cap_unit: {basis: "own", currency: "USD"}, break_even_unit: {basis: "break_even", currency: "USD"},
    price_unit: {basis: "break_even", currency: "USD"}})});
  vi.mocked(getCampaign).mockResolvedValue(c);
  renderPage();
  await screen.findByText("2.01x");
  expect(within(field("cap")).getByText("500 USD")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", {name: "改每賣一筆最多花"}));
  expect(within(field("cap")).getByRole("button", {name: "用打平 559 USD"}).hasAttribute("disabled")).toBe(true);
});

it.each([undefined, null, "USD"])("an unresolved break-even does not promise a blank-input fallback: %s", async currency => {
  vi.mocked(getCampaign).mockResolvedValue(campaign({cap: capView({
    break_even_unit: currency === undefined ? undefined : {basis: "break_even", currency}})}));
  renderPage();
  await screen.findByText(LONG);
  expect(within(field("cap")).queryByText(/先不填就用打平/)).toBeNull();
  expect(screen.queryByText(/上限沒填會先用打平/)).toBeNull();
  await userEvent.click(screen.getByRole("button", {name: "改每賣一筆最多花"}));
  expect(within(field("cap")).getByText("填一個整數金額；留空保留目前設定")).toBeTruthy();
  expect(within(field("cap")).getByRole("button", {name: /用打平/}).hasAttribute("disabled")).toBe(true);
});

it("the generate action explains why it is unavailable before the campaign loads", () => {
  vi.mocked(getCampaign).mockReturnValue(new Promise(() => {}));
  renderPage();
  const button = screen.getByRole("button", {name: "產生策略 →"});
  expect(button.hasAttribute("disabled")).toBe(true);
  expect(document.getElementById(button.getAttribute("aria-describedby")!)?.textContent).toBe("活動資料讀取完成後才能產生策略");
});


// The tooltip measures its trigger in a browser; jsdom does not implement that observer.
vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
afterAll(() => vi.unstubAllGlobals());
