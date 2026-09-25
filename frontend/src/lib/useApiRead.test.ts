/** Feature F29 Contract K: `useApiRead` — a failed read stays failed (never empty data), `reload` re-runs,
 * and a read is aborted on unmount and on a dependency change (its late answer is dropped). */
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useApiRead } from "./useApiRead";

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe("useApiRead", () => {
  it("loading → ready with exactly what the read returned", async () => {
    const read = vi.fn().mockResolvedValue(["a"]);
    const { result } = renderHook(() => useApiRead(read, []));
    expect(result.current.status).toBe("loading");
    expect(result.current.data).toBeNull();
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.data).toEqual(["a"]);
    expect(result.current.error).toBeNull();
    expect(read.mock.calls[0][0]).toBeInstanceOf(AbortSignal);
  });

  it("a failed read is the error state with its message, never empty data; reload re-requests and recovers", async () => {
    const read = vi.fn().mockRejectedValueOnce(new Error("伺服器沒回應")).mockResolvedValueOnce([1, 2]);
    const { result } = renderHook(() => useApiRead(read, []));
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe("伺服器沒回應");
    act(() => result.current.reload());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(read).toHaveBeenCalledTimes(2);
    expect(result.current.data).toEqual([1, 2]);
  });

  it("a non-Error rejection still says the read failed", async () => {
    const read = vi.fn().mockRejectedValue("boom");
    const { result } = renderHook(() => useApiRead(read, []));
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBe("讀取失敗，請稍後再試。");
  });

  it("reload keeps the last good data while loading, then a failure clears it", async () => {
    const second = deferred<string>();
    const read = vi.fn().mockResolvedValueOnce("first").mockReturnValueOnce(second.promise);
    const { result } = renderHook(() => useApiRead(read, []));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    act(() => result.current.reload());
    expect(result.current.status).toBe("loading");
    expect(result.current.data).toBe("first");
    await act(async () => { second.reject(new Error("x")); });
    expect(result.current.status).toBe("error");
    expect(result.current.data).toBeNull();
  });

  it("a dependency change aborts the old read, drops its late answer and resets data", async () => {
    const first = deferred<string>();
    const signals: AbortSignal[] = [];
    const read = vi.fn((id: string, signal: AbortSignal) => {
      signals.push(signal);
      return id === "a" ? first.promise : Promise.resolve(`data-${id}`);
    });
    const { result, rerender } = renderHook(({ id }) => useApiRead((s) => read(id, s), [id]), { initialProps: { id: "a" } });
    rerender({ id: "b" });
    expect(signals[0].aborted).toBe(true);
    await waitFor(() => expect(result.current.data).toBe("data-b"));
    await act(async () => { first.resolve("late-a"); });
    expect(result.current.data).toBe("data-b");
    expect(result.current.status).toBe("ready");
  });

  it("unmount aborts the read in flight", () => {
    const signals: AbortSignal[] = [];
    const { unmount } = renderHook(() => useApiRead((s) => { signals.push(s); return new Promise(() => {}); }, []));
    unmount();
    expect(signals[0].aborted).toBe(true);
  });
});
