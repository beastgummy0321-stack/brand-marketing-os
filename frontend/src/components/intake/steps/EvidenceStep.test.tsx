/** frontend/src/components/intake/steps/EvidenceStep.test.tsx — brand onboarding `#/b4` 證據與政策 (F42-I09):
 * the policy chips and 「更多政策」 come from the API registry; a chosen policy shows its params and the offer it
 * becomes; an empty required param or a 不適用 cooling-off without text blocks 下一步 with the reason in the bar;
 * 下一步 sends every list in full through `PUT …/onboarding/evidence`; 自訂 results join their lists. No server:
 * the API calls are fakes. */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeOnboardingApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeOnboardingApi")>("@/lib/intakeOnboardingApi");
  return { ...actual, fetchOnboardingEvidence: vi.fn(), saveOnboardingEvidence: vi.fn(), proposeCustom: vi.fn() };
});

import type { OnboardingEvidence, PolicyType } from "@/lib/intakeOnboardingApi";
import { fetchOnboardingEvidence, proposeCustom, saveOnboardingEvidence } from "@/lib/intakeOnboardingApi";
import { BRAND_STEPS, brandCrumb, type StepNav } from "../OnboardingStepHead";
import { EvidenceStep } from "./EvidenceStep";

const mockFetch = vi.mocked(fetchOnboardingEvidence);
const mockSave = vi.mocked(saveOnboardingEvidence);
const mockPropose = vi.mocked(proposeCustom);

const NAV: StepNav = { crumb: brandCrumb("山嵐手作果醬"), steps: BRAND_STEPS, current: 4 };

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const type = (t: Partial<PolicyType> & Pick<PolicyType, "key" | "group" | "label" | "offer_key" | "offer_label">): PolicyType => ({
  params: [], common: false, threshold: null, template: t.label, ...t,
});

/** A slice of the server registry (`vocab.POLICY_TYPES`) in its order: 3 common, 4 more in 3 groups. */
const TYPES: PolicyType[] = [
  type({ key: "ship_threshold", group: "運送", label: "滿額免運", params: [{ name: "threshold", label: "門檻 NT$", kind: "money" }], offer_key: "free_shipping", offer_label: "免運", common: true, threshold: "threshold", template: "滿 NT${threshold} 免運" }),
  type({ key: "ship_cvs", group: "運送", label: "超商取貨免運", params: [{ name: "threshold", label: "門檻 NT$（0＝不設）", kind: "money", optional: true }], offer_key: "free_shipping", offer_label: "免運", common: true, threshold: "threshold" }),
  type({ key: "ship_all", group: "運送", label: "全館免運", offer_key: "free_shipping", offer_label: "免運" }),
  type({ key: "first_order", group: "首購與會員", label: "新會員首購禮", params: [{ name: "content", label: "內容", kind: "text" }], offer_key: "discount", offer_label: "折扣", common: true }),
  type({ key: "birthday", group: "首購與會員", label: "生日禮", params: [{ name: "content", label: "內容", kind: "text" }], offer_key: "discount", offer_label: "折扣" }),
  type({ key: "cod", group: "付款", label: "貨到付款", offer_key: "none", offer_label: "安心賣點" }),
  type({ key: "gift_box", group: "出貨與服務", label: "禮盒包裝", offer_key: "none", offer_label: "安心賣點" }),
];

function evidence(over: Partial<OnboardingEvidence> = {}): OnboardingEvidence {
  return {
    proof: [
      { id: null, fact_key: "founder_voice", text: "創辦人是健身教練，吞不下藥丸才自己做軟糖", source: "ai", note: "about 頁" },
    ],
    proof_kinds: [
      { key: "customer_review", label: "顧客評論原話" },
      { key: "expert_endorsement", label: "專家背書" },
      { key: "lab_report", label: "檢驗報告／認證" },
      { key: "sales_numbers", label: "銷售數據" },
      { key: "media_coverage", label: "媒體報導" },
      { key: "founder_voice", label: "創辦人第一手" },
    ],
    policies: [
      { key: "ship_threshold", label: "滿額免運", group: "運送", params: { threshold: 999 }, offer_key: "free_shipping", offer_label: "免運", sentence: "滿 NT$999 免運", source: "ai", note: "運費說明頁" },
    ],
    policy_types: TYPES,
    cooling_off: { applies: true, disclosure: "" },
    forbidden: [{ id: "rul_1", text: "不講「最」「第一」" }],
    regime_label: "台灣食品（食安法）",
    ...over,
  };
}

