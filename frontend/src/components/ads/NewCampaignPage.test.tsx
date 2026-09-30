import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NewCampaignPage } from "./NewCampaignPage";
import { createCampaign, getCampaign, listCampaigns, patchCampaign, type CampaignCard, type CampaignDetail } from "@/lib/adsApi";
import { fetchChannels } from "@/lib/adsLaunchApi";
import { createCampaignFromPicks, getWizardOptions, type WizardOptions } from "@/lib/adsWizardApi";
import { useAuthedImage } from "@/lib/useAuthedImage";
import { readDraft, saveDraft } from "./campaignDraft";

vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "u:o" }) }));
vi.mock("@/lib/adsApi", async (original) => ({ ...await original<object>(), getCampaign: vi.fn(), listCampaigns: vi.fn(), patchCampaign: vi.fn(), createCampaign: vi.fn() }));
vi.mock("@/lib/adsLaunchApi", async (original) => ({ ...await original<object>(), fetchChannels: vi.fn() }));
vi.mock("@/lib/adsWizardApi", () => ({ getWizardOptions: vi.fn(), createCampaignFromPicks: vi.fn() }));
vi.mock("@/lib/useAuthedImage", () => ({ useAuthedImage: vi.fn(() => ({ src: null, failed: true })) }));
vi.mock("./UserAssetsLibrary", () => ({ UserAssetsLibrary: () => <div>選擇已完成素材</div> }));

const LONG = "Beast Gummy咖啡因機能軟糖・終極組合包(T-shirt+12盒)";
const options = (): WizardOptions => ({
  products: [
    { id: "prd_a", name: "Beast Gummy咖啡因機能軟糖・三盒", price: 999, currency: "TWD", thumbnail_url: "/api/products/brands/b/products/prd_a/thumbnail", has_cost: true },
    { id: "prd_b", name: LONG, price: null, currency: null, thumbnail_url: null, has_cost: false },
  ],
  objectives: [
    { key: "購買", label: "購買", description: "看每賣一筆花多少", available: true, platforms: { meta: "銷售業績", google_ads: "銷售" } },
    { key: "名單", label: "名單", description: "看每筆名單成本", available: true, platforms: { meta: "潛在顧客", google_ads: "潛在客戶" } },
    { key: "互動", label: "互動", description: "看每次互動成本", available: false, platforms: { meta: "互動", google_ads: "YouTube 觸及、觀看與互動" } },
  ],
});
const draft = (over: Partial<CampaignDetail> = {}) => ({ id: "cmp_new", objective: "購買", start_date: "2026-10-01", end_date: "2026-10-31", goal_text: "g",
  context_json: { product_ids: ["prd_a"], field_sources: { dates: "system" } }, constraints_json: { budget: 30000 }, parsed: true, ...over }) as unknown as CampaignDetail & { parsed: boolean };

/** The previous period as the prototype has it (drill-7 #10): 「9 月第一期」, 09/26–10/02, Meta, cap 450 against 打平線 520,
 * budget 10,500, the landing URL on the campaign. `status` past draft so it is the one a new campaign copies. */
