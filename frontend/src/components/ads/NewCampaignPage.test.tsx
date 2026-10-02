import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NewCampaignPage } from "./NewCampaignPage";
import { createCampaign, getCampaign, listCampaigns, patchCampaign, type CampaignCard, type CampaignDetail } from "@/lib/adsApi";
import { putTarget } from "@/lib/adsTriageApi";
import { fetchChannels } from "@/lib/adsLaunchApi";
import { createCampaignFromPicks, getWizardOptions, type WizardOptions } from "@/lib/adsWizardApi";
import { useAuthedImage } from "@/lib/useAuthedImage";
import { clearDraft, readDraft } from "./campaignDraft";

vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "u:o" }) }));
vi.mock("@/lib/adsApi", async (original) => ({ ...await original<object>(), getCampaign: vi.fn(), listCampaigns: vi.fn(), patchCampaign: vi.fn(), createCampaign: vi.fn() }));
vi.mock("@/lib/adsLaunchApi", async (original) => ({ ...await original<object>(), fetchChannels: vi.fn() }));
vi.mock("@/lib/adsTriageApi", async (original) => ({ ...await original<object>(), putTarget: vi.fn() }));
vi.mock("@/lib/adsWizardApi", () => ({ getWizardOptions: vi.fn(), createCampaignFromPicks: vi.fn() }));
vi.mock("@/lib/useAuthedImage", () => ({ useAuthedImage: vi.fn(() => ({ src: null, failed: true })) }));
vi.mock("./UserAssetsLibrary", () => ({ UserAssetsLibrary: () => <div>選擇已完成素材</div> }));

const LONG = "Beast Gummy咖啡因機能軟糖・終極組合包(T-shirt+12盒)加贈隨身盒與保冷袋";
const VITAMIN_URL = "https://beastgummy.tw/shop/multivitamin";
const GROUPS = [{ id: "grp_new", who: "新客為主" }, { id: "grp_try", who: "探索一組" }];
type Way = WizardOptions["products"][number];
const sellWay = (over: Partial<Way> & Pick<Way, "id" | "name" | "display_name">): Way => ({
  kind: "single", knowledge_product_id: "kp_vit", knowledge_product_name: "綜合維他命軟糖", price: 399, currency: "TWD",
  thumbnail_url: null, has_cost: true, break_even: 249, cap_per_sale: 249, derived_fields: [], offer_labels: [], customer_groups: GROUPS, landing_url: VITAMIN_URL,
  previous: null, learned: null, ...over,
});
/** F46-I08: 三盒組 ran twice; the newest (closed) one is the previous campaign (prototype `#/new?from=B`). */
const PREV_NAME = "綜合維他命軟糖 · 三盒組・09/19～10/01";
const ranThree = (over: Partial<NonNullable<Way["previous"]>> = {}): Partial<Way> => ({
  previous: { campaign_id: "cmp_b", campaign_name: PREV_NAME, platform: "google_ads", cap: 450, budget: 10000, spend: 9781, ...over },
  learned: { campaigns: [{ id: "cmp_b", name: PREV_NAME }, { id: "cmp_a", name: "綜合維他命軟糖 · 三盒組・09/05～09/18" }], keep: 3, replace: 3 },
});
/** The prototype's shelf: two sell-ways of one product, one of another (no price, no cost, one group, no page URL),
 * then a bundle with a long name — in the server's order (single sell-ways grouped by knowledge product, then bundles). */
const options = (over: Partial<WizardOptions> = {}, three: Partial<Way> = {}): WizardOptions => ({
  products: [
    sellWay({ id: "sw_one", name: "綜合維他命軟糖 · 單盒", display_name: "單盒", thumbnail_url: "/brands/b/assets/file/a1/one.png" }),
    sellWay({ id: "sw_three", name: "綜合維他命軟糖 · 三盒組", display_name: "三盒組", price: 999, break_even: 669, cap_per_sale: 669,
      derived_fields: ["list_price", "unit_variable_cost"], offer_labels: ["組合價", "免運"], ...three }),
    sellWay({ id: "sw_pro", name: "益生菌軟糖 · 單盒", display_name: "單盒", knowledge_product_id: "kp_pro", knowledge_product_name: "益生菌軟糖",
      price: null, currency: null, has_cost: false, break_even: null, cap_per_sale: null, customer_groups: [{ id: "grp_gut", who: "腸胃敏感的上班族" }], landing_url: null }),
    sellWay({ id: "sw_duo", name: LONG, display_name: "雙效組", kind: "bundle", price: 799, break_even: 539, cap_per_sale: 500, offer_labels: ["組合價"],
      landing_url: "https://beastgummy.tw/shop/duo" }),
  ],
  objectives: [
    { key: "購買", label: "購買", description: "看每賣一筆花多少", available: true, platforms: { meta: "銷售業績", google_ads: "銷售" } },
    { key: "名單", label: "名單", description: "看每筆名單成本", available: true, platforms: { meta: "潛在顧客", google_ads: "潛在客戶" } },
    { key: "互動", label: "互動", description: "看每次互動成本", available: false, platforms: { meta: "互動", google_ads: "YouTube 觸及、觀看與互動" } },
  ],
  default_objective: null,
  default_platform: "meta",
  ...over,
});
/** A campaign as the create stores it (F46-I08): the brand's account, the break-even cap, the sell-way's groups and landing. */
const draft = (over: Partial<CampaignDetail> = {}) => ({ id: "cmp_new", objective: "購買", start_date: "2026-10-01", end_date: "2026-10-31", goal_text: "g",
  cap: { own_value: 669, revision: 1 },
  context_json: { product_ids: ["sw_three"], customer_group_ids: ["grp_new", "grp_try"], landing_url: VITAMIN_URL, field_sources: { dates: "system", platform: "brand", audience: "sell_way", cap: "break_even", landing_url: "sell_way" } },
  constraints_json: { budget: 30000, platform: "meta" }, parsed: true, ...over }) as unknown as CampaignDetail & { parsed: boolean };
