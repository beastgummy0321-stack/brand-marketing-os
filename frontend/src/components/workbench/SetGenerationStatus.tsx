import { useState } from "react";
import { Button } from "@/components/layout/ui/button";
import { WorkerStoppedNotice } from "@/components/layout/WorkerStoppedNotice";
import { useWorkerHealth } from "@/lib/useWorkerHealth";
import { runProduct, type ProductPart, type SetDetail } from "@/lib/workbenchApi";

/** How often the studio re-reads a set while a round runs (the page's own poll). */
const SET_POLL_MS = 3000;
/** The copy / script count a rerun uses when the part never ran (the studio's own default). */
const DEFAULT_COUNT = 4;

/** The set studio's generation-status block (moved out of `SetStudioPage.tsx`, F47-I04):
 * - a round queued / running says so; while it waits and the background worker is stopped (F47 Contract C) the
 *   worker-stopped notice follows, whose 再檢查一次 re-reads the worker and the set (`onReload`);
 * - a poll that fails says it will retry;
 * - a failed round shows the server's `generation.error` (the brief's `last_error`, cleared by the next success) with
 *   「重新生成」, which runs `part` again the way the part's own button does (image: no count; else the part's last
 *   count) — disabled with the lock's reason when that part is locked. */
export function SetGenerationStatus({
  brandId,
  set,
  generating,
  pollError,
  part,
  onReload,
  onRunStarted,
  onUpdated,
}: {
  brandId: string;
  set: SetDetail;
  generating: boolean;
  pollError: string | null;
  /** The part 「重新生成」 runs (the open tab; the round's status is one field per set, so the page cannot know
   * which part failed), `null` when the set has none. */
  part: ProductPart | null;
  onReload: () => Promise<unknown>;
  /** The part this browser started (the studio names it on the other tabs' buttons), `null` when it did not start. */
  onRunStarted: (part: ProductPart | null) => void;
  onUpdated: (next: SetDetail) => void;
}) {
  const worker = useWorkerHealth(generating, SET_POLL_MS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const failed = set.generation?.status === "failed";
  const partLocked = part ? (set.products[part]?.locked ?? set.lock.locked) : true;

  async function regenerate() {
    if (!part) return;
    setBusy(true);
    setError(null);
    const count = part === "image_prompt"
      ? undefined
      : ((set.products[part]?.generation_settings.count as number | undefined) ?? DEFAULT_COUNT);
    onRunStarted(part);
    try {
      onUpdated(await runProduct(brandId, set.id, part, count));
    } catch (err) {
      onRunStarted(null);
      setError(err instanceof Error ? err.message : "重新生成沒有送出，請稍後再試。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {generating && (
        <p role="status" className="rounded-md bg-muted p-3 text-sm">
          {set.generation?.status === "queued" ? "素材已排隊，等待生成。" : "素材生成中，完成後會自動更新。"}
        </p>
      )}
      {generating && worker.stalled && (
        <WorkerStoppedNotice onRecheck={() => Promise.all([worker.recheck(), onReload()])} />
      )}
      {pollError && <p role="alert" className="text-sm text-danger">{pollError}</p>}
      {failed && (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-md bg-danger/10 p-3 text-sm text-danger">
          <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
            這輪生成失敗：{set.generation?.error || "沒有收到原因。"}
          </span>
          {part && (
            <Button
              size="sm"
              variant="outline"
              busy={busy}
              disabledReason={partLocked && !busy ? (set.lock.reason ?? "素材組目前已鎖定") : undefined}
              onClick={() => void regenerate()}
            >
              {busy ? "送出中…" : "重新生成"}
            </Button>
          )}
          {error && <span className="w-full text-xs">{error}</span>}
        </div>
      )}
    </>
  );
}
