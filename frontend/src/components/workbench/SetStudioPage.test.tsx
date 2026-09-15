/** frontend/src/components/workbench/SetStudioPage.test.tsx — F02-I13／F07-I12：the half of the
 * 圖片 tab e2e cannot reach because `npm run e2e` never writes a `workbench_output` row (F02
 * Decisions, "e2e asserts only what runs with no worker and no provider key"). This test
 * hand-builds a `SetDetail` payload with a version that already exists and proves the studio
 * renders `prompt_cards`, toggles 顯示提示詞 both ways, renders the API-owned 席位保留 line from
 * the payload (not a re-spelt copy), and (F07-I12) that `version.badges`/`fingerprint_text` and
 * `copy_all_text` are rendered verbatim, never rebuilt — the same importActual+覆寫 fake as
 * `frontend/src/components/intake/IntakeWizard.test.tsx`. */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
const mockWriteText = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  Object.assign(navigator, { clipboard: { writeText: mockWriteText } });
});

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
    // U15：零版本仍要看得到「顯示提示詞」（e2e 靠這顆按鈕存在）。
    expect(screen.getByRole("button", { name: "顯示提示詞" })).toBeTruthy();
  });
});

describe("SetStudioPage 圖片 tab 的 badges／fingerprint／複製全部（F07-I12）", () => {
  const COPY_ALL_TEXT =
    "請一次生成 10 張圖，每張只照下面對應的那一段，一段一張，不要合併。\n\n第 1 張\n一位跑者在夜晚街道上衝刺";

  it("badges 依序全部渲染、fingerprint_text 逐字渲染一行、沒有這兩欄的舊版本不當機也不顯示", async () => {
    mockGetSet.mockResolvedValue(
      setDetail({
        products: {
          image_prompt: {
            state: "未生成",
            selected: 0,
            required: 3,
            generation_settings: {},
            copy_all_text: COPY_ALL_TEXT,
            versions: [
              {
                // U02：排第一位（index 0）但 badges 沒有「建議選這張」——不能靠位置推。
                id: "ver_0",
                version_index: 0,
                generation_round: 1,
                selected_at: null,
                // U02：body.round.recommended_index 跟 badges 唱反調，仍只信 badges。
                body: { round: { recommended_index: 0 } },
                prompt_cards: [{ label: "①主圖", text: "排第一位但不是建議選這張" }],
                badges: ["主力"],
                fingerprint_text: null,
              },
              {
                id: "ver_1",
                version_index: 1,
                generation_round: 1,
                selected_at: null,
                body: null,
                prompt_cards: [{ label: "①主圖", text: "一位跑者在夜晚街道上衝刺" }],
                badges: ["探索", "建議選這張"],
                fingerprint_text: "手機自然光 · 直式 · 手持 · 折扣",
              },
              {
                // pre-F07 版本：沒有 badges/fingerprint_text。
                id: "ver_2",
                version_index: 2,
                generation_round: 1,
                selected_at: null,
                body: null,
                prompt_cards: [{ label: "①主圖", text: "另一張舊版本的提示詞" }],
              },
            ],
          },
        },
      }),
    );
    renderStudio();

    await userEvent.click(await screen.findByRole("button", { name: "顯示提示詞" }));

    expect(screen.getByText("探索")).toBeTruthy();
    // U02：只有 badges 真的帶了「建議選這張」的那張卡顯示，不是位置第一的那張。
    expect(screen.getAllByText("建議選這張")).toHaveLength(1);
    expect(screen.getByText("主力")).toBeTruthy();
    expect(screen.getByText("手機自然光 · 直式 · 手持 · 折扣")).toBeTruthy();
    // U05：fingerprint_text 是 null 的那張卡不生出任何佔位字。
    expect(screen.queryByText("null")).toBeNull();
    expect(screen.queryByText("—")).toBeNull();
    // 舊版本沒有崩潰，卡片內容仍照樣渲染。
    expect(screen.getByText("另一張舊版本的提示詞")).toBeTruthy();
  });

  it("已選定版本但 API 沒有給②卡：不會自己多生成一張變體卡（U07）", async () => {
    mockGetSet.mockResolvedValue(
      setDetail({
        products: {
          image_prompt: {
            state: "已選定",
            selected: 1,
            required: 1,
            generation_settings: {},
            versions: [
              {
                id: "ver_1",
                version_index: 1,
                generation_round: 1,
                selected_at: "2026-09-15T00:00:00Z",
                body: null,
                prompt_cards: [{ label: "①主圖", text: "只有主圖，沒有變體" }],
              },
            ],
          },
        },
      }),
    );
    renderStudio();

    await userEvent.click(await screen.findByRole("button", { name: "顯示提示詞" }));
    expect(screen.getByText("只有主圖，沒有變體")).toBeTruthy();
    expect(screen.queryByText(/②/)).toBeNull();
  });

  it("複製全部提示詞：複製的內容逐字等於 copy_all_text，不是 prompt_cards 拼出來的字串", async () => {
    mockGetSet.mockResolvedValue(
      setDetail({
        products: {
          image_prompt: {
            state: "未生成",
            selected: 0,
            required: 1,
            generation_settings: {},
            copy_all_text: COPY_ALL_TEXT,
            versions: [
              {
                id: "ver_1",
                version_index: 1,
                generation_round: 1,
                selected_at: null,
                body: null,
                prompt_cards: [{ label: "①主圖", text: "一位跑者在夜晚街道上衝刺" }],
              },
            ],
          },
        },
      }),
    );
    renderStudio();

    const copyAllButton = await screen.findByRole("button", { name: "複製全部提示詞" });
    await userEvent.click(copyAllButton);

    expect(mockWriteText).toHaveBeenCalledTimes(1);
    expect(mockWriteText).toHaveBeenCalledWith(COPY_ALL_TEXT);
  });

  it.each([["null" as const, null], ["空字串" as const, ""]])(
    "copy_all_text 是%s：不顯示複製全部按鈕",
    async (_label, copyAllText) => {
      mockGetSet.mockResolvedValue(
        setDetail({
          products: {
            image_prompt: {
              state: "未生成",
              selected: 0,
              required: 1,
              generation_settings: {},
              copy_all_text: copyAllText,
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

      await userEvent.click(await screen.findByRole("button", { name: "顯示提示詞" }));
      expect(screen.getByText("文字")).toBeTruthy();
      expect(screen.queryByRole("button", { name: "複製全部提示詞" })).toBeNull();
    },
  );
});

const LOCK_REASON = "測試用鎖定理由，不是元件裡打死的字串";

describe("SetStudioPage 四個控制（F02-I17）", () => {
  it("已核准（origin_href + locked）：顯示回到投放中心連結、顯示鎖定理由、選定按鈕全部停用", async () => {
    mockGetSet.mockResolvedValue(
      setDetail({
        source_kind: "schedule_node",
        origin_href: "/brands/brd_1/ads/campaigns/cmp_1?tab=assets",
        lock: { locked: true, reason: LOCK_REASON },
      }),
    );
    renderStudio();

    const link = await screen.findByRole("link", { name: /回到投放中心/ });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1?tab=assets");
    expect(screen.getByText(LOCK_REASON)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "選定" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("未核准（origin_href 為 null）：不顯示回到投放中心連結、按鈕可點", async () => {
    mockGetSet.mockResolvedValue(
      setDetail({ source_kind: "free_job", origin_href: null, lock: { locked: false, reason: null } }),
    );
    renderStudio();

    await screen.findByRole("button", { name: "選定" });
    expect(screen.queryByRole("link", { name: /回到投放中心/ })).toBeNull();
    expect(
      (screen.getByRole("button", { name: "選定" }) as HTMLButtonElement).disabled,
    ).toBe(false);
  });
});

describe("SetStudioPage 圖片的生成按鈕（F07-I12 Decision 28）", () => {
  it("沒有數量輸入框、兩個按鈕都叫「再生成一輪（10 張）」、呼叫 runProduct 不帶數量", async () => {
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

    const runButtons = await screen.findAllByRole("button", { name: "再生成一輪（10 張）" });
    expect(runButtons).toHaveLength(2);
    expect(screen.queryByLabelText("產出數量")).toBeNull();
    expect(screen.queryByRole("button", { name: "精準控制" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^再生成 \d+ 張$/ })).toBeNull();

    await userEvent.click(runButtons[0]);
    expect(mockRunProduct).toHaveBeenCalledTimes(1);
    expect(mockRunProduct).toHaveBeenCalledWith("brd_1", "set_1", "image_prompt", undefined);
  });

  it("相似版本：一樣不帶數量呼叫 runProduct（Decision 28 蓋過該版本自己的產出數量）", async () => {
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
    expect(mockRunProduct).toHaveBeenCalledWith("brd_1", "set_1", "image_prompt", undefined);
  });

  it("圖片版本卡不顯示「修改需求」", async () => {
    mockGetSet.mockResolvedValue(setDetail());
    renderStudio();

    await screen.findByRole("button", { name: "相似版本" });
    expect(screen.queryByRole("button", { name: "修改需求" })).toBeNull();
  });
});

function copySetDetail(): SetDetail {
  return setDetail({
    required_parts: ["copy"],
    products: {
      copy: {
        state: "未生成",
        selected: 0,
        required: 1,
        generation_settings: { count: 4 },
        versions: [
          {
            id: "cver_1",
            version_index: 1,
            generation_round: 1,
            selected_at: null,
            body: { body: "主文", headline: "標題", description: "說明" },
          },
        ],
      },
    },
  });
}

describe("SetStudioPage 文案的生成按鈕不變（F07-I12 Decision 28：只動圖片）", () => {
  it("精準控制仍有數量輸入框、按鈕文字仍是「再生成 N 張」", async () => {
    mockGetSet.mockResolvedValue(copySetDetail());
    renderStudio();

    const preciseButton = await screen.findByRole("button", { name: "精準控制" });
    expect(screen.queryByLabelText("產出數量")).toBeNull();
    await userEvent.click(preciseButton);
    expect(screen.getByLabelText("產出數量")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /^再生成 \d+ 張$/ }).length).toBeGreaterThan(0);
  });

  it("呼叫 runProduct 仍帶數量", async () => {
    mockRunProduct.mockResolvedValue(copySetDetail());
    mockGetSet.mockResolvedValue(copySetDetail());
    renderStudio();

    const runButtons = await screen.findAllByRole("button", { name: "再生成 4 張" });
    await userEvent.click(runButtons[0]);

    expect(mockRunProduct).toHaveBeenCalledWith("brd_1", "set_1", "copy", 4);
  });
});