const card = (id: string, status: string, created_at: string, start_date: string | null = null, end_date: string | null = null) =>
  ({ id, status, created_at, start_date, end_date }) as unknown as CampaignCard;

function view(brandId = "b1", path = `/brands/${brandId}/ads/new`) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:b/ads/new" element={<NewCampaignPage brandId={brandId} />} />
        <Route path="/brands/:b/ads/new/:c" element={<p>第二步頁面</p>} />
      </Routes>
    </MemoryRouter>,
  );
}
type User = ReturnType<typeof userEvent.setup>;
async function pickAll(user: User) {
  await user.click(await screen.findByRole("radio", { name: /三盒組/ }));
  await user.click(screen.getByRole("radio", { name: /購買/ }));
  await user.type(screen.getByLabelText("這個活動最多花"), "30000");
}
const openFold = (user: User) => user.click(screen.getByRole("button", { name: /進階：這期不一樣/ }));
const openSentence = async (user: User) => user.click(await screen.findByRole("button", { name: /進階：一句話建立/ }));
const next = () => screen.getByRole("button", { name: /下一步：系統理解/ });
const radio = (id: string) => screen.getAllByRole("radio").find((r) => r.getAttribute("data-value") === id)!;
const nameLine = () => document.querySelector("[data-slot=name-line]")?.textContent;
/** The fold's source label beside a field (`data-slot="field-source"`), by the field's label. */
const source = (label: string) => screen.getByText(label, { selector: "label" }).parentElement?.querySelector("[data-slot=field-source]")?.textContent ?? null;
const value = (label: string) => (screen.getByLabelText(label) as HTMLInputElement | HTMLSelectElement).value;
/** F46-I08: the source tag beside a field of 「期間、預算與平台」 (`data-slot="source-tag"`), by the field's label. */
const tagOf = (label: string) => screen.getByText(label, { selector: "label" }).parentElement?.querySelector("[data-slot=source-tag]") ?? null;
const learnStrip = () => document.querySelector("[data-slot=learn-strip]");

beforeEach(() => {
  sessionStorage.clear(); vi.clearAllMocks();
  // The draft store keeps a memory copy beside sessionStorage: start every test from an empty form.
  for (const brand of ["b1", "a", "b", "p1", "g1", "g2", "s1", "s2", "save", "known", "retry-ai"]) clearDraft(`campaign-draft:u:o:${brand}`);
  vi.mocked(getWizardOptions).mockResolvedValue(options());
  vi.mocked(listCampaigns).mockResolvedValue([]);
  vi.mocked(fetchChannels).mockResolvedValue([{ key: "meta", label: "Meta", connected: true, state_text: "" }, { key: "google_ads", label: "Google Ads", connected: false, state_text: "" }]);
  vi.mocked(useAuthedImage).mockReturnValue({ src: null, failed: true });
});

