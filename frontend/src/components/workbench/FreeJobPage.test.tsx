import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/productsApi", () => ({
  fetchProductList: vi.fn().mockResolvedValue([]),
}));
vi.mock("@/lib/workbenchApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/workbenchApi")>("@/lib/workbenchApi");
  return { ...actual, parseFreeText: vi.fn(), createFreePack: vi.fn() };
});
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({
    brands: [{ brand_id: "brd_1", brand_name: "測試品牌" }],
    // F50-I14: the org is in Taipei whatever zone the test runner is in.
    identity: { org: { id: "org_1", timezone: "Asia/Taipei", today: "2026-10-04" } },
  }),
}));

import { parseFreeText } from "@/lib/workbenchApi";
import { fetchProductList } from "@/lib/productsApi";
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
  it("image_prompt 恆為 1、不帶 image_prompt_count（F07 Decision 28）", () => {
    const body = specToCreateBody(spec(), { text: "幫我做五張夜跑廣告", productId: null });
    expect(body.sets[0].required_outputs).toEqual({ image_prompt: 1 });
    expect(body.sets[0].request).not.toHaveProperty("image_prompt_count");
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
    expect(body.sets[0].required_outputs).toEqual({ image_prompt: 1 });
    expect(body.style_key).toBeNull();
  });

  it("多種產出類型：outputs 每一項各自進 required_outputs", () => {
    const body = specToCreateBody(
      spec({ outputs: [{ part: "image_prompt", count: 5 }, { part: "copy", count: 1 }] }),
      { text: "混合任務", productId: "prod_1" },
    );
    expect(body.sets[0].required_outputs).toEqual({ image_prompt: 1, copy: 1 });
    expect(body.product_id).toBe("prod_1");
  });

  it("video_script：required_outputs 跟 request.video_script_count 用同一個數字", () => {
    const body = specToCreateBody(
      spec({ outputs: [{ part: "video_script", count: 3 }] }),
      { text: "腳本", productId: null },
    );
    expect(body.sets[0].required_outputs).toEqual({ video_script: 3 });
    expect(body.sets[0].request?.video_script_count).toBe(3);
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

// F07-I14（Decision 28）：一輪固定 10 張，精準控制不再問圖片要幾張。
describe("精準控制的產出數量欄位（F07-I14）", () => {
  it("素材類型選圖片：不顯示產出數量；選文案：顯示產出數量", async () => {
    render(
      <MemoryRouter>
        <FreeJobPage brandId="brd_1" />
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("button", { name: "精準控制" }));
    expect(screen.queryByLabelText("產出數量")).toBeNull();

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "素材類型" }), "文案");
    expect(screen.getByLabelText("產出數量")).toBeTruthy();
  });

  it("AI 解析結果的需要產出：image_prompt 顯示「圖片（一輪 10 張）」，不顯示份數", async () => {
    mockParseFreeText.mockResolvedValue({
      parsed: true, note: null, spec: spec({ outputs: [{ part: "image_prompt", count: 5 }] }),
    });

    render(
      <MemoryRouter>
        <FreeJobPage brandId="brd_1" />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText("告訴 AI 你想創作什麼"), "測試文字");
    await userEvent.click(screen.getByRole("button", { name: "建立自由工作 →" }));

    await waitFor(() => expect(screen.getByText("圖片（一輪 10 張）")).toBeTruthy());
    expect(screen.queryByText("圖片 5 份")).toBeNull();
  });

  it("預覽卡的要選幾版：image_prompt 恆為 1，其他 part 仍用解析出的張數（F09）", async () => {
    mockParseFreeText.mockResolvedValue({
      parsed: true, note: null,
      spec: spec({ outputs: [{ part: "image_prompt", count: 5 }, { part: "video_script", count: 3 }] }),
    });

    render(
      <MemoryRouter>
        <FreeJobPage brandId="brd_1" />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText("告訴 AI 你想創作什麼"), "測試文字");
    await userEvent.click(screen.getByRole("button", { name: "建立自由工作 →" }));

    await waitFor(() => expect(screen.getByText("0／1")).toBeTruthy());
    expect(screen.getByText("0／3")).toBeTruthy();
    expect(screen.queryByText("0／5")).toBeNull();
  });
});

