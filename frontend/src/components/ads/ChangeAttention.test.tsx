/** frontend/src/components/ads/ChangeAttention.test.tsx — F19-I02 review repair (d) + re-review：
 * `pending_count === 0` 時整塊不渲染（不印「目前沒有待確認的變更清單」）；讀取中也不佔版面
 * （沒有「正在整理待確認清單…」卡片，不閃一下把佇列卡往下推）；讀取失敗仍要現身讓使用者
 * 看得到、能重試；有待確認清單時內容照舊。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { getChangeControlSummary, type ChangeControlSummary } from "@/lib/adsChangeApi";
import { ChangeAttention } from "./ChangeAttention";

vi.mock("@/lib/adsChangeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsChangeApi")>("@/lib/adsChangeApi");
  return { ...actual, getChangeControlSummary: vi.fn() };
});

function summary(overrides: Partial<ChangeControlSummary> = {}): ChangeControlSummary {
  return { pending_count: 0, items: [], truncated: false, ...overrides };
}

function renderIt() {
  return render(
    <MemoryRouter>
      <ChangeAttention brandId="brd_1" />
    </MemoryRouter>,
  );
}

describe("ChangeAttention（F19-I02 review repair d）", () => {
  it("pending_count 為 0：讀取中與讀取完成都不佔版面（沒有讀取中卡片閃一下）", async () => {
    vi.mocked(getChangeControlSummary).mockResolvedValue(summary({ pending_count: 0 }));
    const { container } = renderIt();

    // 讀取中：不印任何內容，不是先出現卡片再消失。
    expect(container.textContent).toBe("");
    expect(screen.queryByRole("region", { name: "需要你決定的事" })).toBeNull();

    await waitFor(() => expect(getChangeControlSummary).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: "需要你決定的事" })).toBeNull();
  });

  it("有待確認清單：照舊顯示件數與清單", async () => {
    vi.mocked(getChangeControlSummary).mockResolvedValue(
      summary({
        pending_count: 1,
        items: [{ id: "cs_1", campaign_id: "cmp_1", campaign_name: "測試 Campaign", title: "文案調整", status: "draft", pending_items: 1, unknown_items: 0 }],
      }),
    );
    renderIt();

    expect(await screen.findByRole("region", { name: "需要你決定的事" })).toBeTruthy();
    expect(screen.getByText("1 份清單需要確認或核對")).toBeTruthy();
    expect(screen.getByText("文案調整")).toBeTruthy();
  });

  it("讀取失敗：顯示錯誤與重試，按下後恢復", async () => {
    vi.mocked(getChangeControlSummary).mockRejectedValueOnce(new Error("boom"));
    renderIt();

    expect(await screen.findByRole("alert")).toBeTruthy();
    vi.mocked(getChangeControlSummary).mockResolvedValue(summary({ pending_count: 2 }));
    await userEvent.click(screen.getByRole("button", { name: "重新整理待辦" }));

    expect(await screen.findByText("2 份清單需要確認或核對")).toBeTruthy();
  });
});
