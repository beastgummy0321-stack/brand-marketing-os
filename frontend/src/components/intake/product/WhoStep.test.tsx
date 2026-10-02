/** frontend/src/components/intake/product/WhoStep.test.tsx — product onboarding `#/p2` 誰會買、買之前煩什麼 (F43-I09):
 * the product-page read's groups show prefilled with their tag; each group picks 1–2 of the six pains (a third drops
 * the oldest); 「自訂」 under the groups appends a group (its pains checked, marked 你自訂) and hides at three; 「自訂」
 * under a group's pains checks the mapped pain and fills the quote; 下一步 sends the full list through
 * `PUT …/onboarding/who` and moves on only after the server confirmed; a group without 是誰 or without a pain keeps
 * 下一步 off with the reason in the bar. Fixtures are shaped like `app/intake/product_onboarding.py::get_who()`. No server. */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeProductApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeProductApi")>("@/lib/intakeProductApi");
  return { ...actual, fetchProductWho: vi.fn(), proposeProductCustom: vi.fn(), saveProductWho: vi.fn() };
});

import type { ProductWho } from "@/lib/intakeProductApi";
import { fetchProductWho, proposeProductCustom, saveProductWho } from "@/lib/intakeProductApi";
import type { StepNav } from "../OnboardingStepHead";
import { PRODUCT_STEPS, productCrumb } from "./ProductOnboarding";
import { WhoStep } from "./WhoStep";

const mockFetch = vi.mocked(fetchProductWho);
const mockSave = vi.mocked(saveProductWho);
const mockCustom = vi.mocked(proposeProductCustom);

const B = "brd_1";
const P = "prd_vit";

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.clearAllMocks();
});

const PAIN_OPTIONS: ProductWho["pain_options"] = [
  { key: "cost", label: "太貴" },
  { key: "effort", label: "太麻煩" },
  { key: "uncertainty", label: "怕買錯" },
  { key: "availability", label: "買不到" },
  { key: "experience", label: "用起來不舒服" },
  { key: "identity", label: "不像我" },
];

function prefilled(): ProductWho {
  return {
    groups: [
      { id: null, who: "上班族、常加班的 25–40 歲", pain_keys: ["effort"], quote: "「每天吃一堆藥丸好麻煩，常常忘記」", when_used: "早上出門前、辦公桌上", source: "ai", note: "從評論與商品頁推測" },
      { id: null, who: "有運動習慣、在意營養的人", pain_keys: ["uncertainty"], quote: "「不知道軟糖的含量夠不夠」", when_used: "練完之後", source: "ai", note: "從評論與商品頁推測" },
    ],
    pain_options: PAIN_OPTIONS,
  };
}

const nav: StepNav = { crumb: productCrumb(B, "綜合維他命軟糖"), steps: PRODUCT_STEPS, current: 2 };

function renderWho(who: ProductWho) {
  mockFetch.mockResolvedValue(who);
  const onNext = vi.fn();
  render(
    <MemoryRouter>
      <WhoStep brandId={B} productId={P} nav={nav} back={{ label: "商品是什麼", onClick: vi.fn() }} onNext={onNext} />
    </MemoryRouter>,
  );
  return { onNext };
}

const group = (n: number) => screen.getByRole("group", { name: `第 ${n} 群` });
const pains = (n: number) => within(group(n)).getByRole("group", { name: "買之前最煩什麼" });
const pressed = (n: number) =>
  within(pains(n)).getAllByRole("button").filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.textContent);
const input = (n: number, label: string) => within(group(n)).getByLabelText(label) as HTMLInputElement;
const nextButton = () => screen.getByRole("button", { name: "下一步 →" }) as HTMLButtonElement;
const customButtons = () => screen.getAllByRole("button", { name: "✎ 自訂：用自己的話說" });
const groupCustom = () => document.querySelectorAll('[data-slot="custom-escape"][data-block="group"]');
const customBox = () => screen.getByRole("textbox", { name: /覺得上面列的不對/ });

