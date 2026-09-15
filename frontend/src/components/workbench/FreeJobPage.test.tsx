import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/productsApi", () => ({
  fetchProductList: vi.fn().mockResolvedValue([]),
}));
vi.mock("@/lib/workbenchApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/workbenchApi")>("@/lib/workbenchApi");
  return { ...actual, parseFreeText: vi.fn(), createFreePack: vi.fn() };
});
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ brands: [{ brand_id: "brd_1", brand_name: "測試品牌" }] }),
}));

import { parseFreeText } from "@/lib/workbenchApi";
import { FreeJobPage, specToCreateBody } from "./FreeJobPage";
import type { FreeParseSpec } from "@/lib/workbenchApi";

const mockParseFreeText = vi.mocked(parseFreeText);

function spec(overrides: Partial<FreeParseSpec> = {}): FreeParseSpec {
  return {
    topic: "夜跑廣告",
    outputs: [{ part: "image_prompt", count: 5 }],
    style_hint: "ugc",
    platform: "Meta",
    size: "4:5",
    audience: "運動族群",
    key_message: "提升表現",
    ...overrides,
  };
}

describe("specToCreateBody（F02-I10 唯一的分支邏輯）", () => {
  it("count 有給值：required_outputs 跟同一輪的產出數量用同一個數字", () => {
    const body = specToCreateBody(spec(), { text: "幫我做五張夜跑廣告", productId: null });
    expect(body.sets[0].required_outputs).toEqual({ image_prompt: 5 });
    expect(body.sets[0].request?.image_prompt_count).toBe(5);
  });

  it("outputs 沒給 count：預設 1", () => {
    const body = specToCreateBody(
      spec({ outputs: [{ part: "copy", count: undefined as unknown as number }] }),
      { text: "文案", productId: null },
    );
    expect(body.sets[0].required_outputs).toEqual({ copy: 1 });
    expect(body.sets[0].request?.copy_count).toBe(1);
  });

  it("parsed: false 沿用使用者填的預設值，仍然可以送出", () => {
    const fallback = spec({
      topic: null, style_hint: null, platform: null, size: null, audience: null, key_message: null,
    });
    const body = specToCreateBody(fallback, { text: "隨便做點什麼", productId: null });
    expect(body.free_text).toBe("隨便做點什麼");
    expect(body.sets[0].required_outputs).toEqual({ image_prompt: 5 });
    expect(body.style_key).toBeNull();
  });

  it("多種產出類型：outputs 每一項各自進 required_outputs", () => {
    const body = specToCreateBody(
      spec({ outputs: [{ part: "image_prompt", count: 5 }, { part: "copy", count: 1 }] }),
      { text: "混合任務", productId: "prod_1" },
    );
    expect(body.sets[0].required_outputs).toEqual({ image_prompt: 5, copy: 1 });
    expect(body.product_id).toBe("prod_1");
  });

  it("platform 有值：進 context.platform（F02-I18）", () => {
    const body = specToCreateBody(spec({ platform: "Meta" }), { text: "夜跑廣告", productId: null });
    expect(body.context?.platform).toBe("Meta");
  });

  it("platform 是 null：不送 context.platform 這個鍵", () => {
    const body = specToCreateBody(spec({ platform: null }), { text: "夜跑廣告", productId: null });
    expect(body.context).not.toHaveProperty("platform");
  });
});

// F07-I09（Decision 25，Y13）：舊全域風格庫退場——精準控制不再有風格選單，AI 解析結果不再
// 有「風格設定」列，畫面也從不打 `/styles`（那支路由已經 404，見 test_workbench_api.py）。
describe("FreeJobPage 不再讀風格（F07-I09）", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.clearAllMocks();
  });

  it("精準控制沒有風格欄位、AI 解析結果沒有風格設定列、且從不打 /styles", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(new Response("{}"));
    global.fetch = fetchSpy as unknown as typeof fetch;
    mockParseFreeText.mockResolvedValue({
      parsed: true, note: null, spec: spec({ style_hint: "ugc" }),
    });

    render(
      <MemoryRouter>
        <FreeJobPage brandId="brd_1" />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("button", { name: "精準控制" }));
    expect(screen.queryByRole("combobox", { name: "風格" })).toBeNull();

    await userEvent.type(screen.getByLabelText("告訴 AI 你想創作什麼"), "測試文字");
    await userEvent.click(screen.getByRole("button", { name: "建立自由工作 →" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "確認並生成" })).toBeTruthy());
    expect(screen.queryByText("風格設定")).toBeNull();

    const calledPaths = fetchSpy.mock.calls.map((call) => String(call[0]));
    expect(calledPaths.some((path) => path.includes("/styles"))).toBe(false);
  });
});
