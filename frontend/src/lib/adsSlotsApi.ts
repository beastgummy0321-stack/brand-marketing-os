import { apiFetch } from "./http";
import { BASE } from "./adsApi";
import type { MaterialReplaces } from "./adsMaterialApi";
import { AssetApiError, assetRequest, type CopyFields, type Placement } from "./adsUserAssetsApi";

/** F30 Contract F: the assets tab's slots — one planned ad (app-built) or one platform ad (imported).
 * `ready` = the launch rule (a confirmed material, or already a platform ad); `in_progress` = a file
 * uploaded into the slot waiting for confirmation, a revised material, or a workbench pack being worked. */
export type SlotState = "ready" | "missing" | "in_progress";
export interface Slot {
  ad_id: string | null; entity_id: string | null; name: string; state: SlotState;
  /** A platform creative URL, or an authenticated same-origin user-asset path (see `isAuthThumbnail`). */
  thumbnail_url: string | null;
  confirmed: boolean;
  /** The open 「換掉這一則」 request on this slot's platform ad, if any. */
  replace_task_id: string | null;
}
export interface SlotGroup { group_id: string | null; name: string; slots: Slot[] }
export type ReplaceRequestLabel = "等素材工作檯" | "有候選圖" | "已採用";
export interface ReplaceRequest {
  task_id: string; replaces: MaterialReplaces; created_at: string; state_label: ReplaceRequestLabel;
}
export interface CampaignSlots {
  ready: number; total: number; groups: SlotGroup[];
  requests: ReplaceRequest[]; requests_truncated: boolean;
}
/** `{upload_id}` (a finished upload, its own copy unless given) or `{asset_id}` — same as `POST …/placements`. */
export type SlotUpload = { upload_id: string; copy_fields?: CopyFields } | { asset_id: string; copy_fields?: CopyFields };

const slotsPath = (brand: string, campaign: string) => `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}/slots`;

export const getSlots = (brand: string, campaign: string, signal?: AbortSignal) => assetRequest<CampaignSlots>(slotsPath(brand, campaign), { signal });
/** Put a file in one planned ad's slot. The slot reads `in_progress` until the placement is confirmed
 * (`confirmPlacement`); the confirmation assigns it. 409 `placement_copy_conflict` carries the current placement. */
export const uploadIntoSlot = (brand: string, campaign: string, adId: string, body: SlotUpload, signal?: AbortSignal) =>
  assetRequest<{ placement: Placement; slots: CampaignSlots }>(`${slotsPath(brand, campaign)}/${encodeURIComponent(adId)}/upload`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });

/** A user-asset thumbnail is served behind the bearer token, so a bare `<img src>` cannot load it. */
export const isAuthThumbnail = (url: string | null): url is string => !!url && url.startsWith(`${BASE}/`);
/** Fetch an authenticated thumbnail as a Blob (the caller makes and revokes the object URL). */
export async function fetchSlotThumbnail(url: string, signal?: AbortSignal): Promise<Blob> {
  const res = await apiFetch(url, { signal });
  if (!res.ok) throw new AssetApiError("縮圖尚未完成。", res.status);
  return res.blob();
}