function renderStep(onNext = vi.fn()) {
  render(
    <MemoryRouter initialEntries={["/brands/brd_1/intake"]}>
      <Routes>
        <Route path="/brands/:brandId/intake" element={<EvidenceStep nav={NAV} back={{ label: "品牌是誰", onClick: vi.fn() }} onNext={onNext} />} />
      </Routes>
    </MemoryRouter>,
  );
  return onNext;
}

const nextButton = () => screen.getByRole("button", { name: "下一步 →" }) as HTMLButtonElement;
const policyCard = () => screen.getByRole("region", { name: "全店政策" });
const chipNames = (group: string) =>
  within(within(policyCard()).getByRole("group", { name: group })).getAllByRole("button").map((b) => b.textContent);
const chosenRow = (key: string) => document.querySelector(`[data-policy="${key}"]`) as HTMLElement;

describe("EvidenceStep", () => {
  it("常見的政策照 API 的清單順序出現；「更多政策」列出其餘種類並按分組，再按一次收起", async () => {
    mockFetch.mockResolvedValue(evidence());
    renderStep();

    await screen.findByRole("region", { name: "全店政策" });
    expect(mockFetch).toHaveBeenCalledWith("brd_1");
    expect(chipNames("常見的")).toEqual(["滿額免運", "超商取貨免運", "新會員首購禮"]);
    expect(within(policyCard()).queryByRole("group", { name: "付款" })).toBeNull();

    const more = within(policyCard()).getByRole("button", { name: "更多政策（4 種）" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    await userEvent.click(more);

    expect(chipNames("運送")).toEqual(["全館免運"]);
    expect(chipNames("首購與會員")).toEqual(["生日禮"]);
    expect(chipNames("付款")).toEqual(["貨到付款"]);
    expect(chipNames("出貨與服務")).toEqual(["禮盒包裝"]);

    await userEvent.click(within(policyCard()).getByRole("button", { name: "收起" }));
    expect(within(policyCard()).queryByRole("group", { name: "付款" })).toBeNull();
  });

  it("AI 讀到的政策已勾選，帶參數、廣告裡會當成什麼與掃描的標籤；7 天猶豫期固定顯示", async () => {
    mockFetch.mockResolvedValue(evidence());
    renderStep();

    await screen.findByRole("region", { name: "全店政策" });
    expect(within(policyCard()).getByRole("button", { name: "滿額免運" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("你有的（1）")).toBeTruthy();
    const row = chosenRow("ship_threshold");
    expect((within(row).getByLabelText("門檻 NT$") as HTMLInputElement).value).toBe("999");
    expect(row.textContent).toContain("廣告裡會當成：免運・");
    expect(within(row).getByText("✦ 運費說明頁")).toBeTruthy();
    expect(screen.getByText("7 天猶豫期")).toBeTruthy();
    expect(screen.getByText("網購依法都有，顧客收到 7 天內可以退")).toBeTruthy();
    expect(nextButton().disabled).toBe(false);
  });

  it("勾一個政策：出現它的參數欄與「廣告裡會當成」，沒參數的寫「不用填」；再按一次拿掉", async () => {
    mockFetch.mockResolvedValue(evidence({ policies: [] }));
    renderStep();

    await userEvent.click(await within(await screen.findByRole("region", { name: "全店政策" })).findByRole("button", { name: "新會員首購禮" }));
    const row = chosenRow("first_order");
    expect(within(row).getByLabelText("內容")).toBeTruthy();
    expect(row.textContent).toContain("廣告裡會當成：折扣・你選的");
    expect(screen.getByText("你有的（1）")).toBeTruthy();

    await userEvent.click(within(policyCard()).getByRole("button", { name: "更多政策（4 種）" }));
    await userEvent.click(within(policyCard()).getByRole("button", { name: "貨到付款" }));
    const cod = chosenRow("cod");
    expect(within(cod).getByText("不用填")).toBeTruthy();
    expect(cod.textContent).toContain("廣告裡會當成：安心賣點・你選的");
    expect(screen.getByText("你有的（2）")).toBeTruthy();

    await userEvent.click(within(policyCard()).getByRole("button", { name: "新會員首購禮" }));
    expect(chosenRow("first_order")).toBeNull();
    expect(screen.getByText("你有的（1）")).toBeTruthy();
  });

  it("勾了要填的參數卻沒填：下一步不能按，原因寫在底部；填了就能按", async () => {
    mockFetch.mockResolvedValue(evidence({ policies: [] }));
    renderStep();

    await userEvent.click(await within(await screen.findByRole("region", { name: "全店政策" })).findByRole("button", { name: "滿額免運" }));
    expect(screen.getByRole("status").textContent).toBe("滿額免運還沒填門檻");
    expect(nextButton().disabled).toBe(true);

    await userEvent.type(within(chosenRow("ship_threshold")).getByLabelText("門檻 NT$"), "1200");
    expect(screen.queryByRole("status")).toBeNull();
    expect(nextButton().disabled).toBe(false);
  });

  it("選填的參數可以留空（超商取貨免運的門檻）", async () => {
    mockFetch.mockResolvedValue(evidence({ policies: [] }));
    mockSave.mockResolvedValue(evidence());
    renderStep();

    await userEvent.click(await within(await screen.findByRole("region", { name: "全店政策" })).findByRole("button", { name: "超商取貨免運" }));
    expect(nextButton().disabled).toBe(false);
    await userEvent.click(nextButton());
    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    expect(mockSave.mock.calls[0][1].policies).toEqual([{ key: "ship_cvs", params: {} }]);
  });

  it("7 天猶豫期改成「不適用」要填告知文字，沒填夠不能下一步；送出時走 cooling_off", async () => {
    mockFetch.mockResolvedValue(evidence());
    mockSave.mockResolvedValue(evidence());
    const onNext = renderStep();

    const link = await screen.findByRole("button", { name: "改成「不適用」並填網頁上的告知文字" });
    await userEvent.click(link);
    expect(link.getAttribute("aria-expanded")).toBe("true");
    expect(nextButton().disabled).toBe(true);
    expect(screen.getByRole("status").textContent).toContain("要填網頁上的告知文字");

    await userEvent.type(screen.getByLabelText("網頁上的告知文字"), "本店商品為易腐敗食品，依法不適用七天猶豫期");
    expect(nextButton().disabled).toBe(false);
    await userEvent.click(nextButton());

    await waitFor(() => expect(onNext).toHaveBeenCalled());
    const body = mockSave.mock.calls[0][1];
    expect(body.cooling_off).toEqual({ applies: false, disclosure: "本店商品為易腐敗食品，依法不適用七天猶豫期" });
    expect(body.policies.some((p) => p.key === "cooling_off_exempt")).toBe(false);
  });

  it("已存的「不適用」帶回告知文字；再按連結改回適用", async () => {
    mockFetch.mockResolvedValue(evidence({ cooling_off: { applies: false, disclosure: "生鮮食品不適用七天猶豫期" } }));
    mockSave.mockResolvedValue(evidence());
    renderStep();

    expect((await screen.findByLabelText("網頁上的告知文字") as HTMLTextAreaElement).value).toBe("生鮮食品不適用七天猶豫期");
    await userEvent.click(screen.getByRole("button", { name: "改成「不適用」並填網頁上的告知文字" }));
    expect(screen.queryByLabelText("網頁上的告知文字")).toBeNull();
    await userEvent.click(nextButton());
    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    expect(mockSave.mock.calls[0][1].cooling_off).toEqual({ applies: true });
  });

  it("下一步送出完整清單：證據（含空白欄填的）、政策、猶豫期、不能講的話；拿掉的不送", async () => {
    mockFetch.mockResolvedValue(evidence({
      proof: [
        { id: "bft_1", fact_key: "customer_review", text: "吃了三個月，早上不再忘記補充", source: "saved", note: "" },
        { id: null, fact_key: "founder_voice", text: "創辦人是健身教練，吞不下藥丸才自己做軟糖", source: "ai", note: "about 頁" },
      ],
    }));
    mockSave.mockResolvedValue(evidence());
    const onNext = renderStep();

    const proof = await screen.findByRole("region", { name: "讓人相信你的東西（品牌層）" });
    expect(within(proof).getByText("✦ about 頁")).toBeTruthy();
    await userEvent.type(within(proof).getByLabelText("銷售數據"), "累積賣出 12,000 盒");
    expect((within(proof).getByLabelText("媒體報導") as HTMLInputElement).placeholder).toBe("哪個媒體、哪一天報導；沒有就留空");
    await userEvent.click(within(proof).getByRole("button", { name: "改「吃了三個月，早上不再忘記補充」" }));
    await userEvent.type(within(proof).getByLabelText("顧客評論原話"), "！");
    await userEvent.click(screen.getByRole("button", { name: "拿掉「不講「最」「第一」」" }));
    await userEvent.click(nextButton());

    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(mockSave).toHaveBeenCalledWith("brd_1", {
      proof: [
        { id: "bft_1", fact_key: "customer_review", text: "吃了三個月，早上不再忘記補充！" },
        { id: null, fact_key: "founder_voice", text: "創辦人是健身教練，吞不下藥丸才自己做軟糖" },
        { fact_key: "sales_numbers", text: "累積賣出 12,000 盒" },
      ],
      policies: [{ key: "ship_threshold", params: { threshold: 999 } }],
      cooling_off: { applies: true },
      forbidden: [],
    });
  });

  it("拿掉一條證據就不送；那種證據若是媒體報導或銷售數據，空白欄回來", async () => {
    mockFetch.mockResolvedValue(evidence({
      proof: [{ id: "bft_2", fact_key: "media_coverage", text: "2026/08 商周報導", source: "saved", note: "" }],
    }));
    mockSave.mockResolvedValue(evidence());
    renderStep();

    const proof = await screen.findByRole("region", { name: "讓人相信你的東西（品牌層）" });
    expect(within(proof).queryByLabelText("媒體報導")).toBeNull();
    await userEvent.click(within(proof).getByRole("button", { name: "拿掉「2026/08 商周報導」" }));
    expect(within(proof).getByLabelText("媒體報導")).toBeTruthy();
    await userEvent.click(nextButton());
    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    expect(mockSave.mock.calls[0][1].proof).toEqual([]);
  });

  it("自訂的政策以「你自訂」勾進「你有的」，送出時帶它自己的那句話", async () => {
    mockFetch.mockResolvedValue(evidence());
    mockSave.mockResolvedValue(evidence());
    mockPropose.mockResolvedValue({
      block: "policy",
      kind: "option",
      option: {
        key: "custom", label: "訂滿三個月送隨身包", offer_key: "bundle", offer_label: "組合加贈",
        sentence: "訂滿三個月，第四個月送一包隨身包", params: { label: "訂滿三個月送隨身包", offer_key: "bundle" },
      },
    });
    const onNext = renderStep();

    const card = await screen.findByRole("region", { name: "全店政策" });
    await userEvent.click(within(card).getByRole("button", { name: "✎ 自訂：用自己的話說" }));
    await userEvent.type(within(card).getByRole("textbox", { name: /覺得上面列的不對/ }), "買滿三個月的顧客，第四個月送一包隨身包");
    await userEvent.click(within(card).getByRole("button", { name: "讓 AI 整理" }));

    const row = await waitFor(() => chosenRow("custom"));
    expect(mockPropose).toHaveBeenCalledWith("brd_1", "policy", "買滿三個月的顧客，第四個月送一包隨身包");
    expect(within(row).getByText("訂滿三個月送隨身包")).toBeTruthy();
    expect(row.textContent).toContain("廣告裡會當成：組合加贈・你自訂");
    expect(screen.getByText("你有的（2）")).toBeTruthy();
    expect(within(card).getAllByText("你自訂").length).toBe(1);

    await userEvent.click(nextButton());
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(mockSave.mock.calls[0][1].policies).toEqual([
      { key: "ship_threshold", params: { threshold: 999 } },
      { key: "custom", params: { label: "訂滿三個月送隨身包", offer_key: "bundle" }, sentence: "訂滿三個月，第四個月送一包隨身包" },
    ]);
  });

  it("不能講的話：法規標籤、說明，自己加的一條一條；自訂的加進清單", async () => {
    mockFetch.mockResolvedValue(evidence());
    mockSave.mockResolvedValue(evidence());
    mockPropose.mockResolvedValue({ block: "forbidden", kind: "option", option: { text: "不拿別的品牌比較" } });
    renderStep();

    const card = await screen.findByRole("region", { name: "不能講的話" });
    expect(within(card).getByText("台灣食品（食安法）")).toBeTruthy();
    expect(within(card).getByText("已套用食安法常見禁語（治療、預防、改善疾病…）；你自己還有不想講的，加在這裡。")).toBeTruthy();
    expect(within(card).getByText("不講「最」「第一」")).toBeTruthy();
    expect(within(card).getByText("你自己加的")).toBeTruthy();

    await userEvent.click(within(card).getByRole("button", { name: "✎ 自訂：用自己的話說" }));
    await userEvent.type(within(card).getByRole("textbox"), "不要拿別的品牌比較");
    await userEvent.click(within(card).getByRole("button", { name: "讓 AI 整理" }));
    await waitFor(() => expect(within(card).getByText("不拿別的品牌比較")).toBeTruthy());
    expect(within(card).getAllByText("你自訂").length).toBe(1);
    expect(within(card).getAllByText("你自己加的").length).toBe(1);

    await userEvent.click(nextButton());
    await waitFor(() => expect(mockSave).toHaveBeenCalled());
    expect(mockSave.mock.calls[0][1].forbidden).toEqual(["不講「最」「第一」", "不拿別的品牌比較"]);
  });

  it("自訂的證據加進證據清單、標「你自訂」（只出現這一處），它的 × 拿掉", async () => {
    mockFetch.mockResolvedValue(evidence());
    mockSave.mockResolvedValue(evidence());
    mockPropose.mockResolvedValue({
      block: "brand_proof", kind: "option",
      option: { fact_key: "media_coverage", label: "媒體報導", text: "上過《好好吃飯》Podcast 第 42 集" },
    });
    renderStep();

    const card = await screen.findByRole("region", { name: "讓人相信你的東西（品牌層）" });
    await userEvent.click(within(card).getByRole("button", { name: "✎ 自訂：用自己的話說" }));
    await userEvent.type(within(card).getByRole("textbox", { name: /覺得上面列的不對/ }), "我們上過好好吃飯 Podcast");
    await userEvent.click(within(card).getByRole("button", { name: "讓 AI 整理" }));

    await waitFor(() => expect(within(card).getByText("上過《好好吃飯》Podcast 第 42 集")).toBeTruthy());
    expect(within(card).getAllByText("你自訂").length).toBe(1);
    expect(within(card).queryByLabelText("媒體報導")).toBeNull();

    await userEvent.click(within(card).getByRole("button", { name: "拿掉「上過《好好吃飯》Podcast 第 42 集」" }));
    expect(within(card).queryByText("你自訂")).toBeNull();
    expect(within(card).getByLabelText("媒體報導")).toBeTruthy();
  });

  it("沒有適用法規：不顯示法規標籤與禁語說明", async () => {
    mockFetch.mockResolvedValue(evidence({ regime_label: "", forbidden: [] }));
    renderStep();

    const card = await screen.findByRole("region", { name: "不能講的話" });
    expect(within(card).queryByText(/食安法/)).toBeNull();
  });

  it("伺服器擋下時留在這一步並顯示原因", async () => {
    mockFetch.mockResolvedValue(evidence());
    mockSave.mockRejectedValue(new Error("「滿額免運」要填「門檻 NT$」"));
    const onNext = renderStep();

    await screen.findByRole("region", { name: "全店政策" });
    await userEvent.click(nextButton());

    expect((await screen.findByRole("alert")).textContent).toBe("「滿額免運」要填「門檻 NT$」");
    expect(onNext).not.toHaveBeenCalled();
    expect(screen.getByRole("region", { name: "全店政策" })).toBeTruthy();
  });

  it("讀取失敗時顯示原因，沒有表單", async () => {
    mockFetch.mockRejectedValue(new Error("讀取失敗，請稍後再試。"));
    renderStep();

    expect((await screen.findByRole("alert")).textContent).toBe("讀取失敗，請稍後再試。");
    expect(screen.queryByRole("region", { name: "全店政策" })).toBeNull();
  });
});