describe("WhoStep", () => {
  it("商品頁讀到的顧客群帶入：是誰、煩惱、顧客會怎麼說、什麼時候用，群標上來源", async () => {
    renderWho(prefilled());

    expect(await screen.findByRole("group", { name: "第 2 群" })).toBeTruthy();
    expect(input(1, "是誰").value).toBe("上班族、常加班的 25–40 歲");
    expect(pressed(1)).toEqual(["太麻煩"]);
    expect(input(1, "顧客會怎麼說").value).toBe("「每天吃一堆藥丸好麻煩，常常忘記」");
    expect(input(1, "什麼時候用").value).toBe("早上出門前、辦公桌上");
    expect(pressed(2)).toEqual(["怕買錯"]);
    expect(within(pains(1)).getAllByRole("button").map((b) => b.textContent)).toEqual(PAIN_OPTIONS.map((o) => o.label));
    expect(screen.getAllByText("✦ 從評論與商品頁推測")).toHaveLength(2);
    expect(screen.getByText("最多 3 群；AI 會把你的描述整理成一群、並對上煩惱類型")).toBeTruthy();
    expect(nextButton().disabled).toBe(false);
  });

  it("已確認的群沒有來源標籤；改過的群拿掉標籤", async () => {
    const who = prefilled();
    who.groups[0] = { ...who.groups[0], id: "pcg_1", source: "saved", note: "" };
    renderWho(who);

    await screen.findByRole("group", { name: "第 2 群" });
    expect(screen.getAllByText("✦ 從評論與商品頁推測")).toHaveLength(1);
    await userEvent.type(input(2, "什麼時候用"), "、睡前");
    expect(screen.queryByText("✦ 從評論與商品頁推測")).toBeNull();
  });

  it("煩惱最多挑 2 個：挑第三個把最早挑的換掉；可以取消", async () => {
    renderWho(prefilled());
    await screen.findByRole("group", { name: "第 1 群" });

    await userEvent.click(within(pains(1)).getByRole("button", { name: "太貴" }));
    expect(pressed(1)).toEqual(["太貴", "太麻煩"]);
    await userEvent.click(within(pains(1)).getByRole("button", { name: "不像我" }));
    expect(pressed(1)).toEqual(["太貴", "不像我"]);
    await userEvent.click(within(pains(1)).getByRole("button", { name: "太貴" }));
    expect(pressed(1)).toEqual(["不像我"]);
  });

  it("下一步送出整份清單（沒改的帶原來源、改過的算使用者、已確認的帶 id），存好才往下", async () => {
    const who = prefilled();
    who.groups[1] = { ...who.groups[1], id: "pcg_2", source: "saved", note: "" };
    mockSave.mockResolvedValue(who);
    const { onNext } = renderWho(who);
    await screen.findByRole("group", { name: "第 2 群" });

    await userEvent.click(within(pains(1)).getByRole("button", { name: "太貴" }));
    await userEvent.click(within(pains(1)).getByRole("button", { name: "怕買錯" }));
    await userEvent.clear(input(1, "是誰"));
    await userEvent.type(input(1, "是誰"), " 上班族 ");
    await userEvent.click(nextButton());

    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(mockSave).toHaveBeenCalledWith(B, P, [
      { id: null, who: "上班族", pain_keys: ["cost", "uncertainty"], quote: "「每天吃一堆藥丸好麻煩，常常忘記」", when_used: "早上出門前、辦公桌上", source: "user" },
      { id: "pcg_2", who: "有運動習慣、在意營養的人", pain_keys: ["uncertainty"], quote: "「不知道軟糖的含量夠不夠」", when_used: "練完之後", source: "saved" },
    ]);
  });

  it("沒改就下一步：AI 帶的群以 ai 來源送出", async () => {
    mockSave.mockResolvedValue(prefilled());
    const { onNext } = renderWho(prefilled());
    await screen.findByRole("group", { name: "第 2 群" });

    await userEvent.click(nextButton());

    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(mockSave.mock.calls[0][2].map((g) => g.source)).toEqual(["ai", "ai"]);
  });

  it("有群沒寫是誰或沒挑煩惱：下一步不能按，原因寫在底部；補上就能按", async () => {
    renderWho(prefilled());
    await screen.findByRole("group", { name: "第 2 群" });

    await userEvent.clear(input(2, "是誰"));
    expect(nextButton().disabled).toBe(true);
    expect(screen.getByText("第 2 群還沒寫是誰")).toBeTruthy();
    await userEvent.type(input(2, "是誰"), "健身族");
    await userEvent.click(within(pains(1)).getByRole("button", { name: "太麻煩" }));
    expect(nextButton().disabled).toBe(true);
    expect(screen.getByText("第 1 群還沒挑煩惱")).toBeTruthy();
    await userEvent.click(within(pains(1)).getByRole("button", { name: "買不到" }));
    expect(nextButton().disabled).toBe(false);
    expect(screen.queryByText("第 1 群還沒挑煩惱")).toBeNull();
    expect(mockSave).not.toHaveBeenCalled();
  });

  it("存檔失敗留在這一步、輸入不清空", async () => {
    mockSave.mockRejectedValue(new Error("第 1 群：是誰不能超過 100 字。"));
    const { onNext } = renderWho(prefilled());
    await screen.findByRole("group", { name: "第 1 群" });

    await userEvent.click(nextButton());

    expect((await screen.findByRole("alert")).textContent).toBe("第 1 群：是誰不能超過 100 字。");
    expect(onNext).not.toHaveBeenCalled();
    expect(input(1, "是誰").value).toBe("上班族、常加班的 25–40 歲");
  });

  it("群底下的「自訂」走商品那支 group，加一群（煩惱已勾、標你自訂）；滿 3 群就收起來", async () => {
    mockCustom.mockResolvedValue({
      block: "group",
      kind: "option",
      option: { who: "買給爸媽的子女", pain_keys: ["experience", "uncertainty"], quote: "「長輩吞不下藥丸」", when_used: "早餐後" },
    });
    mockSave.mockResolvedValue(prefilled());
    const { onNext } = renderWho(prefilled());
    await screen.findByRole("group", { name: "第 2 群" });

    await userEvent.click(customButtons().at(-1)!);
    expect(customBox().getAttribute("placeholder")).toBe("例如：買給爸媽的子女，怕長輩吞不下藥丸");
    await userEvent.type(customBox(), "買給爸媽的子女，怕長輩吞不下藥丸");
    await userEvent.click(screen.getByRole("button", { name: "讓 AI 整理" }));

    expect(await screen.findByRole("group", { name: "第 3 群" })).toBeTruthy();
    expect(mockCustom).toHaveBeenCalledWith(B, P, "group", "買給爸媽的子女，怕長輩吞不下藥丸");
    expect(input(3, "是誰").value).toBe("買給爸媽的子女");
    expect(pressed(3)).toEqual(["怕買錯", "用起來不舒服"]);
    expect(within(group(3)).getByText("你自訂")).toBeTruthy();
    // Three groups: the group 自訂 is gone, each group keeps its pain 自訂.
    expect(groupCustom()).toHaveLength(0);
    expect(customButtons()).toHaveLength(3);
    expect(screen.getByText("最多 3 群；AI 會把你的描述整理成一群、並對上煩惱類型")).toBeTruthy();

    await userEvent.click(nextButton());
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(mockSave.mock.calls[0][2][2]).toEqual({
      id: null,
      who: "買給爸媽的子女",
      pain_keys: ["experience", "uncertainty"],
      quote: "「長輩吞不下藥丸」",
      when_used: "早餐後",
      source: "custom",
    });
  });

  it("拿掉一群：後面的群往前編號，3 群時收起的「自訂」回來", async () => {
    const who = prefilled();
    who.groups.push({ id: null, who: "學生", pain_keys: ["cost"], quote: "", when_used: "", source: "ai", note: "從評論與商品頁推測" });
    renderWho(who);
    await screen.findByRole("group", { name: "第 3 群" });
    expect(groupCustom()).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "拿掉第 1 群" }));

    expect(screen.queryByRole("group", { name: "第 3 群" })).toBeNull();
    expect(input(1, "是誰").value).toBe("有運動習慣、在意營養的人");
    expect(groupCustom()).toHaveLength(1);
  });

  it("煩惱的「自訂」走商品那支 pain：勾上對到的煩惱、填進顧客會怎麼說並標你自訂", async () => {
    mockCustom.mockResolvedValue({ block: "pain", kind: "option", option: { pain_key: "uncertainty", label: "怕買錯", quote: "「怕吃了跟藥物衝突」" } });
    renderWho(prefilled());
    await screen.findByRole("group", { name: "第 1 群" });

    await userEvent.click(within(group(1)).getByRole("button", { name: "✎ 自訂：用自己的話說" }));
    expect(customBox().getAttribute("placeholder")).toBe("例如：怕吃了跟藥物衝突");
    await userEvent.type(customBox(), "怕吃了跟藥物衝突");
    await userEvent.click(screen.getByRole("button", { name: "讓 AI 整理" }));

    await waitFor(() => expect(input(1, "顧客會怎麼說").value).toBe("「怕吃了跟藥物衝突」"));
    expect(mockCustom).toHaveBeenCalledWith(B, P, "pain", "怕吃了跟藥物衝突");
    expect(pressed(1)).toEqual(["太麻煩", "怕買錯"]);
    expect(within(group(1)).getByText("你自訂")).toBeTruthy();
    expect(screen.getAllByText("你自訂")).toHaveLength(1);
    await userEvent.type(input(1, "顧客會怎麼說"), "！");
    expect(screen.queryByText("你自訂")).toBeNull();
  });

  it("沒有任何顧客群：只有自訂與說明，可以直接下一步", async () => {
    mockSave.mockResolvedValue({ groups: [], pain_options: PAIN_OPTIONS });
    const { onNext } = renderWho({ groups: [], pain_options: PAIN_OPTIONS });

    expect(await screen.findByText("最多 3 群；AI 會把你的描述整理成一群、並對上煩惱類型")).toBeTruthy();
    expect(customButtons()).toHaveLength(1);
    await userEvent.click(nextButton());
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(mockSave).toHaveBeenCalledWith(B, P, []);
  });

  it("讀取失敗顯示原因，留返回", async () => {
    mockFetch.mockRejectedValue(new Error("找不到這個商品。"));
    render(
      <MemoryRouter>
        <WhoStep brandId={B} productId={P} nav={nav} back={{ label: "商品是什麼", onClick: vi.fn() }} onNext={vi.fn()} />
      </MemoryRouter>,
    );

    expect((await screen.findByRole("alert")).textContent).toBe("找不到這個商品。");
    expect(screen.getByRole("button", { name: "← 商品是什麼" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "下一步 →" })).toBeNull();
  });

  it("F47-I03 (faults F7): an AI-organised group and an edit come back after a reload, as they were, until saved", async () => {
    mockCustom.mockResolvedValue({
      block: "group",
      kind: "option",
      option: { who: "上班族與通勤族", pain_keys: ["effort"], quote: "「早上來不及吃早餐」", when_used: "通勤路上" },
    });
    mockSave.mockResolvedValue(prefilled());
    renderWho(prefilled());
    await screen.findByRole("group", { name: "第 2 群" });
    await userEvent.click(customButtons().at(-1)!);
    await userEvent.type(customBox(), "上班族與通勤族");
    await userEvent.click(screen.getByRole("button", { name: "讓 AI 整理" }));
    await screen.findByRole("group", { name: "第 3 群" });
    await userEvent.clear(input(3, "什麼時候用"));
    await userEvent.type(input(3, "什麼時候用"), "捷運上");
    cleanup();

    const { onNext } = renderWho(prefilled());
    expect(await screen.findByRole("group", { name: "第 3 群" })).toBeTruthy();
    expect(input(3, "是誰").value).toBe("上班族與通勤族");
    expect(input(3, "什麼時候用").value).toBe("捷運上");
    expect(input(1, "是誰").value).toBe("上班族、常加班的 25–40 歲");
    expect(screen.getAllByText("✦ 從評論與商品頁推測")).toHaveLength(2);

    await userEvent.click(nextButton());
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(mockSave.mock.calls[0][2][2]).toMatchObject({ who: "上班族與通勤族", when_used: "捷運上", source: "user" });
    expect(sessionStorage.length).toBe(0);
  });
});