// F29-I10 Contract K: a failed product read is said out loud with 重試 — never a silently empty product list.
describe("FreeJobPage product list read (F29-I10)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("the product read fails: the error line and 重試 show; 重試 re-requests and the products come back", async () => {
    vi.mocked(fetchProductList)
      .mockRejectedValueOnce(new Error("伺服器沒回應"))
      .mockResolvedValueOnce([
        { id: "p1", name: "夜跑鞋", kind: "knowledge" },
        { id: "p2", name: "夜跑鞋 · 單雙", kind: "sell_way" },
      ] as Awaited<ReturnType<typeof fetchProductList>>);
    render(
      <MemoryRouter>
        <FreeJobPage brandId="brd_1" />
      </MemoryRouter>,
    );
    expect((await screen.findByRole("alert")).textContent).toContain("商品清單讀取失敗：伺服器沒回應");
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(vi.mocked(fetchProductList)).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole("option", { name: "夜跑鞋" })).toBeTruthy();
    // F50 Contract R: a free job's context is a knowledge product; sell-ways are not listed.
    expect(screen.queryByRole("option", { name: "夜跑鞋 · 單雙" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("FreeJobPage preview card (F50-I14, Contract K)", () => {
  it("the not-yet-created pack shows no made-up 「更新於」 stamp", async () => {
    render(
      <MemoryRouter>
        <FreeJobPage brandId="brd_1" />
      </MemoryRouter>,
    );
    expect(await screen.findByText("自由工作 #（建立後產生）")).toBeTruthy();
    expect(screen.queryByText(/更新於/)).toBeNull();
    expect(screen.queryByText(/小時前/)).toBeNull();
  });
});

function FreeJobLocation() {
  const location = useLocation();
  return <output data-testid="free-job-location">{location.pathname}</output>;
}

describe("FreeJobPage presentational preview (F52-I17)", () => {
  it("has no dead controls, skips preview during Tab navigation and still creates the real pack", async () => {
    const user = userEvent.setup();
    const { createFreePack } = await import("@/lib/workbenchApi");
    mockParseFreeText.mockResolvedValue({ parsed: true, note: null, spec: spec({ outputs: [{ part: "copy", count: 1 }] }) });
    vi.mocked(createFreePack).mockResolvedValue({ id: "wbp_created" } as Awaited<ReturnType<typeof createFreePack>>);
    render(<MemoryRouter initialEntries={["/brands/brd_1/workbench/new"]}><FreeJobPage brandId="brd_1" /><FreeJobLocation /></MemoryRouter>);
    const preview = (await screen.findByRole("heading", { name: "預覽將建立的工作項目" })).parentElement!;
    expect(within(preview).queryAllByRole("button")).toHaveLength(0);
    expect(within(preview).queryAllByRole("link")).toHaveLength(0);
    expect(preview.querySelector('[tabindex]:not([tabindex="-1"]),input,select,textarea')).toBeNull();
    expect(within(preview).getByText("預覽")).toBeTruthy();
    expect(within(preview).queryByText("待處理")).toBeNull();
    await user.click(within(preview).getByRole("heading", { name: "自由工作 #（建立後產生）" }));
    expect(screen.getByTestId("free-job-location").textContent).toBe("/brands/brd_1/workbench/new");
    await user.type(screen.getByLabelText("告訴 AI 你想創作什麼"), "新手夜跑主題，說明商品適用情境");
    const create = screen.getByRole("button", { name: "建立自由工作 →" });
    create.focus();
    await user.tab();
    expect(preview.contains(document.activeElement)).toBe(false);
    await user.click(create);
    expect(await screen.findByRole("button", { name: "確認並生成" })).toBeTruthy();
    expect(within(preview).queryAllByRole("button")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "確認並生成" }));
    await waitFor(() => expect(screen.getByTestId("free-job-location").textContent).toBe("/brands/brd_1/workbench/packs/wbp_created"));
    expect(createFreePack).toHaveBeenCalledWith("brd_1", specToCreateBody(spec({ outputs: [{ part: "copy", count: 1 }] }), { text: "新手夜跑主題，說明商品適用情境", productId: null }));
  });
});


it("explains why an empty free job cannot be created and clears the reason after typing", async () => {
  render(<MemoryRouter><FreeJobPage brandId="brd_1"/></MemoryRouter>);
  const button = screen.getByRole("button",{name:"建立自由工作 →"});
  expect(button).toHaveProperty("disabled",true);
  expect(document.getElementById(button.getAttribute("aria-describedby")!)?.textContent).toBe("先填寫你想創作的內容");
  await userEvent.type(screen.getByLabelText("告訴 AI 你想創作什麼"),"新品文案");
  expect(button).toHaveProperty("disabled",false);
  expect(screen.queryByText("先填寫你想創作的內容")).toBeNull();
});