describe("new-campaign step 1, slimmed (F43-I15, prototype f41-onboarding #/new)", () => {
  it("lists sell-ways per product, then 組合, each 〈賣法〉 〈price〉 over 打平・offers; no F40 bar or 這次怎麼投 card", async () => {
    view();
    const group = await screen.findByRole("radiogroup", { name: "要推什麼" });
    const order = Array.from(group.querySelectorAll("[data-slot=pick-section], [role=radio]"))
      .map((e) => (e.getAttribute("role") === "radio" ? e.getAttribute("data-value") : e.textContent));
    expect(order).toEqual(["綜合維他命軟糖", "sw_one", "sw_three", "益生菌軟糖", "sw_pro", "組合", "sw_duo"]);
    expect(within(radio("sw_three")).getByText("三盒組 NT$999")).toBeTruthy();
    expect(within(radio("sw_three")).getByText("打平 669（推算）・組合價＋免運")).toBeTruthy();
    expect(within(radio("sw_one")).getByText("單盒 NT$399")).toBeTruthy();
    expect(within(radio("sw_one")).getByText("打平 249・沒有優惠")).toBeTruthy();
    expect(within(radio("sw_pro")).getByText("單盒 價格未填")).toBeTruthy();
    expect(within(radio("sw_pro")).getByText("缺成本・沒有優惠")).toBeTruthy();
    expect(within(radio("sw_duo")).getByText("打平 539・組合價")).toBeTruthy();
    // Only the purpose line names 上一期 (no F40 「照上一期」 bar); a sell-way never run says so on its card.
    expect(screen.queryAllByText(/照上一期/).map((e) => e.textContent)).toEqual(["選要推什麼、推多久、花多少；其他照上一期或商品建檔帶入"]);
    expect(within(radio("sw_three")).getByText("還沒投過")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "這次怎麼投" })).toBeNull();
    expect(screen.queryByRole("button", { name: "清空重填" })).toBeNull();
    expect(screen.queryByRole("radio", { name: /互動/ })).toBeNull();
    expect(within(screen.getByRole("list", { name: "尚未開放的目標" })).getByText("互動・尚未開放")).toBeTruthy();
  });

  it("loads a sell-way thumbnail through the authenticated image hook, never as a bare src", async () => {
    vi.mocked(useAuthedImage).mockImplementation((url) => ({ src: url ? "blob:thumb" : null, failed: !url }));
    view();
    await screen.findByRole("radiogroup", { name: "要推什麼" });
    expect(useAuthedImage).toHaveBeenCalledWith("/brands/b/assets/file/a1/one.png");
    expect(radio("sw_one").querySelector("img")?.getAttribute("src")).toBe("blob:thumb");
    expect(document.querySelector('img[src^="/brands/"]')).toBeNull();
  });

  it("preselects the brand's conversion goal with its caption; without one nothing is preselected", async () => {
    vi.mocked(getWizardOptions).mockResolvedValue(options({ default_objective: "名單" }));
    const first = view("g1");
    await waitFor(() => expect(screen.getByRole("radio", { name: /名單/ }).getAttribute("aria-checked")).toBe("true"));
    expect(screen.getByText("預設＝品牌的成效目標")).toBeTruthy();
    first.unmount();
    vi.mocked(getWizardOptions).mockResolvedValue(options());
    view("g2");
    await screen.findByRole("radio", { name: /購買/ });
    expect(screen.getAllByRole("radio", { name: /購買|名單/ }).map((r) => r.getAttribute("aria-checked"))).toEqual(["false", "false"]);
    expect(screen.queryByText("預設＝品牌的成效目標")).toBeNull();
  });

  it("?sell_way= (from 商品建檔 ⑤) preselects that sell-way; an id that is not pickable is ignored", async () => {
    const first = view("s1", "/brands/s1/ads/new?sell_way=sw_duo");
    await waitFor(() => expect(radio("sw_duo").getAttribute("aria-checked")).toBe("true"));
    first.unmount();
    view("s2", "/brands/s2/ads/new?sell_way=kp_vit");
    await screen.findByRole("radiogroup", { name: "要推什麼" });
    expect(screen.getAllByRole("radio").filter((r) => r.getAttribute("aria-checked") === "true")).toHaveLength(0);
  });

  it("with no finished sell-way the section links to 建第一個商品", async () => {
    vi.mocked(getWizardOptions).mockResolvedValue(options({ products: [] }));
    view();
    const link = await screen.findByRole("link", { name: "建第一個商品" });
    expect(link.getAttribute("href")).toBe("/brands/b1/products/new");
    expect(screen.queryByRole("radiogroup", { name: "要推什麼" })).toBeNull();
  });

  it("keeps the primary action disabled until sell-way, result and budget are set, then sends only the picks", async () => {
    vi.mocked(createCampaignFromPicks).mockResolvedValue(draft());
    const user = userEvent.setup();
    view();
    await screen.findByRole("radiogroup", { name: "要推什麼" });
    expect(next()).toHaveProperty("disabled", true);
    expect(screen.getByText("選好要推什麼和想要的結果")).toBeTruthy();
    await user.click(radio("sw_three"));
    await user.click(screen.getByRole("radio", { name: /購買/ }));
    expect(next()).toHaveProperty("disabled", true);
    expect(screen.getByText("填這個活動最多花")).toBeTruthy();
    await user.type(screen.getByLabelText("這個活動最多花"), "30000");
    expect(next()).toHaveProperty("disabled", false);
    await user.click(next());
    expect(await screen.findByText("第二步頁面")).toBeTruthy();
    // The fold was never touched: platform／audience／cap／landing come from the brand and the sell-way on the server.
    expect(createCampaignFromPicks).toHaveBeenCalledWith("b1", { product_ids: ["sw_three"], objective: "購買", budget: 30000 });
    expect(readDraft("campaign-draft:u:o:b1").productId).toBeNull();
  });

  it("names the campaign like the server: 〈sell-way name〉・MM/DD～MM/DD, a long name cut at 30 characters", async () => {
    const user = userEvent.setup();
    view();
    await screen.findByRole("radiogroup", { name: "要推什麼" });
    expect(nameLine()).toBeUndefined();
    await user.click(radio("sw_three"));
    expect(nameLine()).toBe("活動名稱會叫「綜合維他命軟糖 · 三盒組」加上期間（沒填日期就從今天起算 30 天）");
    await user.type(screen.getByLabelText("開始"), "2026-10-10");
    await user.type(screen.getByLabelText("結束"), "2026-10-16");
    expect(nameLine()).toBe("活動名稱會叫「綜合維他命軟糖 · 三盒組・10/10～10/16」");
    await user.click(radio("sw_duo"));
    expect(nameLine()).toBe(`活動名稱會叫「${LONG.slice(0, 30)}…・10/10～10/16」`);
  });

  it("the period starts the day after the latest non-draft campaign ends, same length; nothing else is copied", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([
      card("cmp_draft", "draft", "2026-09-29T00:00:00Z", "2026-12-01", "2026-12-31"),
      card("cmp_old", "ended", "2026-08-01T00:00:00Z", "2026-08-01", "2026-08-07"),
      card("cmp_prev", "live", "2026-09-25T00:00:00Z", "2026-09-26", "2026-10-02"),
    ]);
    view("p1");
    await waitFor(() => expect(value("開始")).toBe("2026-10-03"));
    expect(value("結束")).toBe("2026-10-09");
    expect(screen.getByText("日期接在上一期後面（上一期 09/26～10/02）")).toBeTruthy();
    expect(value("這個活動最多花")).toBe("");
    expect(screen.getAllByRole("radio").filter((r) => r.getAttribute("aria-checked") === "true")).toHaveLength(0);
    expect(getCampaign).not.toHaveBeenCalled();
  });

  it("asks for both dates or neither and sends them when both are set", async () => {
    vi.mocked(createCampaignFromPicks).mockResolvedValue(draft());
    const user = userEvent.setup();
    view();
    await pickAll(user);
    await user.type(screen.getByLabelText("開始"), "2026-10-01");
    expect(screen.getByText("開始和結束要一起填")).toBeTruthy();
    expect(next()).toHaveProperty("disabled", true);
    await user.type(screen.getByLabelText("結束"), "2026-10-31");
    await user.click(next());
    await screen.findByText("第二步頁面");
    expect(createCampaignFromPicks).toHaveBeenCalledWith("b1", expect.objectContaining({ start_date: "2026-10-01", end_date: "2026-10-31" }));
  });
});

