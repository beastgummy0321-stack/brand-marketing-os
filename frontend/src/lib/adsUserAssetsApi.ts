import { apiFetch, errorMessageFrom } from "./http";
import { BASE } from "./adsApi";
import type { NativeObservation } from "./adsExternalApi";

export type CopyFields = Record<string, string>;
export interface UserAsset { id: string; filename: string; mime_type: string; status: string; error: string | null; duration?: number | null; preview_duration?: number | null }
export interface AssetUpload { id: string; batch_id: string; filename: string; expected_size: number; status: string; error: string | null; asset_id: string | null; copy_fields: CopyFields; deduplicated?: boolean; storage_key?: string | null; sha256?: string | null }
export interface UploadBatch { id: string; uploads: AssetUpload[] }
export interface AssetLibrary { assets: UserAsset[]; uploads: AssetUpload[]; next_cursor: string | null; next_upload_cursor: string | null }
export interface Placement {
  id: string; revision: number; is_current: boolean; asset_id: string; filename: string; mime_type: string;
  asset_status: string; asset_error: string | null; copy_fields: CopyFields; suggested_copy: CopyFields;
  purpose: string | null; destination_entity_id: string | null; start_date: string | null; end_date: string | null;
  status: string; pending_reason: string; pending_reasons?: string[]; required: boolean; confirmed_at: string | null;
  suggestion_batch_id: string | null;
}
export interface SuggestionResult { id: string; revision: number; original_copy: CopyFields; suggested_copy: CopyFields; effective_copy: CopyFields; purpose: string; pending_reasons: string[]; notes: string[]; destination_entity_id: string | null; start_date: string | null; end_date: string | null; required: boolean; status: string; unknowns: string[] }
export interface SuggestionBatch { id: string; status: string; error: string | null; created_at: string; results?: SuggestionResult[]; input_json?: { placements: { id: string; revision: number }[] }; remaining_count?: number; usage_notice?: string; retry_notice?: string; stale?: boolean }
export interface AssetBinding { id: string; placement_revision: number; existence_status: string; evidence_level: string; stale_reason: string | null; valid_to: string | null; last_verified_at: string | null; native_id: string | null }
export interface AssetHandoff {
  original_copy: CopyFields; suggested_copy: CopyFields; effective_copy: CopyFields;
  tracking_name: string; notice: string; bindings: AssetBinding[]; purpose: string | null;
  destination_entity_id: string | null; download_url: string; start_date: string | null; end_date: string | null;
}
export interface BindingCandidate { entity_id: string; name: string | null; native_id: string; native_label?: string; native_status?: string }
export interface VersionMetrics { observations: (NativeObservation & { binding_id: string; attributed?: boolean; unattributed_reason?: string | null })[]; totals: null; [key: string]: unknown }
export class AssetApiError extends Error {
  status: number; details?: unknown;
  constructor(message: string, status: number, details?: unknown) { super(message); this.status = status; this.details = details; }
}
export const userAssetPath = (brand: string) => `${BASE}/brands/${encodeURIComponent(brand)}/user-assets`;
export const placementPath = (brand: string, campaign: string, id?: string) => `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}/placements${id ? `/${encodeURIComponent(id)}` : ""}`;
const suggestionPath = (brand: string, campaign: string) => `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}/asset-suggestions`;
export async function assetRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new AssetApiError(errorMessageFrom(data, "素材操作失敗，請稍後重試。"), res.status, data?.error?.details);
  return data as T;
}
const json = (body: unknown, method = "POST"): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const listUserAssets = (brand: string, cursor?: string | null, uploadCursor?: string | null, signal?: AbortSignal) => assetRequest<AssetLibrary>(`${userAssetPath(brand)}?${new URLSearchParams({ ...(cursor ? { cursor } : {}), ...(uploadCursor ? { upload_cursor: uploadCursor } : {}) })}`, { signal });
export const createUploadBatch = (brand: string, files: { filename: string; size: number; content_type: string; copy_fields: CopyFields }[]) => assetRequest<{ batch: UploadBatch }>(`${userAssetPath(brand)}/batches`, json({ files }));
export const putUpload = (brand: string, id: string, file: File, signal?: AbortSignal) => assetRequest<{ upload: AssetUpload }>(`${userAssetPath(brand)}/uploads/${encodeURIComponent(id)}/content`, { method: "PUT", body: file, signal, headers: { "Content-Type": "application/octet-stream" } });
export const retryUpload = (brand: string, id: string) => assetRequest<{ upload: AssetUpload }>(`${userAssetPath(brand)}/uploads/${encodeURIComponent(id)}/retry`, json({}));
export const getUploadBatch = (brand: string, id: string, signal?: AbortSignal) => assetRequest<{ batch: UploadBatch }>(`${userAssetPath(brand)}/batches/${encodeURIComponent(id)}`, { signal });
export const retryPreview = (brand: string, id: string) => assetRequest<{ asset: UserAsset }>(`${userAssetPath(brand)}/${encodeURIComponent(id)}/retry-preview`, json({}));
export const listPlacements = (brand: string, campaign: string) => assetRequest<{ placements: Placement[] }>(`${placementPath(brand, campaign)}?history=true`);
export const attachUpload = (brand: string, campaign: string, upload_id: string) => assetRequest<{ placement: Placement }>(placementPath(brand, campaign), json({ upload_id }));
export const attachAsset = (brand: string, campaign: string, asset_id: string) => assetRequest<{ placement: Placement }>(placementPath(brand, campaign), json({ asset_id, copy_fields: {} }));
export const revisePlacement = (brand: string, campaign: string, id: string, body: unknown) => assetRequest<{ placement: Placement }>(placementPath(brand, campaign, id), json(body, "PATCH"));
export const confirmPlacement = (brand: string, campaign: string, p: Placement, batch_id: string | null) => assetRequest<{ placement: Placement }>(`${placementPath(brand, campaign, p.id)}/confirm`, json({ expected_revision: p.revision, batch_id }));
export const listSuggestionBatches = (brand: string, campaign: string, cursor?: string) => assetRequest<{ batches: SuggestionBatch[]; next_cursor: string | null }>(`${suggestionPath(brand, campaign)}${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`);
export const getSuggestionBatch = (brand: string, campaign: string, id: string) => assetRequest<{ batch: SuggestionBatch }>(`${suggestionPath(brand, campaign)}/${encodeURIComponent(id)}`);
export const suggestAssets = (brand: string, campaign: string, placements: Placement[], idempotency_key: string, summary: string) => assetRequest<{ batch: SuggestionBatch; limits: { codex_notice: string } }>(suggestionPath(brand, campaign), json({ placements: placements.map(p => ({ id: p.id, revision: p.revision })), idempotency_key, summary }));
export const assetHandoff = (brand: string, campaign: string, p: Placement) => assetRequest<AssetHandoff>(`${placementPath(brand, campaign, p.id)}/handoff?revision=${p.revision}`);
export const bindingCandidates = (brand: string, campaign: string, p: Placement, platform: string, account_id: string, cursor?: string) => assetRequest<{ candidates: BindingCandidate[]; next_cursor: string | null }>(`${placementPath(brand, campaign, p.id)}/binding-candidates?${new URLSearchParams({ revision: String(p.revision), platform, account_id, ...(cursor ? { cursor } : {}) })}`);
export const bindingAction = (brand: string, campaign: string, p: Placement, action: "self-report" | "verify-binding" | "end-binding", fields: Record<string, unknown> = {}) => assetRequest<{ binding: AssetBinding }>(`${placementPath(brand, campaign, p.id)}/${action}`, json({ expected_revision: p.revision, ...fields }));
export const versionMetrics = (brand: string, campaign: string, p: Placement, start: string, end: string) => assetRequest<VersionMetrics>(`${placementPath(brand, campaign, p.id)}/version-metrics?${new URLSearchParams({ revision: String(p.revision), start, end })}`);
export async function assetBlob(brand: string, id: string, kind: "download" | "preview" | "thumbnail", signal?: AbortSignal): Promise<Blob> {
  const res = await apiFetch(`${userAssetPath(brand)}/${encodeURIComponent(id)}/${kind}`, { signal });
  if (!res.ok) throw new AssetApiError(errorMessageFrom(await res.json().catch(() => null), "讀取原檔或預覽失敗。"), res.status);
  return res.blob();
}
