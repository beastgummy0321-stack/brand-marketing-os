import { Button } from "@/components/layout/ui/button";

/** F28-I15: the confirm page's primary action on an outdated cleanup draft (`cleanupDraft.ts::useCleanupRebuild`)
 * — it replaces 核准清理, which is not offered while the draft differs from the latest proposal. */
export function AdoptLatestButton({ busy, onClick }: { busy: boolean; onClick: () => void }) {
  return <Button disabled={busy} onClick={onClick}>{busy ? "處理中…" : "改用最新提議 →"}</Button>;
}
