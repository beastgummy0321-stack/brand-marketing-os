/** frontend/src/components/intake/product/ProductEvidenceStep.test.tsx — product onboarding `#/p3` 證據與說法
 * (F43-I10): proof rows + the empty 專家背書 input; one 可以講／不能講 per claim, a 食安法 hit a reminder on the row
 * with its law line and the choice still the user's (F48 decision 13); 下一步 disabled with 「還有 N 句沒選」 while a claim is unset; 下一步 sends both lists in full through
 * `PUT …/onboarding/evidence`; 自訂 results join their lists. No server: the API calls are fakes. */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeProductApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeProductApi")>("@/lib/intakeProductApi");
  return { ...actual, fetchProductEvidence: vi.fn(), saveProductEvidence: vi.fn(), proposeProductCustom: vi.fn() };
});

import type { ProductEvidence } from "@/lib/intakeProductApi";
import { fetchProductEvidence, proposeProductCustom, saveProductEvidence } from "@/lib/intakeProductApi";
import type { StepNav } from "../OnboardingStepHead";
import { ProductEvidenceStep } from "./ProductEvidenceStep";

const mockFetch = vi.mocked(fetchProductEvidence);
const mockSave = vi.mocked(saveProductEvidence);
const mockPropose = vi.mocked(proposeProductCustom);

const NAV: StepNav = {
  crumb: [{ label: "商品" }, { label: "商品建檔", strong: true }, { label: "綜合維他命軟糖" }],
  steps: ["商品是什麼", "誰會買", "證據與說法", "賣法與價格", "完成"],
  current: 3,
};

const LAW = { term: "預防感冒", sentence: "「預防感冒」屬宣稱預防疾病（食安法第 28 條）" };

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.clearAllMocks();
});

function evidence(over: Partial<ProductEvidence> = {}): ProductEvidence {
  return {
    proof: [
      { id: "pf_1", fact_key: "lab_report", text: "SGS 重金屬與塑化劑檢驗合格（2026/06）", source: "saved", note: "" },
      { id: null, fact_key: "customer_review", text: "「終於找到不用配水的維他命，放包包隨時吃」", source: "ai", note: "評論區" },
    ],
    proof_kinds: [
      { key: "customer_review", label: "顧客評論原話" },
      { key: "expert_endorsement", label: "專家背書" },
      { key: "lab_report", label: "檢驗報告／認證" },
      { key: "sales_numbers", label: "銷售數據" },
      { key: "media_coverage", label: "媒體報導" },
      { key: "founder_voice", label: "創辦人第一手" },
    ],
    claims: [
      { id: "clm_1", text: "每顆含維生素 C 150 mg", from_note: "", source: "saved", verdict: "ok", statutory: null },
      { id: null, text: "增強免疫力、預防感冒", from_note: "商品頁", source: "ai", verdict: null, statutory: LAW },
      { id: null, text: "吃了精神變好", from_note: "顧客評論", source: "ai", verdict: null, statutory: null },
      { id: null, text: "不用配水，一天一顆", from_note: "商品頁", source: "ai", verdict: null, statutory: null },
    ],
    ...over,
  };
}

function renderStep(onNext = vi.fn()) {
  render(<ProductEvidenceStep brandId="brd_1" productId="prd_1" nav={NAV} back={{ label: "誰會買", onClick: vi.fn() }} onNext={onNext} />);
  return onNext;
}

const nextButton = () => screen.getByRole("button", { name: "下一步 →" }) as HTMLButtonElement;
const claimsCard = () => screen.getByRole("region", { name: "這些話可以在廣告裡講嗎" });
const proofCard = () => screen.getByRole("region", { name: "這個商品的證據" });
const verdictGroup = (text: string) => within(claimsCard()).getByRole("radiogroup", { name: text });

