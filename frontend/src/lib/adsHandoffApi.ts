import { apiFetch } from "./http";
import { BASE, parseJsonOrThrow } from "./adsApi";
import type { ChangeSet } from "./adsChangeApi";
import type { NativeEntity } from "./adsExternalApi";

export interface HandoffEvidence {
  entity_exists?: boolean;
  setting_matches?: boolean | null;
  material_evidence?: string;
  matched_fields?: string[];
  unknown_fields?: string[];
  deviated_fields?: string[];
  message?: string;
  delivery_confirmed?: boolean;
}
export interface HandoffItem {
  id: string; name: string; planned_kind: string; planned_id: string;
  status: "pending" | "reported" | "confirmed" | "deviated" | "unknown" | "stale";
  change_set_id: string; parent_item_id: string | null; expected_parent_name: string | null;
  placement_id: string | null; placement_revision: number | null;
  entity_id: string | null; platform: string | null; source_account: string | null;
  native_kind: string | null; native_id: string | null;
  reported_at: string | null; observed_at: string | null;
  entity_exists: boolean; setting_matches: boolean | null; material_evidence: string;
  expected_json: Record<string, unknown>; evidence_json: HandoffEvidence;
}
export interface HandoffPlacement {
  id: string; revision: number; filename: string; purpose: string;
  destination_entity_id: string | null;
}
export interface HandoffWorkspace {
  items: HandoffItem[]; items_truncated: boolean;
  ready_placements: HandoffPlacement[]; destinations: NativeEntity[];
  destinations_truncated: boolean; notice: string;
}
export interface HandoffIdentity {
  platform: string; source_account: string; native_kind: string; native_id: string;
  user_verified: boolean;
}
export interface NewAdHandoffRequest {
  operation_id: string; title: string; month: string; placement_id: string; revision: number;
  destination_entity_id: string; reason: string; review_id?: string; recommendation_id?: string;
  /** F27-I14 Contract E: the ACTIVE ad this new ad replaces (same campaign) — carried only when
   * this handoff answers a review round's material step, never guessed from context. */
  replaces_entity_id?: string;
}
export class HandoffRequestRejected extends Error {}
const path = (brand: string, campaign: string) => `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}`;
async function request<T>(url: string, method: string, body: unknown, signal?: AbortSignal): Promise<T> {
  try {
    const response = await apiFetch(url, { method, signal, ...(body === undefined ? {} : {
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }) });
    try { return await parseJsonOrThrow<T>(response, "尚未收到可確認的結果，請沿用原操作重試。"); }
    catch (error) {
      if (response.status >= 400 && response.status < 500) throw new HandoffRequestRejected(error instanceof Error ? error.message : "請修正內容後重試。");
      throw error;
    }
  } catch (error) {
    if (error instanceof TypeError) throw new Error("未收到伺服器回應，結果尚未確認。請重試同一次操作，不要在平台重建廣告。");
    throw error;
  }
}
export const getHandoff = (brand: string, campaign: string, signal?: AbortSignal) => request<HandoffWorkspace>(`${path(brand, campaign)}/handoff`, "GET", undefined, signal);
export async function reportHandoff(brand: string, campaign: string, id: string, signal?: AbortSignal) {
  return (await request<{ item: HandoffItem }>(`${path(brand, campaign)}/handoff/${encodeURIComponent(id)}/report`, "POST", {}, signal)).item;
}
export async function checkHandoff(brand: string, campaign: string, id: string, body: HandoffIdentity, signal?: AbortSignal) {
  return (await request<{ item: HandoffItem }>(`${path(brand, campaign)}/handoff/${encodeURIComponent(id)}/check`, "POST", body, signal)).item;
}
export async function createNewAdHandoff(brand: string, campaign: string, body: NewAdHandoffRequest, signal?: AbortSignal) {
  return (await request<{ change_set: ChangeSet }>(`${path(brand, campaign)}/new-ad-handoffs`, "POST", body, signal)).change_set;
}
export async function reconsiderHandoff(brand: string, campaign: string, id: string, reason: string, signal?: AbortSignal) {
  return (await request<{ item: HandoffItem }>(`${path(brand, campaign)}/handoff/${encodeURIComponent(id)}/reconsider`, "POST", { reason }, signal)).item;
}
export const refreshHandoffSources = (brand: string, campaign: string, signal?: AbortSignal) => request(`${path(brand, campaign)}/sync`, "POST", {}, signal);

export interface PlannedMaterialAd {
  id: string; name: string; group_id: string; group_name: string;
  placement_id: string | null; placement_revision: number | null;
  assignment_status: "unassigned" | "confirmed" | "stale";
  filename: string | null; copy_fields: { headline?: string; body?: string; description?: string }; reason: string | null;
}
export interface PlannedMaterialWorkspace {
  planned_ads: PlannedMaterialAd[];
  ready_placements: { id: string; revision: number; filename: string; copy_fields: PlannedMaterialAd["copy_fields"] }[];
}
export const getPlannedMaterials = (brand: string, campaign: string, signal?: AbortSignal) => request<PlannedMaterialWorkspace>(`${path(brand, campaign)}/launch-materials`, "GET", undefined, signal);
export const assignPlannedMaterial = (brand: string, campaign: string, ad: string, body: { placement_id: string | null; revision: number | null }, signal?: AbortSignal) => request<PlannedMaterialWorkspace>(`${path(brand, campaign)}/launch-materials/${encodeURIComponent(ad)}`, "PUT", body, signal);
