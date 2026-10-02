/** frontend/src/components/intake/product/WhatStep.test.tsx — product onboarding `#/p1` 這個商品是什麼 (F43-I08):
 * the new-product form posts the create; fields the product-page read proposed carry its tag, confirmed ones do not;
 * 下一步 sends `PUT …/onboarding/what` with the typed values and moves on only after the server confirmed; a later
 * `what` (the read finished) fills only the fields the user left alone; a photo goes through the official-asset
 * upload with `product_id`; 「自訂」 under the difference goes through the product call and fills the field marked 你自訂. Fixtures are shaped like `app/intake/product_onboarding.py::get_what()`. No server. */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeProductApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeProductApi")>("@/lib/intakeProductApi");
  return { ...actual, createProduct: vi.fn(), fetchProductWhat: vi.fn(), proposeProductCustom: vi.fn(), saveProductWhat: vi.fn() };
});
vi.mock("@/lib/libraryApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/libraryApi")>("@/lib/libraryApi");
  return { ...actual, uploadAsset: vi.fn() };
});
vi.mock("@/lib/useAuthedImage", () => ({
  useAuthedImage: (url: string | undefined) => ({ src: url ? `blob:${url}` : null, failed: !url }),
}));

import type { ProductWhat } from "@/lib/intakeProductApi";
import { createProduct, fetchProductWhat, proposeProductCustom, saveProductWhat } from "@/lib/intakeProductApi";
import { uploadAsset } from "@/lib/libraryApi";
import type { StepNav } from "../OnboardingStepHead";
import { PRODUCT_STEPS, productCrumb } from "./ProductOnboarding";
import { NewProductStep, WhatStep } from "./WhatStep";

const mockCreate = vi.mocked(createProduct);
const mockFetch = vi.mocked(fetchProductWhat);
const mockSave = vi.mocked(saveProductWhat);
const mockUpload = vi.mocked(uploadAsset);
const mockCustom = vi.mocked(proposeProductCustom);

const B = "brd_1";
const P = "prd_vit";
const PHOTO = { id: "oa_1", url: `/brands/${B}/assets/file/oa_1/front.jpg` };

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function prefilled(): ProductWhat {
  return {
    name: "綜合維他命軟糖",
    page_url: "https://beastgummy.tw/shop/multivitamin",
    photos: [PHOTO],
    intro: { value: "一天一顆，12 種維生素與礦物質，不用配水", source: "ai", note: "商品頁" },
    mechanism: { value: "每顆含維生素 C 150 mg、B 群、D3、鋅；明膠改用果膠，素食可", source: "ai", note: "商品頁" },
    difference: { value: "", source: "none", note: "" },
  };
}

const nav = (name = "綜合維他命軟糖"): StepNav => ({ crumb: productCrumb(B, name), steps: PRODUCT_STEPS, current: 1 });

function renderWhat(what: ProductWhat, opts: { prefillDone?: boolean; onSaved?: () => void } = {}) {
  const onSaved = opts.onSaved ?? vi.fn();
  const back = vi.fn();
  const view = render(
    <MemoryRouter>
      <WhatStep brandId={B} productId={P} nav={nav()} back={{ label: "商品", onClick: back }} what={what} prefillDone={opts.prefillDone ?? true} onSaved={onSaved} />
    </MemoryRouter>,
  );
  const rerender = (next: ProductWhat) =>
    view.rerender(
      <MemoryRouter>
        <WhatStep brandId={B} productId={P} nav={nav()} back={{ label: "商品", onClick: back }} what={next} prefillDone onSaved={onSaved} />
      </MemoryRouter>,
    );
  return { onSaved, back, rerender };
}

const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement | HTMLTextAreaElement;
const nextButton = () => screen.getByRole("button", { name: "下一步 →" }) as HTMLButtonElement;