describe("「期間、預算與平台」 starts from the previous campaign (F46-I08, prototype f46-learnings #/new)", () => {
  it("a sell-way never run: the brand's account, 打平線 for the cap, an empty budget 「第一次推，要自己填」 and the no-learning strip", async () => {
    const user = userEvent.setup();
    view();
    await user.click(await screen.findByRole("radio", { name: /三盒組/ }));
    expect(screen.getByRole("heading", { name: "期間、預算與平台" })).toBeTruthy();
    expect(value("平台")).toBe("meta");
    expect(tagOf("平台")?.textContent).toBe("已接上的帳戶");
    expect(within(screen.getByLabelText("平台")).getAllByRole("option").map((o) => o.textContent)).toEqual(["Meta（已接上）", "Google Ads（還沒接上）"]);
    expect(value("每筆上限")).toBe("669");
    expect(tagOf("每筆上限")?.textContent).toBe("打平線");
    expect(screen.getByText("等於打平 669（推算）")).toBeTruthy();
    expect(value("這個活動最多花")).toBe("");
    expect(tagOf("這個活動最多花")).toBeNull();
    expect(screen.getByText("第一次推，要自己填")).toBeTruthy();
    expect(learnStrip()?.textContent).toBe("「三盒組」還沒結案過・沒有學習可用，每筆上限先用打平線");
    expect(screen.queryByText(/標「沿用上一期」的照/)).toBeNull();
    // A sell-way with its own cap above nothing: 來自賣法.
    await user.click(radio("sw_duo"));
    expect(value("每筆上限")).toBe("500");
    expect(tagOf("每筆上限")?.textContent).toBe("來自賣法");
    expect(learnStrip()?.textContent).toBe("「雙效組」還沒結案過・沒有學習可用");
  });

  it("a sell-way that ran: platform, cap and budget 沿用上一期 with the spend, the learn strip, and only the picks are sent", async () => {
    vi.mocked(getWizardOptions).mockResolvedValue(options({}, ranThree()));
    vi.mocked(createCampaignFromPicks).mockResolvedValue(draft());
    const user = userEvent.setup();
    view("b1", "/brands/b1/ads/new?sell_way=sw_three");
    await waitFor(() => expect(value("這個活動最多花")).toBe("10000"));
    expect(value("平台")).toBe("google_ads");
    expect(value("每筆上限")).toBe("450");
    for (const label of ["平台", "每筆上限", "這個活動最多花"]) {
      expect(tagOf(label)?.textContent, label).toBe("沿用上一期");
      expect(tagOf(label)?.getAttribute("title"), label).toBe(`上一期：${PREV_NAME}`);
    }
    expect(screen.getByText("上一期 09/19～10/01 花了 NT$9,781")).toBeTruthy();
    expect(screen.getByText(`標「沿用上一期」的照 ${PREV_NAME}`)).toBeTruthy();
    expect(learnStrip()?.textContent).toBe(`這期會用 2 期的學習・${PREV_NAME}、綜合維他命軟糖 · 三盒組・09/05～09/18留下 3換掉 3看學到什麼 →`);
    expect(within(learnStrip() as HTMLElement).getByRole("link", { name: "看學到什麼 →" }).getAttribute("href")).toBe("/brands/b1/library?tab=ads-learnings");
    await user.click(screen.getByRole("radio", { name: /購買/ }));
    await user.click(next());
    await screen.findByText("第二步頁面");
    // Shown = stored: the server fills the untouched values with the same rule.
    expect(createCampaignFromPicks).toHaveBeenCalledWith("b1", { product_ids: ["sw_three"], objective: "購買", budget: 10000 });
  });

  it("a previous campaign's empty field falls through for that field only", async () => {
    vi.mocked(getWizardOptions).mockResolvedValue(options({}, ranThree({ platform: null, cap: null, budget: null, spend: null })));
    const user = userEvent.setup();
    view();
    await user.click(await screen.findByRole("radio", { name: /三盒組/ }));
    expect(value("平台")).toBe("meta");
    expect(tagOf("平台")?.textContent).toBe("已接上的帳戶");
    expect(value("每筆上限")).toBe("669");
    expect(tagOf("每筆上限")?.textContent).toBe("打平線");
    expect(value("這個活動最多花")).toBe("");
    expect(screen.queryByText("第一次推，要自己填")).toBeNull(); // it ran before
  });

  it("changed values are 你改的 and sent; a value typed back to the default is not", async () => {
    vi.mocked(getWizardOptions).mockResolvedValue(options({}, ranThree()));
    vi.mocked(createCampaignFromPicks).mockResolvedValue(draft());
    const user = userEvent.setup();
    view();
    await user.click(await screen.findByRole("radio", { name: /三盒組/ }));
    await user.click(screen.getByRole("radio", { name: /購買/ }));
    await user.clear(screen.getByLabelText("這個活動最多花"));
    await user.type(screen.getByLabelText("這個活動最多花"), "12000");
    await user.clear(screen.getByLabelText("每筆上限"));
    await user.type(screen.getByLabelText("每筆上限"), "600");
    expect(screen.getByText("比打平 669（推算） 低 69")).toBeTruthy();
    await user.selectOptions(screen.getByLabelText("平台"), "meta");
    for (const label of ["平台", "每筆上限", "這個活動最多花"]) expect(tagOf(label)?.textContent, label).toBe("你改的");
    expect(screen.queryByText(/花了 NT\$/)).toBeNull();
    await user.selectOptions(screen.getByLabelText("平台"), "google_ads");
    expect(tagOf("平台")?.textContent).toBe("沿用上一期");
    await user.click(next());
    await screen.findByText("第二步頁面");
    expect(createCampaignFromPicks).toHaveBeenCalledWith("b1", { product_ids: ["sw_three"], objective: "購買", budget: 12000, cap: 600 });
  });

  it("a cleared default cap blocks 下一步 until filled (it would not be stored as shown)", async () => {
    const user = userEvent.setup();
    view();
    await pickAll(user);
    await user.clear(screen.getByLabelText("每筆上限"));
    expect(screen.getByText("填每筆上限")).toBeTruthy();
    expect(next()).toHaveProperty("disabled", true);
    await user.type(screen.getByLabelText("每筆上限"), "669");
    expect(next()).toHaveProperty("disabled", false);
    expect(tagOf("每筆上限")?.textContent).toBe("打平線");
  });

  it("another sell-way swaps a prefilled budget for its own; a restored draft keeps its own budget", async () => {
    vi.mocked(getWizardOptions).mockResolvedValue(options({}, ranThree()));
    const user = userEvent.setup();
    const first = view("a");
    await user.click(await screen.findByRole("radio", { name: /三盒組/ }));
    expect(value("這個活動最多花")).toBe("10000");
    await user.click(radio("sw_one"));
    expect(value("這個活動最多花")).toBe("");
    await user.type(screen.getByLabelText("這個活動最多花"), "30000");
    expect(tagOf("這個活動最多花")?.textContent).toBe("你改的");
    first.unmount();
    view("a");
    await screen.findByRole("radio", { name: /三盒組/ });
    await user.click(radio("sw_three"));
    expect(value("這個活動最多花")).toBe("30000");
    expect(tagOf("這個活動最多花")?.textContent).toBe("你改的");
  });

  it("labels a derived break-even 「（推算）」 and a base sell-way's own break-even not (F45, ads §6.49 Picker)", async () => {
    const user = userEvent.setup();
    view();
    await user.click(await screen.findByRole("radio", { name: /三盒組/ }));
    expect(screen.getByText("等於打平 669（推算）")).toBeTruthy();
    await user.click(screen.getByRole("radio", { name: /單盒 NT\$399/ }));
    expect(screen.getByText("等於打平 249")).toBeTruthy();
    expect(screen.queryByText(/推算）$/)).toBeNull();
    expect(within(radio("sw_one")).getByText("打平 249・沒有優惠")).toBeTruthy();
  });
});

