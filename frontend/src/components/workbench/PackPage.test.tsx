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

describe("F12 任務包的一般完成路徑", () => {
  it("逐項列出未完成部分的名稱並提供素材組直達連結", async () => {
    mockGetPack.mockResolvedValue(
      packDetail({
        can_approve: false,
        blocking_text: "還有 1 個必要產物未選定",
        sets: [
          {
            id: "set_missing",
            name: "新客主力",
            status: "等待決定",
            cells: [
              {
                part: "copy",
                label: "文案",
                state: "未生成",
                selected: 0,
                required: 1,
                text: "尚未選定",
              },
              {
                part: "video_script",
                label: "腳本",
                state: "不需要",
                selected: 0,
                required: null,
                text: "—",
              },
            ],
          },
        ],
      }),
    );
    renderPack();

    const link = await screen.findByRole("link", { name: "新客主力：文案（尚未選定）" });
    expect(link.getAttribute("href")).toBe(
      "/brands/brd_1/workbench/packs/pack_1/sets/set_missing?part=copy",
    );
    expect(screen.queryByRole("link", { name: /腳本/ })).toBeNull();
    expect(screen.getAllByText(/還有 1 個必要產物未選定/).length).toBeGreaterThan(0);
    expect((screen.getByRole("button", { name: "核准整包" }) as HTMLButtonElement).disabled)
      .toBe(true);
  });

  it("所有產物已選定時不顯示未完成清單", async () => {
    mockGetPack.mockResolvedValue(
      packDetail({
        sets: [
          {
            id: "set_done",
            name: "新客主力",
            status: "已完成",
            cells: [
              {
                part: "image_prompt",
                label: "圖片",
                state: "已選定",
                selected: 1,
                required: 1,
                text: "已選 1／1",
              },
            ],
          },
        ],
      }),
    );
    renderPack();

    await screen.findByRole("button", { name: "核准整包" });
    expect(screen.queryByLabelText("尚未完成的產物")).toBeNull();
  });
});

describe("F40-I05 核准整包灰掉時的原因列（drill-7 #14）", () => {
  it("按鈕停用且有 blocking_text：原因以「⚠ 」開頭、與按鈕同列、帶警示色", async () => {
    const reason = "還沒勾「確認內容符合品牌規範」「可核准整包並回報上游」";
    mockGetPack.mockResolvedValue(packDetail({ can_approve: false, blocking_text: reason }));
    renderPack();

    const note = await screen.findByRole("note", { name: "核准整包停用原因" });
    expect(note.textContent).toBe(`⚠ ${reason}`);
    expect(note.className).toContain("text-warning");
    const approveButton = screen.getByRole("button", { name: "核准整包" });
    expect((approveButton as HTMLButtonElement).disabled).toBe(true);
    expect(note.parentElement).toBe(approveButton.parentElement);
  });

  it("按鈕可點時：不渲染原因列", async () => {
    mockGetPack.mockResolvedValue(packDetail({ can_approve: true, blocking_text: "" }));
    renderPack();

    const approveButton = await screen.findByRole("button", { name: "核准整包" });
    expect((approveButton as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByRole("note", { name: "核准整包停用原因" })).toBeNull();
    expect(screen.queryByText(/⚠/)).toBeNull();
  });
});