describe("NewProductStep", () => {
  it("商品名稱＋商品頁網址 → 建立商品，交出新商品的 id", async () => {
    mockCreate.mockResolvedValue({ product_id: "prd_new", created: true });
    const onCreated = vi.fn();
    render(
      <MemoryRouter>
        <NewProductStep brandId={B} nav={nav("")} back={{ label: "商品", onClick: vi.fn() }} onCreated={onCreated} />
      </MemoryRouter>,
    );

    expect(nextButton().disabled).toBe(true);
    expect(screen.getByText("也是廣告預設的落地頁")).toBeTruthy();
    // F47-I03 (drill-10 乙 #4): a URL alone keeps 下一步 off and says the name is missing.
    await userEvent.type(field("商品頁網址"), "https://beastgummy.tw/shop/probiotic");
    expect(nextButton().disabled).toBe(true);
    expect(screen.getByText("先填商品名稱")).toBeTruthy();
    await userEvent.type(field("商品名稱"), " 益生菌軟糖 ");
    expect(screen.queryByText("先填商品名稱")).toBeNull();
    expect(screen.getByRole("navigation", { name: "建檔位置" }).textContent).toBe("商品›商品建檔›益生菌軟糖");
    await userEvent.click(nextButton());

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith({ product_id: "prd_new", created: true }));
    expect(mockCreate).toHaveBeenCalledWith(B, { name: "益生菌軟糖", page_url: "https://beastgummy.tw/shop/probiotic" });
  });

  it("沒給網址只送名稱；建立失敗留在這一步並顯示原因", async () => {
    mockCreate.mockRejectedValue(new Error("商品名稱不能超過 80 字。"));
    const onCreated = vi.fn();
    render(
      <MemoryRouter>
        <NewProductStep brandId={B} nav={nav("")} back={{ label: "商品", onClick: vi.fn() }} onCreated={onCreated} />
      </MemoryRouter>,
    );

    await userEvent.type(field("商品名稱"), "益生菌軟糖");
    await userEvent.click(nextButton());

    expect((await screen.findByRole("alert")).textContent).toBe("商品名稱不能超過 80 字。");
    expect(mockCreate).toHaveBeenCalledWith(B, { name: "益生菌軟糖" });
    expect(onCreated).not.toHaveBeenCalled();
  });
});

