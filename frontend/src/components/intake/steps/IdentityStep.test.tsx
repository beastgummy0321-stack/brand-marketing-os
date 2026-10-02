/** frontend/src/components/intake/steps/IdentityStep.test.tsx — brand onboarding `#/b3` 品牌是誰 (F42-I08):
 * AI-prefilled fields carry the scan's tag, confirmed ones do not; at most two tones (the oldest drops);
 * a 自訂 tone is appended and picked; 下一步 sends `PUT …/onboarding/identity` and moves on only after the
 * server confirmed. No server: the API calls are fakes. */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/intakeOnboardingApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeOnboardingApi")>("@/lib/intakeOnboardingApi");
  return { ...actual, fetchOnboardingIdentity: vi.fn(), saveOnboardingIdentity: vi.fn(), proposeCustom: vi.fn() };
});
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "usr_1:org_1" }) }));
vi.mock("@/lib/useAuthedImage", () => ({
  useAuthedImage: (url: string | undefined) => ({ src: url ? `blob:${url}` : null, failed: !url }),
}));

import type { OnboardingIdentity } from "@/lib/intakeOnboardingApi";
import { fetchOnboardingIdentity, proposeCustom, saveOnboardingIdentity } from "@/lib/intakeOnboardingApi";
import { BRAND_STEPS, brandCrumb, type StepNav } from "../OnboardingStepHead";
import { IdentityStep } from "./IdentityStep";

const mockFetch = vi.mocked(fetchOnboardingIdentity);
const mockSave = vi.mocked(saveOnboardingIdentity);
const mockPropose = vi.mocked(proposeCustom);

const NAV: StepNav = { crumb: brandCrumb("山嵐手作果醬"), steps: BRAND_STEPS, current: 3 };
const TONES = ["親切", "專業", "直接", "幽默", "溫柔", "熱血"];

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.clearAllMocks();
});

function prefilled(): OnboardingIdentity {
  return {
    positioning: { value: "給忙到沒空好好吃飯的人：一顆軟糖，把今天的維他命補齊", source: "ai", note: "about 頁" },
    tone: { values: ["親切", "直接"], options: TONES, source: "ai", note: "從網站文字判斷" },
    visual: {
      value: "明亮、自然光、桌面小物、暖色系",
      source: "ai",
      note: "從品牌照片看出",
      photo_urls: ["/brands/brd_1/assets/file/oa_logo/logo.png", "/brands/brd_1/assets/file/oa_store/store.jpg"],
    },
  };
}

function saved(): OnboardingIdentity {
  return {
    positioning: { value: "手工小批果醬", source: "saved", note: "" },
    tone: { values: ["溫柔"], options: TONES, source: "saved", note: "" },
    visual: { value: "木桌、自然光", source: "saved", note: "", photo_urls: [] },
  };
}

function renderStep(onNext = vi.fn()) {
  render(
    <MemoryRouter initialEntries={["/brands/brd_1/intake"]}>
      <Routes>
        <Route path="/brands/:brandId/intake" element={<IdentityStep nav={NAV} back={{ label: "AI 讀網站", onClick: vi.fn() }} onNext={onNext} />} />
      </Routes>
    </MemoryRouter>,
  );
  return onNext;
}

const toneButton = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;
const picked = () => TONES.filter((t) => toneButton(t).getAttribute("aria-pressed") === "true");
const nextButton = () => screen.getByRole("button", { name: "下一步 →" }) as HTMLButtonElement;
const positioningBox = () => screen.getByLabelText("一句話說你的品牌") as HTMLTextAreaElement;

