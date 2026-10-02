/** frontend/src/components/intake/product/ProductDoneStep.test.tsx — product onboarding `#/p5` 〈商品〉建好了 (F43-I12):
 * a finished product shows 可以投放 and four green rows built from saved values only (商品是什麼 parts, groups with
 * pain labels, proof kinds and claim verdicts, sell-ways with price / break-even / offers); 「用它建活動 →」 carries the
 * first sell-way's id; a product still missing its sell-ways shows 建到一半, a red 「賣法：還沒有」 row whose 「去補」 opens
 * step 4, and no campaign link; four steps saved but 完成 not recorded completes once on entering. Fixtures are shaped
 * like `app/intake/product_onboarding.py` (`status`, `get_who`, `get_evidence`, `get_sell_ways`). No server. */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeProductApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeProductApi")>("@/lib/intakeProductApi");
  return {
    ...actual,
    fetchProductOnboarding: vi.fn(),
    fetchProductWho: vi.fn(),
    fetchProductEvidence: vi.fn(),
    fetchProductSellWays: vi.fn(),
    completeProductOnboarding: vi.fn(),
  };
});

import type {
  ProductEvidence,
  ProductOnboardingStatus,
  ProductSellWays,
  ProductWhat,
  ProductWho,
  SellWayRow,
} from "@/lib/intakeProductApi";
import {
  completeProductOnboarding,
  fetchProductEvidence,
  fetchProductOnboarding,
  fetchProductSellWays,
  fetchProductWho,
} from "@/lib/intakeProductApi";
import type { StepNav } from "../OnboardingStepHead";
import { ProductDoneStep } from "./ProductDoneStep";
import { PRODUCT_STEPS, productCrumb } from "./ProductOnboarding";

const B = "brd_1";
const P = "prd_vit";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const saved = (value: string) => ({ value, source: "saved" as const, note: "" });

const WHAT: ProductWhat = {
  name: "綜合維他命軟糖",
  page_url: "https://beastgummy.tw/shop/multivitamin",
  photos: [],
  intro: saved("一天一顆，12 種維生素與礦物質，不用配水"),
  mechanism: saved("每顆含維生素 C 150 mg、B 群、D3、鋅"),
  difference: saved("軟糖不用配水、低糖（每顆 1.2 g）"),
};

const WHO: ProductWho = {
  groups: [
    { id: "cg_1", who: "上班族", pain_keys: ["effort"], quote: "「每天吃一堆藥丸好麻煩」", when_used: "早上出門前", source: "saved", note: "" },
    { id: "cg_2", who: "運動族", pain_keys: ["uncertainty", "cost"], quote: "", when_used: "", source: "saved", note: "" },
  ],
  pain_options: [
    { key: "cost", label: "太貴" },
    { key: "effort", label: "太麻煩" },
    { key: "uncertainty", label: "怕買錯" },
    { key: "availability", label: "買不到" },
    { key: "experience", label: "用起來不舒服" },
    { key: "identity", label: "不像我" },
  ],
};

const EVIDENCE: ProductEvidence = {
  proof: [
    { id: "pf_1", fact_key: "lab_report", text: "SGS 檢驗 12 項重金屬未檢出", source: "saved", note: "" },
    { id: "pf_2", fact_key: "customer_review", text: "「終於記得每天吃」", source: "saved", note: "" },
  ],
  proof_kinds: [
    { key: "customer_review", label: "顧客評論原話" },
    { key: "lab_report", label: "檢驗報告／認證" },
  ],
  claims: [
    { id: "cl_1", text: "一天一顆", from_note: "", source: "saved", verdict: "ok", statutory: null },
    { id: "cl_2", text: "不用配水", from_note: "", source: "saved", verdict: "ok", statutory: null },
    { id: "cl_3", text: "低糖", from_note: "", source: "saved", verdict: "ok", statutory: null },
    { id: "cl_4", text: "增強免疫", from_note: "", source: "saved", verdict: "no", statutory: { term: "增強免疫", sentence: "「增強免疫」屬改變生理功能" } },
  ],
};

function way(id: string | null, name: string, price: number, breakEven: number | null, offers: string[]): SellWayRow {
  return {
    id, name, price, list_price: price, list_price_derived: true, list_price_note: "", cost: 90, cost_derived: false,
    cost_note: "", shipping: 60, break_even: breakEven, cap_per_sale: breakEven, cap_is_default: true,
    landing_url: WHAT.page_url, landing_is_default: true, offer_labels: offers, offer_notes: [], assumptions: [],
    shape: "base", components: [], used_by: [], price_derived: false, price_note: "", cost_estimate: null, cost_missing: [],
    free_shipping: false, break_even_derived: false, offer_sentences: [], source: id ? "saved" : "ai", note: "",
  };
}

const SELL_WAYS: ProductSellWays = {
  sell_ways: [
    way("sw_single", "單盒", 399, 249, []),
    way("sw_three", "三盒組", 999, 669, ["組合價 省 198", "滿 NT$999 免運"]),
  ],
  show_close_rate: false,
  assumptions: {
    gross_margin: { value: 0.45, source_text: "毛利率假設 45%" },
    shipping_cost: { value: 60, source_text: "運費假設 60" },
  },
};