describe("「進階：這期不一樣」 (F43-I15; F46-I08 keeps 受眾 and 落地頁)", () => {
  it("is folded, and shows each value with where it comes from", async () => {
    const user = userEvent.setup();
    view();
    await user.click(await screen.findByRole("radio", { name: /三盒組/ }));
    expect(screen.getByRole("button", { name: "進階：這期不一樣（受眾、落地頁）" }).getAttribute("aria-expanded")).toBe("false");
    await openFold(user);
    expect(value("受眾")).toBe("");
    expect(within(screen.getByLabelText("受眾")).getAllByRole("option").map((o) => o.textContent)).toEqual(["2 群都投（新客為主、探索一組）", "只投：新客為主", "只投：探索一組"]);
    expect(source("受眾")).toBe("來自商品：2 群顧客");
    expect(value("落地頁")).toBe(VITAMIN_URL);
    expect(source("落地頁")).toBe("來自賣法「三盒組」");
  });

  it("sends only the changed values and names them 你改的; a value typed back to the default is not sent", async () => {
    vi.mocked(createCampaignFromPicks).mockResolvedValue(draft());
    const user = userEvent.setup();
    view();
    await pickAll(user);
    await openFold(user);
    await user.selectOptions(screen.getByLabelText("受眾"), "grp_try");
    await user.selectOptions(screen.getByLabelText("平台"), "google_ads");
    await user.clear(screen.getByLabelText("落地頁"));
    await user.type(screen.getByLabelText("落地頁"), VITAMIN_URL);
    expect(source("受眾")).toBe("你改的");
    expect(tagOf("平台")?.textContent).toBe("你改的");
    expect(source("落地頁")).toBe("來自賣法「三盒組」");
    await user.click(next());
    await screen.findByText("第二步頁面");
    expect(createCampaignFromPicks).toHaveBeenCalledWith("b1", {
      product_ids: ["sw_three"], objective: "購買", budget: 30000, platform: "google_ads", customer_group_ids: ["grp_try"],
    });
  });

  it("a changed landing URL is sent; a cleared one falls back to the product page and is not sent", async () => {
    vi.mocked(createCampaignFromPicks).mockResolvedValue(draft());
    const user = userEvent.setup();
    view();
    await pickAll(user);
    await openFold(user);
    await user.clear(screen.getByLabelText("落地頁"));
    expect(screen.getByText("留空＝用賣法的落地頁")).toBeTruthy();
    await user.type(screen.getByLabelText("落地頁"), "https://beastgummy.tw/lp/autumn");
    expect(source("落地頁")).toBe("你改的");
    await user.click(next());
    await screen.findByText("第二步頁面");
    expect(createCampaignFromPicks).toHaveBeenLastCalledWith("b1", expect.objectContaining({ landing_url: "https://beastgummy.tw/lp/autumn" }));
  });

  it("another sell-way brings its own audience, cap and landing; a one-group sell-way has no audience choice", async () => {
    const user = userEvent.setup();
    view();
    await user.click(await screen.findByRole("radio", { name: /三盒組/ }));
    await openFold(user);
    await user.selectOptions(screen.getByLabelText("受眾"), "grp_new");
    await user.clear(screen.getByLabelText("每筆上限"));
    await user.type(screen.getByLabelText("每筆上限"), "700");
    await user.click(radio("sw_duo"));
    expect(value("受眾")).toBe("");
    expect(value("每筆上限")).toBe("500");
    expect(tagOf("每筆上限")?.textContent).toBe("來自賣法");
    expect(value("落地頁")).toBe("https://beastgummy.tw/shop/duo");
    await user.click(radio("sw_pro"));
    expect(screen.getByLabelText("受眾")).toHaveProperty("disabled", true);
    expect(source("受眾")).toBe("來自商品：1 群顧客");
    expect(value("每筆上限")).toBe("");
    expect(tagOf("每筆上限")).toBeNull();
    expect(screen.getByText("這個賣法還算不出打平；可以自己填")).toBeTruthy();
    expect(source("落地頁")).toBe("來自賣法「單盒」");
    expect(value("落地頁")).toBe("");
  });

  it("a brand with no connected account says so; the platform can still be picked", async () => {
    vi.mocked(getWizardOptions).mockResolvedValue(options({ default_platform: null }));
    vi.mocked(fetchChannels).mockResolvedValue([{ key: "meta", label: "Meta", connected: false, state_text: "" }]);
    const user = userEvent.setup();
    view();
    await user.click(await screen.findByRole("radio", { name: /三盒組/ }));
    expect(screen.getByText("品牌還沒接上帳戶")).toBeTruthy();
    expect(value("平台")).toBe("");
    expect(tagOf("平台")).toBeNull();
    await user.selectOptions(screen.getByLabelText("平台"), "meta");
    expect(tagOf("平台")?.textContent).toBe("你改的");
  });
});

