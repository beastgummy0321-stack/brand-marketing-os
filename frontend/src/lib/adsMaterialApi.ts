import { apiFetch, errorMessageFrom } from "./http";
import { BASE } from "./adsApi";
import type { CopyFields } from "./adsUserAssetsApi";

export type MaterialMode = "existing" | "external_image" | "workbench_image" | "copy";
export interface MaterialPrompt {
  source: "none" | "manual" | "workbench"; text?: string | null; origin?: string;
  set_id?: string; version_id?: string; card_index?: number | null;
}
export interface MaterialCandidate {
  id: string; asset_id: string; filename: string; mime_type: string;
  prompt: MaterialPrompt; reference_asset_ids: string[];
}
export interface MaterialTask {
  id: string; campaign_id: string; revision: number; title: string; mode: MaterialMode;
  instruction: string; copy_fields: CopyFields; prompt: MaterialPrompt;
  reference_asset_ids: string[]; review_id: string | null; recommendation_id: string | null;
  review_context: Record<string, unknown> | null; content_hash: string; candidates: MaterialCandidate[];
  selected_candidate_id: string | null; placement_id: string | null; placement_revision: number | null;
  placement_current: boolean | null; pack_id: string | null;
  dispatch_status: "not_requested" | "prepared" | "queued" | "unknown";
  history: { revision: number; content_hash: string; created_at: string }[];
  limitations: string[]; created_at: string;
}
export interface MaterialOption {
  set_id: string; version_id: string; part: "image_prompt" | "copy";
  label: string; text: string; card_index: number | null; copy_fields?: CopyFields;
}
export interface MaterialOperation { path: string; method: "POST" | "PATCH"; body: Record<string, unknown> }
export function promptInput(prompt: MaterialPrompt): MaterialPrompt {
  if (prompt.source === "none") return { source: "none" };
  if (prompt.source === "manual") return { source: "manual", text: prompt.text, ...(prompt.origin ? { origin: prompt.origin } : {}) };
  return { source: "workbench", set_id: prompt.set_id, version_id: prompt.version_id, card_index: prompt.card_index };
}
export class MaterialRequestError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}
export const materialPath = (brand: string, campaign: string) => `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}/material-tasks`;
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(path, init);
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new MaterialRequestError(errorMessageFrom(body, "素材任務尚未完成，請重新讀取確認已保存的內容。"), response.status);
  return body as T;
}
export const listMaterialTasks = (brand: string, campaign: string, signal?: AbortSignal) => request<{ tasks: MaterialTask[]; truncated?: boolean }>(materialPath(brand, campaign), { signal });
export const getMaterialTask = (brand: string, campaign: string, id: string, signal?: AbortSignal) => request<{ task: MaterialTask }>(`${materialPath(brand, campaign)}/${encodeURIComponent(id)}`, { signal });
export const materialOptions = (brand: string, campaign: string, id: string, signal?: AbortSignal) => request<{ options: MaterialOption[] }>(`${materialPath(brand, campaign)}/${encodeURIComponent(id)}/prompt-options`, { signal });
export const saveMaterialOperation = (operation: MaterialOperation, signal?: AbortSignal) => request<{ task: MaterialTask }>(operation.path, { method: operation.method, body: JSON.stringify(operation.body), headers: { "Content-Type": "application/json" }, signal });