const PREV_URL = "https://beastgummy.tw/shop";
const previous = (over: Partial<CampaignDetail> = {}) => ({
  id: "cmp_prev", name: "9 月第一期", status: "live", objective: "購買", start_date: "2026-09-26", end_date: "2026-10-02", created_at: "2026-09-25T00:00:00Z",
  cap: { value: 450, basis: "own", own_value: 450, break_even: 520, price: 998, product_id: "prd_a", result_kind: "purchase", result_label: "購買", missing: [], revision: 2 },
  context_json: { product_ids: ["prd_a"], audience_hint: "新客為主、探索一組", landing_url: PREV_URL, field_sources: { dates: "user" } },
  constraints_json: { platform: "meta", budget: 10500 }, ...over,
}) as unknown as CampaignDetail;
const card = (id: string, status: string, created_at: string) => ({ id, status, created_at }) as unknown as CampaignCard;
/** A newer draft and an older ended campaign sit beside it: the latest non-draft one wins. */
function withPrevious(detail: CampaignDetail = previous()) {
  vi.mocked(listCampaigns).mockResolvedValue([
    card("cmp_draft", "draft", "2026-09-29T00:00:00Z"), card("cmp_old", "ended", "2026-08-01T00:00:00Z"), card(detail.id, detail.status, detail.created_at),
  ]);
  vi.mocked(getCampaign).mockImplementation(async (_b, id) => { if (id === detail.id) return detail; throw new Error(`unexpected read ${id}`); });
}
const PREV_PICKS = { product_ids: ["prd_a"], objective: "購買", budget: 10500, start_date: "2026-10-03", end_date: "2026-10-09" };
const PREV_EXTRAS = { platform: "meta", audience_hint: "新客為主、探索一組", cap: 450, landing_url: PREV_URL };

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
async function pickAll(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("radio", { name: /三盒/ }));
  await user.click(screen.getByRole("radio", { name: /購買/ }));
  await user.type(screen.getByLabelText("這個活動最多花"), "30000");
}
const next = () => screen.getByRole("button", { name: /下一步：系統理解/ });

beforeEach(() => {
  sessionStorage.clear(); vi.clearAllMocks();
  vi.mocked(getWizardOptions).mockResolvedValue(options());
  vi.mocked(listCampaigns).mockResolvedValue([]);
  vi.mocked(fetchChannels).mockResolvedValue([{ key: "meta", label: "Meta", connected: true, state_text: "" }, { key: "google_ads", label: "Google Ads", connected: false, state_text: "" }]);
  vi.mocked(useAuthedImage).mockReturnValue({ src: null, failed: true });
});

