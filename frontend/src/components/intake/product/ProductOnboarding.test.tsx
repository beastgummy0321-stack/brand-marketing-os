import { ApiResponseError } from "@/lib/http";
/** frontend/src/components/intake/product/ProductOnboarding.test.tsx — the product-onboarding shell (F43-I08):
 * `/products/new` creates the product and opens its onboarding; `?step=N` re-enters a step, a finished product
 * without it opens step 5, a product being built its current step; the crumb and the five dots; while the
 * product-page read runs step 1 shows 「正在讀商品頁…」 above its form and fills the form when the read ends; a failed
 * read offers 重試 / 自己填 without blanking the head; step 1's 下一步 saves, then step 2 opens. Fixtures are shaped like
 * `app/intake/product_onboarding.py` (`status()`, `get_what()`). No server: the API calls are fakes. */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeProductApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeProductApi")>("@/lib/intakeProductApi");
  return {
    ...actual,
    createProduct: vi.fn(),
    fetchProductOnboarding: vi.fn(),
    fetchProductWhat: vi.fn(),
    saveProductWhat: vi.fn(),
    startProductScan: vi.fn(),
  };
});
vi.mock("@/lib/jobsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/jobsApi")>("@/lib/jobsApi");
  return { ...actual, fetchActiveJobs: vi.fn() };
});
vi.mock("@/lib/useAuthedImage", () => ({
  useAuthedImage: (url: string | undefined) => ({ src: url ? `blob:${url}` : null, failed: !url }),
}));

import type { ProductOnboardingStatus, ProductWhat } from "@/lib/intakeProductApi";
import { createProduct, fetchProductOnboarding, fetchProductWhat, saveProductWhat, startProductScan } from "@/lib/intakeProductApi";
import { fetchActiveJobs, type ActiveJobsSnapshot } from "@/lib/jobsApi";
import { ProductOnboarding } from "./ProductOnboarding";

const mockCreate = vi.mocked(createProduct);
const mockStatus = vi.mocked(fetchProductOnboarding);
const mockWhat = vi.mocked(fetchProductWhat);
const mockSave = vi.mocked(saveProductWhat);
const mockScan = vi.mocked(startProductScan);
const mockJobs = vi.mocked(fetchActiveJobs);
const B = "brd_1";
/** `GET /api/jobs/active` with this org's product read queued; `stalled` = the worker is stopped (F47 Contract C). */
const jobs = (stalled: boolean): ActiveJobsSnapshot => ({
  data: [], total: 1, other_count: 0, done_today: 0, failed_today: 0, generated_at: "2026-10-02T02:00:00Z",
  worker_alive: !stalled, stalled,
});

beforeEach(() => {
  mockJobs.mockResolvedValue(jobs(false));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const status = (over: Partial<ProductOnboardingStatus> = {}): ProductOnboardingStatus => ({
  step: 1,
  completed: false,
  prefill_status: "none",
  prefill_error: null,
  ...over,
});

function blankWhat(): ProductWhat {
  return {
    name: "綜合維他命軟糖",
    page_url: "https://beastgummy.tw/shop/multivitamin",
    photos: [],
    intro: { value: "", source: "none", note: "" },
    mechanism: { value: "", source: "none", note: "" },
    difference: { value: "", source: "none", note: "" },
  };
}

function readWhat(): ProductWhat {
  return {
    ...blankWhat(),
    intro: { value: "一天一顆，12 種維生素與礦物質，不用配水", source: "ai", note: "商品頁" },
    mechanism: { value: "每顆含維生素 C 150 mg、B 群、D3、鋅", source: "ai", note: "商品頁" },
    difference: { value: "軟糖不用配水、低糖（每顆 1.2 g）", source: "ai", note: "商品頁" },
  };
}

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.search}</div>;
}

function OnboardingAt() {
  const { productId } = useParams<{ productId: string }>();
  return <ProductOnboarding key={productId} brandId={B} productId={productId ?? ""} />;
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:brandId/products/new" element={<ProductOnboarding brandId={B} productId={null} />} />
        <Route path="/brands/:brandId/products/:productId/onboarding" element={<OnboardingAt />} />
        <Route path="/brands/:brandId/products" element={<p>商品頁</p>} />
      </Routes>
      <Where />
    </MemoryRouter>,
  );
}

const where = () => screen.getByTestId("where").textContent;
const crumb = () => screen.getByRole("navigation", { name: "建檔位置" });
const heading = () => screen.getByRole("heading", { level: 1 }).textContent;
const currentDot = () => document.querySelector('[aria-current="step"]')?.textContent;

