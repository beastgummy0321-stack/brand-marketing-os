import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";

export interface ReviewMonitor {
  id: string; entity_id: string; entity_name: string | null; revision: number; enabled: boolean;
  window_days: number; cadence_days: number;
  state: "scheduled" | "waiting" | "queued" | "running" | "ready" | "needs_attention" | "paused";
  next_check_at: string | null; last_checked_at: string | null; reason: string | null;
  review_id: string | null;
  window: { start: string; end: string; previous_id: string | null } | null;
}
export interface RuntimeData {
  monitors: ReviewMonitor[];
  sources: { platform: string; source_account: string; status: string; last_attempt_at: string | null; last_success_at: string | null; coverage: { start: string; end: string } | null; error: string | null }[];
  health: { code: string; severity: "info" | "warning" | "unknown"; message: string; observed_at: string | null }[];
  last_checked_at: string | null; last_bootstrap_at: string | null; notice: string;
  budget: { month: string; currency: string | null; amount: number | null; known_spend: number | null; available: number | null; uncertainties: string[]; can_increase: boolean } | null;
}
const route = (brand: string, campaign: string) => `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}`;
export async function getRuntime(brand: string, campaign: string, signal?: AbortSignal) {
  return parseJsonOrThrow<RuntimeData>(await apiFetch(`${route(brand, campaign)}/runtime`, { signal }), "暫時讀不到追蹤進度；已保存的檢討與操作仍保留，請重新讀取。");
}
export async function saveMonitor(brand: string, campaign: string, entity: string, value: { expected_revision: number; enabled: boolean; window_days: number; cadence_days: number; reset_window: boolean }, signal?: AbortSignal) {
  return parseJsonOrThrow<{ monitor: ReviewMonitor }>(await apiFetch(`${route(brand, campaign)}/review-monitors/${encodeURIComponent(entity)}`, {
    method: "PUT", signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify(value),
  }), "設定尚未確認保存，請先重新讀取；不會操作平台投放。");
}
