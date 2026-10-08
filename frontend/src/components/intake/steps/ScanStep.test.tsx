/** frontend/src/components/intake/steps/ScanStep.test.tsx — brand onboarding `#/b2` AI 讀網站 (F42-I07): the found
 * rows (area · text · 「✦ 讀到」 with the note) and one row joining the areas not found; a scan that never ran is started once
 * and read until it is done; a failed scan shows the backend's message with 重試 and 「先跳過，自己填」, and the head
 * and bar stay; 「開始確認」 moves on. No server: the API calls are fakes (importActual + override). */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/lib/intakeOnboardingApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/intakeOnboardingApi")>("@/lib/intakeOnboardingApi");
  return { ...actual, fetchOnboardingScan: vi.fn(), startOnboardingScan: vi.fn() };
});

vi.mock("@/lib/jobsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/jobsApi")>("@/lib/jobsApi");
  return { ...actual, fetchActiveJobs: vi.fn() };
});

import { fetchOnboardingScan, startOnboardingScan, type OnboardingScan } from "@/lib/intakeOnboardingApi";
import { fetchActiveJobs, type ActiveJobsSnapshot } from "@/lib/jobsApi";
import { BRAND_STEPS, brandCrumb, type StepNav } from "../OnboardingStepHead";
import { ScanStep } from "./ScanStep";

const mockFetch = vi.mocked(fetchOnboardingScan);
const mockStart = vi.mocked(startOnboardingScan);
const mockJobs = vi.mocked(fetchActiveJobs);
/** `GET /api/jobs/active` with one queued scan of this org; `stalled` = the worker is stopped (F47 Contract C). */
const jobs = (stalled: boolean): ActiveJobsSnapshot => ({
  data: [], total: 1, other_count: 0, done_today: 0, failed_today: 0, generated_at: "2026-10-02T02:00:00Z",
  worker_alive: !stalled, stalled,
});

beforeEach(() => {
  mockJobs.mockResolvedValue(jobs(false));
});
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
  urls_read: ["https://beastprime.com.tw/about"],
  pages_failed: [],
};
const scan = (overrides: Partial<OnboardingScan>): OnboardingScan => ({
  ...DONE, found: [], not_found: [], prefilled: 0, pages_read: 0, photos_read: 0, urls_read: [], pages_failed: [], ...overrides,
});
const BROKEN = { url: "https://beastprime.com.tw/abuot", reason: "打不開這個網址" };

