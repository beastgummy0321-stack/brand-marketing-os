/** F28-I15: a cleanup change set's own logic — how its draft compares with the queue row's current proposal, and
 * the one way a cleanup set is created (first write on the propose route, and 「改用最新提議」). Kept out of
 * `ConfirmPage.tsx` so that page stays a router over kinds. */
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { createChangeSet, type ChangeItem, type ChangeSet } from "@/lib/adsChangeApi";
import type { QueueCleanup, QueueCleanupAd, QueueItem } from "@/lib/adsTriageApi";
import { currentBudgetMonth } from "../MonthlyBudgetPanel";
import { useOrgClock } from "@/lib/orgClock";
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
  // F29-I14: a proposed ad the user unticked (`plan_json.declined_ids`) is the user's own subset, not an outdated
  // draft — only an ad the draft neither closes nor declined is new.
  const declined = new Set(declinedIdsOf(set));
  const added = cleanup.ads.filter((a) => !draftIds.has(a.entity_id) && !declined.has(a.entity_id));
  const dropped = set.items.filter((i) => !latestIds.has(i.target_id));
  return added.length || dropped.length ? { added, dropped } : null;
}

/** F29-I01 Contract B: the proposed ads the user unticked, as the set stored them (`plan_json.declined_ids`). The
 * set view returns its whole row, `plan_json` included, but `adsChangeApi.ts::ChangeSet` (out of this issue's touch)
 * does not type it — read through a local widening, same technique as `changeFlow.ts::itemAngle`. */
type ChangeSetPlan = ChangeSet & { plan_json?: { declined_ids?: string[] | null } | null };
export function declinedIdsOf(set: ChangeSet | null | undefined): string[] {
  return (set as ChangeSetPlan | null | undefined)?.plan_json?.declined_ids ?? [];
}

/** F27-I15 Contract F: a cleanup set is one `pause` item per ad of the queue row's `cleanup.ads`, marked
 * `source: "cleanup"` (the backend's `_matching_cleanup_set` only matches on `plan_json.source`). F28-I15:
 * `supersedesId` replaces an outdated draft with the latest proposal. F29-I14: `declinedIds` are the proposed ads the
 * user unticked — they are left out of the items and sent as `declined_ids` (Contract B: remembered at approval). */
export function createCleanupSet(
  brandId: string, campaignId: string, cleanup: QueueCleanup, operationId: string, timezone: string, supersedesId?: string,
  declinedIds: string[] = [],
): Promise<ChangeSet> {
  const declined = new Set(declinedIds);
  const kept = cleanup.ads.filter((ad) => declined.has(ad.entity_id)).map((ad) => ad.entity_id);
  return createChangeSet(brandId, campaignId, {
    operation_id: operationId,
    title: cleanupTitle(cleanup.campaign_name),
    month: currentBudgetMonth(timezone),
    items: buildCleanupDraftItems(cleanup.ads.filter((ad) => !declined.has(ad.entity_id))),
    ...(supersedesId ? { supersedes_id: supersedesId } : {}),
    source: "cleanup",
    ...(kept.length ? { declined_ids: kept } : {}),
  });
}

/** F29-I14: the user's pick on a cleanup proposal (prototype v10 `q.skip`): every proposed ad is ticked; the ones the
 * user unticks stay. The unticked ids live in the URL (`?keep=`), so the proposal step and its confirm step (the same
 * propose URL with `?step=confirm`) and a reload agree. Unknown ids (no longer proposed) are ignored. `changed` = the
 * user unticked at least one ad. */
export const KEEP_PARAM = "keep";
export interface CleanupPick {
  ticked: QueueCleanupAd[]; declined: string[]; changed: boolean;
  isTicked: (entityId: string) => boolean; toggle: (entityId: string, on: boolean) => void; reset: () => void;
  /** The search string of `step` (none = the proposal step) with the current pick (`?step=confirm&keep=…`); "" when
   * there is nothing to carry. */
  href: (step?: string) => string;
}
export function useCleanupPick(cleanup: QueueCleanup | null | undefined): CleanupPick {
  const [params, setParams] = useSearchParams();
  const proposed = cleanup?.ads ?? [];
  const raw = new Set((params.get(KEEP_PARAM) ?? "").split(",").filter(Boolean));
  const declined = proposed.filter((ad) => raw.has(ad.entity_id)).map((ad) => ad.entity_id);
  const declinedSet = new Set(declined);
  const write = (next: string[]) => setParams((prev) => {
    const out = new URLSearchParams(prev);
    if (next.length) out.set(KEEP_PARAM, next.join(",")); else out.delete(KEEP_PARAM);
    return out;
  }, { replace: true });
  return {
    ticked: proposed.filter((ad) => !declinedSet.has(ad.entity_id)),
    declined,
    changed: declined.length > 0,
    isTicked: (id) => !declinedSet.has(id),
    toggle: (id, on) => write(on ? declined.filter((x) => x !== id) : [...declined, id]),
    reset: () => write([]),
    href: (step) => {
      const out = new URLSearchParams(step ? { step } : {});
      if (declined.length) out.set(KEEP_PARAM, declined.join(","));
      const search = out.toString();
      return search ? `?${search}` : "";
    },
  };
}

/** F29-I14: whether a cleanup set closes exactly the ads `ticked` closes (order is not a difference). */
export function samePick(set: ChangeSet, ticked: QueueCleanupAd[]): boolean {
  const ids = new Set(set.items.map((i) => i.target_id));
  return ids.size === ticked.length && ticked.every((ad) => ids.has(ad.entity_id));
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
  const { timezone } = useOrgClock();
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
      // The user's own unticks that the latest proposal still proposes carry over (Contract B).
      const rebuilt = await createCleanupSet(brandId, campaignId, cleanup, operationId, timezone, changeSet.id, declinedIdsOf(changeSet));
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
