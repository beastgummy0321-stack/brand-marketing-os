/** frontend/src/components/intake/steps/StartStep.test.tsx — brand onboarding `#/b1` 基本 (F42-I06):
 * name + advertising history are required, the bar's button says 「讓系統讀網站」 only when a website or
 * photo was given, each photo is sent with its slot's kind, and an existing brand edits through
 * `PUT …/onboarding/basics`. F31-I01: the unsent text survives leaving the step, per user and brand,
 * and is gone after a successful save. No server: the API calls are fakes. */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const workspace = { scope: "usr_1:org_1", refreshBrands: vi.fn() };

vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => workspace,
}));
vi.mock("@/lib/intakeApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeApi")>("@/lib/intakeApi");
  return { ...actual, submitIntakeStart: vi.fn(), uploadIntakePhoto: vi.fn() };
});
vi.mock("@/lib/intakeOnboardingApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeOnboardingApi")>("@/lib/intakeOnboardingApi");
  return { ...actual, fetchOnboardingBasics: vi.fn(), saveOnboardingBasics: vi.fn() };
});
vi.mock("@/lib/libraryApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/libraryApi")>("@/lib/libraryApi");
  return { ...actual, setAdvertisingHistory: vi.fn() };
});
vi.mock("@/lib/useAuthedImage", () => ({
  useAuthedImage: (url: string | undefined) => ({ src: url ? `blob:${url}` : null, failed: !url }),
}));

import { submitIntakeStart, uploadIntakePhoto } from "@/lib/intakeApi";
import type { OnboardingBasics } from "@/lib/intakeOnboardingApi";
import { fetchOnboardingBasics, saveOnboardingBasics } from "@/lib/intakeOnboardingApi";
import { setAdvertisingHistory } from "@/lib/libraryApi";
import { BRAND_STEPS, brandCrumb, type StepNav } from "../OnboardingStepHead";
import { StartStep } from "./StartStep";

const mockSubmitIntakeStart = vi.mocked(submitIntakeStart);
const mockUpload = vi.mocked(uploadIntakePhoto);
const mockFetchBasics = vi.mocked(fetchOnboardingBasics);
const mockSaveBasics = vi.mocked(saveOnboardingBasics);
const mockSetAdvertisingHistory = vi.mocked(setAdvertisingHistory);

const NAV: StepNav = { crumb: brandCrumb(""), steps: BRAND_STEPS, current: 1 };

beforeAll(() => {
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  workspace.scope = "usr_1:org_1";
  vi.clearAllMocks();
});

function renderNew(onSaved = vi.fn()) {
  return render(<StartStep brandId={null} nav={NAV} onSaved={onSaved} />);
}

const nameBox = () => screen.getByLabelText("品牌名稱") as HTMLInputElement;
const submitButton = () => screen.getByRole("button", { name: /讓系統讀網站|下一步/ });

function basics(overrides: Partial<OnboardingBasics> = {}): OnboardingBasics {
  return {
    name: "山嵐手作果醬 Mountain Mist Handmade Jam Co.",
    urls: ["https://mountainmist.example/"],
    photos: [{ id: "oa_logo", kind: "logo", url: "/brands/brd_1/assets/file/oa_logo/logo.png" }],
    market_region: "TW",
    regulatory_regime: "food_tw",
    advertising_history: "has_history",
    client_name: "",
    description: "",
    ...overrides,
  };
}

