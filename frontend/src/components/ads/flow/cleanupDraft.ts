/** F28-I15: a cleanup change set's own logic — how its draft compares with the queue row's current proposal, and
 * the one way a cleanup set is created (first write on the propose route, and 「改用最新提議」). Kept out of
 * `ConfirmPage.tsx` so that page stays a router over kinds. */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createChangeSet, type ChangeItem, type ChangeSet } from "@/lib/adsChangeApi";
import type { QueueCleanup, QueueCleanupAd, QueueItem } from "@/lib/adsTriageApi";
import { currentBudgetMonth } from "../MonthlyBudgetPanel";
import { buildCleanupDraftItems, changeStepPath, cleanupTitle } from "./changeFlow";

/** How a cleanup draft's frozen close list differs from the queue row's current `cleanup.ads` — `added` = ads the
 * latest proposal closes that the draft does not, `dropped` = draft items the latest proposal no longer closes.
 * Compared by entity id only (order and reasons are not a difference). `null` when there is nothing to adopt: the
 * set is not a draft (a rejected / deferred / approved set is never rebuilt this way), the queue row is missing
 * (read failed or the row left the queue), the lists match, or the latest proposal is empty (a set needs at least
 * one item, so there is nothing to rebuild into). */
export interface CleanupDrift { added: QueueCleanupAd[]; dropped: ChangeItem[] }
export function cleanupDrift(set: ChangeSet | null, cleanup: QueueCleanup | null | undefined): CleanupDrift | null {
  if (!set || set.status !== "draft" || !cleanup || cleanup.ads.length === 0) return null;
  const draftIds = new Set(set.items.map((i) => i.target_id));
  const latestIds = new Set(cleanup.ads.map((a) => a.entity_id));
  const added = cleanup.ads.filter((a) => !draftIds.has(a.entity_id));
  const dropped = set.items.filter((i) => !latestIds.has(i.target_id));
  return added.length || dropped.length ? { added, dropped } : null;
}

/** F27-I15 Contract F: a cleanup set is one `pause` item per ad of the queue row's `cleanup.ads`, marked
 * `source: "cleanup"` (the backend's `_matching_cleanup_set` only matches on `plan_json.source`). F28-I15:
 * `supersedesId` replaces an outdated draft with the latest proposal. */
export function createCleanupSet(
  brandId: string, campaignId: string, cleanup: QueueCleanup, operationId: string, supersedesId?: string,
): Promise<ChangeSet> {
  return createChangeSet(brandId, campaignId, {
    operation_id: operationId,
    title: cleanupTitle(cleanup.campaign_name),
    month: currentBudgetMonth(),
    items: buildCleanupDraftItems(cleanup.ads),
    ...(supersedesId ? { supersedes_id: supersedesId } : {}),
    source: "cleanup",
  });
}

/** F28-I15: an outdated cleanup draft on the confirm page. A cleanup draft built from an older proposal is not what
 * the queue row proposes now — `drift` (`cleanupDrift` above) tells the page to show the difference and
 * offer only 「改用最新提議」 (never 核准 of the outdated list); `null` = page as before. `draftProposalId`: the
 * propose route's confirm step, once the row already has a cleanup draft, is that draft's own confirm page — so the
 * comparison happens in one place, and 核准 never silently approves an older list; the page shows its skeleton while
 * this hook redirects. `adopt` rebuilds the draft from the latest proposal (superseding it; the backend marks the old
 * draft `superseded`) and opens the new set's confirm step. `busy` and the error line are the page's own. */
export function useCleanupRebuild({ brandId, campaignId, setId, isCleanup, proposeConfirmStep, changeSet, triageItem, busy, setBusy, setChangeSet, setActionError }: {
  brandId: string; campaignId: string; setId?: string; isCleanup: boolean; proposeConfirmStep: boolean;
  changeSet: ChangeSet | null; triageItem: QueueItem | null; busy: boolean;
  setBusy: (value: boolean) => void; setChangeSet: (set: ChangeSet) => void; setActionError: (message: string | null) => void;
}): { drift: CleanupDrift | null; draftProposalId: string | null; adopt: () => Promise<void> } {
  const navigate = useNavigate();
  // One operation id per page, so a retry after a lost response replays the same set.
  const [operationId] = useState(() => `triage-cleanup-adopt:${setId ?? campaignId}:${crypto.randomUUID()}`);
  const drift = isCleanup ? cleanupDrift(changeSet, triageItem?.cleanup) : null;
  const proposal = triageItem?.proposal;
  const draftProposalId = proposeConfirmStep && proposal?.kind === "cleanup" && proposal.status === "draft"
    ? proposal.change_set_id : null;
  useEffect(() => {
    if (draftProposalId) navigate(changeStepPath(brandId, campaignId, draftProposalId, "confirm"), { replace: true });
  }, [draftProposalId, brandId, campaignId, navigate]);

  async function adopt() {
    const cleanup = triageItem?.cleanup;
    if (busy || !changeSet || !cleanup) return;
    setBusy(true);
    setActionError(null);
    try {
      const rebuilt = await createCleanupSet(brandId, campaignId, cleanup, operationId, changeSet.id);
      setChangeSet(rebuilt);
      navigate(changeStepPath(brandId, campaignId, rebuilt.id, "confirm"), { replace: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。");
    } finally {
      setBusy(false);
    }
  }

  return { drift, draftProposalId, adopt };
}