describe("ProductOnboarding", () => {
  it("新商品：填名稱與網址 → 建立 → 打開這個商品的建檔", async () => {
    mockCreate.mockResolvedValue({ product_id: "prd_new", created: true });
    mockStatus.mockResolvedValue(status({ prefill_status: "running" }));
    mockWhat.mockResolvedValue({ ...blankWhat(), name: "益生菌軟糖" });
    renderAt(`/brands/${B}/products/new`);

    expect(heading()).toBe("這個商品是什麼");
    expect(crumb().textContent).toBe("商品›商品建檔");
    expect(currentDot()).toBe("1商品是什麼");
    await userEvent.type(screen.getByLabelText("商品名稱"), "益生菌軟糖");
    await userEvent.type(screen.getByLabelText("商品頁網址"), "https://beastgummy.tw/shop/probiotic");
    await userEvent.click(screen.getByRole("button", { name: "下一步 →" }));

    await waitFor(() => expect(where()).toBe(`/brands/${B}/products/prd_new/onboarding`));
    expect(mockCreate).toHaveBeenCalledWith(B, { name: "益生菌軟糖", page_url: "https://beastgummy.tw/shop/probiotic" });
    expect(await screen.findByText("正在讀商品頁…")).toBeTruthy();
    expect(crumb().textContent).toBe("商品›商品建檔›益生菌軟糖");
  });

  it("麵包屑「商品」回商品頁；五個步驟點；「← 商品」也回商品頁", async () => {
    mockStatus.mockResolvedValue(status());
    mockWhat.mockResolvedValue(blankWhat());
    renderAt(`/brands/${B}/products/prd_vit/onboarding`);

    expect(await screen.findByLabelText("商品名稱")).toBeTruthy();
    expect(crumb().textContent).toBe("商品›商品建檔›綜合維他命軟糖");
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["1商品是什麼", "2誰會買", "3證據與說法", "4賣法與價格", "5完成"]);
    await userEvent.click(screen.getByRole("button", { name: "← 商品" }));
    expect(where()).toBe(`/brands/${B}/products`);
  });

  it("建好的商品沒帶 step 打開第 5 步；?step=1 回到第 1 步，已確認的值沒有標籤", async () => {
    mockStatus.mockResolvedValue(status({ step: 5, completed: true, prefill_status: "done" }));
    const saved = readWhat();
    for (const key of ["intro", "mechanism", "difference"] as const) saved[key] = { ...saved[key], source: "saved", note: "" };
    mockWhat.mockResolvedValue(saved);
    renderAt(`/brands/${B}/products/prd_vit/onboarding`);

    // F50-I18: 「建好了」 needs the served `ready`; this test only checks that step 5 opens.
    await waitFor(() => expect(currentDot()).toBe("5完成"));
    await userEvent.click(screen.getByRole("button", { name: "回到商品是什麼" }));

    await waitFor(() => expect(where()).toBe(`/brands/${B}/products/prd_vit/onboarding?step=1`));
    expect((await screen.findByLabelText("一句話介紹") as HTMLInputElement).value).toBe("一天一顆，12 種維生素與礦物質，不用配水");
    expect(screen.queryByText("✦ 商品頁")).toBeNull();
  });

  it("建到一半的商品打開它目前那一步", async () => {
    mockStatus.mockResolvedValue(status({ step: 3 }));
    mockWhat.mockResolvedValue(readWhat());
    renderAt(`/brands/${B}/products/prd_vit/onboarding`);

    await waitFor(() => expect(heading()).toBe("證據與說法"));
    expect(currentDot()).toBe("3證據與說法");
    expect(screen.getByRole("button", { name: "← 誰會買" })).toBeTruthy();
  });

  it("商品頁讀取中：步驟頭不空、表單照常，讀完把 AI 預填補進來", async () => {
    mockStatus.mockResolvedValueOnce(status({ prefill_status: "running" })).mockResolvedValue(status({ prefill_status: "done" }));
    mockWhat.mockResolvedValueOnce(blankWhat()).mockResolvedValue(readWhat());
    renderAt(`/brands/${B}/products/prd_vit/onboarding`);

    expect(await screen.findByText("正在讀商品頁…")).toBeTruthy();
    expect(heading()).toBe("這個商品是什麼");
    expect((screen.getByLabelText("一句話介紹") as HTMLInputElement).value).toBe("");

    await waitFor(() => expect((screen.getByLabelText("一句話介紹") as HTMLInputElement).value).toBe("一天一顆，12 種維生素與礦物質，不用配水"), { timeout: 4000 });
    expect(screen.queryByText("正在讀商品頁…")).toBeNull();
    expect(screen.getAllByText("✦ 商品頁")).toHaveLength(3);
  });

  it("讀取失敗：顯示原因、可以重試或自己填，步驟頭和表單都在", async () => {
    mockStatus.mockResolvedValue(status({ prefill_status: "failed", prefill_error: "讀不到商品頁：網站沒有回應。" }));
    mockWhat.mockResolvedValue(blankWhat());
    mockScan.mockResolvedValue(status({ prefill_status: "running" }));
    renderAt(`/brands/${B}/products/prd_vit/onboarding`);

    expect((await screen.findByRole("alert")).textContent).toBe("讀不到商品頁：網站沒有回應。");
    expect(heading()).toBe("這個商品是什麼");
    expect(screen.getByLabelText("商品名稱")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(mockScan).toHaveBeenCalledWith(B, "prd_vit", "https://beastgummy.tw/shop/multivitamin");
    expect(await screen.findByText("正在讀商品頁…")).toBeTruthy();
  });

  it("改了商品頁網址再按重試：讀的是欄位裡的新網址，不是舊的（drill-10 R2）", async () => {
    sessionStorage.clear();
    mockStatus.mockResolvedValue(status({ prefill_status: "failed", prefill_error: "讀不到商品頁（網址打不開或沒有文字），也沒有商品照；可以重試，或直接自己填。" }));
    mockWhat.mockResolvedValue(blankWhat());
    mockScan.mockResolvedValue(status({ prefill_status: "running" }));
    renderAt(`/brands/${B}/products/prd_vit/onboarding`);

    const field = (await screen.findByLabelText("商品頁網址")) as HTMLInputElement;
    await userEvent.clear(field);
    await userEvent.type(field, "https://beastgummy.tw/shop/multivitamin-fixed ");
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(mockScan).toHaveBeenCalledWith(B, "prd_vit", "https://beastgummy.tw/shop/multivitamin-fixed");
    sessionStorage.clear();
  });

  it("「自己填」收起失敗列，只留表單", async () => {
    mockStatus.mockResolvedValue(status({ prefill_status: "failed", prefill_error: "AI 讀商品頁失敗，可以重試，或直接自己填。" }));
    mockWhat.mockResolvedValue(blankWhat());
    renderAt(`/brands/${B}/products/prd_vit/onboarding`);

    await userEvent.click(await screen.findByRole("button", { name: "自己填" }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByLabelText("商品名稱")).toBeTruthy();
  });

  it("第 1 步存好後重讀狀態，再打開第 2 步", async () => {
    mockStatus.mockResolvedValueOnce(status({ prefill_status: "done" })).mockResolvedValue(status({ step: 2, prefill_status: "done" }));
    mockWhat.mockResolvedValue(readWhat());
    mockSave.mockResolvedValue(readWhat());
    renderAt(`/brands/${B}/products/prd_vit/onboarding?step=1`);

    await userEvent.click(await screen.findByRole("button", { name: "下一步 →" }));

    await waitFor(() => expect(where()).toBe(`/brands/${B}/products/prd_vit/onboarding?step=2`));
    expect(heading()).toBe("誰會買、買之前煩什麼");
    expect(mockStatus).toHaveBeenCalledTimes(2);
  });

  it("讀取中而背景程式停了：說原因、資料沒丟；再檢查一次（背景程式已起來）後提示消失、狀態重讀", async () => {
    mockStatus.mockResolvedValue(status({ prefill_status: "running" }));
    mockWhat.mockResolvedValue(blankWhat());
    mockJobs.mockResolvedValue(jobs(true));
    renderAt(`/brands/${B}/products/prd_vit/onboarding`);

    const notice = (await screen.findByText(/背景程式停了/)).closest("[data-slot=worker-stopped]");
    expect(notice?.textContent).toContain("背景程式停了：這件工作還排著，已填的資料沒丟。重新啟動行銷系統後會自動接著做。");
    expect(screen.getByText("正在讀商品頁…")).toBeTruthy();
    expect(screen.getByLabelText("商品名稱")).toBeTruthy();

    mockJobs.mockResolvedValue(jobs(false));
    const reads = mockWhat.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "再檢查一次" }));
    await waitFor(() => expect(screen.queryByText(/背景程式停了/)).toBeNull());
    expect(mockWhat.mock.calls.length).toBeGreaterThan(reads);
  });

  it("找不到的商品顯示空狀態", async () => {
    mockStatus.mockRejectedValue(new ApiResponseError("任意文案", 404, {}));
    mockWhat.mockResolvedValue(blankWhat());
    renderAt(`/brands/${B}/products/prd_gone/onboarding`);

    expect(await screen.findByText("找不到這個商品")).toBeTruthy();
  });
});
