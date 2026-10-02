/** F47 Contract C: is the background worker stopped while this page waits on a job?
 *
 * A page that waits on a background job (a site read, a product-page read, copy generation, a
 * workbench set) passes `waiting` and its own polling interval. Only while `waiting` is true the
 * hook reads `GET /api/jobs/active` — at once, then every `intervalMs` — and reports `stalled`
 * (no live worker while this org has queued/running work). A failed read never reads as stopped;
 * `waiting` false resets it. `recheck()` reads once now (the notice's 「再檢查一次」). */
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchActiveJobs } from "./jobsApi";

export interface WorkerHealth {
  stalled: boolean;
  recheck: () => Promise<void>;
}

export function useWorkerHealth(waiting: boolean, intervalMs: number): WorkerHealth {
  const [stalled, setStalled] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const read = useCallback(async () => {
    try {
      const snapshot = await fetchActiveJobs();
      if (mounted.current) setStalled(snapshot.stalled === true);
    } catch {
      if (mounted.current) setStalled(false);
    }
  }, []);

  useEffect(() => {
    if (!waiting) {
      setStalled(false);
      return;
    }
    void read();
    const timer = window.setInterval(() => void read(), intervalMs);
    return () => window.clearInterval(timer);
  }, [waiting, intervalMs, read]);

  return { stalled: waiting && stalled, recheck: read };
}
