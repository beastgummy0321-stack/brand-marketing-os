/** frontend/src/components/workbench/SetStudioPage.test.tsx — F02-I13／F07-I12：the half of the
 * 圖片 tab e2e cannot reach because `npm run e2e` never writes a `workbench_output` row (F02
 * Decisions, "e2e asserts only what runs with no worker and no provider key"). This test
 * hand-builds a `SetDetail` payload with a version that already exists and proves the studio
 * renders `prompt_cards`, toggles 顯示提示詞 both ways, renders the API-owned 席位保留 line from
 * the payload (not a re-spelt copy), and (F07-I12) that `version.badges`/`fingerprint_text` and
 * `copy_all_text` are rendered verbatim, never rebuilt — the same importActual+覆寫 fake as
 * `frontend/src/components/intake/IntakeWizard.test.tsx`. */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/workbenchApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/workbenchApi")>("@/lib/workbenchApi");
  return { ...actual, getSet: vi.fn(), runProduct: vi.fn(), selectVersion: vi.fn() };
});
vi.mock("@/lib/jobsApi", async (original) => ({ ...await original<typeof import("@/lib/jobsApi")>(), fetchActiveJobs: vi.fn() }));
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ brands: [{ brand_id: "brd_1", brand_name: "測試品牌" }] }),
}));

import type { SetDetail } from "@/lib/workbenchApi";
import { getSet, runProduct, selectVersion } from "@/lib/workbenchApi";
import { fetchActiveJobs, type ActiveJobsSnapshot } from "@/lib/jobsApi";
import { ApiNetworkError } from "@/lib/http";
import { SetStudioPage } from "./SetStudioPage";

const mockGetSet = vi.mocked(getSet);
const mockRunProduct = vi.mocked(runProduct);
const mockSelectVersion = vi.mocked(selectVersion);
const mockWriteText = vi.fn().mockResolvedValue(undefined);

/** `GET /api/jobs/active` with this set's job queued; `stalled` = the worker is stopped (F47 Contract C). */
const jobs = (stalled: boolean): ActiveJobsSnapshot => ({
  data: [], total: 1, other_count: 0, done_today: 0, failed_today: 0, generated_at: "2026-10-02T02:00:00Z",
  worker_alive: !stalled, stalled,
});

beforeEach(() => {
  Object.assign(navigator, { clipboard: { writeText: mockWriteText } });
  vi.mocked(fetchActiveJobs).mockResolvedValue(jobs(false));
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

function renderStudio(entry = "/brands/brd_1/workbench/packs/pack_1/sets/set_1") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <SetStudioPage brandId="brd_1" packId="pack_1" setId="set_1" />
    </MemoryRouter>,
  );
}

