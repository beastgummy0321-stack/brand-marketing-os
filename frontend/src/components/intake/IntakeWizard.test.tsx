/** frontend/src/components/intake/IntakeWizard.test.tsx — 票 04（plan-quality）：品牌從沒建檔過
 * （`GET .../draft` 404）跟品牌建檔已完成，都要能開新一輪調研，不能卡在「找不到建檔進度」
 * 空狀態或只剩「前往品牌頁」。全程假 fetchIntakeDraft／fetchTruthCard，不連任何伺服器
 * （跟 `frontend/src/components/auth/OrgMenu.test.tsx` 同一套 importActual+覆寫的假法）。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeApi")>("@/lib/intakeApi");
  return { ...actual, fetchIntakeDraft: vi.fn() };
});
vi.mock("@/lib/intakeT2Api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeT2Api")>("@/lib/intakeT2Api");
  return { ...actual, fetchTruthCard: vi.fn(), fetchPersonas: vi.fn().mockRejectedValue(new Error("not mocked")) };
});
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ refreshBrands: vi.fn() }),
}));

import type { IntakeDraft } from "@/lib/intakeApi";
import { fetchIntakeDraft } from "@/lib/intakeApi";
import { fetchTruthCard } from "@/lib/intakeT2Api";
import { IntakeWizard } from "./IntakeWizard";

const mockFetchIntakeDraft = vi.mocked(fetchIntakeDraft);
const mockFetchTruthCard = vi.mocked(fetchTruthCard);

afterEach(() => {
  vi.clearAllMocks();
});

function renderWizard(brandId: string) {
  return render(
    <MemoryRouter>
      <IntakeWizard brandId={brandId} />
    </MemoryRouter>,
  );
}

describe("IntakeWizard", () => {
  it("品牌從沒建檔過（draft 404）時顯示重新調研表單，不是找不到建檔進度空狀態", async () => {
    mockFetchIntakeDraft.mockRejectedValue(new Error("找不到建檔進度"));

    renderWizard("brd_x");

    await waitFor(() => expect(screen.getByText("開始這一輪調研")).toBeTruthy());
    expect(screen.queryByText("找不到建檔進度")).toBeNull();
  });

  it("建檔已完成的品牌按「再跑一次調研」會換成重新調研表單", async () => {
    mockFetchIntakeDraft.mockResolvedValue({ completed: true, brand_name: "測試品牌", step: 5, photos: [] } as unknown as IntakeDraft);
    mockFetchTruthCard.mockResolvedValue({ accepted: [], needs_confirmation: [], forbidden: [] });

    renderWizard("brd_done");

    const restartButton = await screen.findByText("再跑一次調研");
    await userEvent.click(restartButton);

    await waitFor(() => expect(screen.getByText("開始這一輪調研")).toBeTruthy());
  });
});
