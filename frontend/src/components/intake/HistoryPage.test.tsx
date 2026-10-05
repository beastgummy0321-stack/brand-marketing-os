/** frontend/src/components/intake/HistoryPage.test.tsx — F50-I16 (Contract J, R7 A12): the history page says how the
 * 37-month pull ended from `GET …/backfill`'s stored `outcome` (shape of `app/meta/routes.py` `BackfillStatusResponse`),
 * a failed status read shows its error, and the poll stops on unmount. All API calls are fakes. */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/scheduleApi", () => ({
  fetchHistory: vi.fn(),
  refetchHistoryCreatives: vi.fn(),
  tagHistoryAd: vi.fn(),
}));
vi.mock("@/lib/metaApi", () => ({ fetchMetaBackfillStatus: vi.fn(), startMetaBackfill: vi.fn() }));
// The org is in Taipei whatever zone the test runner is in (F50-I14).
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({ identity: { org: { id: "org_1", timezone: "Asia/Taipei", today: "2026-10-05" } } }),
}));

import { fetchHistory, type History } from "@/lib/scheduleApi";
import { fetchMetaBackfillStatus, startMetaBackfill, type MetaBackfillStatus } from "@/lib/metaApi";
import { HistoryPage } from "./HistoryPage";

const mockHistory = vi.mocked(fetchHistory);
const mockStatus = vi.mocked(fetchMetaBackfillStatus);
const mockStart = vi.mocked(startMetaBackfill);

function history(adRows: number, running = false): History {
  return {
    connected: true,
    backfill: { running, earliest_spend_date: adRows ? "2023-09-01" : null, latest_spend_date: adRows ? "2026-10-04" : null, ad_rows: adRows },
    breakeven: null,
    currencies: [],
    coordinates: [],
  };
}

function status(over: Partial<MetaBackfillStatus>): MetaBackfillStatus {
  return { running: false, earliest_spend_date: null, latest_spend_date: null, ad_rows: 0, outcome: null, ...over };
}

beforeEach(() => {
  mockHistory.mockReset();
  mockStatus.mockReset();
  mockStart.mockReset().mockResolvedValue({ started: true, running: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("HistoryPage backfill outcome", () => {
  it("empty: says the pull finished with no ad data, with the served range sentence", async () => {
    mockHistory.mockResolvedValue(history(0));
    mockStatus.mockResolvedValue(status({
      outcome: { state: "empty", code: "no_rows", text: "2023-09-05 ~ 2026-10-05 這段期間 Meta 沒有回任何成效資料。", finished_at: "2026-10-05T03:00:00+00:00" },
    }));
    render(<HistoryPage brandId="brd_x" />);
    expect(await screen.findByText("拉完了：這段期間沒有廣告資料")).toBeTruthy();
    expect(screen.getByText("2023-09-05 ~ 2026-10-05 這段期間 Meta 沒有回任何成效資料。")).toBeTruthy();
    expect(screen.queryByText("還沒有任何一天的數字，先拉 37 個月的歷史資料。")).toBeNull();
  });

  it("failed: shows the served reason and 再試一次 starts the pull again", async () => {
    mockHistory.mockResolvedValue(history(0));
    mockStatus.mockResolvedValue(status({
      outcome: { state: "failed", code: "account_failed", text: "主帳戶（act_1001）：權杖過期，請重新接上 Meta。", finished_at: "2026-10-05T03:00:00+00:00" },
    }));
    render(<HistoryPage brandId="brd_x" />);
    expect(await screen.findByText("主帳戶（act_1001）：權杖過期，請重新接上 Meta。")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "再試一次" }));
    await waitFor(() => expect(mockStart).toHaveBeenCalledWith("brd_x"));
    expect(await screen.findByText(/正在從 Meta 拉數字/)).toBeTruthy();
  });

  it("done: says the pull finished with the stored date range and row count above the cards", async () => {
    mockHistory.mockResolvedValue(history(120));
    mockStatus.mockResolvedValue(status({
      earliest_spend_date: "2023-09-01", latest_spend_date: "2026-10-04", ad_rows: 120,
      outcome: { state: "done", code: null, text: null, finished_at: "2026-10-05T03:00:00+00:00" },
    }));
    render(<HistoryPage brandId="brd_x" />);
    expect(await screen.findByText("拉完了：2023/09/01～2026/10/04，共 120 筆廣告每日數字")).toBeTruthy();
  });

  it("a done org pull with no row for this brand (an account bound after it) claims nothing and keeps the start button", async () => {
    mockHistory.mockResolvedValue(history(0));
    mockStatus.mockResolvedValue(status({ ad_rows: 0, outcome: { state: "done", code: null, text: null, finished_at: "2026-10-01T03:00:00+00:00" } }));
    render(<HistoryPage brandId="brd_x" />);
    expect(await screen.findByRole("button", { name: "開始拉 37 個月的數字" })).toBeTruthy();
    await waitFor(() => expect(mockStatus).toHaveBeenCalled());
    expect(screen.queryByText(/拉完了/)).toBeNull();
  });

  it("never pulled: the start button stays and nothing claims an outcome", async () => {
    mockHistory.mockResolvedValue(history(0));
    mockStatus.mockResolvedValue(status({ outcome: null }));
    render(<HistoryPage brandId="brd_x" />);
    expect(await screen.findByRole("button", { name: "開始拉 37 個月的數字" })).toBeTruthy();
    await waitFor(() => expect(mockStatus).toHaveBeenCalled());
    expect(screen.queryByText(/拉完了/)).toBeNull();
  });

  it("a failed status read shows the read error instead of nothing", async () => {
    mockHistory.mockResolvedValue(history(0));
    mockStatus.mockRejectedValue(new Error("讀取失敗（狀態碼 500）"));
    render(<HistoryPage brandId="brd_x" />);
    expect(await screen.findByText("讀取失敗（狀態碼 500）")).toBeTruthy();
  });

  it("polls while running and stops polling on unmount", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockHistory.mockResolvedValue(history(0, true));
    mockStatus.mockResolvedValue(status({ running: true, outcome: { state: "running", code: null, text: null, finished_at: null } }));
    const { unmount } = render(<HistoryPage brandId="brd_x" />);
    expect(await screen.findByText(/正在從 Meta 拉數字/)).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5100);
    });
    const calls = mockStatus.mock.calls.length;
    expect(calls).toBeGreaterThanOrEqual(2);
    unmount();
    await vi.advanceTimersByTimeAsync(20000);
    expect(mockStatus.mock.calls.length).toBe(calls);
  });
});
