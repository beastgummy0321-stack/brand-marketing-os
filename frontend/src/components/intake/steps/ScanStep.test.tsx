/** frontend/src/components/intake/steps/ScanStep.test.tsx — brand onboarding `#/b2` AI 讀網站 (F42-I07): the found
 * rows (area · text · 「✦ 讀到」 with the note) and one row per area not found; a scan that never ran is started once
 * and read until it is done; a failed scan shows the backend's message with 重試 and 「先跳過，自己填」, and the head
 * and bar stay; 「開始確認」 moves on. No server: the API calls are fakes (importActual + override). */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/lib/intakeOnboardingApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeOnboardingApi")>("@/lib/intakeOnboardingApi");
  return { ...actual, fetchOnboardingScan: vi.fn(), startOnboardingScan: vi.fn() };
});

import { fetchOnboardingScan, startOnboardingScan, type OnboardingScan } from "@/lib/intakeOnboardingApi";
import { BRAND_STEPS, brandCrumb, type StepNav } from "../OnboardingStepHead";
import { ScanStep } from "./ScanStep";

const mockFetch = vi.mocked(fetchOnboardingScan);
const mockStart = vi.mocked(startOnboardingScan);
const nav: StepNav = { crumb: brandCrumb("Beast Gummy"), steps: BRAND_STEPS, current: 2 };

/** The shape F42-I05 returns for the scripted prefill reply. */
const DONE: OnboardingScan = {
  status: "done",
  error: null,
  found: [
    { area: "品牌是誰", text: "「給忙到沒空吃飯的人的維他命軟糖」・語氣親切、直接・畫面明亮、自然光", note: "頁面 1" },
    { area: "品牌證據", text: "創辦人故事：創辦人自己吞不下藥丸才做了軟糖", note: "about 頁" },
    { area: "政策", text: "滿 NT$999 免運", note: "頁面 1" },
    { area: "可能的商品", text: "綜合維他命軟糖", note: "" },
  ],
  not_found: ["媒體報導", "銷售數據"],
  prefilled: 5,
  pages_read: 1,
  photos_read: 1,
};
const scan = (overrides: Partial<OnboardingScan>): OnboardingScan => ({
  ...DONE, found: [], not_found: [], prefilled: 0, pages_read: 0, photos_read: 0, ...overrides,
});

function renderStep({ withNav = true } = {}) {
  const onNext = vi.fn();
  const back = { label: "基本", onClick: vi.fn() };
  render(
    <MemoryRouter>
      <ScanStep brandId="brd_1" nav={withNav ? nav : undefined} back={back} onNext={onNext} />
    </MemoryRouter>,
  );
  return { onNext, back };
}

