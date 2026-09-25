import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NewCampaignPage } from "./NewCampaignPage";
import { getCampaign, patchCampaign, type CampaignDetail } from "@/lib/adsApi";
import { createCampaignFromPicks, getWizardOptions, type WizardOptions } from "@/lib/adsWizardApi";
import { useAuthedImage } from "@/lib/useAuthedImage";
import { readDraft } from "./campaignDraft";

vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "u:o" }) }));
vi.mock("@/lib/adsApi", async (original) => ({ ...await original<object>(), getCampaign: vi.fn(), patchCampaign: vi.fn() }));
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
    const reserved = screen.getByRole("radio", { name: /互動/ });
    expect(reserved).toHaveProperty("disabled", true);
    expect(within(reserved).getByText("尚未開放")).toBeTruthy();
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

  it("keeps the brand's own images／videos folded under 進階", async () => {
    const user = userEvent.setup();
    view();
    await screen.findByRole("radio", { name: /三盒/ });
    expect(screen.queryByText("選擇已完成素材")).toBeNull();
    await user.click(screen.getByRole("button", { name: /進階/ }));
    expect(screen.getByText("選擇已完成素材")).toBeTruthy();
  });
});
