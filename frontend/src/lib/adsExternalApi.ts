import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";

export interface SourceAccount { platform: string; label: string; account_id: string; name?: string }
export interface NativeEntity {
  id: string; platform: string; source_account: string; native_kind: string; native_id: string;
  native_label: string | null; name: string | null; parent_native_id: string | null;
  native_status: string | null; start_date: string | null; end_date: string | null;
  budget_amount: number | null; budget_type: string; budget_raw: Record<string, unknown>;
  currency: string | null; last_success_at: string | null; sync_error: string | null;
  creative: { kind?: string; fields?: Record<string, unknown> };
}
export interface NativeObservation {
  id: string; entity_id: string; day: string; metric_scope: string; attribution_key: string;
  currency: string | null; spend: number | null; impressions: number | null; clicks: number | null;
  purchases: number | null; revenue: number | null; availability: Record<string, string>;
}
export interface SyncJob { id: string; status: string; last_success_at: string | null; error?: string | null }
export interface ExistingPage {
  items: { id: string; native_kind: string; native_id: string; snapshot: NativeEntity }[];
  sources: SourceAccount[]; platform?: string; source_account?: string;
  next_cursor: string | null; job: SyncJob | null;
}
export interface ExternalView {
  entities: NativeEntity[]; observations: NativeObservation[];
  next_entity_cursor: string | null; next_observation_cursor: string | null;
  window: { start: string; end: string };
  connections: { platform: string; source_account: string; state: string }[];
  sync: Record<string, { status?: string; last_success_at?: string; error?: string; error_code?: string }>;
  coverage: Record<string, unknown>;
}
const brandPath = (brand: string) => `${BASE}/brands/${encodeURIComponent(brand)}`;
export function query(values: Record<string, string | undefined | null>): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => { if (value) params.set(key, value); });
  return params.toString();
}
export async function existingCampaigns(brand: string, values: Record<string, string | undefined> = {}, signal?: AbortSignal): Promise<ExistingPage> {
  return parseJsonOrThrow(await apiFetch(`${brandPath(brand)}/existing-campaigns?${query(values)}`, { signal }), "讀取既有活動失敗。");
}
export async function importExisting(brand: string, source: { platform: string; source_account: string; native_kind: string; native_id: string }): Promise<{ campaign: { id: string } }> {
  return parseJsonOrThrow(await apiFetch(`${brandPath(brand)}/imports`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(source) }), "納入活動失敗。");
}
export async function refreshExisting(brand: string, platform: string, source_account: string): Promise<{ job: SyncJob }> {
  return parseJsonOrThrow(await apiFetch(`${brandPath(brand)}/existing-campaigns/refresh`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ platform, source_account }) }), "更新清單失敗。");
}
export async function externalView(brand: string, campaign: string, values: Record<string, string | undefined> = {}, signal?: AbortSignal): Promise<ExternalView> {
  return parseJsonOrThrow(await apiFetch(`${brandPath(brand)}/campaigns/${encodeURIComponent(campaign)}/external?${query(values)}`, { signal }), "讀取原始資料失敗。");
}
export async function syncCampaign(brand: string, campaign: string): Promise<{ job: SyncJob }> {
  return parseJsonOrThrow(await apiFetch(`${brandPath(brand)}/campaigns/${encodeURIComponent(campaign)}/sync`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }), "同步失敗。");
}
export async function syncJob(brand: string, id: string, signal?: AbortSignal): Promise<{ job: SyncJob; connected: boolean }> {
  return parseJsonOrThrow(await apiFetch(`${brandPath(brand)}/sync-jobs/${encodeURIComponent(id)}`, { signal }), "讀取同步狀態失敗。");
}