describe("StartStep", () => {
  it("品牌名稱和「投過網路廣告嗎」都選了才能往下", async () => {
    renderNew();
    expect((submitButton() as HTMLButtonElement).disabled).toBe(true);
    // F47-I03 (drill-10 甲 建檔 #9): the off button names what is missing.
    expect(screen.getByText("先填品牌名稱、選「投過網路廣告嗎」")).toBeTruthy();
    await userEvent.type(nameBox(), "虛構品牌");
    expect((submitButton() as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("先選「投過網路廣告嗎」")).toBeTruthy();
    await userEvent.click(screen.getByRole("radio", { name: "完全沒投過" }));
    expect((submitButton() as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText("先選「投過網路廣告嗎」")).toBeNull();
    expect(screen.getByRole("radio", { name: "完全沒投過" }).getAttribute("aria-checked")).toBe("true");
  });

  it("沒給網站和照片是「下一步」；給了網站換成「讓系統讀網站」並提示約 1 分鐘", async () => {
    renderNew();
    expect(screen.getByRole("button", { name: "下一步 →" })).toBeTruthy();
    expect(screen.queryByText("下一步系統讀網站，約 1 分鐘")).toBeNull();

    await userEvent.type(screen.getByLabelText("品牌網站 1"), "https://a.example");

    expect(screen.getByRole("button", { name: "讓系統讀網站 →" })).toBeTruthy();
    expect(screen.getByText("下一步系統讀網站，約 1 分鐘")).toBeTruthy();
  });

  it("「＋再加一個」最多到 5 個網址", async () => {
    renderNew();
    for (let i = 0; i < 4; i += 1) await userEvent.click(screen.getByRole("button", { name: "＋再加一個" }));
    expect(screen.getByLabelText("品牌網站 5")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "＋再加一個" })).toBeNull();
  });

  it("建立品牌時照片帶著所在格子的種類送出，法規與地區一起送、投放史另存", async () => {
    mockUpload.mockResolvedValue({ token: "tok_store", name: "store.jpg", size_mb: 0.4 });
    mockSubmitIntakeStart.mockResolvedValue({ brand_id: "brd_new", quick: false });
    mockSetAdvertisingHistory.mockResolvedValue("has_history");
    const onSaved = vi.fn();
    renderNew(onSaved);
    await userEvent.type(nameBox(), "虛構品牌");
    await userEvent.upload(screen.getByLabelText("上傳門市／工作室照片"), new File(["x"], "store.jpg", { type: "image/jpeg" }));
    expect(await screen.findByRole("button", { name: "讓系統讀網站 →" })).toBeTruthy();
    await userEvent.click(screen.getByLabelText(/台灣食品/));
    await userEvent.click(screen.getByRole("radio", { name: "投過" }));
    await userEvent.click(screen.getByRole("button", { name: "讓系統讀網站 →" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ brand_id: "brd_new" }));
    expect(mockSubmitIntakeStart).toHaveBeenCalledWith(expect.objectContaining({
      brand_name: "虛構品牌",
      photo_tokens: ["tok_store"],
      photo_kinds: ["store"],
      market_region: "TW",
      regulatory_regime: "food_tw",
    }));
    expect(mockSetAdvertisingHistory).toHaveBeenCalledWith("brd_new", "has_history");
  });

  it("投放史存失敗後再按一次，不會再建第二個品牌", async () => {
    mockSubmitIntakeStart.mockResolvedValue({ brand_id: "brd_new", quick: false });
    mockSetAdvertisingHistory.mockRejectedValueOnce(new Error("網路斷了")).mockResolvedValueOnce("none");
    const onSaved = vi.fn();
    renderNew(onSaved);
    await userEvent.type(nameBox(), "虛構品牌");
    await userEvent.click(screen.getByRole("radio", { name: "完全沒投過" }));
    await userEvent.click(screen.getByRole("button", { name: "下一步 →" }));
    expect(await screen.findByText("網路斷了")).toBeTruthy();
    expect(onSaved).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "下一步 →" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ brand_id: "brd_new" }));
    expect(mockSubmitIntakeStart).toHaveBeenCalledTimes(1);
  });

  it("已有的品牌讀回基本資料，改完用 PUT basics 存；換掉的照片不再保留", async () => {
    mockFetchBasics.mockResolvedValue(basics());
    mockSaveBasics.mockResolvedValue(basics());
    mockUpload.mockResolvedValue({ token: "tok_logo2", name: "logo2.png", size_mb: 0.1 });
    const onSaved = vi.fn();
    render(<StartStep brandId="brd_1" nav={NAV} onSaved={onSaved} />);

    await waitFor(() => expect(nameBox().value).toBe("山嵐手作果醬 Mountain Mist Handmade Jam Co."));
    expect(screen.getByRole("radio", { name: "投過" }).getAttribute("aria-checked")).toBe("true");
    expect((screen.getByLabelText(/台灣食品/) as HTMLInputElement).checked).toBe(true);
    await userEvent.upload(screen.getByLabelText("上傳LOGO照片"), new File(["x"], "logo2.png", { type: "image/png" }));
    await waitFor(() => expect(mockUpload).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: "讓系統讀網站 →" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ brand_id: "brd_1" }));
    expect(mockSaveBasics).toHaveBeenCalledWith("brd_1", expect.objectContaining({
      name: "山嵐手作果醬 Mountain Mist Handmade Jam Co.",
      urls: ["https://mountainmist.example/"],
      advertising_history: "has_history",
      regulatory_regime: "food_tw",
      photo_ids: [],
      photo_tokens: ["tok_logo2"],
      photo_kinds: ["logo"],
    }));
    expect(mockSubmitIntakeStart).not.toHaveBeenCalled();
  });

  it("離開再回來，沒送出的文字還在", async () => {
    const first = renderNew();
    await userEvent.type(nameBox(), "虛構品牌");
    await userEvent.type(screen.getByLabelText("品牌網站 1"), "https://a.example");
    await userEvent.click(screen.getByText("進階：所屬客戶、品牌描述"));
    await userEvent.type(screen.getByLabelText("所屬客戶"), "某客戶");
    await userEvent.type(screen.getByLabelText("品牌描述"), "一句描述");
    await userEvent.click(screen.getByRole("radio", { name: "完全沒投過" }));
    first.unmount();

    renderNew();

    expect(nameBox().value).toBe("虛構品牌");
    expect((screen.getByLabelText("所屬客戶") as HTMLInputElement).value).toBe("某客戶");
    expect((screen.getByLabelText("品牌描述") as HTMLInputElement).value).toBe("一句描述");
    expect(screen.getByDisplayValue("https://a.example")).toBeTruthy();
    expect(screen.getByRole("radio", { name: "完全沒投過" }).getAttribute("aria-checked")).toBe("true");
  });

  it("別的使用者看不到這份留著的文字", async () => {
    const first = renderNew();
    await userEvent.type(nameBox(), "虛構品牌");
    first.unmount();

    workspace.scope = "usr_2:org_1";
    renderNew();

    expect(nameBox().value).toBe("");
  });

  it("送出成功後就清掉，下次回來是空的", async () => {
    mockSubmitIntakeStart.mockResolvedValue({ brand_id: "brd_new", quick: false });
    mockSetAdvertisingHistory.mockResolvedValue("none");
    const onSaved = vi.fn();
    const first = renderNew(onSaved);
    await userEvent.type(nameBox(), "虛構品牌");
    await userEvent.click(screen.getByRole("radio", { name: "完全沒投過" }));
    await userEvent.click(screen.getByRole("button", { name: "下一步 →" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    first.unmount();

    renderNew();

    expect(nameBox().value).toBe("");
  });

  it("沒勾「台灣食品」就不送適用法規", async () => {
    mockSubmitIntakeStart.mockResolvedValue({ brand_id: "brd_new", quick: false });
    mockSetAdvertisingHistory.mockResolvedValue("none");
    const onSaved = vi.fn();
    renderNew(onSaved);
    await userEvent.type(nameBox(), "虛構品牌");
    await userEvent.click(screen.getByRole("radio", { name: "完全沒投過" }));
    await userEvent.click(screen.getByRole("button", { name: "下一步 →" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(mockSubmitIntakeStart).toHaveBeenCalledWith(expect.objectContaining({ regulatory_regime: "", photo_tokens: [], photo_kinds: [] }));
  });
});
