/** frontend/src/components/workbench/PackPage.test.tsx — F07-I12（F07 Decision 29）：探索風格
 * 佔比過低的提醒逐字渲染在核准整包按鈕旁，永遠不影響 `can_approve`／`blocking_text` 算出來的
 * 按鈕停用狀態。 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/workbenchApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/workbenchApi")>("@/lib/workbenchApi");
  return { ...actual, getPack: vi.fn() };
});
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ brands: [{ brand_id: "brd_1", brand_name: "測試品牌" }] }),
}));

import type { PackDetail } from "@/lib/workbenchApi";
import { getPack } from "@/lib/workbenchApi";
import { PackPage } from "./PackPage";

const mockGetPack = vi.mocked(getPack);

afterEach(() => {
  vi.clearAllMocks();
});

function packDetail(overrides: Partial<PackDetail> = {}): PackDetail {
  return {
    id: "pack_1",
    name: "任務包 A",
    subtitle: "",
    source_kind: "free_job",
    source_label: "自由創作",
    status: "running",
    sets_total: 1,
    sets_done: 0,
    progress_pct: 0,
    next_step: null,
    counts: [],
    updated_at: "2026-09-01T00:00:00Z",
    created_at: "2026-09-01T00:00:00Z",
    source_ref: {},
    meta: { platform: "Meta", goal: null, sets_required: 1 },
    summary: {},
    completion: [],
    can_approve: true,
    blocking_text: "",
    sets: [],
    ...overrides,
  };
}

function renderPack() {
  return render(
    <MemoryRouter>
      <PackPage brandId="brd_1" packId="pack_1" />
    </MemoryRouter>,
  );
}

describe("PackPage 探索風格提醒（F07-I12）", () => {
  it("image_exploration_warning 逐字顯示在核准整包旁，且核准整包仍是可點的", async () => {
    const warning =
      "這包選定的圖裡，探索風格只有 1／10 張（少於三成），新風格很難被測到。可以在標著「建議選這張」的探索圖改選。";
    mockGetPack.mockResolvedValue(packDetail({ image_exploration_warning: warning }));
    renderPack();

    expect(await screen.findByText(warning)).toBeTruthy();
    const approveButton = screen.getByRole("button", { name: "核准整包" });
    expect((approveButton as HTMLButtonElement).disabled).toBe(false);
  });

  it("image_exploration_warning 是 null：不渲染任何提醒文字（也不是字面上的「null」）", async () => {
    mockGetPack.mockResolvedValue(packDetail({ image_exploration_warning: null }));
    renderPack();

    await screen.findByRole("button", { name: "核准整包" });
    expect(screen.queryByText(/探索風格/)).toBeNull();
    expect(screen.queryByText("null")).toBeNull();
  });

  it("can_approve 為 false 時，警告不改動按鈕的停用狀態（由 can_approve 決定）", async () => {
    const warning = "探索風格只有 1／10 張（少於三成）";
    mockGetPack.mockResolvedValue(
      packDetail({ can_approve: false, image_exploration_warning: warning }),
    );
    renderPack();

    expect(await screen.findByText(warning)).toBeTruthy();
    const approveButton = screen.getByRole("button", { name: "核准整包" });
    expect((approveButton as HTMLButtonElement).disabled).toBe(true);
  });
});
