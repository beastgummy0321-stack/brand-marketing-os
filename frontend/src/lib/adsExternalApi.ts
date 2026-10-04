import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";

export interface ExternalCampaignFields {
  origin?: "internal" | "imported";
  capabilities?: { allowed: string[]; unavailable: Record<string, string> };
  external_view?: ExternalView | null;
}

export interface SourceAccount { platform: string; label: string; account_id: string; name?: string }
export interface NativeEntity {
  id: string; platform: string; source_account: string; native_kind: string; native_id: string;
  native_label: string | null; name: string | null; parent_native_id: string | null;
  native_status: string | null; start_date: string | null; end_date: string | null;
  budget_amount: number | null; budget_type: string; budget_raw: Record<string, unknown>;
  currency: string | null; last_success_at: string | null; sync_error: string | null;
  creative: { kind?: string; fields?: Record<string, unknown> };
  objective?: string | null;
  parent_native_kind?: string | null;
  availability?: Record<string, string>;
  /** F49 Contract L: the served word for `native_status` (`external_view` entities) — print it, never the code. */
  delivery_label?: string;
}
export interface NativeObservation {
  id: string; entity_id: string; day: string; metric_scope: string; attribution_key: string;
  currency: string | null; spend: number | null; impressions: number | null; clicks: number | null;
  purchases: number | null; revenue: number | null; availability: Record<string, string>;
  result_kind?: string | null; result_count?: number | null;
  result_action?: string | null; result_attribution?: string | null;
}
export interface SyncJob { id: string; status: string; last_success_at: string | null; error?: string | null; platform?: string; source_account?: string }
/** F49 Contract O: a platform read's one outcome (`app/ads/external_sync.py` `outcome`). `code` names why (a reason
 * code, `no_rows`, `not_read`); `text` is the sentence to print. Read it through `useSyncOutcome`. */
export interface SyncOutcome {
  state: "running" | "failed" | "partial" | "empty" | "found";
  code: string | null;
  text: string;
}
/** `GET …/campaigns/{c}/sync-outcome`: the worst outcome over the jobs covering the campaign. */
export interface CampaignSyncOutcome extends SyncOutcome {
  job_ids: string[];
  last_success_at: string | null;
}
export interface ExistingPage {
  /** `campaign_id`: the workspace campaign this platform campaign is
   * already in, so the join dialog marks it 「已在工作區」 instead of offering to add it again. */
  items: {
    id: string; native_kind: string; native_id: string; snapshot: NativeEntity; campaign_id: string | null;
    /** F49 Contract L: the served word for `snapshot.native_status`. */
    delivery_label?: string;
  }[];
  sources: SourceAccount[]; platform?: string; source_account?: string;
  next_cursor: string | null; job: SyncJob | null;
  /** F49 Contract O: the account read's outcome; null when the brand has no bound account. The listing is read-only —
   * an unreadable account still lists its cached rows, with `job: null` and a failed outcome. */
  outcome?: SyncOutcome | null;
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
/** `range` (F47 Contract H, the connections page's `reread`): read these days again instead of the default window. */
export async function refreshExisting(brand: string, platform: string, source_account: string, range?: { start: string; end: string }): Promise<{ job: SyncJob }> {
  return parseJsonOrThrow(await apiFetch(`${brandPath(brand)}/existing-campaigns/refresh`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ platform, source_account, ...range }) }), "更新清單失敗。");
}
export async function externalView(brand: string, campaign: string, values: Record<string, string | undefined> = {}, signal?: AbortSignal): Promise<ExternalView> {
  return parseJsonOrThrow(await apiFetch(`${brandPath(brand)}/campaigns/${encodeURIComponent(campaign)}/external?${query(values)}`, { signal }), "讀取原始資料失敗。");
}

/** Both cursors are independent. Never publish a partial page as campaign totals. */
export async function completeExternalView(brand: string, campaign: string, signal?: AbortSignal): Promise<ExternalView> {
  const first = await externalView(brand, campaign, {}, signal);
  const result: ExternalView = { ...first, entities: [...first.entities], observations: [...first.observations], connections: [...first.connections] };
  for (const kind of ["entity", "observation"] as const) {
    const seen = new Set<string>();
    let cursor = kind === "entity" ? first.next_entity_cursor : first.next_observation_cursor;
    while (cursor) {
      if (seen.has(cursor)) throw new Error("平台資料分頁重複，請重新載入。");
      seen.add(cursor);
      const page = await externalView(brand, campaign, { start: first.window.start, end: first.window.end, [`${kind}_cursor`]: cursor }, signal);
      if (kind === "entity") {
        result.entities.push(...page.entities);
        result.connections.push(...page.connections);
        cursor = page.next_entity_cursor;
      } else {
        result.observations.push(...page.observations);
        cursor = page.next_observation_cursor;
      }
    }
  }
  result.entities = [...new Map(result.entities.map(row => [row.id, row])).values()];
  result.observations = [...new Map(result.observations.map(row => [row.id, row])).values()];
  result.connections = [...new Map(result.connections.map(row => [`${row.platform}:${row.source_account}`, row])).values()];
  result.next_entity_cursor = null;
  result.next_observation_cursor = null;
  return result;
}
/** `jobs`: every job the re-read requested (each account it covers); `job` is the first. */
export async function syncCampaign(brand: string, campaign: string): Promise<{ job: SyncJob; jobs?: SyncJob[] }> {
  return parseJsonOrThrow(await apiFetch(`${brandPath(brand)}/campaigns/${encodeURIComponent(campaign)}/sync`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }), "同步失敗。");
}
/** `campaignId` scopes `outcome` to that campaign's tasks (plus the account's own). */
export async function syncJob(brand: string, id: string, signal?: AbortSignal, campaignId?: string): Promise<{ job: SyncJob; connected: boolean; outcome?: SyncOutcome }> {
  const scope = query({ campaign_id: campaignId });
  return parseJsonOrThrow(await apiFetch(`${brandPath(brand)}/sync-jobs/${encodeURIComponent(id)}${scope ? `?${scope}` : ""}`, { signal }), "讀取同步狀態失敗。");
}
export async function syncOutcome(brand: string, campaign: string, signal?: AbortSignal): Promise<CampaignSyncOutcome> {
  return parseJsonOrThrow(await apiFetch(`${brandPath(brand)}/campaigns/${encodeURIComponent(campaign)}/sync-outcome`, { signal }), "讀取同步結果失敗。");
}