describe("WhatStep", () => {
  it("商品頁讀到的欄位帶著來源標籤，沒讀到的標「網站上沒找到」，商品照有縮圖", () => {
    renderWhat(prefilled());

    expect(field("商品名稱").value).toBe("綜合維他命軟糖");
    expect(field("商品頁網址").value).toBe("https://beastgummy.tw/shop/multivitamin");
    expect(field("一句話介紹").value).toBe("一天一顆，12 種維生素與礦物質，不用配水");
    expect(screen.getAllByText("✦ 商品頁")).toHaveLength(2);
    expect(screen.getByText("網站上沒找到")).toBeTruthy();
    expect(document.querySelector(`img[src="blob:${PHOTO.url}"]`)).toBeTruthy();
    expect(screen.getByText("＋上傳")).toBeTruthy();
  });

  it("讀取還沒結束時，空的欄位不標「網站上沒找到」；已確認的欄位沒有標籤", () => {
    const what = prefilled();
    what.intro = { value: "一天一顆", source: "saved", note: "" };
    renderWhat(what, { prefillDone: false });

    expect(screen.getAllByText("✦ 商品頁")).toHaveLength(1);
    expect(screen.queryByText("網站上沒找到")).toBeNull();
  });

  it("改過的欄位拿掉標籤；下一步送出畫面上的值，存好才往下", async () => {
    const saved = { ...prefilled(), difference: { value: "軟糖不用配水、低糖（每顆 1.2 g）", source: "saved" as const, note: "" } };
    mockSave.mockResolvedValue(saved);
    const { onSaved } = renderWhat(prefilled());

    await userEvent.type(field("跟別人不一樣的地方"), "軟糖不用配水、低糖（每顆 1.2 g）");
    await userEvent.clear(field("一句話介紹"));
    await userEvent.type(field("一句話介紹"), "一天一顆，不用配水 ");
    expect(screen.getAllByText("✦ 商品頁")).toHaveLength(1);
    expect(screen.queryByText("網站上沒找到")).toBeNull();
    await userEvent.click(nextButton());

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
    expect(mockSave).toHaveBeenCalledWith(B, P, {
      name: "綜合維他命軟糖",
      page_url: "https://beastgummy.tw/shop/multivitamin",
      intro: "一天一顆，不用配水",
      mechanism: "每顆含維生素 C 150 mg、B 群、D3、鋅；明膠改用果膠，素食可",
      difference: "軟糖不用配水、低糖（每顆 1.2 g）",
    });
  });

  it("存檔失敗留在這一步、輸入不清空", async () => {
    mockSave.mockRejectedValue(new Error("商品名稱不能空白。"));
    const { onSaved } = renderWhat(prefilled());

    await userEvent.type(field("跟別人不一樣的地方"), "台灣工廠");
    await userEvent.click(nextButton());

    expect((await screen.findByRole("alert")).textContent).toBe("商品名稱不能空白。");
    expect(onSaved).not.toHaveBeenCalled();
    expect(field("跟別人不一樣的地方").value).toBe("台灣工廠");
  });

  it("讀取完成後的新資料只填進使用者沒動過的欄位", async () => {
    const empty: ProductWhat = {
      ...prefilled(),
      photos: [],
      intro: { value: "", source: "none", note: "" },
      mechanism: { value: "", source: "none", note: "" },
      difference: { value: "", source: "none", note: "" },
    };
    const { rerender } = renderWhat(empty, { prefillDone: false });
    await userEvent.type(field("跟別人不一樣的地方"), "我自己寫的");

    rerender({ ...prefilled(), difference: { value: "低糖", source: "ai", note: "商品頁" } });

    expect(field("一句話介紹").value).toBe("一天一顆，12 種維生素與礦物質，不用配水");
    expect(field("跟別人不一樣的地方").value).toBe("我自己寫的");
    expect(screen.getAllByText("✦ 商品頁")).toHaveLength(2);
  });

  it("＋上傳走既有的官方素材上傳（商品照、帶 product_id），上傳後重讀縮圖", async () => {
    const extra = { id: "oa_2", url: `/brands/${B}/assets/file/oa_2/side.jpg` };
    mockUpload.mockResolvedValue(undefined);
    mockFetch.mockResolvedValue({ ...prefilled(), photos: [PHOTO, extra] });
    renderWhat(prefilled());

    const file = new File(["x"], "side.jpg", { type: "image/jpeg" });
    await userEvent.upload(screen.getByLabelText("上傳商品照"), file);

    await waitFor(() => expect(document.querySelector(`img[src="blob:${extra.url}"]`)).toBeTruthy());
    expect(mockUpload).toHaveBeenCalledWith(B, { asset_kind: "product_photo", product_id: P, title: "side.jpg", file });
    expect(mockFetch).toHaveBeenCalledWith(B, P);
  });
  it("跟別人不一樣的地方的「自訂」走商品那支，結果填進欄位、標「你自訂」，下一步一起存", async () => {
    mockCustom.mockResolvedValue({ block: "difference", kind: "value", value: "台灣自己的工廠，一批一批驗" });
    mockSave.mockResolvedValue(prefilled());
    renderWhat(prefilled());

    await userEvent.click(screen.getByRole("button", { name: "✎ 自訂：用自己的話說" }));
    expect(screen.getByRole("textbox", { name: /覺得上面列的不對/ }).getAttribute("placeholder")).toBe("例如：我們是台灣自己的工廠做的，一批一批驗");
    await userEvent.type(screen.getByRole("textbox", { name: /覺得上面列的不對/ }), "我們是台灣自己的工廠做的");
    await userEvent.click(screen.getByRole("button", { name: "讓 AI 整理" }));

    await waitFor(() => expect(field("跟別人不一樣的地方").value).toBe("台灣自己的工廠，一批一批驗"));
    expect(mockCustom).toHaveBeenCalledWith(B, P, "difference", "我們是台灣自己的工廠做的");
    expect(screen.getByText("你自訂")).toBeTruthy();
    expect(screen.queryByText("網站上沒找到")).toBeNull();
    await userEvent.type(field("跟別人不一樣的地方"), "！");
    expect(screen.queryByText("你自訂")).toBeNull();
    await userEvent.clear(field("跟別人不一樣的地方"));
    await userEvent.type(field("跟別人不一樣的地方"), "台灣自己的工廠，一批一批驗");
    expect(screen.getByText("你自訂")).toBeTruthy();
    await userEvent.click(nextButton());

    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    expect(mockSave.mock.calls[0][2].difference).toBe("台灣自己的工廠，一批一批驗");
  });
});
