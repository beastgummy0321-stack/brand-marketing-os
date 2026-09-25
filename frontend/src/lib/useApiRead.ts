import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";

/** Feature F29 Contract K: the one read convention for screen data. A failed read is its own state
 * (`error`), never empty data — the caller renders it (ads pages: `ReadFailed`; other pages: their
 * existing error line with 重試) instead of an empty list, a hidden block or a silent no-op.
 *
 * - `loading`: the first read, a dependency change (data reset to `null`) or `reload()` (the last
 *   good `data` stays, so a refresh does not flash an empty block).
 * - `ready`: `data` is exactly what the read returned (it may itself be `null` when the read says
 *   "nothing", which is a real answer, not a failure).
 * - `error`: `data` is `null`; `error` is the message to show.
 *
 * The read gets an `AbortSignal`; it is aborted on unmount and whenever the dependencies change or
 * `reload()` runs, and a late answer from an aborted read is dropped either way. */
export type ApiReadState<T> =
  | { status: "loading"; data: T | null; error: null }
  | { status: "ready"; data: T; error: null }
  | { status: "error"; data: null; error: string };

export type ApiRead<T> = ApiReadState<T> & { reload: () => void };

const FALLBACK_MESSAGE = "讀取失敗，請稍後再試。";

export function readErrorMessage(err: unknown): string {
  return err instanceof Error && err.message ? err.message : FALLBACK_MESSAGE;
}

export function useApiRead<T>(read: (signal: AbortSignal) => Promise<T>, deps: DependencyList): ApiRead<T> {
  const [state, setState] = useState<ApiReadState<T>>({ status: "loading", data: null, error: null });
  const [nonce, setNonce] = useState(0);
  const readRef = useRef(read);
  readRef.current = read;

  // A dependency change means a different thing is being read: its old data must not stand in.
  useEffect(() => {
    setState({ status: "loading", data: null, error: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the caller's own dependency list.
  }, deps);

  useEffect(() => {
    const controller = new AbortController();
    setState((prev) => (prev.status === "loading" ? prev : { status: "loading", data: prev.data, error: null }));
    readRef.current(controller.signal).then(
      (data) => { if (!controller.signal.aborted) setState({ status: "ready", data, error: null }); },
      (err: unknown) => { if (!controller.signal.aborted) setState({ status: "error", data: null, error: readErrorMessage(err) }); },
    );
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the caller's own dependency list plus `reload`.
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, reload };
}
