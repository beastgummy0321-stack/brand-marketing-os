/** frontend/src/components/intake/shared/CustomEscape.test.tsx — 「自訂」 under an AI-judged onboarding block
 * (F42-I08, F42-I09): a `value` proposal goes to `onValue`, an `option` proposal to `onOption`; the box lists
 * nothing of its own (the caller shows the result where it lives, marked `CustomMark`); the server's 422
 * message stays in the box; 取消 keeps nothing; a caller's `propose` (product onboarding, F43-I08) replaces the brand call.
 * No server: `proposeCustom` is a fake. */
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeOnboardingApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeOnboardingApi")>("@/lib/intakeOnboardingApi");
  return { ...actual, proposeCustom: vi.fn() };
});

import { proposeCustom } from "@/lib/intakeOnboardingApi";
import { CustomEscape, CustomMark } from "./CustomEscape";

const mockPropose = vi.mocked(proposeCustom);

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const openButton = () => screen.getByRole("button", { name: "✎ 自訂：用自己的話說" });
const box = () => screen.getByRole("textbox");
const organise = () => screen.getByRole("button", { name: "讓 AI 整理" });

describe("CustomEscape", () => {
  it("value：整理好的文字交給 onValue，框關上，自己不再列一份", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mockPropose.mockResolvedValue({ block: "positioning", kind: "value", value: "給懶人的營養零食" });
    render(<CustomEscape brandId="brd_1" block="positioning" placeholder="例如：我們不是保健品" onValue={onValue} />);

    await user.click(openButton());
    expect(box().getAttribute("placeholder")).toBe("例如：我們不是保健品");
    expect(screen.getByText("覺得上面列的不對、不像你、或選項太少？直接用一句話描述，AI 幫你整理成選項")).toBeTruthy();
    expect((organise() as HTMLButtonElement).disabled).toBe(true);
    // F47-I03 (drill-10 乙 #5): the off button says what is missing, until the box has text.
    expect(screen.getByText("先在上面寫一句話，AI 才有東西整理")).toBeTruthy();
    await user.type(box(), "我們不是保健品，是給懶人的營養零食");
    expect(screen.queryByText("先在上面寫一句話，AI 才有東西整理")).toBeNull();
    await user.click(organise());

    expect(mockPropose).toHaveBeenCalledWith("brd_1", "positioning", "我們不是保健品，是給懶人的營養零食");
    expect(onValue).toHaveBeenCalledWith("給懶人的營養零食");
    expect(screen.queryByText("你自訂")).toBeNull();
    expect(screen.queryByText("給懶人的營養零食")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(openButton()).toBeTruthy();
  });

  it("option：整理好的選項交給 onOption（不交給 onValue），自己不再列一份", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    const onOption = vi.fn();
    mockPropose.mockResolvedValue({ block: "tone", kind: "option", option: { label: "教練朋友" } });
    render(<CustomEscape brandId="brd_1" block="tone" placeholder="例如" onValue={onValue} onOption={onOption} />);

    await user.click(openButton());
    await user.type(box(), "像健身房的教練朋友");
    await user.click(organise());

    expect(onOption).toHaveBeenCalledWith({ label: "教練朋友" });
    expect(onValue).not.toHaveBeenCalled();
    expect(screen.queryByText("教練朋友")).toBeNull();
  });

  it("政策的選項整包交給 onOption", async () => {
    const user = userEvent.setup();
    mockPropose.mockResolvedValue({
      block: "policy",
      kind: "option",
      option: {
        key: "custom",
        label: "老客第四個月送隨身包",
        offer_key: "bundle",
        offer_label: "加贈",
        sentence: "連續訂滿三個月，第四個月送隨身包",
        params: { label: "老客第四個月送隨身包", offer_key: "bundle" },
      },
    });
    const onOption = vi.fn();
    render(<CustomEscape brandId="brd_1" block="policy" placeholder="例如" onOption={onOption} />);

    await user.click(openButton());
    await user.type(box(), "買滿三個月的顧客，第四個月送一包隨身包");
    await user.click(organise());

    expect(onOption).toHaveBeenCalledWith(expect.objectContaining({ key: "custom", offer_key: "bundle", sentence: "連續訂滿三個月，第四個月送隨身包" }));
    expect(screen.queryByText("連續訂滿三個月，第四個月送隨身包")).toBeNull();
  });

  it("CustomMark：預設寫「你自訂」，也可以換字", () => {
    render(<><CustomMark /><CustomMark>你選的</CustomMark></>);
    expect(screen.getByText("你自訂").getAttribute("data-slot")).toBe("custom-mark");
    expect(screen.getByText("你選的")).toBeTruthy();
  });

  it("422：伺服器的話留在框裡，框不關、文字還在、什麼都沒交出去", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    mockPropose.mockRejectedValue(new Error("AI 整理不出來，換個說法再試一次"));
    render(<CustomEscape brandId="brd_1" block="visual" placeholder="例如" onValue={onValue} />);

    await user.click(openButton());
    await user.type(box(), "隨便");
    await user.click(organise());

    expect(screen.getByRole("alert").textContent).toBe("AI 整理不出來，換個說法再試一次");
    expect((box() as HTMLTextAreaElement).value).toBe("隨便");
    expect(onValue).not.toHaveBeenCalled();
    expect(screen.queryByText("你自訂")).toBeNull();
  });

  it("取消：什麼都不留，再打開是空的", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    render(<CustomEscape brandId="brd_1" block="positioning" placeholder="例如" onValue={onValue} />);

    await user.click(openButton());
    await user.type(box(), "寫了一半");
    await user.click(screen.getByRole("button", { name: "取消" }));

    expect(screen.queryByRole("textbox")).toBeNull();
    expect(mockPropose).not.toHaveBeenCalled();
    expect(onValue).not.toHaveBeenCalled();
    expect(screen.queryByText("你自訂")).toBeNull();
    await user.click(openButton());
    expect((box() as HTMLTextAreaElement).value).toBe("");
  });

  it("整理中按取消：晚到的結果不算數", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    let answer!: (p: Awaited<ReturnType<typeof proposeCustom>>) => void;
    mockPropose.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    render(<CustomEscape brandId="brd_1" block="positioning" placeholder="例如" onValue={onValue} />);

    await user.click(openButton());
    await user.type(box(), "一句話");
    await user.click(organise());
    expect((organise() as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "取消" }));
    answer({ block: "positioning", kind: "value", value: "晚到" });
    await Promise.resolve();

    expect(onValue).not.toHaveBeenCalled();
    expect(screen.queryByText("你自訂")).toBeNull();
  });
  it("傳了 propose（商品建檔）：改走它、不打品牌那支，value 與 option 照樣分給 onValue／onOption", async () => {
    const user = userEvent.setup();
    const onValue = vi.fn();
    const onOption = vi.fn();
    const propose = vi.fn()
      .mockResolvedValueOnce({ block: "difference", kind: "value", value: "台灣自己的工廠，一批一批驗" })
      .mockResolvedValueOnce({
        block: "group",
        kind: "option",
        option: { who: "買給爸媽的子女", pain_keys: ["experience"], quote: "長輩吞不下藥丸", when_used: "早餐後" },
      });
    const { rerender } = render(<CustomEscape brandId="brd_1" block="difference" placeholder="例如" propose={propose} onValue={onValue} />);

    await user.click(openButton());
    await user.type(box(), "我們是台灣自己的工廠做的");
    await user.click(organise());
    expect(propose).toHaveBeenCalledWith("我們是台灣自己的工廠做的");
    expect(onValue).toHaveBeenCalledWith("台灣自己的工廠，一批一批驗");

    rerender(<CustomEscape brandId="brd_1" block="group" placeholder="例如" propose={propose} onOption={onOption} />);
    await user.click(openButton());
    await user.type(box(), "買給爸媽");
    await user.click(organise());
    expect(onOption).toHaveBeenCalledWith({ who: "買給爸媽的子女", pain_keys: ["experience"], quote: "長輩吞不下藥丸", when_used: "早餐後" });
    expect(mockPropose).not.toHaveBeenCalled();
  });
});
