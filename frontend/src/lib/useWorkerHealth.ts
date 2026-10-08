/** Shared worker health while a page waits: poll immediately and at its own interval.
 * Read failures are unknown; only an explicit stopped projection means stalled.
 * Earlier requests cannot overwrite a newer request or a new waiting lifecycle. */
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchActiveJobs, workerHealthState, type WorkerHealthProjection } from "./jobsApi";

export interface WorkerHealth {
  stalled: boolean;
  unavailable: boolean;
  state: WorkerHealthProjection["state"];
  recheck: () => Promise<void>;
}

export function useWorkerHealth(waiting: boolean, intervalMs: number): WorkerHealth {
  const [state, setState] = useState<WorkerHealthProjection["state"]>("unknown");
  const epoch = useRef(0);
  const requestId = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const read = useCallback(async () => {
    const generation = epoch.current;
    const id = ++requestId.current;
    try {
      const snapshot = await fetchActiveJobs();
      if (mounted.current && generation === epoch.current && id === requestId.current) {
        setState(workerHealthState(snapshot));
      }
    } catch {
      if (mounted.current && generation === epoch.current && id === requestId.current) setState("unknown");
    }
  }, []);

  useEffect(() => {
    epoch.current += 1;
    setState("unknown");
    if (!waiting) {
      return;
    }
    void read();
    const timer = window.setInterval(() => void read(), intervalMs);
    return () => {
      epoch.current += 1;
      window.clearInterval(timer);
    };
  }, [waiting, intervalMs, read]);

  return { state, stalled: waiting && state === "stopped", unavailable: waiting && state === "unknown", recheck: read };
}
