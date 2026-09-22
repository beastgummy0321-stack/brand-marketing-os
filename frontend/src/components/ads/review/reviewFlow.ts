/** F23-I02: shared, presentation-free logic for the v7 six-step "review" flow (variant of the
 * three-step "light" flow, `docs/design/ads/prototype-v7-ads-center.html` `review()`/`sheet()`/
 * `prepare()`/`copy()`). Kept separate from `ReviewEvidencePage.tsx` so I03 (選方向) and I04
 * (改文案) reuse the same path/accessor helpers instead of re-deriving them — same pattern as
 * `flow/changeFlow.ts` for the light flow. */
import type { QueueItem, QueuePayload } from "@/lib/adsTriageApi";
import type { CommerceEvidence, Recommendation, ReviewPeriod, ReviewResultView } from "@/lib/adsReviewApi";

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

/** Which queue row a review round's entity belongs to (mirrors `flow/changeFlow.ts::findFlowTriageItem`). */
export function findReviewTriageItem(queue: QueuePayload | null, entityId: string | undefined): QueueItem | null {
  if (!queue || !entityId) return null;
  return queue.items.find((i) => i.triage.entity_id === entityId) ?? null;
}

export function reviewPosition(queue: QueuePayload | null, item: QueueItem | null): { pos: number; total: number } | null {
  if (!queue || !item) return null;
  return { pos: queue.items.indexOf(item) + 1, total: queue.items.length };
}

/** `revisit_at` is always a timezone-carrying ISO instant (feature Decisions) — printed in the
 * browser's local timezone as `M/D`, matching `home/status.ts::formatRevisitLabel`. */
export function formatRevisitLabel(revisitAt: string): string {
  const d = new Date(revisitAt);
  return `${d.getMonth() + 1}/${d.getDate()} 重看`;
}

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
