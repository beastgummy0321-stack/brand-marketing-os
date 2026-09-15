/** frontend/src/components/workbench/VisualSpecWarnings.test.tsx — F07-I12（F07 Decision 24）：
 * 每一句警告文字跟「去品牌智庫」連結都是 `getVisualSpec` 給的，這支不重打規則；沒有警告或
 * fetch 失敗就整個不顯示，不當作錯誤處理。 */
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/workbenchApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/workbenchApi")>("@/lib/workbenchApi");
  return { ...actual, getVisualSpec: vi.fn() };
});

import { getVisualSpec } from "@/lib/workbenchApi";
import { VisualSpecWarnings } from "./VisualSpecWarnings";

const mockGetVisualSpec = vi.mocked(getVisualSpec);

afterEach(() => {
  vi.clearAllMocks();
});

function renderWarnings(brandId = "brd_1") {
  return render(
    <MemoryRouter>
      <VisualSpecWarnings brandId={brandId} />
    </MemoryRouter>,
  );
}

describe("VisualSpecWarnings（F07-I12）", () => {
  it("一則警告：逐字顯示 text，並附「去品牌智庫」連結，href 逐字等於 API 給的 href", async () => {
    mockGetVisualSpec.mockResolvedValue({
      warnings: [
        {
          text: "視覺基礎裡有 3 句「不要／避免」這類限制；限制太多會鎖死整張圖的設計，建議只留最重要的一兩句。",
          href: "/brands/brd_1/library?tab=facts",
        },
      ],
    });

    renderWarnings("brd_1");

    expect(mockGetVisualSpec).toHaveBeenCalledWith("brd_1");
    expect(
      await screen.findByText(
        "視覺基礎裡有 3 句「不要／避免」這類限制；限制太多會鎖死整張圖的設計，建議只留最重要的一兩句。",
      ),
    ).toBeTruthy();
    const link = screen.getByRole("link", { name: "去品牌智庫" });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/library?tab=facts");
  });

  it("多則警告：每一則都逐字渲染，不是只顯示第一則", async () => {
    mockGetVisualSpec.mockResolvedValue({
      warnings: [
        { text: "第一則警告文字", href: "/brands/brd_1/library?tab=facts" },
        { text: "第二則警告文字", href: "/brands/brd_1/library?tab=facts&x=2" },
      ],
    });

    renderWarnings("brd_1");

    expect(await screen.findByText("第一則警告文字")).toBeTruthy();
    expect(screen.getByText("第二則警告文字")).toBeTruthy();
    const links = screen.getAllByRole("link", { name: "去品牌智庫" });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/brands/brd_1/library?tab=facts",
      "/brands/brd_1/library?tab=facts&x=2",
    ]);
  });

  it("沒有警告：什麼都不渲染", async () => {
    mockGetVisualSpec.mockResolvedValue({ warnings: [] });

    const { container } = renderWarnings("brd_1");

    await waitFor(() => expect(mockGetVisualSpec).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  it("getVisualSpec 失敗：不渲染任何內容、不丟未接的 rejection", async () => {
    mockGetVisualSpec.mockRejectedValue(new Error("網路錯誤"));

    const { container } = renderWarnings("brd_1");

    await waitFor(() => expect(mockGetVisualSpec).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
    expect(screen.queryByText("網路錯誤")).toBeNull();
  });
});