function renderStep() {
  const onNext = vi.fn();
  const back = { label: "基本", onClick: vi.fn() };
  render(
    <MemoryRouter>
      <ScanStep brandId="brd_1" nav={nav} back={back} onNext={onNext} />
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
  it("shows the found rows with their notes and one row joining the areas not found", async () => {
    mockFetch.mockResolvedValue(DONE);
    renderStep();

    expect(await screen.findByRole("heading", { level: 1, name: "我讀完你的網站了" })).toBeTruthy();
    expect(screen.getByText("讀了 1 頁網站、1 張品牌照片；下面是我找到的，後面每一步會先幫你填好，你確認就好")).toBeTruthy();
    expect(screen.getByText("預填 5 項")).toBeTruthy();
    expect(within(row("品牌證據")).getByText("創辦人故事：創辦人自己吞不下藥丸才做了軟糖")).toBeTruthy();
    expect(within(row("品牌證據")).getByText("✦ 讀到（about 頁）")).toBeTruthy();
    expect(within(row("政策")).getByText("✦ 讀到（頁面 1）")).toBeTruthy();
    expect(within(row("可能的商品")).getByText("✦ 讀到")).toBeTruthy();
    expect(within(row("媒體報導、銷售數據")).getByText("沒找到，後面問你；沒有也沒關係")).toBeTruthy();
    expect(within(row("媒體報導、銷售數據")).getByText("網站上沒找到")).toBeTruthy();
    expect(screen.getAllByRole("listitem").filter((li) => li.closest("[data-slot=scan-rows]"))).toHaveLength(5);
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

  it("a running scan with the worker stopped says so; 再檢查一次 with a live worker clears it and reads the scan again", async () => {
    mockFetch.mockResolvedValue(scan({ status: "running" }));
    mockJobs.mockResolvedValue(jobs(true));
    renderStep();

    const notice = await screen.findByText(/背景程式停了/);
    expect(notice.closest("[data-slot=worker-stopped]")?.textContent).toContain(
      "背景程式停了：這件工作還排著，已填的資料沒丟。重新啟動行銷系統後會自動接著做。",
    );
    expect((screen.getByRole("status")).textContent).toBe("正在讀網站…");

    mockJobs.mockResolvedValue(jobs(false));
    const reads = mockFetch.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "再檢查一次" }));
    await waitFor(() => expect(screen.queryByText(/背景程式停了/)).toBeNull());
    expect(mockFetch.mock.calls.length).toBeGreaterThan(reads);
  });

  it("unavailable worker health never labels a waiting scan as stopped", async () => {
    mockFetch.mockResolvedValue(scan({ status: "running" }));
    mockJobs.mockRejectedValue(new Error("unavailable"));
    renderStep();
    expect(await screen.findByText("背景程式狀態無法確認")).toBeTruthy();
    expect(screen.queryByText(/背景程式停了/)).toBeNull();
    expect(screen.getByRole("button", { name: "再檢查一次" })).toBeTruthy();
  });

  it("does not read the worker state once the scan is done", async () => {
    mockFetch.mockResolvedValue(DONE);
    renderStep();
    await screen.findByText("預填 5 項");
    expect(mockJobs).not.toHaveBeenCalled();
  });

  it("nothing read never says 讀完你的網站了: it lists the unread URL with its reason and both exits (drill-10 R1)", async () => {
    mockFetch.mockResolvedValue(scan({ status: "done", urls_read: [BROKEN.url], pages_failed: [BROKEN] }));
    const { onNext, back } = renderStep();

    expect(await screen.findByRole("heading", { level: 1, name: "網站沒有讀到" })).toBeTruthy();
    expect(screen.queryByText("我讀完你的網站了")).toBeNull();
    expect(screen.queryByText(/預填 \d+ 項/)).toBeNull();
    const box = screen.getByText(/個網址讀不到/).closest("[data-slot=unread-pages]") as HTMLElement;
    expect(within(box).getByText(BROKEN.url)).toBeTruthy();
    expect(within(box).getByText("打不開這個網址")).toBeTruthy();
    await userEvent.click(within(box).getByRole("button", { name: "改網址再讀一次" }));
    expect(back.onClick).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "開始確認 →" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "跳過，自己填 →" }));
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("some pages read: the found card plus the unread URLs", async () => {
    mockFetch.mockResolvedValue({ ...DONE, pages_failed: [BROKEN] });
    renderStep();
    expect(await screen.findByRole("heading", { level: 1, name: "我讀完你的網站了" })).toBeTruthy();
    expect(screen.getByText("預填 5 項")).toBeTruthy();
    expect(screen.getByText(BROKEN.url)).toBeTruthy();
    expect(screen.getByRole("button", { name: "開始確認 →" })).toBeTruthy();
  });

  it("photos only: the title does not claim a website was read", async () => {
    mockFetch.mockResolvedValue({ ...DONE, pages_read: 0, photos_read: 2 });
    renderStep();
    expect(await screen.findByRole("heading", { level: 1, name: "我看完你的品牌照片了" })).toBeTruthy();
  });

  it("a website list changed since the read (the server says none) starts a new read instead of the old result", async () => {
    mockFetch.mockResolvedValueOnce(scan({ status: "none" })).mockResolvedValue(DONE);
    mockStart.mockResolvedValue(scan({ status: "running" }));
    renderStep();
    expect(await screen.findByText("預填 5 項", {}, { timeout: 4000 })).toBeTruthy();
    expect(mockStart).toHaveBeenCalledTimes(1);
  });

  it("no not-found row when the scan found every area", async () => {
    mockFetch.mockResolvedValue({ ...DONE, not_found: [] });
    renderStep();
    await screen.findByText("預填 5 項");
    expect(screen.queryByText("網站上沒找到")).toBeNull();
  });
});
