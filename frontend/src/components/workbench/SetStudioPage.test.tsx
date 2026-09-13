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
  return { ...actual, getSet: vi.fn(), runProduct: vi.fn() };
});
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ brands: [{ brand_id: "brd_1", brand_name: "測試品牌" }] }),
}));

import type { SetDetail } from "@/lib/workbenchApi";
import { getSet, runProduct } from "@/lib/workbenchApi";
import { SetStudioPage } from "./SetStudioPage";

const mockGetSet = vi.mocked(getSet);
const mockRunProduct = vi.mocked(runProduct);

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
    source_kind: "free_job",
    lock: { locked: false, reason: null },
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

const LOCK_REASON = "測試用鎖定理由，不是元件裡打死的字串";

describe("SetStudioPage 四個控制（F02-I17）", () => {
  it("已核准（schedule_node + locked）：顯示到投放中心連結、顯示鎖定理由、選定按鈕全部停用", async () => {
    mockGetSet.mockResolvedValue(
      setDetail({ source_kind: "schedule_node", lock: { locked: true, reason: LOCK_REASON } }),
    );
    renderStudio();

    const link = await screen.findByRole("link", { name: /到投放中心/ });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads");
    expect(screen.getByText(LOCK_REASON)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "選定" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("未核准（free_job + unlocked）：不顯示到投放中心連結、按鈕可點", async () => {
    mockGetSet.mockResolvedValue(
      setDetail({ source_kind: "free_job", lock: { locked: false, reason: null } }),
    );
    renderStudio();

    await screen.findByRole("button", { name: "選定" });
    expect(screen.queryByRole("link", { name: /到投放中心/ })).toBeNull();
    expect(
      (screen.getByRole("button", { name: "選定" }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it("相似版本：用該版本產出的數量呼叫 runProduct 一次", async () => {
    mockRunProduct.mockResolvedValue(setDetail());
    mockGetSet.mockResolvedValue(
      setDetail({
        products: {
          image_prompt: {
            state: "未生成",
            selected: 0,
            required: 1,
            generation_settings: { count: 6 },
            versions: [
              {
                id: "ver_1",
                version_index: 1,
                generation_round: 1,
                selected_at: null,
                body: null,
                prompt_cards: [{ label: "①主圖", text: "文字" }],
              },
            ],
          },
        },
      }),
    );
    renderStudio();

    const similarButton = await screen.findByRole("button", { name: "相似版本" });
    await userEvent.click(similarButton);

    expect(mockRunProduct).toHaveBeenCalledTimes(1);
    expect(mockRunProduct).toHaveBeenCalledWith("brd_1", "set_1", "image_prompt", 6);
  });

  it("修改需求：切到精準控制，出現產出數量輸入框", async () => {
    mockGetSet.mockResolvedValue(setDetail());
    renderStudio();

    const editButton = await screen.findByRole("button", { name: "修改需求" });
    expect(screen.queryByLabelText("產出數量")).toBeNull();
    await userEvent.click(editButton);
    expect(screen.getByLabelText("產出數量")).toBeTruthy();
  });
});
