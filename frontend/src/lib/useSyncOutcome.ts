/** F49 Contract O: a platform read's one outcome, read the same way by every screen.
 *
 * `useSyncOutcome({ brandId, campaignId })` reads `GET …/campaigns/{c}/sync-outcome` (the worst outcome over the jobs
 * covering the campaign); `useSyncOutcome({ brandId, jobId, campaignId? })` reads `GET …/sync-jobs/{id}` and its
 * `outcome` (scoped to `campaignId` when given). It reads at once, then every 3 s while the state is `running`, stops
 * when the read finished (found, empty, partial or failed), and aborts on unmount. `refresh()` reads once more (after
 * the caller requested a new read) and polls again while it runs.
 *
 * This hook is the only reader of a sync job's status and error (`oneRuler.test.ts` forbids `.job.status`,
 * `.job.error` and `syncJob(` anywhere else): a screen prints `text` and branches on `state`／`code`. */
import { useCallback, useEffect, useState } from "react";
import { syncJob, syncOutcome, type SyncOutcome } from "./adsExternalApi";

export const SYNC_POLL_MS = 3000;

export type SyncTarget =
  | { brandId: string; campaignId: string; jobId?: undefined }
  | { brandId: string; jobId: string; campaignId?: string };

export interface SyncOutcomeRead {
  /** null until the first read answers. */
  state: SyncOutcome["state"] | null;
  code: string | null;
  text: string;
  /** The oldest clean read over the covering jobs (campaign read) or the job's own last clean read. */
  lastSuccessAt: string | null;
  /** The outcome itself could not be read (network／server); the last known outcome is kept. */
  error: string | null;
  refresh: () => void;
}

interface Snapshot { state: SyncOutcome["state"] | null; code: string | null; text: string; lastSuccessAt: string | null; error: string | null }

const EMPTY: Snapshot = { state: null, code: null, text: "", lastSuccessAt: null, error: null };

export function useSyncOutcome(target: SyncTarget): SyncOutcomeRead {
  const { brandId } = target;
  const jobId = target.jobId ?? null;
  const campaignId = target.campaignId ?? null;
  const [snapshot, setSnapshot] = useState<Snapshot>(EMPTY);
  const [round, setRound] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function read() {
      try {
        let next: Snapshot;
        if (jobId) {
          const result = await syncJob(brandId, jobId, controller.signal, campaignId ?? undefined);
          const outcome = result.outcome;
          next = { state: outcome?.state ?? null, code: outcome?.code ?? null, text: outcome?.text ?? "", lastSuccessAt: result.job.last_success_at, error: null };
        } else if (campaignId) {
          const outcome = await syncOutcome(brandId, campaignId, controller.signal);
          next = { state: outcome.state, code: outcome.code, text: outcome.text, lastSuccessAt: outcome.last_success_at, error: null };
        } else return;
        if (controller.signal.aborted) return;
        setSnapshot(next);
        if (next.state === "running") timer = setTimeout(() => void read(), SYNC_POLL_MS);
      } catch (e) {
        if (controller.signal.aborted) return;
        setSnapshot((prev) => ({ ...prev, error: e instanceof Error ? e.message : "讀取同步結果失敗。" }));
      }
    }
    void read();
    return () => {
      controller.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [brandId, jobId, campaignId, round]);

  const refresh = useCallback(() => setRound((n) => n + 1), []);
  return { ...snapshot, refresh };
}
