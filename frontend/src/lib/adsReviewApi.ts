import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";
import type { NativeEntity } from "./adsExternalApi";

export type ReviewStatus = "waiting" | "queued" | "running" | "ready" | "completed" | "deferred" | "unjudgeable" | "failed" | "unknown";
export interface ReviewSeries {
  metric_scope: string; attribution_key: string; currency: string | null; source: string;
  row_count: number; days_present: number; result_kind?: string | null;
  metrics: Record<"spend" | "impressions" | "clicks" | "purchases" | "revenue" | "ctr" | "cpc" | "cpa" | "roas", number | null>
    & Partial<Record<"result_count" | "cost_per_result", number | null>>;
  known_counts: Record<string, number>;
}
export interface ReviewPeriod {
  row_count: number; days_present: number; days_expected: number; missing_days: number; series: ReviewSeries[];
}
export interface CommerceEvidence {
  scope: string; start: string; end: string;
  order_summary: {
    count: number; non_void_count: number; order_net_amount: number | null; paid_net_amount: number | null;
    unknown_payment_count: number; currency: string | null; currency_basis: string; coverage: string;
    latest_import_at: string | null; void_count?: number; unpaid_count?: number; refunded_count?: number;
    unknown_amount_count?: number; known_net_count?: number; paid_count?: number; known_paid_net_count?: number;
  };
  channels: { channel: string; currency: string | null; amount: number | null; row_count: number; source_type: string; source?: string }[];
  limitations: string[]; attribution: string;
}
export interface Recommendation {
  id: string; target_id: string; recommendation: "retain" | "observe" | "adjust" | "new_test";
  evidence_refs: string[]; hypothesis: string; risks: string[]; next_step: string;
  suggested_copy?: { title?: string; body?: string };
}
export interface ReviewRound {
  id: string; entity_id: string; window_start: string; window_end: string; previous_id: string | null;
  status: ReviewStatus; evidence_hash: string; llm_task_id: string | null;
  error: string | null; decision: string | null; reason: string | null; revisit_at: string | null;
  created_at: string;
  result_json: { recommendations?: Recommendation[]; limitations?: string[] };
  evidence_json: {
    target: Pick<NativeEntity, "id" | "name" | "platform" | "source_account" | "native_id">;
    window: { start: string; end: string; previous_start: string; previous_end: string; timezone: string | null };
    current: ReviewPeriod; previous: ReviewPeriod;
    commerce: { current: CommerceEvidence; previous: CommerceEvidence };
    conditions: { history: string; creative_snapshot: { kind?: string; copy_fields?: Record<string, string | null> }; binding_count: number };
    previous_review: { id: string; result_json: ReviewRound["result_json"]; decision: string | null; reason: string | null; actions: Record<string, unknown>[] } | null;
    source_review?: { relation: "new_test"; review_id: string; source_entity_id: string; recommendation_id: string; evidence_hash: string; handoff_item_id: string; change_set_id: string; action_id: string; window: { start: string; end: string }; recommendation: Pick<Recommendation, "recommendation" | "hypothesis" | "risks" | "next_step" | "evidence_refs">; current: ReviewPeriod; material: Record<string, unknown>; readback: { state: string; reported_at: string | null; first_observed_at: string | null; entity_exists: boolean; setting_matches: boolean | null; material_evidence: string; delivery_confirmed: false }; limitations: string[] } | null;
    limitations: string[]; waiting_reasons: string[]; sources: { id: string; text: string }[];
  };
}
export interface ReviewsData { reviews: ReviewRound[]; targets: NativeEntity[]; targets_truncated: boolean; reviews_truncated: boolean }
const route = (brand: string, campaign: string) => `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}/reviews`;
async function request<T>(path: string, signal?: AbortSignal, body?: unknown): Promise<T> {
  const response = await apiFetch(path, { signal, ...(body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
  return parseJsonOrThrow<T>(response, "目前無法讀取或保存本次檢討，請稍後重新讀取。已保存的內容會保留。");
}
export const getReviews = (brand: string, campaign: string, signal?: AbortSignal) => request<ReviewsData>(route(brand, campaign), signal);
export async function getReview(brand: string, campaign: string, id: string, signal?: AbortSignal) {
  return (await request<{ review: ReviewRound }>(`${route(brand, campaign)}/${encodeURIComponent(id)}`, signal)).review;
}
export async function createReview(brand: string, campaign: string, value: { entity_id: string; start: string; end: string; previous_id?: string }, signal?: AbortSignal) {
  return (await request<{ review: ReviewRound }>(route(brand, campaign), signal, value)).review;
}
export async function decideReview(brand: string, campaign: string, id: string, value: { decision: "completed" | "deferred" | "unjudgeable"; reason: string; revisit_at?: string }, signal?: AbortSignal) {
  return (await request<{ review: ReviewRound }>(`${route(brand, campaign)}/${encodeURIComponent(id)}/decision`, signal, value)).review;
}
