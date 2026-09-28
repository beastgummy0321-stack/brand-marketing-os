/** frontend/src/components/workbench/WorkbenchHomePage.test.tsx — F36-I02 (drill-6 #5): the empty
 * brand state names the real entry (「投放結構」 → 「開始做素材 →」), no longer mentions a 派工 button
 * that does not exist, and links to the campaigns list. */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/workbenchApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/workbenchApi")>("@/lib/workbenchApi");
  return { ...actual, listPacks: vi.fn(), closePack: vi.fn() };
});
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ brands: [{ brand_id: "brd_1", brand_name: "測試品牌" }] }),
}));

import { listPacks } from "@/lib/workbenchApi";
import { WorkbenchHomePage } from "./WorkbenchHomePage";

const mockListPacks = vi.mocked(listPacks);

afterEach(() => {
  vi.clearAllMocks();
});

function renderHome(brandId = "brd_1") {
  return render(
    <MemoryRouter>
      <WorkbenchHomePage brandId={brandId} />
    </MemoryRouter>,
  );
}

describe("WorkbenchHomePage 空狀態（F36-I02）", () => {
  it("沒有任務包時，說明句指向「投放結構」→「開始做素材 →」", async () => {
    mockListPacks.mockResolvedValue([]);
    renderHome();

    expect(
      await screen.findByText(
        "＋ 自由創作 自己開一個工作；或到投放中心打開一個活動，在「投放結構」按「開始做素材 →」，任務包就會送過來。",
      ),
    ).toBeTruthy();
  });

  it("不再提到不存在的「派工」按鈕", async () => {
    mockListPacks.mockResolvedValue([]);
    renderHome();

    await screen.findByText("目前沒有任務包");
    expect(screen.queryByText(/派工/)).toBeNull();
  });

  it("空狀態下方的連結指向該品牌的投放中心活動列表", async () => {
    mockListPacks.mockResolvedValue([]);
    renderHome("brd_1");

    const link = await screen.findByRole("link", { name: "前往投放中心 →" });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns");
  });
});
