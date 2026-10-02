/** F23-I02: shared, presentation-free logic for the v7 six-step "review" flow (variant of the
 * three-step "light" flow, `docs/design/ads/prototype-v7-ads-center.html` `review()`/`sheet()`/
 * `prepare()`/`copy()`). Kept separate from `ReviewEvidencePage.tsx` so I03 (選方向) and I04
 * (改文案) reuse the same path/accessor helpers instead of re-deriving them — same pattern as
 * `flow/changeFlow.ts` for the light flow. */
import type { QueueItem, QueuePayload, TriageHistoryEntry } from "@/lib/adsTriageApi";
import type { CommerceEvidence, Recommendation, ReviewPeriod, ReviewResultView } from "@/lib/adsReviewApi";
import { decisionPosition } from "../home/status";

export type ReviewStepName = "review" | "prepare" | "copy";

const brandPath = (brandId: string) => `/brands/${brandId}`;
const campaignPath = (brandId: string, campaignId: string) => `${brandPath(brandId)}/ads/campaigns/${campaignId}`;

/** `review/:entityId` — entry for a `worse` row with no review round yet (feature Decisions
 * "Agent choice — routes"). */
export function reviewEntryPath(brandId: string, campaignId: string, entityId: string): string {
  return `${campaignPath(brandId, campaignId)}/review/${entityId}`;
}

/** `reviews/:reviewId[/step]` — the canonical route once a review round exists. Mirrors
 * `home/status.ts::reviewRoundPath` exactly (routes must match — that module isn't touched here,
 * this is a parallel copy for the same reason `QueueRow.tsx` keeps its own money formatters). */
export function reviewRoundPath(
  brandId: string, campaignId: string, reviewId: string, step?: "prepare" | "copy",
): string {
  return `${campaignPath(brandId, campaignId)}/reviews/${reviewId}${step ? `/${step}` : ""}`;
}

/** `reviews/:reviewId/material?mode=…` — F27-I12 Prepare page's 換一張圖／用現成素材 destination
 * (the page itself is built by F27-I14; this issue only needs the href). `mode` mirrors
 * `adsMaterialApi.ts::MaterialMode`, narrowed to the two Prepare page ever links to. */
export function reviewMaterialPath(
  brandId: string, campaignId: string, reviewId: string, mode: "workbench_image" | "existing",
): string {
  return `${reviewRoundPath(brandId, campaignId, reviewId)}/material?mode=${mode}`;
}

/** Which queue row a review round's entity belongs to (mirrors `flow/changeFlow.ts::findFlowTriageItem`). */
export function findReviewTriageItem(queue: QueuePayload | null, entityId: string | undefined): QueueItem | null {
  if (!queue || !entityId) return null;
  return queue.items.find((i) => i.triage.entity_id === entityId) ?? null;
}

/** F47-I07: 「第 N 件／共 M 件」 counts the open home decisions — the same owner as the home and the top bar. */
export function reviewPosition(queue: QueuePayload | null, item: QueueItem | null): { pos: number; total: number } | null {
  return decisionPosition(queue, item);
}

/** F47-I07: the one 「M/D 再看」 label (`home/status.ts`), re-exported for the review pages. */
export { formatRevisitLabel } from "../home/status";

/** `M/D` for a plain `YYYY-MM-DD` window date (evidence legend) — no timezone conversion, these
 * are report dates, not instants. */
export function formatWindowDate(date: string): string {
  const [, m, d] = date.split("-");
  return `${Number(m)}/${Number(d)}`;
}

/** This ad's own known spend, summed across every `attribution_key` subgroup of the `ad` scope —
 * mirrors `app/ads/triage.py::_ad_spend` exactly (issue Done #3): any unknown subgroup, or more
 * than one currency among them, makes the whole window's spend unknown. Never an arbitrary pick
 * (feature Decisions "NOT `series[0]`, which `ReviewEvidence.tsx:32` uses"). */
export function adSpend(period: ReviewPeriod): number | null {
  const entries = period.series.filter((s) => s.metric_scope === "ad");
  if (entries.length === 0 || entries.some((s) => s.metrics.spend === null)) return null;
  if (new Set(entries.map((s) => s.currency)).size > 1) return null;
  return entries.reduce((sum, s) => sum + (s.metrics.spend as number), 0);
}

/** This ad's own result view — mirrors `app/ads/triage.py::_ad_window`: more than one `ad`-scope
 * `result_views` entry has no single unambiguous view, treated as unknown, never an arbitrary
 * pick. `null` when there is exactly zero or more than one. */
export function adResultView(period: ReviewPeriod): ReviewResultView | null {
  const views = (period.result_views ?? []).filter((v) => v.metric_scope === "ad");
  return views.length === 1 ? views[0] : null;
}

/** Title by `recommendation` (feature Decisions "看證據 cards"). */
export const RECOMMENDATION_TITLE: Record<Recommendation["recommendation"], string> = {
  adjust: "保留圖片，換文案試試",
  observe: "先觀察一段時間",
  retain: "維持現狀",
  new_test: "做新的素材測試",
};

/** `evidence_json.commerce.*.order_summary.coverage` is always the literal `"unknown"`
 * (`app/orders/commerce_evidence.py:88`) — never a condition. The 「報表期間待確認」 chip instead
 * reads the actual unknown counts (feature Decisions "看證據 cards"). */
export function commerceCoverageWarn(summary: CommerceEvidence["order_summary"]): boolean {
  return (summary.unknown_amount_count ?? 0) > 0 || summary.unknown_payment_count > 0;
}

export function formatTargetAmount(value: number | null): string {
  if (value === null) return "尚未設定";
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

/** F27-I11 non-sales 「這條素材的紀錄」 card: whether this campaign is in the sales objective
 * family — `TriageTargetView.result_kind` is `targets.resolve()`'s own output (`triage.py:58`),
 * already carrying the internal-campaign fallback (`docs/architecture/ads.md` "result_kind 的
 * 來源"), never a second, frontend-invented objective vocabulary. `null`/missing (no matched
 * queue item) reads as non-sales — the honest unknown, not an invented shop attribution. */
export function isSalesResultKind(resultKind: string | null | undefined): boolean {
  return resultKind === "purchase";
}

/** F27-I11 Contract A: `TriageHistoryEntry.kind` label — past tense, matches the prototype's own
 * 「9/06 改過文案」 wording. `budget` never actually appears here (correction 11: budget items
 * target owners, not an ad), kept only so the map is total over the type. */
export const HISTORY_KIND_LABEL: Record<TriageHistoryEntry["kind"], string> = {
  copy: "改過文案", new_ad: "換過素材", budget: "調過預算", pause: "暫停過廣告",
};

/** `M/D` for a history entry's `approved_at` (a timezone-carrying ISO instant, browser-local —
 * same convention as `formatRevisitLabel`). */
export function formatEntryDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

/** `cost_before`/`cost_after` printed value — `null` (fewer than 7 known days, contract A) reads
 * as the same 「待確認」 unknown label `EvidenceRow` uses, never a guessed number. */
export function formatCostLabel(value: number | null): string {
  return value === null ? "待確認" : value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}