describe("new-campaign step 1 flow (F30-I05, kept)", () => {
  it("shows the wait line while understanding, then the fail box with 重試; 上一步 keeps the picks", async () => {
    let fail!: (e: Error) => void;
    vi.mocked(createCampaignFromPicks).mockReturnValueOnce(new Promise((_r, reject) => { fail = reject; }));
    const user = userEvent.setup();
    view();
    await pickAll(user);
    await user.click(next());
    expect(await screen.findByText("系統正在理解你選的內容")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "系統理解中" })).toBeTruthy();
    await act(async () => fail(new Error("AI 暫時沒有回應")));
    const box = await screen.findByRole("alert");
    expect(within(box).getByText(/AI 暫時沒有回應/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "← 上一步" }));
    expect(radio("sw_three").getAttribute("aria-checked")).toBe("true");
    expect(value("這個活動最多花")).toBe("30000");
    vi.mocked(createCampaignFromPicks).mockResolvedValue(draft());
    await user.click(next());
    expect(await screen.findByText("第二步頁面")).toBeTruthy();
    expect(createCampaignFromPicks).toHaveBeenCalledTimes(2);
  });

  it("retries from the fail box without going back", async () => {
    vi.mocked(createCampaignFromPicks).mockRejectedValueOnce(new Error("離線")).mockResolvedValueOnce(draft());
    const user = userEvent.setup();
    view();
    await pickAll(user);
    await user.click(next());
    await user.click(await screen.findByRole("button", { name: "重試" }));
    expect(await screen.findByText("第二步頁面")).toBeTruthy();
  });

  it("shows ReadFailed with 重試 when the options cannot be read, never an empty list", async () => {
    vi.mocked(getWizardOptions).mockRejectedValueOnce(new Error("讀取商品與目標失敗。"));
    const user = userEvent.setup();
    view();
    expect(await screen.findByText(/賣法和目標清單讀不到/)).toBeTruthy();
    expect(screen.queryByRole("radio")).toBeNull();
    await user.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByRole("radio", { name: /三盒組/ })).toBeTruthy();
  });

  it("restores unsent picks after leaving and isolates another brand", async () => {
    const user = userEvent.setup();
    const first = view("a");
    await pickAll(user);
    first.unmount();
    const other = view("b");
    expect((await screen.findByRole("radio", { name: /三盒組/ })).getAttribute("aria-checked")).toBe("false");
    other.unmount();
    view("a");
    expect((await screen.findByRole("radio", { name: /三盒組/ })).getAttribute("aria-checked")).toBe("true");
    expect(value("這個活動最多花")).toBe("30000");
  });

  it("going back to a created campaign reloads its picks and patches only what changed", async () => {
    vi.mocked(getCampaign).mockResolvedValue(draft());
    vi.mocked(patchCampaign).mockResolvedValue(draft({ objective: "名單" }));
    const user = userEvent.setup();
    view("b1", "/brands/b1/ads/new?created=cmp_new");
    await waitFor(() => expect(radio("sw_three").getAttribute("aria-checked")).toBe("true"));
    expect(value("這個活動最多花")).toBe("30000");
    expect(value("開始")).toBe("");
    await user.click(screen.getByRole("radio", { name: /名單/ }));
    await user.click(next());
    expect(await screen.findByText("第二步頁面")).toBeTruthy();
    expect(patchCampaign).toHaveBeenCalledWith("b1", "cmp_new", { objective: "名單" });
    expect(putTarget).not.toHaveBeenCalled();
    expect(createCampaignFromPicks).not.toHaveBeenCalled();
  });

  it("going back: the audience change is a PATCH of customer_group_ids and the cap goes through the target", async () => {
    vi.mocked(getCampaign).mockResolvedValue(draft());
    vi.mocked(patchCampaign).mockResolvedValue(draft());
    vi.mocked(putTarget).mockResolvedValue({} as never);
    const user = userEvent.setup();
    view("b1", "/brands/b1/ads/new?created=cmp_new");
    await waitFor(() => expect(radio("sw_three").getAttribute("aria-checked")).toBe("true"));
    await openFold(user);
    await user.selectOptions(screen.getByLabelText("受眾"), "grp_new");
    await user.clear(screen.getByLabelText("每筆上限"));
    await user.type(screen.getByLabelText("每筆上限"), "600");
    await user.click(next());
    expect(await screen.findByText("第二步頁面")).toBeTruthy();
    expect(patchCampaign).toHaveBeenCalledWith("b1", "cmp_new", { customer_group_ids: ["grp_new"] });
    expect(putTarget).toHaveBeenCalledWith("b1", "cmp_new", { basis: "own", value: 600, expected_revision: 1 });
  });

  it("going back: another sell-way PATCHes it with its landing and cap (the server resets the groups)", async () => {
    vi.mocked(getCampaign).mockResolvedValue(draft());
    vi.mocked(patchCampaign).mockResolvedValue(draft({ cap: { own_value: 669, revision: 2 } } as Partial<CampaignDetail>));
    vi.mocked(putTarget).mockResolvedValue({} as never);
    const user = userEvent.setup();
    view("b1", "/brands/b1/ads/new?created=cmp_new");
    await waitFor(() => expect(radio("sw_three").getAttribute("aria-checked")).toBe("true"));
    await user.click(radio("sw_duo"));
    await user.click(next());
    expect(await screen.findByText("第二步頁面")).toBeTruthy();
    expect(patchCampaign).toHaveBeenCalledWith("b1", "cmp_new", { product_ids: ["sw_duo"], landing_url: "https://beastgummy.tw/shop/duo" });
    expect(putTarget).toHaveBeenCalledWith("b1", "cmp_new", { basis: "own", value: 500, expected_revision: 2 });
  });
});

