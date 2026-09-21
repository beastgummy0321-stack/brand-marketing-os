/** F22-I02: shared, presentation-free logic for the v7 three-step "light" repair flow
 * (`docs/design/ads/prototype-v7-ads-center.html` `confirmPage()`/`handoff()`/`verify()`).
 * Kept separate from `ConfirmPage.tsx` so I03 (到平台完成) and I04 (核對結果) reuse the same
 * step rule and paths instead of re-deriving them. */
import type { ChangeInput, ChangeItem, ChangeKind, ChangeSet } from "@/lib/adsChangeApi";

export type FlowStepName = "confirm" | "handoff" | "verify";

export interface FlowStep {
  step: FlowStepName;
  /** True on the confirm page when the set is terminal and not actionable (rejected / deferred /
   * superseded) — feature Decisions "Step from a change set". */
  closed: boolean;
}

/** Which of the three v7 screens a change set currently belongs on, mirroring the prototype's
 * `state(q)` for the `light` flow (the six-step `review` flow is a different feature). Approved
 * sets split on the single item's `verification_state`/`reported_at` per feature Decisions —
 * multi-item sets are handled by the caller (they link out instead of rendering). */
export function stepFromChangeSet(set: ChangeSet): FlowStep {
  if (set.status === "draft") return { step: "confirm", closed: false };
  if (set.status === "rejected" || set.status === "deferred" || set.status === "superseded") {
    return { step: "confirm", closed: true };
  }
  const item = set.items[0];
  if (item && item.verification_state === "pending" && item.reported_at === null) {
    return { step: "handoff", closed: false };
  }
  return { step: "verify", closed: false };
}

const brandPath = (brandId: string) => `/brands/${encodeURIComponent(brandId)}`;
const campaignPath = (brandId: string, campaignId: string) =>
  `${brandPath(brandId)}/ads/campaigns/${encodeURIComponent(campaignId)}`;

/** `changes/:setId/confirm|handoff|verify` — the canonical route once a change set exists
 * (feature Decisions "Agent choice — routes"). */
export function changeStepPath(brandId: string, campaignId: string, setId: string, step: FlowStepName): string {
  return `${campaignPath(brandId, campaignId)}/changes/${encodeURIComponent(setId)}/${step}`;
}

/** `propose/pause/:entityId` — the confirm page for a proposal that has no change set yet. */
export function proposePausePath(brandId: string, campaignId: string, entityId: string): string {
  return `${campaignPath(brandId, campaignId)}/propose/pause/${encodeURIComponent(entityId)}`;
}

/** Multi-item sets, and any change-item kind this flow doesn't render, fall back to the existing
 * workspace change list instead of being re-interpreted (feature Decisions "Multi-item sets"). */
export function campaignChangesPath(brandId: string, campaignId: string): string {
  return `${campaignPath(brandId, campaignId)}?tab=changes`;
}

/** Feature Decisions "Agent choice — the draft is created lazily": the one fixed reason this
 * batch's single kind (`pause`) proposes. */
export const PAUSE_REASON = "花費超過停損線（目標 × 3）仍未達成目標";

export function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

/** `title = 暫停「<ad name, cut to 60 chars; null → 未命名廣告>」`. */
export function pauseTitle(adName: string | null): string {
  return `暫停「${truncate(adName ?? "未命名廣告", 60)}」`;
}

export function buildPauseDraftItem(entityId: string): ChangeInput {
  return { kind: "pause", target_id: entityId, after: { status: "PAUSED" }, reason: PAUSE_REASON };
}

/** Rebuilding a draft after approve answers a conflict (feature Decisions: "the page rebuilds the
 * draft once with a NEW operation_id and supersedes_id = the old set") resends the same items. */
export function toChangeInput(item: ChangeItem): ChangeInput {
  return { kind: item.kind as ChangeKind, target_id: item.target_id, after: item.after, reason: item.reason };
}

/** Money formatting for the pause card's meter caption — same honest-null convention as
 * `home/QueueRow.tsx` (spend/counts are measured values missing "累積中"; target/stop-loss lines
 * are configuration values missing "尚未設定"). Not imported from there: `QueueRow.tsx` keeps its
 * own copy as its own module-private helper (feature Decisions). */
export function formatAmount(value: number | null): string {
  if (value === null) return "累積中";
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}
export function formatTargetAmount(value: number | null): string {
  if (value === null) return "尚未設定";
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}