const row = (area: string) => screen.getByText(area, { selector: "li > span" }).closest("li") as HTMLElement;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ScanStep", () => {
  it("shows the found rows with their notes and one row per area not found", async () => {
    mockFetch.mockResolvedValue(DONE);
    renderStep();

    expect(await screen.findByRole("heading", { level: 1, name: "我讀完你的網站了" })).toBeTruthy();
    expect(screen.getByText("讀了 1 頁網站、1 張品牌照片；下面是我找到的，後面每一步會先幫你填好，你確認就好")).toBeTruthy();
    expect(screen.getByText("預填 5 項")).toBeTruthy();
    expect(within(row("品牌證據")).getByText("創辦人故事：創辦人自己吞不下藥丸才做了軟糖")).toBeTruthy();
    expect(within(row("品牌證據")).getByText("✦ 讀到（about 頁）")).toBeTruthy();
    expect(within(row("政策")).getByText("✦ 讀到（頁面 1）")).toBeTruthy();
    expect(within(row("可能的商品")).getByText("✦ 讀到")).toBeTruthy();
    for (const area of ["媒體報導", "銷售數據"]) {
      expect(within(row(area)).getByText("沒找到，後面問你；沒有也沒關係")).toBeTruthy();
      expect(within(row(area)).getByText("網站上沒找到")).toBeTruthy();
    }
    expect(screen.getAllByRole("listitem").filter((li) => li.closest("[data-slot=scan-rows]"))).toHaveLength(6);
    expect(mockStart).not.toHaveBeenCalled();
  });

  it("leaves a zero count out of the purpose line", async () => {
    mockFetch.mockResolvedValue({ ...DONE, pages_read: 3, photos_read: 0 });
    renderStep();
    expect(await screen.findByText("讀了 3 頁網站；下面是我找到的，後面每一步會先幫你填好，你確認就好")).toBeTruthy();
  });

  it("開始確認 moves to the next step; ← 基本 goes back", async () => {
    mockFetch.mockResolvedValue(DONE);
    const { onNext, back } = renderStep();
    await screen.findByText("預填 5 項");
    await userEvent.click(screen.getByRole("button", { name: "開始確認 →" }));
    expect(onNext).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "← 基本" }));
    expect(back.onClick).toHaveBeenCalledTimes(1);
  });

  it("starts a scan that never ran, shows the spinner, then the rows once it is done", async () => {
    mockFetch
      .mockResolvedValueOnce(scan({ status: "none" }))
      .mockResolvedValueOnce(scan({ status: "running" }))
      .mockResolvedValue(DONE);
    mockStart.mockResolvedValue(scan({ status: "running" }));
    renderStep();

    expect((await screen.findByRole("status")).textContent).toBe("正在讀網站…");
    expect(screen.getByRole("heading", { level: 1, name: "AI 讀網站" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "開始確認 →" }) as HTMLButtonElement).disabled).toBe(true);
    expect(mockStart).toHaveBeenCalledTimes(1);
    expect(mockStart).toHaveBeenCalledWith("brd_1");

    expect(await screen.findByText("預填 5 項", {}, { timeout: 4000 })).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "我讀完你的網站了" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "開始確認 →" }) as HTMLButtonElement).disabled).toBe(false);
    expect(mockStart).toHaveBeenCalledTimes(1);
  });

  it("does not start a scan that is already running", async () => {
    mockFetch.mockResolvedValueOnce(scan({ status: "running" })).mockResolvedValue(DONE);
    renderStep();
    expect(await screen.findByText("預填 5 項", {}, { timeout: 4000 })).toBeTruthy();
    expect(mockStart).not.toHaveBeenCalled();
  });

  it("a failed scan shows the backend message, 重試 starts it again, the head and bar stay", async () => {
    mockFetch.mockResolvedValueOnce(scan({ status: "failed", error: "網站讀不到（逾時）" })).mockResolvedValue(DONE);
    mockStart.mockResolvedValue(scan({ status: "running" }));
    const { back } = renderStep();

    expect((await screen.findByRole("alert")).textContent).toBe("網站讀不到（逾時）");
    expect(screen.getByRole("heading", { level: 1, name: "AI 讀網站" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "建檔位置" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "← 基本" })).toBeTruthy();
    expect(mockStart).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "← 基本" }));
    expect(back.onClick).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(mockStart).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("預填 5 項", {}, { timeout: 4000 })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("先跳過，自己填 goes to step 3 when the scan cannot start", async () => {
    mockFetch.mockResolvedValue(scan({ status: "none" }));
    mockStart.mockRejectedValue(new Error("這次建檔的 AI 用量已到上限（US$ 1.00／US$ 1.00），AI 先不讀網站；可以直接往下自己填。"));
    const { onNext } = renderStep();

    expect((await screen.findByRole("alert")).textContent).toContain("AI 用量已到上限");
    expect(screen.queryByRole("button", { name: "開始確認 →" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "先跳過，自己填 →" }));
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("a failed status read keeps the step and offers 重試", async () => {
    mockFetch.mockRejectedValueOnce(new Error("處理失敗（狀態碼 500）")).mockResolvedValue(DONE);
    mockStart.mockResolvedValue(DONE);
    renderStep();

    expect((await screen.findByRole("alert")).textContent).toBe("處理失敗（狀態碼 500）");
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText("預填 5 項")).toBeTruthy();
  });

  it("without nav (the wizard draws the dots) still shows the title, purpose and bar", async () => {
    mockFetch.mockResolvedValue(DONE);
    renderStep({ withNav: false });
    expect(await screen.findByRole("heading", { level: 1, name: "我讀完你的網站了" })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "建檔位置" })).toBeNull();
    await waitFor(() => expect(screen.getByRole("button", { name: "開始確認 →" })).toBeTruthy());
  });
});
