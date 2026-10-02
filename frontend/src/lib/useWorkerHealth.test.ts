/** frontend/src/lib/useWorkerHealth.test.ts — F47 Contract C: the hook reads `GET /api/jobs/active` only while its
 * caller waits on a job (at once, then on the caller's interval), reports `stalled` only when the server says so, never
 * from a failed read, resets when the waiting ends, and `recheck()` reads once now. */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./jobsApi", async (original) => ({ ...await original<typeof import("./jobsApi")>(), fetchActiveJobs: vi.fn() }));

import { fetchActiveJobs, type ActiveJobsSnapshot } from "./jobsApi";
import { useWorkerHealth } from "./useWorkerHealth";

const mockJobs = vi.mocked(fetchActiveJobs);
const snapshot = (stalled: boolean): ActiveJobsSnapshot => ({
  data: [], total: 1, other_count: 0, done_today: 0, failed_today: 0, generated_at: "2026-10-02T02:00:00Z",
  worker_alive: !stalled, stalled,
});

beforeEach(() => {
  mockJobs.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useWorkerHealth", () => {
  it("does not read while the caller is not waiting", async () => {
    mockJobs.mockResolvedValue(snapshot(true));
    const { result } = renderHook(() => useWorkerHealth(false, 1000));
    await act(async () => {});
    expect(mockJobs).not.toHaveBeenCalled();
    expect(result.current.stalled).toBe(false);
  });

  it("reads at once while waiting and reports the server's stalled", async () => {
    mockJobs.mockResolvedValue(snapshot(true));
    const { result } = renderHook(() => useWorkerHealth(true, 1000));
    await waitFor(() => expect(result.current.stalled).toBe(true));
    expect(mockJobs).toHaveBeenCalledTimes(1);
  });

  it("reads again on the caller's interval, and stops when the waiting ends", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockJobs.mockResolvedValue(snapshot(false));
    const { rerender, result } = renderHook(({ waiting }) => useWorkerHealth(waiting, 3000), { initialProps: { waiting: true } });
    await act(async () => {});
    expect(mockJobs).toHaveBeenCalledTimes(1);
    mockJobs.mockResolvedValue(snapshot(true));
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(mockJobs).toHaveBeenCalledTimes(2);
    expect(result.current.stalled).toBe(true);

    rerender({ waiting: false });
    expect(result.current.stalled).toBe(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(mockJobs).toHaveBeenCalledTimes(2);
  });

  it("a failed read is not a stopped worker", async () => {
    mockJobs.mockRejectedValue(new Error("讀取失敗（狀態碼 500）"));
    const { result } = renderHook(() => useWorkerHealth(true, 1000));
    await waitFor(() => expect(mockJobs).toHaveBeenCalled());
    await act(async () => {});
    expect(result.current.stalled).toBe(false);
  });

  it("a response without the field (an older server) is not a stopped worker", async () => {
    mockJobs.mockResolvedValue({
      data: [], total: 1, other_count: 0, done_today: 0, failed_today: 0, generated_at: "2026-10-02T02:00:00Z",
    });
    const { result } = renderHook(() => useWorkerHealth(true, 1000));
    await waitFor(() => expect(mockJobs).toHaveBeenCalled());
    await act(async () => {});
    expect(result.current.stalled).toBe(false);
  });

  it("recheck() reads now: a live worker clears stalled", async () => {
    mockJobs.mockResolvedValue(snapshot(true));
    const { result } = renderHook(() => useWorkerHealth(true, 60_000));
    await waitFor(() => expect(result.current.stalled).toBe(true));
    mockJobs.mockResolvedValue(snapshot(false));
    await act(async () => { await result.current.recheck(); });
    expect(result.current.stalled).toBe(false);
    expect(mockJobs).toHaveBeenCalledTimes(2);
  });
});