describe("優惠來源僅提醒，由使用者確認", () => {
  it("顯示橘色提醒與選用入口，返回不選定、確認後完成且不再提醒", async () => {
    const detail = setDetail({ required_parts: ["copy"], products: { copy: {
      state: "待選定", selected: 0, required: 1, generation_settings: {}, versions: [{
        id: "copy_warn", version_index: 1, generation_round: 1, selected_at: null,
        body: { body: "三盒一起備著，先試用感受是否合拍" },
        claim_warning: { message: "「試用」可能包含未確認的優惠／試用／背書。", href: "/brands/brd_1/library?tab=claims" },
      }, {
        id: "copy_clean", version_index: 2, generation_round: 1, selected_at: null,
        body: { body: "配合你的高頻移動日程" }, claim_warning: null,
      }],
    } } });
    mockGetSet.mockResolvedValue(detail);
    const selected = structuredClone(detail);
    selected.products.copy!.versions[0].selected_at = "2026-09-18T00:00:00Z";
    selected.products.copy!.selected = 1;
    selected.products.copy!.state = "已選定";
    mockSelectVersion.mockResolvedValue(selected);
    renderStudio();
    expect((await screen.findByRole("status")).className).toContain("text-warning");
    expect(screen.getByRole("link", { name: "前往品牌智庫補充資料（選用）" }).getAttribute("href"))
      .toBe("/brands/brd_1/library?tab=claims");
    await userEvent.click(screen.getByRole("button", { name: "選定" }));
    expect(mockSelectVersion).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "返回查看" }));
    expect(mockSelectVersion).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "選定" }));
    await userEvent.click(screen.getByRole("button", { name: "下一版" }));
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("button", { name: "確認無誤，選定此版" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "下一版" }));
    expect(screen.queryByRole("button", { name: "確認無誤，選定此版" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "選定" }));
    await userEvent.click(screen.getByRole("button", { name: "確認無誤，選定此版" }));
    expect(mockSelectVersion).toHaveBeenCalledWith("brd_1", "set_1", "copy_warn");
    expect(await screen.findByRole("button", { name: "✓ 已選定" })).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
    expect((screen.getByRole("button", { name: "完成此素材組" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("F34 食安法提醒：列出字詞與句子，確認後仍可選定", async () => {
    const detail = setDetail({ required_parts: ["copy"], products: { copy: {
      state: "待選定", selected: 0, required: 1, generation_settings: {}, versions: [{
        id: "copy_statute", version_index: 1, generation_round: 1, selected_at: null,
        body: { body: "十分鐘內治療你的午後疲勞，幫你減肥又提神，健康食品等級的安心配方" },
        claim_warning: null,
        statutory_warning: {
          terms: [
            { term: "治療", tier_label: "醫療效能" },
            { term: "減肥", tier_label: "改變生理功能" },
            { term: "健康食品", tier_label: "未取得許可不得使用" },
          ],
          sentence: "食品廣告通常不能這樣講（食安法第 28 條）。確認無誤仍可選定。",
          href: "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0040140",
        },
      }],
    } } });
    mockGetSet.mockResolvedValue(detail);
    const selected = structuredClone(detail);
    selected.products.copy!.versions[0].selected_at = "2026-09-27T00:00:00Z";
    selected.products.copy!.selected = 1;
    selected.products.copy!.state = "已選定";
    mockSelectVersion.mockResolvedValue(selected);
    renderStudio();
    const status = await screen.findByRole("status");
    expect(status.textContent).toContain("食安法提醒");
    for (const word of ["治療", "醫療效能", "減肥", "改變生理功能", "健康食品", "未取得許可不得使用"]) {
      expect(status.textContent).toContain(word);
    }
    expect(status.textContent).toContain("食品廣告通常不能這樣講（食安法第 28 條）。確認無誤仍可選定。");
    const link = screen.getByRole("link", { name: "衛福部認定準則" });
    expect(link.getAttribute("href")).toBe("https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=L0040140");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(screen.queryByRole("link", { name: "前往品牌智庫補充資料（選用）" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "選定" }));
    expect(mockSelectVersion).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "確認無誤，選定此版" }));
    expect(mockSelectVersion).toHaveBeenCalledWith("brd_1", "set_1", "copy_statute");
    expect(await screen.findByRole("button", { name: "✓ 已選定" })).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("沒有警告的版本直接選定", async () => {
    const detail = setDetail();
    mockGetSet.mockResolvedValue(detail);
    mockSelectVersion.mockResolvedValue(detail);
    renderStudio();
    await userEvent.click(await screen.findByRole("button", { name: "選定" }));
    expect(mockSelectVersion).toHaveBeenCalledWith("brd_1", "set_1", "ver_1");
    expect(screen.queryByRole("button", { name: "確認無誤，選定此版" })).toBeNull();
  });
});

describe("F31-I04 選定上限與未通過檢查（Contract L）", () => {
  function imageVersions() {
    const base = setDetail().products.image_prompt!.versions[0];
    return [
      { ...base, id: "img_fail", version_index: 1, validation_warning: {
        lines: ["❌ items[1].prompt_leak：圖上出現分類術語：['主力']"],
      } },
      { ...base, id: "img_clean", version_index: 2, validation_warning: null },
    ];
  }

  it("有 ❌ 的版本要確認才選定，並列出沒通過的檢查", async () => {
    const detail = setDetail({ products: { image_prompt: {
      ...setDetail().products.image_prompt!, versions: imageVersions(),
    } } });
    mockGetSet.mockResolvedValue(detail);
    mockSelectVersion.mockResolvedValue(detail);
    renderStudio();

    const selectButtons = await screen.findAllByRole("button", { name: "選定" });
    expect(screen.queryByText("❌ items[1].prompt_leak：圖上出現分類術語：['主力']")).toBeNull();
    await userEvent.click(selectButtons[0]);
    expect(mockSelectVersion).not.toHaveBeenCalled();
    expect(screen.getByText("❌ items[1].prompt_leak：圖上出現分類術語：['主力']")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "確認無誤，選定此版" }));
    expect(mockSelectVersion).toHaveBeenCalledWith("brd_1", "set_1", "img_fail");
  });

  it("沒有 ❌ 的版本一鍵選定", async () => {
    const detail = setDetail({ products: { image_prompt: {
      ...setDetail().products.image_prompt!, versions: imageVersions(),
    } } });
    mockGetSet.mockResolvedValue(detail);
    mockSelectVersion.mockResolvedValue(detail);
    renderStudio();

    const selectButtons = await screen.findAllByRole("button", { name: "選定" });
    await userEvent.click(selectButtons[1]);
    expect(mockSelectVersion).toHaveBeenCalledWith("brd_1", "set_1", "img_clean");
    expect(screen.queryByRole("button", { name: "確認無誤，選定此版" })).toBeNull();
  });

  it("已選滿時其他版本的選定停用並說明要先取消", async () => {
    const [failed, clean] = imageVersions();
    mockGetSet.mockResolvedValue(setDetail({ products: { image_prompt: {
      ...setDetail().products.image_prompt!, state: "已選定", selected: 1, selection_full: true,
      versions: [{ ...clean, selected_at: "2026-09-26T00:00:00Z" }, failed],
    } } }));
    renderStudio();

    const cancel = await screen.findByRole("button", { name: "✓ 已選定" });
    expect((cancel as HTMLButtonElement).disabled).toBe(false);
    const other = screen.getByRole("button", { name: "選定" }) as HTMLButtonElement;
    expect(other.disabled).toBe(true);
    expect(screen.getByText("已選滿，先取消一張再選")).toBeTruthy();
    await userEvent.click(other);
    expect(mockSelectVersion).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "確認無誤，選定此版" })).toBeNull();
  });
});

