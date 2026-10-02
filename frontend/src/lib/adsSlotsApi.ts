import { apiFetch, errorMessageFrom } from "./http";
import { BASE } from "./adsApi";
import type { MaterialReplaces } from "./adsMaterialApi";
import { AssetApiError, assetRequest, type CopyFields, type Placement } from "./adsUserAssetsApi";

/** F30 Contract F: the assets tab's slots — one planned ad (app-built) or one platform ad (imported).
 * `ready` = the launch rule (a confirmed material, or already a platform ad); `in_progress` = a file
 * uploaded into the slot waiting for confirmation, a revised material, or a workbench pack being worked.
 * F35 Contract T: the slot is two halves, the image and the copy. `copy_only` = the ad's selected workbench
 * copy is known but no file is in the slot yet (an upload carries the copy in and the slot is ready at once);
 * `image_only` = a file is in the slot but its placement has no headline and no body (the picker,
 * `chooseSlotCopy`, fills the other half). Copy never makes a slot ready on its own.
 * F44 Contract D: `blocked` = the slot's automatic confirmation was refused (or its file failed); the slot says why
 * (`Slot.blocked`) and is not ready. Nothing changes it by itself, so it is not `in_progress`.
 * F45 Contract W (ads.md §6.49): `in_progress` only while a background job for the slot runs (`Slot.job`); nothing
 * running, nothing refused and not ready → `waiting` with the user's next action (`Slot.waiting`). */
export type SlotState = "ready" | "missing" | "in_progress" | "waiting" | "copy_only" | "image_only" | "blocked";
/** F45 Contract W: the user's next action on a `waiting` slot — `pick_on_workbench` (the ad's set has no selected copy;
 * the slot's `workbench_href` goes there) or `confirm_copy` (an unconfirmed placement; the button runs `recheckSlot`).
 * `text` is the server's sentence (「等你：…」). */
export interface SlotWaiting { action: "pick_on_workbench" | "confirm_copy"; text: string }
/** F45 Contract W: the job a slot is `in_progress` for — its original's preview or its workbench set's copy
 * generation; `done`/`of` are `null` unless the workbench read gives them. */
export interface SlotJob { kind: "preview" | "copy"; done: number | null; of: number | null }
/** F44 Contract D: why a slot is blocked — the first reason as one sentence, the offending words it quotes (`terms`),
 * the exit that fixes it (`copy` = another copy version, `file` = another file, `null` = nothing on the slot itself)
 * and how many other reasons there are (`more`). */
export interface SlotBlocked { text: string; terms: string[]; fix: "copy" | "file" | null; more: number }
/** The copy half: the ad's selected workbench version (`workbench`, label 「工作檯第 N 版」) before any file, or the
 * placement's effective copy once a file is in the slot (`placement`, label 已確認／待確認). */
export interface SlotCopy {
  source: "workbench" | "placement"; label: string;
  headline: string | null; body: string | null; description: string | null;
}
export interface Slot {
  ad_id: string | null; entity_id: string | null; name: string; state: SlotState;
  /** A platform creative URL, or an authenticated same-origin user-asset path (see `isAuthThumbnail`). */
  thumbnail_url: string | null;
  confirmed: boolean;
  /** The open 「換掉這一則」 request on this slot's platform ad, if any. */
  replace_task_id: string | null;
  /** `null` on an imported campaign and on a planned ad with neither a file nor a selected workbench copy. */
  copy: SlotCopy | null;
  /** The ad's workbench set (an `/app/…` path, see `internalHref`); `null` when the ad has no set. */
  workbench_href: string | null;
  /** F40-I01: the planned ad's own `ads_ad.format_key` (`"video"` = the slot needs a video, a photo is refused);
   * `null` for an ad without one and for an imported campaign's platform ad. Optional only for older fixtures. */
  format_key?: string | null;
  /** F44 Contract D: set exactly when `state === "blocked"`. Optional only for older fixtures. */
  blocked?: SlotBlocked | null;
  /** F44 Contract D: the planned ad's offer coordinate label (「無優惠」, 「組合優惠」…); `null` for an ad without one
   * and on an imported campaign. Optional only for older fixtures. */
  offer_label?: string | null;
  /** F45 Contract W: set exactly when `state === "waiting"`. */
  waiting: SlotWaiting | null;
  /** F45 Contract W: set exactly when `state === "in_progress"`. */
  job: SlotJob | null;
}
/** One workbench copy version for the picker (= `workbench.material_options(part="copy")`). */
export interface SlotCopyOption { set_id: string; version_id: string; label: string; copy_fields: CopyFields }
export interface SlotGroup { group_id: string | null; name: string; slots: Slot[] }
export type ReplaceRequestLabel = "等素材工作檯" | "有候選圖" | "已採用";
export interface ReplaceRequest {
  task_id: string; replaces: MaterialReplaces; created_at: string; state_label: ReplaceRequestLabel;
}
export interface CampaignSlots {
  ready: number; total: number; groups: SlotGroup[];
  requests: ReplaceRequest[]; requests_truncated: boolean;
}
/** `{upload_id}` (a finished upload, its own copy unless given) or `{asset_id}` — same as `POST …/placements`.
 * F41-I01: `{placement_id}` = a finished asset already placed in this campaign (the advanced 「將成品指派給計畫中的廣告」
 * panel); the ad's selected workbench copy rides in, else that placement's own copy. */