describe("「進階：一句話建立、自帶圖片／影片」 (kept, feature Unresolved)", () => {
  it("one-sentence create: keeps a failed submission and clears the draft only after success", async () => {
    const user = userEvent.setup();
    vi.mocked(createCampaign).mockRejectedValueOnce(new Error("離線"));
    view("save");
    await openSentence(user);
    await user.type(screen.getByLabelText("你這次想做到什麼？"), "新品銷售");
    await user.click(screen.getByRole("button", { name: "產生建議" }));
    expect(await screen.findByText(/離線/)).toBeTruthy();
    expect(readDraft("campaign-draft:u:o:save").goalText).toBe("新品銷售");
    vi.mocked(createCampaign).mockResolvedValue({ id: "draft", parsed: true } as Awaited<ReturnType<typeof createCampaign>>);
    await user.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText("第二步頁面")).toBeTruthy();
    expect(createCampaign).toHaveBeenLastCalledWith("save", { goal_text: "新品銷售" });
    expect(createCampaignFromPicks).not.toHaveBeenCalled();
    expect(readDraft("campaign-draft:u:o:save").goalText).toBe("");
  });

  it("can request one AI draft from saved brand data without entering the same data again", async () => {
    vi.mocked(createCampaign).mockResolvedValue({ id: "suggested", parsed: true } as Awaited<ReturnType<typeof createCampaign>>);
    const user = userEvent.setup();
    view("known");
    await openSentence(user);
    await user.click(screen.getByRole("button", { name: "請 AI 依品牌資料建議" }));
    await waitFor(() => expect(createCampaign).toHaveBeenCalledTimes(1));
    expect(createCampaign).toHaveBeenCalledWith("known", { goal_text: expect.stringContaining("沿用已知資訊") });
  });

  it("keeps a failed AI request editable and does not replace a written goal", async () => {
    vi.mocked(createCampaign).mockRejectedValueOnce(new Error("暫時無法連線"));
    const user = userEvent.setup();
    view("retry-ai");
    await openSentence(user);
    await user.click(screen.getByRole("button", { name: "請 AI 依品牌資料建議" }));
    expect(await screen.findByText(/暫時無法連線/)).toBeTruthy();
    expect(readDraft("campaign-draft:u:o:retry-ai").goalText).toContain("沿用已知資訊");
    await user.click(screen.getByRole("button", { name: "← 上一步" }));
    await user.clear(screen.getByLabelText("你這次想做到什麼？"));
    await user.type(screen.getByLabelText("你這次想做到什麼？"), "我想增加名單");
    expect(screen.queryByRole("button", { name: "請 AI 依品牌資料建議" })).toBeNull();
    expect(screen.getByRole("button", { name: "產生建議" })).toBeTruthy();
    expect(createCampaign).toHaveBeenCalledTimes(1);
  });

  it("sends the sentence with the picks when both are given", async () => {
    vi.mocked(createCampaignFromPicks).mockResolvedValue(draft());
    const user = userEvent.setup();
    view();
    await pickAll(user);
    await openSentence(user);
    await user.type(screen.getByLabelText("你這次想做到什麼？"), "主打上班族");
    await user.click(next());
    await screen.findByText("第二步頁面");
    expect(createCampaignFromPicks).toHaveBeenCalledWith("b1", { product_ids: ["sw_three"], objective: "購買", budget: 30000, goal_text: "主打上班族" });
  });

  it("keeps the brand's own images／videos folded under it, below 這期不一樣", async () => {
    const user = userEvent.setup();
    view();
    await screen.findByRole("radio", { name: /三盒組/ });
    const folds = screen.getAllByRole("button", { name: /^進階：/ }).map((b) => b.textContent);
    expect(folds).toEqual(["進階：這期不一樣（受眾、落地頁）", "進階：一句話建立、自帶圖片／影片"]);
    expect(screen.queryByText("選擇已完成素材")).toBeNull();
    await openSentence(user);
    expect(screen.getByText("選擇已完成素材")).toBeTruthy();
  });
});
