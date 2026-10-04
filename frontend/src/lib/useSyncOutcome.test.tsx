/** frontend/src/lib/useSyncOutcome.test.tsx — F49 Contract O: the one reader of a platform read's outcome. It reads at
 * once, polls every 3 s while `running`, keeps a partial／failed read's sentence, stops polling once the read finished,
 * re-reads on `refresh()`, and aborts its request on unmount. */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./adsExternalApi", async (original) => ({
  ...await original<typeof import("./adsExternalApi")>(),
  syncJob: vi.fn(),
  syncOutcome: vi.fn(),
}));

import { syncJob, syncOutcome, type CampaignSyncOutcome, type SyncJob, type SyncOutcome } from "./adsExternalApi";
import { SYNC_POLL_MS, useSyncOutcome } from "./useSyncOutcome";

const mockCampaign = vi.mocked(syncOutcome);
const mockJob = vi.mocked(syncJob);

const campaignRead = (state: SyncOutcome["state"], text: string, code: string | null = null): CampaignSyncOutcome => ({
  state, code, text, job_ids: ["aes_1", "aes_2"], last_success_at: "2026-10-04T01:00:00Z",
});
const job: SyncJob = { id: "aes_1", status: "partial", last_success_at: null };
const jobRead = (state: SyncOutcome["state"], text: string, code: string | null = null) => ({
  job, connected: true, outcome: { state, code, text },
});

beforeEach(() => {
  mockCampaign.mockReset();
  mockJob.mockReset();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useSyncOutcome", () => {
  it("polls a running campaign read every 3 s until it is found", async () => {
    mockCampaign.mockResolvedValueOnce(campaignRead("running", "正在讀取平台資料"))
      .mockResolvedValueOnce(campaignRead("running", "正在讀取平台資料"))
      .mockResolvedValue(campaignRead("found", "已讀到平台資料"));
    const { result } = renderHook(() => useSyncOutcome({ brandId: "b1", campaignId: "c1" }));
    await waitFor(() => expect(result.current.state).toBe("running"));
    expect(mockCampaign).toHaveBeenCalledWith("b1", "c1", expect.any(AbortSignal));
    await act(async () => { await vi.advanceTimersByTimeAsync(SYNC_POLL_MS); });
    expect(mockCampaign).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(SYNC_POLL_MS); });
    expect(result.current.state).toBe("found");
    expect(result.current.text).toBe("已讀到平台資料");
    expect(result.current.lastSuccessAt).toBe("2026-10-04T01:00:00Z");
    await act(async () => { await vi.advanceTimersByTimeAsync(SYNC_POLL_MS * 3); });
    expect(mockCampaign).toHaveBeenCalledTimes(3);
  });

  it("a partial job read keeps its sentence and code, scoped to the campaign", async () => {
    const text = "有部分平台資料沒讀到：資料量超過一次可讀的上限，這次沒有讀完";
    mockJob.mockResolvedValue(jobRead("partial", text, "page_limit"));
    const { result } = renderHook(() => useSyncOutcome({ brandId: "b1", jobId: "aes_1", campaignId: "c1" }));
    await waitFor(() => expect(result.current.state).toBe("partial"));
    expect(result.current.text).toBe(text);
    expect(result.current.code).toBe("page_limit");
    expect(mockJob).toHaveBeenCalledWith("b1", "aes_1", expect.any(AbortSignal), "c1");
  });

  it("a failed read stops polling; refresh() reads once more", async () => {
    mockJob.mockResolvedValue(jobRead("failed", "這次沒讀到平台資料：平台授權已失效或權限不足，請重新授權", "permission_denied"));
    const { result } = renderHook(() => useSyncOutcome({ brandId: "b1", jobId: "aes_1" }));
    await waitFor(() => expect(result.current.state).toBe("failed"));
    await act(async () => { await vi.advanceTimersByTimeAsync(SYNC_POLL_MS * 4); });
    expect(mockJob).toHaveBeenCalledTimes(1);
    mockJob.mockResolvedValue(jobRead("found", "已讀到平台資料"));
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.state).toBe("found"));
    expect(mockJob).toHaveBeenCalledTimes(2);
  });

  it("refresh() says running until the new read answers — never the previous read's found", async () => {
    mockJob.mockResolvedValueOnce(jobRead("found", "已讀到平台資料"));
    const { result } = renderHook(() => useSyncOutcome({ brandId: "b1", jobId: "aes_1" }));
    await waitFor(() => expect(result.current.state).toBe("found"));
    let answer: (value: ReturnType<typeof jobRead>) => void = () => {};
    mockJob.mockImplementationOnce(() => new Promise((resolve) => { answer = resolve; }));
    act(() => result.current.refresh());
    expect(result.current.state).toBe("running");
    expect(result.current.text).not.toBe("已讀到平台資料");
    await waitFor(() => expect(mockJob).toHaveBeenCalledTimes(2));
    expect(result.current.state).toBe("running");
    await act(async () => { answer(jobRead("partial", "有部分平台資料沒讀到：平台暫時沒有回應，稍後會再試", "source_error")); });
    await waitFor(() => expect(result.current.state).toBe("partial"));
    expect(result.current.code).toBe("source_error");
  });

  it("a failed outcome request keeps the last outcome and says the read failed", async () => {
    mockCampaign.mockResolvedValueOnce(campaignRead("empty", "沒有讀到資料：平台在這段期間沒有回傳任何資料", "no_rows"))
      .mockRejectedValueOnce(new Error("讀取同步結果失敗。"));
    const { result } = renderHook(() => useSyncOutcome({ brandId: "b1", campaignId: "c1" }));
    await waitFor(() => expect(result.current.state).toBe("empty"));
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.error).toBe("讀取同步結果失敗。"));
    expect(result.current.state).toBe("empty");
    expect(result.current.code).toBe("no_rows");
  });

  it("unmount aborts the request in flight and schedules nothing more", async () => {
    let signal: AbortSignal | undefined;
    mockCampaign.mockImplementation((_b, _c, s) => {
      signal = s;
      return new Promise(() => {});
    });
    const { unmount } = renderHook(() => useSyncOutcome({ brandId: "b1", campaignId: "c1" }));
    await waitFor(() => expect(mockCampaign).toHaveBeenCalledTimes(1));
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(SYNC_POLL_MS * 3); });
    expect(mockCampaign).toHaveBeenCalledTimes(1);
  });

  it("unmount while running cancels the next poll", async () => {
    mockCampaign.mockResolvedValue(campaignRead("running", "正在讀取平台資料"));
    const { result, unmount } = renderHook(() => useSyncOutcome({ brandId: "b1", campaignId: "c1" }));
    await waitFor(() => expect(result.current.state).toBe("running"));
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(SYNC_POLL_MS * 3); });
    expect(mockCampaign).toHaveBeenCalledTimes(1);
  });
});