const status = (step: number, completed: boolean): ProductOnboardingStatus => ({
  step, completed, prefill_status: "done", prefill_error: null,
});

function renderDone({ completed = true, sellWays = SELL_WAYS, onboarding = status(5, true), whoError = "" } = {}) {
  vi.mocked(fetchProductOnboarding).mockResolvedValue(onboarding);
  if (whoError) vi.mocked(fetchProductWho).mockRejectedValueOnce(new Error(whoError)).mockResolvedValue(WHO);
  else vi.mocked(fetchProductWho).mockResolvedValue(WHO);
  vi.mocked(fetchProductEvidence).mockResolvedValue(EVIDENCE);
  vi.mocked(fetchProductSellWays).mockResolvedValue(sellWays);
  vi.mocked(completeProductOnboarding).mockResolvedValue(status(5, true));
  const onGoStep = vi.fn();
  const nav: StepNav = { crumb: productCrumb(B, WHAT.name), steps: PRODUCT_STEPS, current: 5 };
  render(
    <MemoryRouter>
      <ProductDoneStep brandId={B} productId={P} nav={nav} what={WHAT} completed={completed} onGoStep={onGoStep} />
    </MemoryRouter>,
  );
  return { onGoStep };
}

const rows = () => [...document.querySelectorAll('[data-slot="check-row"]')] as HTMLElement[];
const chip = () => within(screen.getByRole("region", { name: "這個商品" })).getByText(/可以投放|建到一半/);

describe("ProductDoneStep", () => {
  it("建好的商品：可以投放、四列全綠，內容只取已存的值", async () => {
    renderDone();
    await waitFor(() => expect(rows()).toHaveLength(4));
    expect(screen.getByRole("heading", { name: "綜合維他命軟糖建好了" })).toBeTruthy();
    expect(chip().textContent).toBe("可以投放");
    expect(rows().map((r) => r.dataset.state)).toEqual(["green", "green", "green", "green"]);
    expect(rows().map((r) => r.textContent)).toEqual([
      "✓商品是什麼一句話、成分、差異",
      "✓誰會買：2 群上班族（太麻煩）・運動族（怕買錯、太貴）",
      "✓證據 2 項・說法 3 可以講、1 不能講檢驗報告／認證、顧客評論原話",
      "✓賣法 2 種單盒 399（打平 249）・三盒組 999（打平 669，組合價 省 198＋滿 NT$999 免運）",
    ]);
    expect(screen.queryByRole("button", { name: "去補" })).toBeNull();
    // A finished product needs no status read and is not completed again.
    expect(fetchProductOnboarding).not.toHaveBeenCalled();
    expect(completeProductOnboarding).not.toHaveBeenCalled();
  });

  it("「用它建活動 →」帶第一個賣法的 id；另兩個出口到新增商品與新增組合", async () => {
    renderDone();
    const primary = await screen.findByRole("link", { name: "用它建活動 →" });
    expect(primary.getAttribute("href")).toBe(`/brands/${B}/ads/new?sell_way=sw_single`);
    expect(screen.getByRole("link", { name: "再建一個商品" }).getAttribute("href")).toBe(`/brands/${B}/products/new`);
    expect(screen.getByRole("link", { name: "做跨商品組合" }).getAttribute("href")).toBe(`/brands/${B}/products/bundles/new`);
  });

  it("還沒存賣法：建到一半、賣法列紅色，「去補」回第 4 步，不能拿它建活動", async () => {
    const proposal: ProductSellWays = { ...SELL_WAYS, sell_ways: [way(null, "單盒", 399, null, [])] };
    const { onGoStep } = renderDone({ completed: false, onboarding: status(4, false), sellWays: proposal });
    await waitFor(() => expect(rows()).toHaveLength(4));
    expect(chip().textContent).toBe("建到一半");
    expect(rows().map((r) => r.dataset.state)).toEqual(["green", "green", "green", "red"]);
    const red = rows()[3];
    expect(red.textContent).toBe("!賣法：還沒有去補");
    await userEvent.click(within(red).getByRole("button", { name: "去補" }));
    expect(onGoStep).toHaveBeenCalledWith(4);
    expect(screen.queryByRole("link", { name: "用它建活動 →" })).toBeNull();
    expect((screen.getByRole("button", { name: "用它建活動 →" }) as HTMLButtonElement).disabled).toBe(true);
    expect(completeProductOnboarding).not.toHaveBeenCalled();
  });

  it("四步都存了但沒記完成：進來時補完成一次，變可以投放", async () => {
    renderDone({ completed: false, onboarding: status(5, false) });
    await waitFor(() => expect(chip().textContent).toBe("可以投放"));
    expect(completeProductOnboarding).toHaveBeenCalledTimes(1);
    expect(completeProductOnboarding).toHaveBeenCalledWith(B, P);
    expect((await screen.findByRole("link", { name: "用它建活動 →" })).getAttribute("href")).toContain("sell_way=sw_single");
  });

  it("讀取失敗：顯示原因與重新載入", async () => {
    renderDone({ whoError: "讀取失敗（狀態碼 500）" });
    expect((await screen.findByRole("alert")).textContent).toBe("讀取失敗（狀態碼 500）");
    await userEvent.click(screen.getByRole("button", { name: "重新載入" }));
    await waitFor(() => expect(rows()).toHaveLength(4));
  });
});
