import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/libraryApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/libraryApi")>("@/lib/libraryApi");
  return { ...actual, fetchLibrary: vi.fn() };
});
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ refreshBrands: vi.fn() }) }));
vi.mock("./tabs/FactsTab", () => ({ FactsTab: () => <p>品牌事實內容</p> }));
vi.mock("./tabs/RulesTab", () => ({ RulesTab: () => <p>限制規則內容</p> }));
vi.mock("./tabs/ClaimsTab", () => ({ ClaimsTab: () => <p>宣稱內容</p> }));
vi.mock("./tabs/AssetsTab", () => ({ AssetsTab: () => <p>官方素材內容</p> }));
vi.mock("./tabs/ChannelsTab", () => ({ ChannelsTab: () => <p>自有渠道內容</p> }));
vi.mock("./tabs/CustomerVoiceTab", () => ({ CustomerVoiceTab: () => <p>顧客原話內容</p> }));
vi.mock("./tabs/ResearchReportsTab", () => ({ ResearchReportsTab: () => <p>調研報告內容</p> }));
vi.mock("./tabs/CoordinatesTab", () => ({ CoordinatesTab: () => <p>創意座標內容</p> }));

import { fetchLibrary, type LibraryData } from "@/lib/libraryApi";
import { LibraryPage } from "./LibraryPage";

const mockFetchLibrary = vi.mocked(fetchLibrary);
const DATA: LibraryData = {
  brand: { id: "brand-1", name: "測試品牌", client_name: null, status: "active", market_region: "TW", conversion_goal: "purchase", advertising_history: null, delete_impact: [] },
  products: [], facts: [], rules: [], claims: [], assets: [], channels: [], customer_voices: [],
};

function view(entry = "/brands/brand-1/library") {
  mockFetchLibrary.mockResolvedValue(DATA);
  return render(<MemoryRouter initialEntries={[entry]}><LibraryPage brandId="brand-1" /></MemoryRouter>);
}

afterEach(() => vi.clearAllMocks());

describe("LibraryPage 一般與進階內容", () => {
  it("預設顯示品牌事實，宣稱也留在一般層可直接進入", async () => {
    view();
    expect(await screen.findByText("品牌事實內容")).toBeTruthy();
    expect(screen.getByRole("button", { name: /品牌事實/ }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: /宣稱/ })).toBeTruthy();
    expect(screen.getByText("進階內容").closest("details")?.open).toBe(false);
  });

  it("既有創意座標深連結會打開同頁進階區，也能切到另一個進階分類", async () => {
    view("/brands/brand-1/library?tab=coordinates");
    expect(await screen.findByText("創意座標內容")).toBeTruthy();
    expect(screen.getByText("進階內容").closest("details")?.open).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "調研報告" }));
    expect(await screen.findByText("調研報告內容")).toBeTruthy();
  });
});
