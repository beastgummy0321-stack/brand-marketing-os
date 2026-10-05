import { apiFetch, readJson } from "./http";
import { BASE } from "./adsApi";
export interface SimulationRow { ad_id: string; spend: number; impressions: number; clicks: number; purchases: number; revenue: number }
export interface SimulationDay {
  enabled: boolean; reason: string | null; started: boolean; day: string; revision: number;
  saved_at: string | null; saved_by: string | null; rows: SimulationRow[]; closed: boolean;
  receipts: Record<string, { revision: number; saved_at: string; saved_by: string; ad_count: number; missing_ad_count: number }>;
}
function path(brand: string, campaign: string) { return `${BASE}/brands/${encodeURIComponent(brand)}/campaigns/${encodeURIComponent(campaign)}/simulation`; }
export async function readSimulation(brand: string, campaign: string, day: string): Promise<SimulationDay> {
  return readJson(await apiFetch(`${path(brand, campaign)}/${day}`), "讀取模擬回收失敗。");
}
export async function startSimulation(brand: string, campaign: string): Promise<void> {
  await readJson(await apiFetch(`${path(brand, campaign)}/start`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm_isolation: true }) }), "啟用隔離回收失敗。");
}
export async function saveSimulation(brand: string, campaign: string, day: string, revision: number, rows: SimulationRow[]): Promise<SimulationDay> {
  return readJson(await apiFetch(`${path(brand, campaign)}/${day}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ revision, mode: "daily_increment", rows }) }), "儲存模擬成效失敗。");
}