export type SlotUpload =
  | { upload_id: string; copy_fields?: CopyFields }
  | { asset_id: string; copy_fields?: CopyFields }
  | { placement_id: string; copy_fields?: CopyFields };

const slotsPath = (brand: string, campaign: string) => `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}/slots`;

export const getSlots = (brand: string, campaign: string, signal?: AbortSignal) => assetRequest<CampaignSlots>(slotsPath(brand, campaign), { signal });
/** Put a file in one planned ad's slot. The slot reads `in_progress` until the placement is confirmed
 * (`confirmPlacement`); the confirmation assigns it. 409 `placement_copy_conflict` carries the current placement. */
export const uploadIntoSlot = (brand: string, campaign: string, adId: string, body: SlotUpload, signal?: AbortSignal) =>
  assetRequest<{ placement: Placement; slots: CampaignSlots }>(`${slotsPath(brand, campaign)}/${encodeURIComponent(adId)}/upload`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });

/** The brand's workbench copy versions, for the picker on an `image_only` slot. */
export const getSlotCopyOptions = (brand: string, campaign: string, signal?: AbortSignal) =>
  assetRequest<{ options: SlotCopyOption[] }>(`${slotsPath(brand, campaign)}/copy-options`, { signal });
/** Put one workbench copy version into a slot that already has a file: the placement takes the copy and the ad's
 * name as purpose, is confirmed and assigned. 409 `slot_no_file` when the slot has no pending placement. */
export const chooseSlotCopy = (brand: string, campaign: string, adId: string, body: { set_id: string; version_id: string }, signal?: AbortSignal) =>
  assetRequest<{ placement: Placement; slots: CampaignSlots }>(`${slotsPath(brand, campaign)}/${encodeURIComponent(adId)}/copy`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });

/** F45: save the copy typed in the slot editor (`{copy_fields}`; a field not sent keeps its value) into the slot's
 * unconfirmed placement; the confirmation runs at once and the slots come back ready or blocked with the reason.
 * 409 `slot_no_file` when the slot has no unconfirmed placement; 400 `slot_copy_invalid` for an empty or unknown field. */
export const editSlotCopy = (brand: string, campaign: string, adId: string, copyFields: CopyFields, signal?: AbortSignal) =>
  assetRequest<{ placement: Placement; slots: CampaignSlots }>(`${slotsPath(brand, campaign)}/${encodeURIComponent(adId)}/copy`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ copy_fields: copyFields }), signal });

/** A refused recheck. `code` tells `slot_no_file` (the slot has nothing to check any more — re-read the slots) from
 * the errors whose `message` is for the user (`user_asset_unavailable`, `campaign_unknown`). */
export class SlotRecheckError extends AssetApiError {
  code: string | null;
  constructor(message: string, status: number, code: string | null) { super(message, status); this.code = code; }
}
/** F44 Contract D: run a blocked slot's confirmation again (no body). 200 carries the slots whether the slot became
 * ready or is still blocked (then with the new refusal's reason). */
export async function recheckSlot(brand: string, campaign: string, adId: string, signal?: AbortSignal): Promise<{ slots: CampaignSlots }> {
  const res = await apiFetch(`${slotsPath(brand, campaign)}/${encodeURIComponent(adId)}/recheck`, { method: "POST", signal });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new SlotRecheckError(errorMessageFrom(data, "沒有檢查成功，請稍後再試。"), res.status, typeof data?.error?.code === "string" ? data.error.code : null);
  return data as { slots: CampaignSlots };
}

/** A user-asset thumbnail is served behind the bearer token, so a bare `<img src>` cannot load it. */
export const isAuthThumbnail = (url: string | null): url is string => !!url && url.startsWith(`${BASE}/`);
/** Fetch an authenticated thumbnail as a Blob (the caller makes and revokes the object URL). */
export async function fetchSlotThumbnail(url: string, signal?: AbortSignal): Promise<Blob> {
  const res = await apiFetch(url, { signal });
  if (!res.ok) throw new AssetApiError("縮圖尚未完成。", res.status);
  return res.blob();
}