describe("new-campaign wizard step 1 (F30-I05)", () => {
  it("shows products with price or 價格未填 and 有成本／缺成本, catalog objectives with reserved ones greyed", async () => {
    view();
    const long = await screen.findByRole("radio", { name: new RegExp(LONG.replace(/[()+]/g, "\\$&")) });
    expect(within(long).getByText("價格未填")).toBeTruthy();
    expect(within(long).getByText("缺成本")).toBeTruthy();
    const cheap = screen.getByRole("radio", { name: /三盒/ });
    expect(within(cheap).getByText("NT$999")).toBeTruthy();
    expect(within(cheap).getByText("有成本")).toBeTruthy();
    expect(screen.queryByRole("radio", { name: /互動/ })).toBeNull();
    expect(within(screen.getByRole("list", { name: "尚未開放的目標" })).getByText("互動・尚未開放")).toBeTruthy();
    expect(screen.getAllByRole("radio", { name: /購買|名單/ })).toHaveLength(2);
    expect(screen.getByLabelText("這個活動最多花")).toBeTruthy();
  });

  it("loads a product thumbnail through the authenticated image hook, never as a bare src", async () => {
    vi.mocked(useAuthedImage).mockImplementation((url) => ({ src: url ? "blob:thumb" : null, failed: !url }));
    view();
    const card = await screen.findByRole("radio", { name: /三盒/ });
    expect(useAuthedImage).toHaveBeenCalledWith("/api/products/brands/b/products/prd_a/thumbnail");
    expect(card.querySelector("img")?.getAttribute("src")).toBe("blob:thumb");
    expect(document.querySelector('img[src^="/api/"]')).toBeNull();
  });

  it("keeps the primary action disabled until product, objective and cap are set, then creates from the picks", async () => {
    vi.mocked(createCampaignFromPicks).mockResolvedValue(draft());
    const user = userEvent.setup();
    view();
    await screen.findByRole("radio", { name: /三盒/ });
    expect(next()).toHaveProperty("disabled", true);
    expect(screen.getByText("選好商品和結果")).toBeTruthy();
    await user.click(screen.getByRole("radio", { name: /三盒/ }));
    await user.click(screen.getByRole("radio", { name: /購買/ }));
    expect(next()).toHaveProperty("disabled", true);
    expect(screen.getByText("填這個活動最多花")).toBeTruthy();
    await user.type(screen.getByLabelText("這個活動最多花"), "30000");
    expect(next()).toHaveProperty("disabled", false);
    await user.click(next());
    expect(await screen.findByText("第二步頁面")).toBeTruthy();
    expect(createCampaignFromPicks).toHaveBeenCalledWith("b1", { product_ids: ["prd_a"], objective: "購買", budget: 30000 });
    expect(readDraft("campaign-draft:u:o:b1").productId).toBeNull();
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
    expect(screen.getByRole("radio", { name: /三盒/ }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByLabelText("這個活動最多花")).toHaveProperty("value", "30000");
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
    expect(await screen.findByText(/商品和目標清單讀不到/)).toBeTruthy();
    expect(screen.queryByRole("radio")).toBeNull();
    await user.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByRole("radio", { name: /三盒/ })).toBeTruthy();
  });

  it("restores unsent picks after leaving and isolates another brand", async () => {
    const user = userEvent.setup();
    const first = view("a");
    await pickAll(user);
    first.unmount();
    const other = view("b");
    expect((await screen.findByRole("radio", { name: /三盒/ })).getAttribute("aria-checked")).toBe("false");
    other.unmount();
    view("a");
    expect((await screen.findByRole("radio", { name: /三盒/ })).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByLabelText("這個活動最多花")).toHaveProperty("value", "30000");
  });

  it("going back to a created campaign reloads its picks and patches changes instead of creating again", async () => {
    vi.mocked(getCampaign).mockResolvedValue(draft());
    vi.mocked(patchCampaign).mockResolvedValue(draft({ objective: "名單" }));
    const user = userEvent.setup();
    view("b1", "/brands/b1/ads/new?created=cmp_new");
    await waitFor(() => expect(screen.getByRole("radio", { name: /三盒/ }).getAttribute("aria-checked")).toBe("true"));
    expect(screen.getByLabelText("這個活動最多花")).toHaveProperty("value", "30000");
    expect(screen.getByLabelText("開始")).toHaveProperty("value", "");
    await user.click(screen.getByRole("radio", { name: /名單/ }));
    await user.click(next());
    expect(await screen.findByText("第二步頁面")).toBeTruthy();
    expect(patchCampaign).toHaveBeenCalledWith("b1", "cmp_new", { objective: "名單" });
    expect(createCampaignFromPicks).not.toHaveBeenCalled();
  });

  it("one-sentence create under 進階: keeps a failed submission and clears the draft only after success", async () => {
    const user = userEvent.setup();
    vi.mocked(createCampaign).mockRejectedValueOnce(new Error("離線"));
    view("save");
    await user.click(await screen.findByRole("button", { name: /進階/ }));
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
    await user.click(await screen.findByRole("button", { name: /進階/ }));
    await user.click(screen.getByRole("button", { name: "請 AI 依品牌資料建議" }));
    await waitFor(() => expect(createCampaign).toHaveBeenCalledTimes(1));
    expect(createCampaign).toHaveBeenCalledWith("known", { goal_text: expect.stringContaining("沿用已知資訊") });
  });

  it("keeps a failed AI request editable and does not replace a written goal", async () => {
    vi.mocked(createCampaign).mockRejectedValueOnce(new Error("暫時無法連線"));
    const user = userEvent.setup();
    view("retry-ai");
    await user.click(await screen.findByRole("button", { name: /進階/ }));
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

  it("sends the sentence with the picks when both are given, and the cap with a sentence-only create", async () => {
    vi.mocked(createCampaignFromPicks).mockResolvedValue(draft());
    const user = userEvent.setup();
    view();
    await pickAll(user);
    await user.click(screen.getByRole("button", { name: /進階/ }));
    await user.type(screen.getByLabelText("你這次想做到什麼？"), "主打上班族");
    await user.click(next());
    await screen.findByText("第二步頁面");
    expect(createCampaignFromPicks).toHaveBeenCalledWith("b1", { product_ids: ["prd_a"], objective: "購買", budget: 30000, goal_text: "主打上班族" });
  });

  it("keeps the brand's own images／videos folded under 進階", async () => {
    const user = userEvent.setup();
    view();
    await screen.findByRole("radio", { name: /三盒/ });
    expect(screen.queryByText("選擇已完成素材")).toBeNull();
    await user.click(screen.getByRole("button", { name: /進階/ }));
    expect(screen.getByText("選擇已完成素材")).toBeTruthy();
  });
});

/** Prototype `#/new` (F40, drill-7 #10): the form opens pre-filled from the latest non-draft campaign. */
describe("new-campaign wizard step 1 pre-filled from the previous campaign (F40-I12)", () => {
  const bar = () => screen.queryByText("照上一期「9 月第一期」帶入，可改");
  const values = () => ({
    platform: (screen.getByLabelText("平台") as HTMLSelectElement).value,
    audience: (screen.getByLabelText("受眾方向") as HTMLInputElement).value,
    cap: (screen.getByLabelText("每賣一筆上限") as HTMLInputElement).value,
    landing: (screen.getByLabelText("落地頁") as HTMLInputElement).value,
  });

  it("shows the bar and the four values under 這次怎麼投, the period after the previous one, and sends the four keys", async () => {
    withPrevious();
    vi.mocked(createCampaignFromPicks).mockResolvedValue(draft());
    const user = userEvent.setup();
    view("p1");
    expect(await screen.findByText("照上一期「9 月第一期」帶入，可改")).toBeTruthy();
    expect(screen.getByText("每一格都能直接改；沒改的就照上一期")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "這次怎麼投" })).toBeTruthy();
    expect(values()).toEqual({ platform: "meta", audience: "新客為主、探索一組", cap: "450", landing: PREV_URL });
    expect(screen.getByText("從「追蹤」分頁搬來")).toBeTruthy();
    expect(screen.getByText("上一期 450・比打平線 520 低 70")).toBeTruthy();
    expect(screen.getByRole("radio", { name: /三盒/ }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: /購買/ }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByLabelText("開始")).toHaveProperty("value", "2026-10-03");
    expect(screen.getByLabelText("結束")).toHaveProperty("value", "2026-10-09");
    expect(screen.getByLabelText("這個活動最多花")).toHaveProperty("value", "10500");
    expect(screen.getByText("日期接在上一期後面（上一期 09/26～10/02）；金額照上一期")).toBeTruthy();
    expect(next()).toHaveProperty("disabled", false);
    await user.click(next());
    expect(await screen.findByText("第二步頁面")).toBeTruthy();
    expect(createCampaignFromPicks).toHaveBeenCalledWith("p1", { ...PREV_PICKS, ...PREV_EXTRAS });
  });

  it("an edited value goes out as edited; a cap above the 打平線 reads 高", async () => {
    withPrevious();
    vi.mocked(createCampaignFromPicks).mockResolvedValue(draft());
    const user = userEvent.setup();
    view("p2");
    await screen.findByText("照上一期「9 月第一期」帶入，可改");
    await user.selectOptions(screen.getByLabelText("平台"), "google_ads");
    await user.clear(screen.getByLabelText("每賣一筆上限"));
    await user.type(screen.getByLabelText("每賣一筆上限"), "600");
    expect(screen.getByText("比打平線 520 高 80")).toBeTruthy();
    await user.clear(screen.getByLabelText("落地頁"));
    await user.click(next());
    await screen.findByText("第二步頁面");
    // The cleared landing URL is left out so the server copies the previous one (F40-I04).
    expect(createCampaignFromPicks).toHaveBeenCalledWith("p2", { ...PREV_PICKS, platform: "google_ads", audience_hint: "新客為主、探索一組", cap: 600 });
  });

  it("清空重填 empties every field, hides the bar and disables 下一步 until the required fields are set again", async () => {
    withPrevious();
    const user = userEvent.setup();
    view("p3");
    await screen.findByText("照上一期「9 月第一期」帶入，可改");
    await user.click(screen.getByRole("button", { name: "清空重填" }));
    expect(bar()).toBeNull();
    expect(values()).toEqual({ platform: "", audience: "", cap: "", landing: "" });
    expect(screen.getByRole("radio", { name: /三盒/ }).getAttribute("aria-checked")).toBe("false");
    expect(screen.getByLabelText("開始")).toHaveProperty("value", "");
    expect(screen.getByLabelText("這個活動最多花")).toHaveProperty("value", "");
    expect(screen.queryByText(/日期接在上一期後面/)).toBeNull();
    expect(next()).toHaveProperty("disabled", true);
    expect(screen.getByText("選好商品和結果")).toBeTruthy();
    // The 打平線 belongs to the previous product: it comes back as a hint once that product is picked again.
    expect(screen.queryByText(/打平線/)).toBeNull();
    await user.click(screen.getByRole("radio", { name: /三盒/ }));
    expect(screen.getByText("打平線 520；上限不超過它才有賺")).toBeTruthy();
    await user.click(screen.getByRole("radio", { name: /購買/ }));
    await user.type(screen.getByLabelText("這個活動最多花"), "30000");
    expect(next()).toHaveProperty("disabled", false);
  });

  it("keeps the draft's own picks and dates, filling only what the draft lacks", async () => {
    withPrevious();
    saveDraft("campaign-draft:u:o:p4", { productId: "prd_b", objective: "名單", startDate: "2026-11-01", endDate: "2026-11-07", budget: null, goalText: "" });
    view("p4");
    await screen.findByText("照上一期「9 月第一期」帶入，可改");
    expect(screen.getByRole("radio", { name: /終極組合包/ }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("radio", { name: /名單/ }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByLabelText("開始")).toHaveProperty("value", "2026-11-01");
    expect(screen.getByLabelText("這個活動最多花")).toHaveProperty("value", "10500");
    expect(screen.getByText("金額照上一期")).toBeTruthy();
    expect(values()).toEqual({ platform: "meta", audience: "新客為主、探索一組", cap: "450", landing: PREV_URL });
    // Another product: the previous cap still shows, its 打平線 does not (unknown for this product).
    expect(screen.getByText("上一期 450")).toBeTruthy();
    expect(screen.queryByText(/打平線/)).toBeNull();
  });

  it("without a previous campaign (or when the list cannot be read) the form opens as today", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([card("cmp_draft", "draft", "2026-09-29T00:00:00Z")]);
    const first = view("p5");
    await screen.findByRole("radio", { name: /三盒/ });
    expect(bar()).toBeNull();
    expect(values()).toEqual({ platform: "", audience: "", cap: "", landing: "" });
    expect(next()).toHaveProperty("disabled", true);
    expect(getCampaign).not.toHaveBeenCalled();
    first.unmount();
    vi.mocked(listCampaigns).mockRejectedValue(new Error("離線"));
    view("p5");
    await screen.findByRole("radio", { name: /三盒/ });
    expect(bar()).toBeNull();
    expect(values().platform).toBe("");
  });

  it("going back to a created campaign shows its own values without the bar and PATCHes what changed", async () => {
    vi.mocked(listCampaigns).mockResolvedValue([card("cmp_prev", "live", "2026-09-25T00:00:00Z")]);
    const created = draft({ context_json: { product_ids: ["prd_a"], audience_hint: "上班族", landing_url: "https://a.tw/x", field_sources: { dates: "system" } }, constraints_json: { budget: 30000, platform: "meta" } });
    vi.mocked(getCampaign).mockResolvedValue(created);
    vi.mocked(patchCampaign).mockResolvedValue(created);
    const user = userEvent.setup();
    view("p6", "/brands/p6/ads/new?created=cmp_new");
    await waitFor(() => expect(values()).toEqual({ platform: "meta", audience: "上班族", cap: "", landing: "https://a.tw/x" }));
    expect(bar()).toBeNull();
    expect(listCampaigns).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText("落地頁"));
    await user.type(screen.getByLabelText("落地頁"), "https://a.tw/y");
    await user.click(next());
    expect(await screen.findByText("第二步頁面")).toBeTruthy();
    expect(patchCampaign).toHaveBeenCalledWith("p6", "cmp_new", { landing_url: "https://a.tw/y" });
    expect(createCampaignFromPicks).not.toHaveBeenCalled();
  });
});
