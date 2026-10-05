/** Canonical router paths for ads campaigns. IDs are encoded once at this boundary. */
export const WORKSPACE_TABS = ["overview", "strategy", "structure", "assets", "perf", "changes"] as const;
export type WorkspaceTab = typeof WORKSPACE_TABS[number];
type Query = Record<string, string | number | undefined | null>;
const segment = encodeURIComponent;
function queryPath(path: string, query: Query = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) if (value != null) params.set(key, String(value));
  return params.size ? `${path}?${params}` : path;
}
export function campaignPath(brand: string, campaign: string, query: Query & { tab?: WorkspaceTab } = {}): string {
  return queryPath(`/brands/${segment(brand)}/ads/campaigns/${segment(campaign)}`, query);
}
export function campaignFlowPath(brand: string, campaign: string, parts: string[], query: Query = {}): string {
  return queryPath(`${campaignPath(brand, campaign)}/${parts.map(segment).join("/")}`, query);
}
export function newCampaignPath(brand: string, query: Query = {}): string {
  return queryPath(`/brands/${segment(brand)}/ads/new`, query);
}
