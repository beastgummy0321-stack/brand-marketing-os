/** frontend/src/components/workbench/SetStudioPage.test.tsx — F02-I13：the half of the 圖片 tab
 * e2e cannot reach because `npm run e2e` never writes a `workbench_output` row (F02 Decisions,
 * "e2e asserts only what runs with no worker and no provider key"). This test hand-builds a
 * `SetDetail` payload with a version that already exists and proves the studio renders
 * `prompt_cards`, toggles 顯示提示詞 both ways, and renders the API-owned 席位保留 line from the
 * payload (not a re-spelt copy) — the same importActual+覆寫 fake as
 * `frontend/src/components/intake/IntakeWizard.test.tsx`. */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/workbenchApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/workbenchApi")>("@/lib/workbenchApi");
  return { ...actual, getSet: vi.fn() };
});
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ brands: [{ brand_id: "brd_1", brand_name: "測試品牌" }] }),
}));

import type { SetDetail } from "@/lib/workbenchApi";
import { getSet } from "@/lib/workbenchApi";
import { SetStudioPage } from "./SetStudioPage";

const mockGetSet = vi.mocked(getSet);

afterEach(() => {
  vi.clearAllMocks();
});

const RESERVED_SEAT_REASON = "測試用保留席位理由，不是元件裡打死的字串";

function setDetail(overrides: Partial<SetDetail> = {}): SetDetail {
  return {
    id: "set_1",
    pack_id: "pack_1",
    pack_name: "任務包 A",
    name: "主力 C",
    status: "等待決定",
    chips: { platform: "Meta", style: "UGC", size: "4:5" },
    siblings: [{ id: "set_1", name: "主力 C", angle: null, status: "等待決定" }],
    required_parts: ["image_prompt"],
    products: {
      image_prompt: {
        state: "未生成",
        selected: 0,
        required: 1,
        generation_settings: {},
        versions: [
          {
            id: "ver_1",
            version_index: 1,
            generation_round: 1,
            selected_at: null,
            body: null,
            prompt_cards: [
              { label: "①主圖", text: "一位跑者在夜晚街道上衝刺" },
              { label: "②變體", text: "同一位跑者的近景特寫" },
            ],
          },
        ],
      },
    },
    generation_settings: [],
    image_generation: { connected: true, reason: RESERVED_SEAT_REASON },
    ...overrides,
  };
}

function renderStudio() {
  return render(
    <MemoryRouter>
      <SetStudioPage brandId="brd_1" packId="pack_1" setId="set_1" />
    </MemoryRouter>,
  );
}

describe("SetStudioPage 圖片 tab（F02-I13）", () => {
  it("有版本：顯示提示詞卡片、各自有複製按鈕、複製全部、且切換鍵兩個方向都真的有效果", async () => {
    mockGetSet.mockResolvedValue(setDetail());
    renderStudio();

    const toggle = await screen.findByRole("button", { name: "顯示提示詞" });

    // connected: true → 預設是收合的保留席位畫面，不是卡片。
    expect(screen.getByText(RESERVED_SEAT_REASON)).toBeTruthy();
    expect(screen.queryByText("一位跑者在夜晚街道上衝刺")).toBeNull();

    // 點一次：卡片出現。
    await userEvent.click(toggle);
    expect(screen.getByText("①主圖")).toBeTruthy();
    expect(screen.getByText("一位跑者在夜晚街道上衝刺")).toBeTruthy();
    expect(screen.getByText("②變體")).toBeTruthy();
    expect(screen.getByText("同一位跑者的近景特寫")).toBeTruthy();
    expect(screen.getByRole("button", { name: "複製①主圖" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "複製②變體" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "複製全部提示詞" })).toBeTruthy();

    // 再點一次：卡片收回、換回保留席位那句話（原樣渲染，不是元件自己重打的字）。
    await userEvent.click(toggle);
    expect(screen.queryByText("一位跑者在夜晚街道上衝刺")).toBeNull();
    expect(screen.getByText(RESERVED_SEAT_REASON)).toBeTruthy();
  });

  it("零版本：顯示還沒有生成過，不是提示詞卡片", async () => {
    mockGetSet.mockResolvedValue(
      setDetail({
        products: {
          image_prompt: {
            state: "未生成",
            selected: 0,
            required: 1,
            generation_settings: {},
            versions: [],
          },
        },
      }),
    );
    renderStudio();

    await waitFor(() => expect(screen.getByText("還沒有生成過")).toBeTruthy());
    expect(screen.queryByText("①主圖")).toBeNull();
  });
});
