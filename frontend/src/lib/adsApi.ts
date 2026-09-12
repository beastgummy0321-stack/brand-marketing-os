/** 投放中心 API 型別與呼叫（F03-I01）。對應 `app/ads/routes.py`——Campaign 物件的共用契約，
 * 只有讀取；後續票在這個檔案上加，不重排這裡已經定的形狀。錯誤處理沿用既有寫法：`apiFetch`
 * 之後檢查 `res.ok`，不行就試著解析 `{"error": {...}}` 信封餵給 `errorMessageFrom`，解不出來就
 * 用預設訊息。 */
import { apiFetch, errorMessageFrom } from "./http";

export type CampaignStatus = "draft" | "ready" | "live" | "ended" | "closed";
export type SuccessMetric = "cpa" | "roas" | "purchases";
export type LocalState = "unbound" | "bound" | "detached" | "retired";

export interface CampaignOutcomeTotals {
  spend: number;
  purchases: number;
  revenue: number;
}

/** `GET /campaigns` 一列。`budget_total` 是後端推導出來的（`sum(投放組.daily_budget) x 天數`），
 * `budget_planned` 是使用者採用的情境金額——兩者可能因為天數捨入而略有出入，畫面上要分開標。 */
export interface CampaignCard {
  id: string;
  name: string;
  status: CampaignStatus;
  start_date: string | null;
  end_date: string | null;
  objective: string;
  budget_planned: number | null;
  budget_total: number | null;
  outcome: CampaignOutcomeTotals;
}

/** Shared by all three binding levels (campaign / group / ad) — same five columns,
 * because Meta's lookups are hierarchical and the campaign node is bound first. */
export interface EntityBinding {
  external_id: string | null;
  external_name: string | null;
  external_status: string | null;
  local_state: LocalState;
  bound_at: string | null;
}

export interface AdRow extends EntityBinding {
  id: string;
  campaign_id: string;
  group_id: string;
  name: string;
  audience_key: string | null;
  pain_key: string | null;
  angle_key: string | null;
  hook_key: string | null;
  proof_key: string | null;
  offer_key: string | null;
  format_key: string | null;
  coordinates_snapshot_json: Record<string, unknown>;
  product_id: string | null;
  asset_ready_source: "workbench" | "manual" | null;
  asset_ready_by: string | null;
  asset_ready_at: string | null;
}

export interface DeliveryGroupRow extends EntityBinding {
  id: string;
  campaign_id: string;
  channel_key: string;
  name: string;
  role: "new" | "retarget" | "explore";
  daily_budget: number;
  start_date: string | null;
  end_date: string | null;
  ads: AdRow[];
}

export interface ActionRow {
  id: string;
  campaign_id: string;
  target_kind: "campaign" | "group" | "ad";
  target_id: string;
  kind: "publish" | "bind" | "budget" | "date" | "pause" | "creative";
  before_json: Record<string, unknown>;
  after_json: Record<string, unknown>;
  approved_by: string | null;
  approved_at: string | null;
  sync_state: "pending_manual" | "confirmed_manual" | "auto_synced";
  platform_ref: string | null;
  reverses_action_id: string | null;
  created_at: string;
}

/** `GET /campaigns/{c}` — 五分頁工作區共用的一份 dict：Campaign 本身欄位 + 推導出來的
 * `budget_total` + 投放組（各自掛著廣告）+ 最新的操作紀錄 + 成效小計。 */
export interface CampaignDetail extends EntityBinding {
  id: string;
  name: string;
  goal_text: string;
  objective: string;
  success_metric: SuccessMetric;
  success_target: number | null;
  success_basis: string | null;
  start_date: string | null;
  end_date: string | null;
  status: CampaignStatus;
  budget_planned: number | null;
  budget_scenario: string | null;
  budget_basis_json: Record<string, unknown>;
  budget_total: number | null;
  context_json: Record<string, unknown>;
  constraints_json: Record<string, unknown>;
  verdict: string | null;
  verdict_json: Record<string, unknown>;
  closed_at: string | null;
  created_by: string | null;
  created_at: string;
  groups: DeliveryGroupRow[];
  actions: ActionRow[];
  outcome: CampaignOutcomeTotals;
}

async function ensureOk(res: Response, fallback: string): Promise<void> {
  if (res.ok) return;
  let message = fallback;
  try {
    const data = (await res.json()) as { error?: { message?: string } };
    message = errorMessageFrom(data, message);
  } catch {
    // 回應不是 JSON，用預設訊息。
  }
  throw new Error(message);
}

async function parseJsonOrThrow<T>(res: Response, fallback: string): Promise<T> {
  await ensureOk(res, fallback);
  return (await res.json()) as T;
}

const BASE = "/api/ads";

export async function listCampaigns(brandId: string): Promise<CampaignCard[]> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/campaigns`);
  const data = await parseJsonOrThrow<{ campaigns: CampaignCard[] }>(res, "讀取 Campaign 清單失敗。");
  return data.campaigns;
}

export async function getCampaign(brandId: string, campaignId: string): Promise<CampaignDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}`,
  );
  const data = await parseJsonOrThrow<{ campaign: CampaignDetail }>(res, "讀取 Campaign 失敗。");
  return data.campaign;
}