describe("IdentityStep", () => {
  it("AI 預填的欄位帶著掃描的標籤，照片縮圖與畫面風格一起出現", async () => {
    mockFetch.mockResolvedValue(prefilled());
    renderStep();

    expect((await screen.findByLabelText("一句話說你的品牌") as HTMLTextAreaElement).value).toBe("給忙到沒空好好吃飯的人：一顆軟糖，把今天的維他命補齊");
    expect(mockFetch).toHaveBeenCalledWith("brd_1");
    expect(screen.getByText("✦ about 頁")).toBeTruthy();
    expect(screen.getByText("✦ 從網站文字判斷")).toBeTruthy();
    expect(screen.getByText("✦ 從品牌照片看出")).toBeTruthy();
    expect(screen.getByText("明亮、自然光、桌面小物、暖色系")).toBeTruthy();
    expect(picked()).toEqual(["親切", "直接"]);
    expect(document.querySelectorAll("img").length).toBe(2);
    expect(screen.getAllByRole("button", { name: "✎ 自訂：用自己的話說" }).length).toBe(3);
  });

  it("沒有 note 的預填寫「AI 從網站讀到」，網站上沒找到的標「網站上沒找到」", async () => {
    mockFetch.mockResolvedValue({
      ...prefilled(),
      positioning: { value: "一句話", source: "ai", note: "" },
      visual: { value: "", source: "none", note: "", photo_urls: [] },
    });
    renderStep();

    expect(await screen.findByText("✦ AI 從網站讀到")).toBeTruthy();
    expect(screen.getByText("網站上沒找到")).toBeTruthy();
  });

  it("已確認過的值不帶標籤", async () => {
    mockFetch.mockResolvedValue(saved());
    renderStep();

    expect((await screen.findByLabelText("一句話說你的品牌") as HTMLTextAreaElement).value).toBe("手工小批果醬");
    expect(document.querySelector('[data-slot="ai-tag"]')).toBeNull();
    expect(picked()).toEqual(["溫柔"]);
    expect(screen.getByText("木桌、自然光")).toBeTruthy();
  });

  it("改過的欄位就不再掛 AI 標籤", async () => {
    mockFetch.mockResolvedValue(prefilled());
    renderStep();
    await userEvent.type(await screen.findByLabelText("一句話說你的品牌"), "！");

    expect(screen.queryByText("✦ about 頁")).toBeNull();
    expect(screen.getByText("✦ 從網站文字判斷")).toBeTruthy();
  });

  it("口氣最多兩個：挑第三個時最早的那個被拿掉；再按一次取消", async () => {
    mockFetch.mockResolvedValue(prefilled());
    renderStep();
    await screen.findByLabelText("一句話說你的品牌");

    await userEvent.click(toneButton("幽默"));
    expect(picked()).toEqual(["直接", "幽默"]);
    await userEvent.click(toneButton("直接"));
    expect(picked()).toEqual(["幽默"]);
  });

  it("自訂口氣：加進口氣選項並選上、標「你自訂」（只出現這一處），超過兩個拿掉最早的；它的 × 拿掉", async () => {
    mockFetch.mockResolvedValue(prefilled());
    mockPropose.mockResolvedValue({ block: "tone", kind: "option", option: { label: "教練朋友" } });
    renderStep();
    await screen.findByLabelText("一句話說你的品牌");

    const toneEscape = document.querySelector('[data-slot="custom-escape"][data-block="tone"]') as HTMLElement;
    await userEvent.click(toneEscape.querySelector("button") as HTMLButtonElement);
    await userEvent.type(screen.getByRole("textbox", { name: /覺得上面列的不對/ }), "像健身房的教練朋友，講話直");
    await userEvent.click(screen.getByRole("button", { name: "讓 AI 整理" }));

    expect(mockPropose).toHaveBeenCalledWith("brd_1", "tone", "像健身房的教練朋友，講話直");
    expect(toneButton("教練朋友").getAttribute("aria-pressed")).toBe("true");
    expect(toneButton("親切").getAttribute("aria-pressed")).toBe("false");
    const group = screen.getByRole("group", { name: "說話的口氣" });
    expect(screen.getAllByText("你自訂").length).toBe(1);
    expect(group.textContent).toContain("你自訂");
    expect(screen.queryByText("✦ 從網站文字判斷")).toBeNull();
    expect(mockSave).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "拿掉「教練朋友」" }));
    expect(screen.queryByText("你自訂")).toBeNull();
    expect(screen.queryByRole("button", { name: "教練朋友" })).toBeNull();
    expect(picked()).toEqual(["直接"]);
  });

  it("自訂品牌一句話：取代欄位內容，欄位的標籤改成「你自訂」（只出現這一處），按下一步才存", async () => {
    mockFetch.mockResolvedValue(prefilled());
    mockPropose.mockResolvedValue({ block: "positioning", kind: "value", value: "給懶人的營養零食" });
    mockSave.mockResolvedValue(prefilled());
    const onNext = renderStep();
    await screen.findByLabelText("一句話說你的品牌");

    const escape = document.querySelector('[data-slot="custom-escape"][data-block="positioning"]') as HTMLElement;
    await userEvent.click(escape.querySelector("button") as HTMLButtonElement);
    await userEvent.type(screen.getByRole("textbox", { name: /覺得上面列的不對/ }), "我們不是保健品，是給懶人的營養零食");
    await userEvent.click(screen.getByRole("button", { name: "讓 AI 整理" }));

    expect(positioningBox().value).toBe("給懶人的營養零食");
    expect(screen.queryByText("✦ about 頁")).toBeNull();
    expect(screen.getAllByText("你自訂").length).toBe(1);
    expect(screen.queryByRole("button", { name: "拿掉「給懶人的營養零食」" })).toBeNull();
    expect(mockSave).not.toHaveBeenCalled();
    await userEvent.click(nextButton());

    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
    expect(mockSave).toHaveBeenCalledWith("brd_1", {
      positioning: "給懶人的營養零食",
      tone: ["親切", "直接"],
      visual: "明亮、自然光、桌面小物、暖色系",
    });
  });

  it("自訂畫面風格：換掉文字，AI 標籤換成「你自訂」；再手改品牌一句話時那個欄位不掛「你自訂」", async () => {
    mockFetch.mockResolvedValue(prefilled());
    mockPropose.mockResolvedValue({ block: "visual", kind: "value", value: "黑底、霓虹感" });
    renderStep();
    await screen.findByLabelText("一句話說你的品牌");

    const escape = document.querySelector('[data-slot="custom-escape"][data-block="visual"]') as HTMLElement;
    await userEvent.click(escape.querySelector("button") as HTMLButtonElement);
    await userEvent.type(screen.getByRole("textbox", { name: /覺得上面列的不對/ }), "黑底、霓虹感、不要粉嫩");
    await userEvent.click(screen.getByRole("button", { name: "讓 AI 整理" }));

    expect(await screen.findByText("黑底、霓虹感")).toBeTruthy();
    expect(screen.queryByText("✦ 從品牌照片看出")).toBeNull();
    expect(screen.getAllByText("你自訂").length).toBe(1);
    await userEvent.type(positioningBox(), "！");
    expect(screen.getAllByText("你自訂").length).toBe(1);
  });

  it("下一步：送出三個欄位，伺服器確認後才往下", async () => {
    mockFetch.mockResolvedValue(prefilled());
    mockSave.mockResolvedValue(prefilled());
    const onNext = renderStep();
    await screen.findByLabelText("一句話說你的品牌");
    await userEvent.click(toneButton("親切"));
    await userEvent.click(nextButton());

    await waitFor(() => expect(onNext).toHaveBeenCalledTimes(1));
    expect(mockSave).toHaveBeenCalledWith("brd_1", {
      positioning: "給忙到沒空好好吃飯的人：一顆軟糖，把今天的維他命補齊",
      tone: ["直接"],
      visual: "明亮、自然光、桌面小物、暖色系",
    });
  });

  it("存檔失敗：留在這一步並顯示伺服器的話", async () => {
    mockFetch.mockResolvedValue(prefilled());
    mockSave.mockRejectedValue(new Error("說話的口氣請挑 1～2 個。"));
    const onNext = renderStep();
    await screen.findByLabelText("一句話說你的品牌");
    await userEvent.click(toneButton("親切"));
    await userEvent.click(toneButton("直接"));
    await userEvent.click(nextButton());

    expect((await screen.findByRole("alert")).textContent).toBe("說話的口氣請挑 1～2 個。");
    expect(onNext).not.toHaveBeenCalled();
    expect(mockSave).toHaveBeenCalledWith("brd_1", expect.objectContaining({ tone: [] }));
    expect(positioningBox()).toBeTruthy();
  });

  it("讀取失敗：顯示錯誤，沒有下一步，還能回上一步", async () => {
    mockFetch.mockRejectedValue(new Error("找不到這筆資料。"));
    renderStep();

    expect((await screen.findByRole("alert")).textContent).toBe("找不到這筆資料。");
    expect(screen.queryByRole("button", { name: "下一步 →" })).toBeNull();
    expect(screen.getByRole("button", { name: "← AI 讀網站" })).toBeTruthy();
  });

  it("F47-I03: unsaved edits come back when the step mounts again (back, step bar, reload) and go once saved", async () => {
    mockFetch.mockResolvedValue(prefilled());
    mockSave.mockResolvedValue(undefined);
    renderStep();
    await userEvent.clear(await screen.findByLabelText("一句話說你的品牌"));
    await userEvent.type(positioningBox(), "我改過的一句話");
    await userEvent.click(toneButton("熱血"));
    cleanup();

    const onNext = renderStep();
    await waitFor(() => expect(positioningBox().value).toBe("我改過的一句話"));
    expect(picked()).toEqual(["直接", "熱血"]);
    await userEvent.click(nextButton());
    await waitFor(() => expect(onNext).toHaveBeenCalled());
    expect(mockSave).toHaveBeenCalledWith("brd_1", expect.objectContaining({ positioning: "我改過的一句話", tone: ["直接", "熱血"] }));
    expect(sessionStorage.length).toBe(0);
    cleanup();

    renderStep();
    await waitFor(() => expect(positioningBox().value).toBe("給忙到沒空好好吃飯的人：一顆軟糖，把今天的維他命補齊"));
  });
});
