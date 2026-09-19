import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";
import type { NativeEntity } from "./adsExternalApi";

export interface MonthlyBudget {
  month: string; currency: string | null; amount: number | null; revision: number;
  known_spend: number | null; ongoing_estimate: number | null; reserved_increases: number;
  available: number | null; uncertainties: string[]; can_increase: boolean;
  period_end: string; confirmed_at: string | null; notice: string;
}
export type ChangeKind = "copy" | "budget" | "pause";
export type SettingValues = { body?: string; title?: string; daily_amount?: number; status?: string };
export interface ChangeInput { kind: ChangeKind; target_id: string; after: SettingValues; reason: string }
export interface ChangeItem extends Omit<ChangeInput, "kind"> {
  kind: ChangeKind | "new_ad" | "launch";
  handoff_snapshot?: { filename: string; revision: number; copy: Record<string, string>; destination: { native_id: string; name?: string }; budget_owner: { budget_amount: number; currency: string } };
  id: string; target: Pick<NativeEntity, "id" | "name" | "platform" | "source_account" | "native_kind" | "native_id">;
  before: SettingValues;
  verification_state: "pending" | "reported" | "confirmed" | "deviated" | "unknown" | "stale";
  evidence_json: Record<string, unknown>; reported_at: string | null;
  first_observed_at: string | null; verified_at: string | null; stale_reason?: string | null;
}
export interface ChangeSet {
  id: string; campaign_id: string; title: string; month: string; operation_id: string; content_hash: string;
  status: "draft" | "approved" | "rejected" | "deferred" | "superseded";
  reason: string | null; revisit_at: string | null; approval_id: string | null;
  created_at: string; approved_at: string | null; items: ChangeItem[];
  can_revise?: boolean;
  review_id?: string | null; recommendation_id?: string | null;
  material_task_id?: string | null; material_revision?: number | null;
}
export interface ChangeDraft { operation_id: string; title: string; month: string; items: ChangeInput[]; supersedes_id?: string; review_id?: string; recommendation_id?: string; material_task_id?: string; material_revision?: number }
export interface ChangeControlData { targets: NativeEntity[]; change_sets: ChangeSet[] }
export interface ChangeControlSummary {
  pending_count: number;
  items: { id: string; campaign_id: string; campaign_name: string; title: string; status: string; pending_items: number; unknown_items: number }[];
  truncated: boolean;
}
const brandPath = (brand: string) => `${BASE}/brands/${encodeURIComponent(brand)}`;
const campaignPath = (brand: string, campaign: string) => `${brandPath(brand)}/campaigns/${encodeURIComponent(campaign)}`;
export class ChangeRequestRejected extends Error {}
async function json<T>(path: string, method: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  try {
    const response = await apiFetch(path, { method, signal, ...(body === undefined ? {} : {
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }) });
    try { return await parseJsonOrThrow(response, "目前無法完成，已保存的內容會保留。請稍後重試。"); }
    catch (error) {
      if (response.status >= 400 && response.status < 500) throw new ChangeRequestRejected(error instanceof Error ? error.message : "內容未保存，請修正後再試。");
      throw error;
    }
  } catch (error) {
    if (error instanceof TypeError) throw new Error("未收到伺服器回應，結果尚未確認。請沿用原操作重試，不要重做平台操作。");
    throw error;
  }
}
export async function getMonthlyBudget(brand: string, month: string, signal?: AbortSignal) {
  return (await json<{ budget: MonthlyBudget }>(`${brandPath(brand)}/monthly-budget?month=${encodeURIComponent(month)}`, "GET", undefined, signal)).budget;
}
export async function saveMonthlyBudget(brand: string, body: { month: string; currency: string; amount: number; expected_revision: number }, signal?: AbortSignal) {
  return (await json<{ budget: MonthlyBudget }>(`${brandPath(brand)}/monthly-budget`, "PUT", body, signal)).budget;
}
export function getChangeControl(brand: string, campaign: string, signal?: AbortSignal) {
  return json<ChangeControlData>(`${campaignPath(brand, campaign)}/change-control`, "GET", undefined, signal);
}
export function getChangeControlSummary(brand: string, signal?: AbortSignal) {
  return json<ChangeControlSummary>(`${brandPath(brand)}/change-control-summary`, "GET", undefined, signal);
}
export async function createChangeSet(brand: string, campaign: string, body: ChangeDraft, signal?: AbortSignal) {
  return (await json<{ change_set: ChangeSet }>(`${campaignPath(brand, campaign)}/change-sets`, "POST", body, signal)).change_set;
}
export async function approveChangeSet(brand: string, campaign: string, set: ChangeSet, signal?: AbortSignal) {
  return (await json<{ change_set: ChangeSet }>(`${campaignPath(brand, campaign)}/change-sets/${encodeURIComponent(set.id)}/approve`, "POST", { content_hash: set.content_hash }, signal)).change_set;
}
export async function decideChangeSet(brand: string, campaign: string, id: string, body: { decision: "rejected" | "deferred"; reason: string; revisit_at?: string }, signal?: AbortSignal) {
  return (await json<{ change_set: ChangeSet }>(`${campaignPath(brand, campaign)}/change-sets/${encodeURIComponent(id)}/decision`, "POST", body, signal)).change_set;
}
export async function actOnChangeItem(brand: string, campaign: string, id: string, itemId: string, action: "report" | "check", signal?: AbortSignal) {
  return (await json<{ change_set: ChangeSet }>(`${campaignPath(brand, campaign)}/change-sets/${encodeURIComponent(id)}/items/${encodeURIComponent(itemId)}/${action}`, "POST", {}, signal)).change_set;
}
