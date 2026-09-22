import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getCampaign, type CampaignDetail } from "@/lib/adsApi";
import { completeExternalView } from "@/lib/adsExternalApi";
import { CampaignWorkspace } from "./CampaignWorkspace";
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ brands: [], scope: "test" }) }));
vi.mock("@/lib/adsApi", () => ({ getCampaign: vi.fn() }));
vi.mock("@/lib/adsLaunchApi", () => ({ fetchChannels: vi.fn().mockResolvedValue([]) }));
vi.mock("@/lib/adsExternalApi", () => ({ completeExternalView: vi.fn(), syncCampaign: vi.fn(), syncJob: vi.fn() }));
vi.mock("./AdsHomePage", () => ({ STATUS_LABEL: { draft: "草稿" }, STATUS_TONE: { draft: "secondary" } }));
vi.mock("./OverviewTab", () => ({ OverviewTab: () => <h2>共用總覽</h2> }));
vi.mock("./StrategyTab", () => ({ StrategyTab: () => <h2>共用策略</h2> }));
vi.mock("./DeliveryTab", () => ({ DeliveryTab: () => <h2>共用結構</h2> }));
vi.mock("./AssetsTab", () => ({ AssetsTab: () => <h2>共用素材</h2> }));
vi.mock("./ReviewPanel", () => ({ ReviewPanel: () => <h2>單則廣告檢討</h2> }));
vi.mock("./PerformanceTab", () => ({ PerformanceTab: () => <h2>共用成效</h2> }));
vi.mock("./PublishPage", () => ({ PublishPage: () => <h2>發布</h2> }));
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getCampaign).mockResolvedValue({ id: "c", name: "真實活動", origin: "imported", status: "draft", groups: [] } as unknown as CampaignDetail);
  vi.mocked(completeExternalView).mockResolvedValue({ entities: [], observations: [], next_entity_cursor: null, next_observation_cursor: null, window: { start: "2026-08-20", end: "2026-09-18" }, connections: [], sync: {}, coverage: {} });
});
it("routes imported campaigns through the same five tab components", async () => {
  render(<MemoryRouter><CampaignWorkspace brandId="b" campaignId="c" /></MemoryRouter>);
  await screen.findByText("共用總覽");
  for (const [label, content] of [["策略", "共用策略"], ["投放結構", "共用結構"], ["素材", "共用素材"], ["成效", "共用成效"]]) {
    fireEvent.click(screen.getByRole("button", { name: label }));
    if (label === "成效") { expect(await screen.findByText("單則廣告檢討")).toBeTruthy(); fireEvent.click(screen.getByRole("button", { name: "查看平台原始成效圖表" })); }
    expect(await screen.findByText(content)).toBeTruthy();
  }
  expect(completeExternalView).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: "選擇上架方式" })).toBeNull();
});
it("offers retry when complete native data cannot be loaded", async () => {
  vi.mocked(completeExternalView).mockRejectedValueOnce(new Error("第二頁讀取失敗"));
  render(<MemoryRouter><CampaignWorkspace brandId="b" campaignId="c" /></MemoryRouter>);
  await screen.findByText("第二頁讀取失敗");
  fireEvent.click(screen.getByRole("button", { name: "重新載入" }));
  await screen.findByText("共用總覽");
});
it("does not request external data for internal campaigns", async () => {
  vi.mocked(getCampaign).mockResolvedValue({ id: "c", name: "內部活動", origin: "internal", status: "draft", groups: [] } as unknown as CampaignDetail);
  render(<MemoryRouter><CampaignWorkspace brandId="b" campaignId="c" /></MemoryRouter>);
  await screen.findByText("共用總覽");
  expect(completeExternalView).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "選擇上架方式" })).toBeTruthy();
});
it("opens the platform performance disclosure by default when the URL highlights an ad", async () => {
  render(
    <MemoryRouter initialEntries={["/?tab=performance&ad=ad_1"]}>
      <CampaignWorkspace brandId="b" campaignId="c" />
    </MemoryRouter>,
  );
  await screen.findByText("單則廣告檢討");
  expect(await screen.findByText("共用成效")).toBeTruthy();
  expect(screen.getByRole("button", { name: "查看平台原始成效圖表" }).getAttribute("aria-expanded")).toBe("true");
});
it("keeps the platform performance disclosure collapsed without an ad highlight", async () => {
  render(
    <MemoryRouter initialEntries={["/?tab=performance"]}>
      <CampaignWorkspace brandId="b" campaignId="c" />
    </MemoryRouter>,
  );
  await screen.findByText("單則廣告檢討");
  expect(screen.getByRole("button", { name: "查看平台原始成效圖表" }).getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByText("共用成效")).toBeNull();
});