describe("SetStudioPage 圖片 tab（F02-I13）", () => {
  it("有版本：顯示提示詞卡片、各自有複製按鈕、複製全部、且切換鍵兩個方向都真的有效果", async () => {
    mockGetSet.mockResolvedValue(setDetail());
    renderStudio();

    const toggle = await screen.findByRole("button", { name: "顯示提示詞" });

    // F12：一般層先給後端原文節錄供選擇，完整提示詞與逐張複製仍收合。
    expect(screen.getByText(RESERVED_SEAT_REASON)).toBeTruthy();
    expect(screen.getByText("①主圖 · 內容節錄")).toBeTruthy();
    expect(screen.getByText("一位跑者在夜晚街道上衝刺")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "複製①主圖" })).toBeNull();

    // 點一次：卡片出現。
    await userEvent.click(toggle);
    expect(screen.getByText("①主圖")).toBeTruthy();
    expect(screen.getByText("一位跑者在夜晚街道上衝刺")).toBeTruthy();
    expect(screen.getByText("②變體")).toBeTruthy();
    expect(screen.getByText("同一位跑者的近景特寫")).toBeTruthy();
    expect(screen.getByRole("button", { name: "複製①主圖" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "複製②變體" })).toBeTruthy();

    // 再點一次：完整提示詞收回，選擇所需的內容節錄仍在一般層。
    await userEvent.click(toggle);
    expect(screen.getByText("①主圖 · 內容節錄")).toBeTruthy();
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
    expect(screen.getAllByText(LOCK_REASON).length).toBeGreaterThan(0);
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
  it("圖片只保留一個主要再生成按鈕、不顯示數量輸入、呼叫 runProduct 不帶數量", async () => {
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
    expect(runButtons).toHaveLength(1);
    expect(screen.queryByRole("spinbutton", { name: "產出數量" })).toBeNull();
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

describe("F52-I19 fixed copy candidates", () => {
  it("states five candidate sets without a variable count, including legacy settings", async () => {
    mockGetSet.mockResolvedValue(copySetDetail());
    renderStudio();

    const advanced = await screen.findByText("進階設定");
    expect(screen.queryByRole("spinbutton", { name: "產出數量" })).toBeNull();
    await userEvent.click(advanced);
    expect(screen.queryByRole("spinbutton", { name: "產出數量" })).toBeNull();
    expect(screen.getByText("每輪提供 5 組文案候選，數量不可調整。")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "再生成一輪（5 組文案）" })).toHaveLength(1);
  });

  it("requests copy without a variable count", async () => {
    mockRunProduct.mockResolvedValue(copySetDetail());
    mockGetSet.mockResolvedValue(copySetDetail());
    renderStudio();

    const runButtons = await screen.findAllByRole("button", { name: "再生成一輪（5 組文案）" });
    await userEvent.click(runButtons[0]);

    expect(mockRunProduct).toHaveBeenCalledWith("brd_1", "set_1", "copy", undefined);
  });

  it.each([1, 2])("keeps script count %i editable and uses it on retry", async (count) => {
    const detail = setDetail({
      required_parts: ["video_script"],
      products: { video_script: {
        state: "未生成", selected: 0, required: 1, generation_settings: { count: 4 }, versions: [],
      } },
    });
    mockGetSet.mockResolvedValue(detail);
    mockRunProduct.mockResolvedValueOnce({ ...detail, generation: { status: "failed", error: "腳本生成失敗" },
      products: { video_script: { ...detail.products.video_script!, generation_settings: { count } } },
    }).mockResolvedValueOnce({ ...detail, generation: { status: "queued", error: null } });
    renderStudio();
    await userEvent.click(await screen.findByText("進階設定"));
    const input = screen.getByRole("spinbutton", { name: "產出數量" });
    fireEvent.change(input, { target: { value: String(count) } });
    await userEvent.click(screen.getByRole("button", { name: `再生成 ${count} 張` }));
    expect(mockRunProduct).toHaveBeenCalledWith("brd_1", "set_1", "video_script", count);
    expect(screen.getByRole("spinbutton", { name: "產出數量" })).toHaveProperty("value", String(count));
    await userEvent.click(await screen.findByRole("button", { name: "重新生成" }));
    expect(mockRunProduct).toHaveBeenLastCalledWith("brd_1", "set_1", "video_script", count);
    expect(mockRunProduct).toHaveBeenCalledTimes(2);
  });
});

describe("F12 一般選擇與同頁詳情", () => {
  it("生成快照預設收合，展開後逐字顯示且仍不可編輯", async () => {
    mockGetSet.mockResolvedValue(
      setDetail({
        generation_settings: [
          { label: "品牌視覺", text: "冷色、留白、清楚層級" },
          { label: "風格分配", text: "主力：明亮乾淨；探索：紀實自然光" },
        ],
      }),
    );
    renderStudio();

    const advanced = await screen.findByText("進階設定");
    const details = advanced.closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    await userEvent.click(advanced);
    expect(details.open).toBe(true);
    expect(screen.getByText("冷色、留白、清楚層級")).toBeTruthy();
    expect(screen.getByText("本次生成快照（唯讀）")).toBeTruthy();
    expect(screen.queryByDisplayValue("冷色、留白、清楚層級")).toBeNull();
  });

  it("未選部分在一般層具名且可直達", async () => {
    const image = setDetail().products.image_prompt!;
    mockGetSet.mockResolvedValue(
      setDetail({
        required_parts: ["image_prompt", "copy"],
        products: {
          image_prompt: { ...image, state: "已選定", selected: 1 },
          copy: copySetDetail().products.copy,
        },
      }),
    );
    renderStudio();

    expect(await screen.findByText("完成前尚需選定：")).toBeTruthy();
    const missingLinks = screen.getAllByRole("button", { name: "文案" });
    await userEvent.click(missingLinks[0]);
    expect(screen.getByText("文案：未生成")).toBeTruthy();
    expect((screen.getByRole("button", { name: "完成此素材組" }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it("必要部分都已選定時，完成按鈕可用", async () => {
    const image = setDetail().products.image_prompt!;
    mockGetSet.mockResolvedValue(
      setDetail({
        status: "已完成",
        products: { image_prompt: { ...image, state: "已選定", selected: 1 } },
      }),
    );
    renderStudio();

    const finish = await screen.findByRole("button", { name: "完成此素材組" });
    expect((finish as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText("完成前尚需選定：")).toBeNull();
  });

  it("part 深連結直接打開指定的未完成分頁", async () => {
    const image = setDetail().products.image_prompt!;
    mockGetSet.mockResolvedValue(
      setDetail({
        required_parts: ["image_prompt", "copy"],
        products: { image_prompt: image, copy: copySetDetail().products.copy },
      }),
    );
    renderStudio("/brands/brd_1/workbench/packs/pack_1/sets/set_1?part=copy");

    expect(await screen.findByText("文案：未生成")).toBeTruthy();
    expect(screen.getAllByText("主文").length).toBeGreaterThan(0);
  });
});

describe("background generation", () => {
  it("shows active work and refreshes completed output without reload", async () => {
    vi.useFakeTimers();
    const pending = setDetail({ generation: { status: "running", error: null }, products: { image_prompt: { state: "未生成", selected: 0, required: 1, generation_settings: {}, versions: [] } } });
    mockGetSet.mockResolvedValueOnce(pending).mockResolvedValue(setDetail({ generation: { status: "done", error: null } }));
    const view = renderStudio();
    try {
      await act(async () => {});
      expect(screen.getByText("素材生成中，完成後會自動更新。")).toBeTruthy();
      expect(screen.queryByText("還沒有生成過")).toBeNull();
      expect((screen.getByRole("button", { name: "素材生成中，完成後才能再生成" }) as HTMLButtonElement).disabled).toBe(true);
      await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
      expect(screen.queryByText("素材生成中，完成後會自動更新。")).toBeNull();
      expect(screen.getByRole("button", { name: "顯示提示詞" })).toBeTruthy();
    } finally { view.unmount(); vi.useRealTimers(); }
  });
  it("keeps failure distinct from never generated and permits retry", async () => {
    mockGetSet.mockResolvedValue(setDetail({ generation: { status: "failed", error: "服務暫時離線" }, products: { image_prompt: { state: "未生成", selected: 0, required: 1, generation_settings: {}, versions: [] } } }));
    renderStudio();
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("服務暫時離線"));
    expect(screen.queryByText("還沒有生成過")).toBeNull();
    expect((screen.getAllByRole("button", { name: "再生成一輪（10 張）" })[0] as HTMLButtonElement).disabled).toBe(false);
  });
});

describe("F40-I11 再生成按鈕說明是哪個部分在生成（drill-7 #16）", () => {
  function twoPartDetail(overrides: Partial<SetDetail> = {}): SetDetail {
    const image = setDetail().products.image_prompt!;
    return setDetail({
      required_parts: ["copy", "image_prompt"],
      products: {
        copy: { ...copySetDetail().products.copy!, state: "待選定" },
        image_prompt: { ...image, state: "待選定" },
      },
      ...overrides,
    });
  }

  it("閒置時是「再生成 N 張」；本頁按了文案後，文案鍵是「生成中…」、圖片鍵寫明正在生成文案", async () => {
    const idle = twoPartDetail();
    mockGetSet.mockResolvedValue(idle);
    mockRunProduct.mockResolvedValue(twoPartDetail({ generation: { status: "queued", error: null } }));
    renderStudio("/brands/brd_1/workbench/packs/pack_1/sets/set_1?part=copy");

    const run = await screen.findByRole("button", { name: "再生成一輪（5 組文案）" });
    expect((run as HTMLButtonElement).disabled).toBe(false);
    await userEvent.click(run);
    expect(mockRunProduct).toHaveBeenCalledWith("brd_1", "set_1", "copy", undefined);
    const own = await screen.findByRole("button", { name: "生成中…" });
    expect((own as HTMLButtonElement).disabled).toBe(true);
    expect(own.getAttribute("title")).toBeNull();

    await userEvent.click(screen.getByRole("tab", { name: "圖片" }));
    const other = await screen.findByRole("button", { name: "正在生成文案，完成後才能再生成" });
    expect((other as HTMLButtonElement).disabled).toBe(true);
    expect(other.getAttribute("title")).toBe("正在生成文案，完成後才能再生成");
    expect(other.textContent).toBe("正在生成文案，完成後才能再生成");
    expect(screen.queryByRole("button", { name: "生成中…" })).toBeNull();
  });

  it("an externally started round stays unknown on both empty and previously generated parts", async () => {
    mockGetSet.mockResolvedValue(twoPartDetail({
      generation: { status: "running", error: null },
      products: {
        copy: { ...copySetDetail().products.copy!, state: "待選定" },
        image_prompt: { state: "未生成", selected: 0, required: 1, generation_settings: {}, versions: [] },
      },
    }));
    renderStudio("/brands/brd_1/workbench/packs/pack_1/sets/set_1?part=image_prompt");

    const own = await screen.findByRole("button", { name: "素材生成中，完成後才能再生成" });
    expect((own as HTMLButtonElement).disabled).toBe(true);

    await userEvent.click(screen.getByRole("tab", { name: "文案" }));
    const other = await screen.findByRole("button", { name: "素材生成中，完成後才能再生成" });
    expect((other as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "生成中…" })).toBeNull();
  });

  it("F52-I19 holds the owned copy request across tabs before its POST returns and shows its failure", async () => {
    mockGetSet.mockResolvedValue(twoPartDetail());
    let reject!: (reason: Error) => void;
    mockRunProduct.mockImplementationOnce(() => new Promise<SetDetail>((_, no) => { reject = no; }));
    renderStudio("/brands/brd_1/workbench/packs/pack_1/sets/set_1?part=copy");
    await userEvent.click(await screen.findByRole("button", { name: /再生成一輪（5 組文案）|再生成 4 張/ }));
    expect((screen.getByRole("button", { name: "生成中…" }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByRole("tab", { name: "圖片" }));
    expect((screen.getByRole("button", { name: /正在生成文案，完成後才能再生成|再生成一輪（10 張）/ }) as HTMLButtonElement).disabled).toBe(true);
    const held = await screen.findByRole("button", { name: "正在生成文案，完成後才能再生成" });
    expect((held as HTMLButtonElement).disabled).toBe(true);
    expect(mockRunProduct).toHaveBeenCalledTimes(1);
    await act(async () => reject(new Error("本次文案請求被拒絕")));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("本次文案請求被拒絕"));
    expect((screen.getByRole("button", { name: "再生成一輪（10 張）" }) as HTMLButtonElement).disabled).toBe(false);
    await userEvent.click(screen.getByRole("tab", { name: "文案" }));
    mockRunProduct.mockResolvedValueOnce(twoPartDetail({ generation: { status: "queued", error: null } }));
    await userEvent.click(screen.getByRole("button", { name: "再生成一輪（5 組文案）" }));
    expect(mockRunProduct).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/本次文案請求被拒絕/)).toBeNull();
    expect(await screen.findByText("素材已排隊，等待生成。")).toBeTruthy();
  });

  it("F52-I19 preserves an unknown write result across tabs without calling it a failure or retrying", async () => {
    mockGetSet.mockResolvedValue(twoPartDetail());
    let reject!: (reason: Error) => void;
    mockRunProduct.mockImplementationOnce(() => new Promise<SetDetail>((_, no) => { reject = no; }));
    renderStudio("/brands/brd_1/workbench/packs/pack_1/sets/set_1?part=copy");
    await userEvent.click(await screen.findByRole("button", { name: "再生成一輪（5 組文案）" }));
    await userEvent.click(screen.getByRole("tab", { name: "圖片" }));
    expect((await screen.findByRole("button", { name: "正在生成文案，完成後才能再生成" }) as HTMLButtonElement).disabled).toBe(true);
    const unknown = new ApiNetworkError(true);
    await act(async () => reject(unknown));
    expect((await screen.findByRole("alert")).textContent).toBe(`文案：${unknown.message}`);
    expect(screen.queryByText(/文案產出失敗/)).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "文案" }));
    expect(screen.getByRole("alert").textContent).toBe(`文案：${unknown.message}`);
    expect(mockRunProduct).toHaveBeenCalledTimes(1);
  });

  it("F52-I19 does not let a delayed old set response replace the navigated set", async () => {
    const oldSet = twoPartDetail();
    const newSet = twoPartDetail({ id: "set_2", name: "第二個素材組", pack_id: "pack_2", pack_name: "第二個任務包" });
    mockGetSet.mockImplementation(async (_, id) => id === "set_2" ? newSet : oldSet);
    let resolve!: (value: SetDetail) => void;
    mockRunProduct.mockImplementationOnce(() => new Promise<SetDetail>((yes) => { resolve = yes; }));
    const view = renderStudio("/brands/brd_1/workbench/packs/pack_1/sets/set_1?part=copy");
    await userEvent.click(await screen.findByRole("button", { name: "再生成一輪（5 組文案）" }));
    view.rerender(<MemoryRouter><SetStudioPage brandId="brd_1" packId="pack_2" setId="set_2" /></MemoryRouter>);
    await screen.findByText("第二個任務包");
    await act(async () => resolve({ ...oldSet, generation: { status: "queued", error: null } }));
    expect(screen.getByText("第二個任務包")).toBeTruthy();
    expect(screen.queryByText("素材已排隊，等待生成。")).toBeNull();
    expect((screen.getByRole("button", { name: "再生成一輪（5 組文案）" }) as HTMLButtonElement).disabled).toBe(false);
    expect(mockGetSet).toHaveBeenLastCalledWith("brd_1", "set_2");
  });
});

describe("F47-I04 worker stopped, failed round, override approval", () => {
  const empty = { state: "未生成", selected: 0, required: 1, generation_settings: {}, versions: [] };

  it("a queued round with the worker stopped shows the notice; 再檢查一次 with a live worker re-reads the set and clears it", async () => {
    mockGetSet.mockResolvedValue(setDetail({ generation: { status: "queued", error: null }, products: { image_prompt: empty } }));
    vi.mocked(fetchActiveJobs).mockResolvedValue(jobs(true));
    renderStudio();

    const notice = (await screen.findByText(/背景程式停了/)).closest("[data-slot=worker-stopped]") as HTMLElement;
    expect(notice.textContent).toContain("背景程式停了：這件工作還排著，已填的資料沒丟。重新啟動行銷系統後會自動接著做。");
    expect(screen.getByText("素材已排隊，等待生成。")).toBeTruthy();

    vi.mocked(fetchActiveJobs).mockResolvedValue(jobs(false));
    const reads = mockGetSet.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "再檢查一次" }));
    await waitFor(() => expect(screen.queryByText(/背景程式停了/)).toBeNull());
    expect(mockGetSet.mock.calls.length).toBeGreaterThan(reads);
  });

  it("a failed round shows the server's error with 重新生成, which runs the open part again", async () => {
    const failed = setDetail({
      required_parts: ["copy"],
      generation: { status: "failed", error: "找不到工單：wbb_01" },
      products: { copy: { ...empty, generation_settings: { count: 3 } } },
    });
    mockGetSet.mockResolvedValue(failed);
    mockRunProduct.mockResolvedValue({ ...failed, generation: { status: "queued", error: "找不到工單：wbb_01" } });
    renderStudio();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("這輪生成失敗：找不到工單：wbb_01");
    await userEvent.click(screen.getByRole("button", { name: "重新生成" }));
    expect(mockRunProduct).toHaveBeenCalledWith("brd_1", "set_1", "copy", undefined);
    expect(await screen.findByText("素材已排隊，等待生成。")).toBeTruthy();
    expect(screen.queryByText(/這輪生成失敗/)).toBeNull();
  });

  it("override-approved set: the missing part stays usable, the selected part is locked, the reason says which", async () => {
    const reason = "這個任務包已核准，但這一組還缺東西：缺的部分可以補生成、選定；已選定的維持鎖定。";
    const image = setDetail().products.image_prompt!;
    mockGetSet.mockResolvedValue(setDetail({
      required_parts: ["copy", "image_prompt"],
      lock: { locked: false, reason, open_parts: ["image_prompt"] },
      products: {
        copy: {
          ...copySetDetail().products.copy!, state: "已選定", selected: 1, locked: true,
          versions: [{ ...copySetDetail().products.copy!.versions[0], selected_at: "2026-10-01T00:00:00Z" }],
        },
        image_prompt: { ...image, state: "待選定", locked: false },
      },
    }));
    renderStudio("/brands/brd_1/workbench/packs/pack_1/sets/set_1?part=image_prompt");

    expect(await screen.findByText(reason)).toBeTruthy();
    expect((screen.getByRole("button", { name: "選定" }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "再生成一輪（10 張）" }) as HTMLButtonElement).disabled).toBe(false);

    await userEvent.click(screen.getByRole("tab", { name: "文案" }));
    expect((await screen.findByRole("button", { name: "再生成一輪（5 組文案）" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "✓ 已選定" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