describe("ProductEvidenceStep", () => {
  it("F48 decision 13: 食安法命中的說法只在列上提醒法條，可以講／不能講照樣可選；選了可以講提醒還在", async () => {
    mockFetch.mockResolvedValue(evidence());
    renderStep();

    await screen.findByRole("region", { name: "這些話可以在廣告裡講嗎" });
    expect(mockFetch).toHaveBeenCalledWith("brd_1", "prd_1");
    const hit = claimsCard().querySelector(`[data-statutory="${LAW.term}"]`) as HTMLElement;
    expect(within(hit).getByText("增強免疫力、預防感冒")).toBeTruthy();
    expect(within(hit).getByText(LAW.sentence)).toBeTruthy();
    expect(hit.textContent).toContain("來自商品頁");
    expect(hit.getAttribute("data-claim")).toBe("unset");
    const ok = within(verdictGroup("增強免疫力、預防感冒")).getByRole("radio", { name: "可以講" }) as HTMLButtonElement;
    expect(ok.disabled).toBe(false);
    await userEvent.click(ok);
    expect(ok.getAttribute("aria-checked")).toBe("true");
    expect(within(hit).getByText(LAW.sentence)).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(within(verdictGroup("每顆含維生素 C 150 mg")).getByRole("radio", { name: "可以講" }).getAttribute("aria-checked")).toBe("true");
    expect(within(claimsCard()).getByText("來自顧客評論")).toBeTruthy();
  });

  it("證據列出種類、原話照搬的評論與 AI 標籤；沒有專家背書時留一格空白可填", async () => {
    mockFetch.mockResolvedValue(evidence());
    renderStep();

    await screen.findByRole("region", { name: "這個商品的證據" });
    const quote = proofCard().querySelector('[data-proof="customer_review"]') as HTMLElement;
    expect(within(quote).getByText("顧客評論原話")).toBeTruthy();
    expect(quote.textContent).toContain("原話照搬，不改寫");
    expect(within(quote).getByText("✦ 評論區")).toBeTruthy();
    const lab = proofCard().querySelector('[data-proof="lab_report"]') as HTMLElement;
    expect(lab.querySelector('[data-slot="ai-tag"]')).toBeNull();
    expect(within(proofCard()).getByRole("textbox", { name: "專家背書" }).getAttribute("placeholder")).toBe("誰、什麼身分、說了什麼；沒有就留空");
  });

  it("還有說法沒選時「下一步」不能按，並顯示還有幾句；選完就能按", async () => {
    mockFetch.mockResolvedValue(evidence());
    renderStep();

    await screen.findByText("還有 3 句沒選");
    expect(nextButton().disabled).toBe(true);
    expect(claimsCard().querySelectorAll('[data-claim="unset"]')).toHaveLength(3);

    await userEvent.click(within(verdictGroup("增強免疫力、預防感冒")).getByRole("radio", { name: "不能講" }));
    expect(screen.getByText("還有 2 句沒選")).toBeTruthy();
    await userEvent.click(within(verdictGroup("吃了精神變好")).getByRole("radio", { name: "不能講" }));
    expect(screen.getByText("還有 1 句沒選")).toBeTruthy();
    expect(nextButton().disabled).toBe(true);

    await userEvent.click(within(verdictGroup("不用配水，一天一顆")).getByRole("radio", { name: "可以講" }));
    expect(screen.queryByText(/句沒選/)).toBeNull();
    expect(nextButton().disabled).toBe(false);
  });

  it("「下一步」把證據與說法整份送出（食安法命中的照使用者選的可以講送出、空白格不送），成功才往下", async () => {
    mockFetch.mockResolvedValue(evidence());
    mockSave.mockResolvedValue(evidence());
    const onNext = renderStep();

    await screen.findByRole("region", { name: "這些話可以在廣告裡講嗎" });
    await userEvent.click(within(verdictGroup("增強免疫力、預防感冒")).getByRole("radio", { name: "可以講" }));
    await userEvent.click(within(verdictGroup("吃了精神變好")).getByRole("radio", { name: "不能講" }));
    await userEvent.click(within(verdictGroup("不用配水，一天一顆")).getByRole("radio", { name: "可以講" }));
    await userEvent.click(within(verdictGroup("每顆含維生素 C 150 mg")).getByRole("radio", { name: "不能講" }));
    await userEvent.type(within(proofCard()).getByRole("textbox", { name: "專家背書" }), "營養師王小明推薦");
    await userEvent.click(nextButton());

    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
    expect(mockSave).toHaveBeenCalledWith("brd_1", "prd_1", {
      proof: [
        { id: "pf_1", fact_key: "lab_report", text: "SGS 重金屬與塑化劑檢驗合格（2026/06）" },
        { id: null, fact_key: "customer_review", text: "「終於找到不用配水的維他命，放包包隨時吃」" },
        { fact_key: "expert_endorsement", text: "營養師王小明推薦" },
      ],
      claims: [
        { id: "clm_1", text: "每顆含維生素 C 150 mg", verdict: "no" },
        { id: null, text: "增強免疫力、預防感冒", verdict: "ok" },
        { id: null, text: "吃了精神變好", verdict: "no" },
        { id: null, text: "不用配水，一天一顆", verdict: "ok" },
      ],
    });
  });

  it("儲存失敗時留在這步並顯示原因", async () => {
    mockFetch.mockResolvedValue(evidence({ claims: [] }));
    mockSave.mockRejectedValue(new Error("還有 1 句沒選「可以講」或「不能講」。"));
    const onNext = renderStep();

    await screen.findByRole("region", { name: "這些話可以在廣告裡講嗎" });
    await userEvent.click(nextButton());
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "還有 1 句沒選「可以講」或「不能講」。");
    expect(onNext).not.toHaveBeenCalled();
  });

  it("自訂說法照 AI 的判斷加進清單並標「你自訂」；食安法命中的帶著提醒加進來，判斷不被改", async () => {
    mockFetch.mockResolvedValue(evidence({ claims: [] }));
    mockSave.mockResolvedValue(evidence());
    mockPropose
      .mockResolvedValueOnce({ block: "claim", kind: "option", option: { text: "一天一顆就夠", verdict: "ok", statutory: null } })
      .mockResolvedValueOnce({ block: "claim", kind: "option", option: { text: "吃了不會感冒", verdict: "ok", statutory: LAW } });
    const onNext = renderStep();

    await screen.findByRole("region", { name: "這些話可以在廣告裡講嗎" });
    const custom = () => within(claimsCard()).getByRole("button", { name: "✎ 自訂：用自己的話說" });
    await userEvent.click(custom());
    await userEvent.type(within(claimsCard()).getByRole("textbox"), "我想講一天一顆就夠");
    await userEvent.click(within(claimsCard()).getByRole("button", { name: "讓 AI 整理" }));

    const added = await within(claimsCard()).findByRole("radiogroup", { name: "一天一顆就夠" });
    expect(mockPropose).toHaveBeenCalledWith("brd_1", "prd_1", "claim", "我想講一天一顆就夠");
    expect(within(added).getByRole("radio", { name: "可以講" }).getAttribute("aria-checked")).toBe("true");
    const addedRow = added.closest("[data-claim]") as HTMLElement;
    expect(within(addedRow).getByText("你自訂")).toBeTruthy();

    await userEvent.click(custom());
    await userEvent.type(within(claimsCard()).getByRole("textbox"), "吃了不會感冒");
    await userEvent.click(within(claimsCard()).getByRole("button", { name: "讓 AI 整理" }));
    await within(claimsCard()).findByText(LAW.sentence);
    const hit = claimsCard().querySelector(`[data-statutory="${LAW.term}"]`) as HTMLElement;
    const hitGroup = within(hit).getByRole("radiogroup", { name: "吃了不會感冒" });
    expect(within(hitGroup).getByRole("radio", { name: "可以講" }).getAttribute("aria-checked")).toBe("true");
    expect(within(hit).getByText("你自訂")).toBeTruthy();

    await userEvent.click(nextButton());
    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
    expect(mockSave.mock.calls[0][2].claims).toEqual([
      { id: null, text: "一天一顆就夠", verdict: "ok" },
      { id: null, text: "吃了不會感冒", verdict: "ok" },
    ]);
  });

  it("自訂的食安法命中說法照 AI 給的不能講加進來，可以拿掉", async () => {
    mockFetch.mockResolvedValue(evidence({ claims: [] }));
    mockSave.mockResolvedValue(evidence());
    mockPropose.mockResolvedValueOnce({ block: "claim", kind: "option", option: { text: "吃了不會感冒", verdict: "no", statutory: LAW } });
    const onNext = renderStep();

    await screen.findByRole("region", { name: "這些話可以在廣告裡講嗎" });
    await userEvent.click(within(claimsCard()).getByRole("button", { name: "✎ 自訂：用自己的話說" }));
    await userEvent.type(within(claimsCard()).getByRole("textbox"), "吃了不會感冒");
    await userEvent.click(within(claimsCard()).getByRole("button", { name: "讓 AI 整理" }));
    await within(claimsCard()).findByText(LAW.sentence);
    const hit = claimsCard().querySelector(`[data-statutory="${LAW.term}"]`) as HTMLElement;
    expect(within(hit).getByRole("radio", { name: "不能講" }).getAttribute("aria-checked")).toBe("true");

    await userEvent.click(within(hit).getByRole("button", { name: "拿掉「吃了不會感冒」" }));
    expect(within(claimsCard()).queryByText("吃了不會感冒")).toBeNull();
    await userEvent.click(nextButton());
    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
    expect(mockSave.mock.calls[0][2].claims).toEqual([]);
  });

  it("自訂證據照 AI 整理的種類加進證據清單並標「你自訂」，一起送出", async () => {
    mockFetch.mockResolvedValue(evidence({ claims: [] }));
    mockSave.mockResolvedValue(evidence());
    mockPropose.mockResolvedValue({
      block: "product_proof", kind: "option",
      option: { fact_key: "expert_endorsement", label: "專家背書", text: "營養師在 IG 推薦過（有截圖）" },
    });
    renderStep();

    await screen.findByRole("region", { name: "這個商品的證據" });
    await userEvent.click(within(proofCard()).getByRole("button", { name: "✎ 自訂：用自己的話說" }));
    await userEvent.type(within(proofCard()).getByRole("textbox", { name: /覺得上面列的不對/ }), "營養師朋友在 IG 推薦過，有截圖");
    await userEvent.click(within(proofCard()).getByRole("button", { name: "讓 AI 整理" }));

    const row = await waitFor(() => proofCard().querySelector('[data-proof="expert_endorsement"]') as HTMLElement);
    expect(mockPropose).toHaveBeenCalledWith("brd_1", "prd_1", "product_proof", "營養師朋友在 IG 推薦過，有截圖");
    expect(within(row).getByText("你自訂")).toBeTruthy();
    expect(within(proofCard()).queryByRole("textbox", { name: "專家背書" })).toBeNull();

    await userEvent.click(nextButton());
    await waitFor(() => expect(mockSave).toHaveBeenCalledTimes(1));
    expect(mockSave.mock.calls[0][2].proof).toContainEqual({ id: null, fact_key: "expert_endorsement", text: "營養師在 IG 推薦過（有截圖）" });
  });

  it("F47-I03 (drill-10 乙 #1, b-04): a removed proof, a picked verdict and a typed slot survive leaving the step and coming back, until saved", async () => {
    mockFetch.mockResolvedValue(evidence());
    mockSave.mockResolvedValue(evidence());
    renderStep();
    await screen.findByRole("region", { name: "這個商品的證據" });
    await userEvent.click(within(proofCard()).getByRole("button", { name: /拿掉.*SGS/ }));
    await userEvent.click(within(verdictGroup("吃了精神變好")).getByRole("radio", { name: "不能講" }));
    await userEvent.type(within(proofCard()).getByLabelText("專家背書"), "營養師王小明推薦");
    cleanup();

    const onNext = renderStep();
    await screen.findByRole("region", { name: "這個商品的證據" });
    expect(within(proofCard()).queryByText(/SGS/)).toBeNull();
    expect(within(verdictGroup("吃了精神變好")).getByRole("radio", { name: "不能講" }).getAttribute("aria-checked")).toBe("true");
    expect((within(proofCard()).getByLabelText("專家背書") as HTMLInputElement).value).toBe("營養師王小明推薦");

    await userEvent.click(within(verdictGroup("不用配水，一天一顆")).getByRole("radio", { name: "可以講" }));
    await userEvent.click(within(verdictGroup("增強免疫力、預防感冒")).getByRole("radio", { name: "不能講" }));
    await userEvent.click(nextButton());
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(sessionStorage.length).toBe(0);
  });
});


it("Enter commits only the inline proof edit", async () => {
  mockFetch.mockResolvedValue(evidence({claims:[]}));
  const onNext = renderStep();
  await userEvent.click(await screen.findByRole("button", {name:/改「SGS/}));
  const box = screen.getByRole("textbox", {name:"檢驗報告／認證"});
  await userEvent.clear(box);
  await userEvent.type(box, "修正後的檢驗描述{Enter}");
  expect(screen.getByText("修正後的檢驗描述")).toBeTruthy();
  expect(mockSave).not.toHaveBeenCalled();
  expect(onNext).not.toHaveBeenCalled();
});
