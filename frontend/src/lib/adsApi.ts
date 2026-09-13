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

/** F04-I08：`app/ads/judgment.py::campaign_judgment()` 的回傳形狀——程式組好的一句判斷，
 * 瀏覽器原樣印，不重拼。 */
export interface CampaignJudgment {
  tone: "neutral" | "good" | "warn";
  text: string;
  detail: string;
}

export interface CampaignBudgetProgress {
  spent: number | null;
  total: number | null;
  pct: number | null;
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
  created_at: string;
  created_by: string | null;
  budget_planned: number | null;
  budget_total: number | null;
  budget_progress: CampaignBudgetProgress;
  judgment: CampaignJudgment;
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
  /** 產生策略前是 `{}`；F03-I05 起是 `AdsBudgetBasisJson`——畫面在讀前先檢查
   * `budget_basis_json.strategy` 存不存在。 */
  budget_basis_json: Partial<AdsBudgetBasisJson>;
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
  /** F03-I08：素材 tab 跟發布畫面共用同一組數字。 */
  asset_readiness: AssetReadinessSummary;
  /** F04-I08：跟 `CampaignCard.judgment` 同一支規則（`campaign_judgment()`）——後端一律回傳，
   * 選填只是為了不逼著每一個既有的手寫測試 fixture（`do_not_touch`：
   * `frontend/src/components/**`）都補上這兩個新欄位。 */
  judgment?: CampaignJudgment;
  /** F04-I08：`actions` 每一列跑過 `judgment.action_line()` 的三句話——`actions` 本身保留
   * 不刪，別的分頁還在讀原始欄位。 */
  action_lines?: AdsActionLine[];
}

/** F04-I08：`app/ads/judgment.py::action_line()` 的回傳形狀，加上呼叫端補的 campaign
 * 資訊——首頁的時間軸跨 Campaign，需要知道這一列屬於哪一個。 */
export interface AdsActionLine {
  campaign_id: string;
  campaign_name: string;
  time_text: string;
  title: string;
  detail: string;
}

// -- F03-I08：素材就緒 -----------------------------------------------------------------------

export type AssetReadinessState =
  | "ready_workbench"
  | "ready_manual"
  | "in_progress"
  | "not_started";

export interface AssetReadinessRow {
  ad_id: string;
  state: AssetReadinessState;
  pack_id: string | null;
  brief_id: string | null;
  source: "workbench" | "manual" | null;
  by: string | null;
  at: string | null;
}

export interface AssetReadinessSummary {
  ready_count: number;
  total: number;
}

/** `POST /campaigns` 的回應：`CampaignDetail` 加一個 transient 的 `parsed` 旗標（F03-I03）——
 * AI 有沒有解析出這次投放的目標；`false` 時欄位仍然是一組可用的預設值，不落地，只存在這次
 * 回應裡，畫面用它決定要不要提示使用者檢查一下 AI 填的內容。 */
export interface CampaignDraft extends CampaignDetail {
  parsed: boolean;
}

/** F04-I11：`context_json.field_sources` 的六格——`"user"`＝你說的，`"system"`＝行銷駕駛艙
 * 沒聽到就幫你補的（ARCHITECTURE.md §6.1 第 11 條）。 */
export type FieldSource = "user" | "system";

export interface CampaignFieldSources {
  product: FieldSource;
  objective: FieldSource;
  platform: FieldSource;
  budget: FieldSource;
  dates: FieldSource;
  audience: FieldSource;
}

/** `POST /campaigns` 的請求體——一句話＋選填的投放期間（兩個都留空讓行銷駕駛艙從句子判斷）
 * ＋選填的額外限制。 */
export interface CreateCampaignInput {
  goal_text: string;
  start_date?: string;
  end_date?: string;
  constraints?: Record<string, unknown>;
}

/** `PATCH /campaigns/{id}` 的請求體——草稿欄位的一般編輯，不是 `ads_action`。所有欄位選填，
 * 沒帶到的欄位維持原樣；`success_target`／`success_basis` 可以明確傳 `null` 清空。 */
export interface PatchCampaignInput {
  name?: string;
  objective?: string;
  success_metric?: SuccessMetric;
  success_target?: number | null;
  success_basis?: string | null;
  start_date?: string;
  end_date?: string;
  constraints_json?: Record<string, unknown>;
  product_ids?: string[];
}

// -- F03-I05：策略（POST .../strategy 與 .../strategy/scenario）------------------------------

export type BudgetScenarioMode = "cold_start" | "history";
export type BudgetScenarioKey = "minimum" | "recommended" | "aggressive" | "conservative";

export interface BudgetScenarioRow {
  key: string;
  label: string;
  daily: number | null;
  total: number | null;
  caption: string;
}

/** `app/ads/budget.py::scenarios()` 的整包回傳——程式算的，AI 只預填百分比。 */
export interface BudgetScenarios {
  mode: BudgetScenarioMode;
  scenarios: BudgetScenarioRow[];
  recommended: string;
  basis: Record<string, unknown>;
}

export type StrategyRole = "new" | "retarget" | "explore";

export interface StrategyAllocationItem {
  role: StrategyRole;
  label: string;
  pct: number;
  rationale: string | null;
  /** 已套用 `budget.split()` 的金額，跟 `total` 精準加總——冷啟動沒有依據時是 `null`。 */
  amount: number | null;
}

export interface StrategyPayload {
  allocation: StrategyAllocationItem[];
  why: string[];
  unknowns: string[];
  alternatives: unknown[];
  /** F04-I13：這一輪想學到什麼，最多 3 條；舊資料沒有這個鍵時當空陣列讀，可選。 */
  learning_goals?: string[];
}

export interface StrategyBasisFact {
  id: string;
  label: string;
  updated_at: string;
}

export interface StrategyBasisPrice {
  product_id: string;
  price: number | null;
  effective_from: string | null;
  stale: boolean;
}

export interface StrategyBasisLearning {
  id: string;
  text: string;
  level: string;
  needs_revalidation: boolean;
}

/** 查看策略依據：這個策略用到哪些品牌事實／商品價格／學習／llm_task，畫面照這個列。 */
export interface StrategyBasis {
  knowledge_item_ids: string[];
  llm_task_id: string;
  input_context_hash: string;
  brand_facts: StrategyBasisFact[];
  prices: StrategyBasisPrice[];
  learnings: StrategyBasisLearning[];
  estimated_fields: string[];
}

/** `ads_campaign.budget_basis_json` 的形狀（F03-I05 起）：策略＋預算情境＋依據，整包存在
 * Campaign 這一列，沒有另開表。 */
export interface AdsBudgetBasisJson {
  strategy: StrategyPayload;
  scenarios: BudgetScenarios;
  basis: StrategyBasis;
}

export interface SelectScenarioInput {
  scenario_key: string;
  custom_total?: number | null;
}

/** F03-I23: mirrors `app/ads/repository.py::_budget_total` exactly (days inclusive of both
 * ends, `null` when either date is missing or `days <= 0`). The browser re-derives this
 * instead of reading `campaign.budget_total` because that field is the value at load time —
 * `patchGroup` returns only the edited group, so after an edit the payload field goes stale
 * while `c.groups` (updated by the caller) stays current. */
export function currentBudgetTotal(
  c: CampaignDetail,
): { dailySum: number; days: number | null; total: number | null } {
  const dailySum = c.groups.reduce((sum, g) => sum + g.daily_budget, 0);
  if (!c.start_date || !c.end_date) return { dailySum, days: null, total: null };
  const days =
    Math.round(
      (new Date(c.end_date).getTime() - new Date(c.start_date).getTime()) / 86_400_000,
    ) + 1;
  if (days <= 0) return { dailySum, days: null, total: null };
  return { dailySum, days, total: Math.round(dailySum * days) };
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

export async function createCampaign(
  brandId: string,
  input: CreateCampaignInput,
): Promise<CampaignDraft> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/campaigns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const data = await parseJsonOrThrow<{ campaign: CampaignDraft }>(res, "建立 Campaign 失敗。");
  return data.campaign;
}

export async function patchCampaign(
  brandId: string,
  campaignId: string,
  input: PatchCampaignInput,
): Promise<CampaignDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}`,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) },
  );
  const data = await parseJsonOrThrow<{ campaign: CampaignDetail }>(res, "更新 Campaign 失敗。");
  return data.campaign;
}

export async function generateStrategy(brandId: string, campaignId: string): Promise<CampaignDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/strategy`,
    { method: "POST" },
  );
  const data = await parseJsonOrThrow<{ campaign: CampaignDetail }>(res, "產生策略失敗。");
  return data.campaign;
}

export async function selectScenario(
  brandId: string,
  campaignId: string,
  input: SelectScenarioInput,
): Promise<CampaignDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/strategy/scenario`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) },
  );
  const data = await parseJsonOrThrow<{ campaign: CampaignDetail }>(res, "選擇預算情境失敗。");
  return data.campaign;
}

/** F04-I13：採用之前調整三個角色的百分比——金額由後端 `budget.split()` 重算，這裡只送
 * `role`／`pct`。角色集合必須跟既有策略一模一樣，不是新增角色的入口。 */
export async function setAllocation(
  brandId: string,
  campaignId: string,
  allocation: { role: string; pct: number }[],
): Promise<CampaignDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/strategy/allocation`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ allocation }) },
  );
  const data = await parseJsonOrThrow<{ campaign: CampaignDetail }>(res, "調整預算分配失敗。");
  return data.campaign;
}

// -- F03-I06：採用策略 -> 投放組／廣告，以及後續編輯 ------------------------------------------

/** `POST .../campaigns/{id}/plan` — 把已採用的策略角色分配展開成投放組／廣告，草稿 -> `ready`。
 * 沒有請求體：策略跟預算都已經存在 Campaign 自己身上，這支不再重新問使用者。 */
export async function adoptStrategy(brandId: string, campaignId: string): Promise<CampaignDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/plan`,
    { method: "POST" },
  );
  const data = await parseJsonOrThrow<{ campaign: CampaignDetail }>(res, "展開投放結構失敗。");
  return data.campaign;
}

export interface CreateGroupInput {
  name: string;
  role: StrategyRole;
  daily_budget: number;
  start_date?: string | null;
  end_date?: string | null;
}

export async function createGroup(
  brandId: string,
  campaignId: string,
  input: CreateGroupInput,
): Promise<DeliveryGroupRow> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/groups`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) },
  );
  const data = await parseJsonOrThrow<{ group: DeliveryGroupRow }>(res, "新增投放組失敗。");
  return data.group;
}

/** `PATCH .../groups/{id}` — 預算只在投放組層；改到已綁定節點的任何欄位會留一列 `ads_action`。 */
export interface PatchGroupInput {
  name?: string;
  role?: StrategyRole;
  daily_budget?: number;
  start_date?: string | null;
  end_date?: string | null;
}

export async function patchGroup(
  brandId: string,
  groupId: string,
  input: PatchGroupInput,
): Promise<DeliveryGroupRow> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/groups/${encodeURIComponent(groupId)}`,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) },
  );
  const data = await parseJsonOrThrow<{ group: DeliveryGroupRow }>(res, "更新投放組失敗。");
  return data.group;
}

export async function deleteGroup(brandId: string, groupId: string): Promise<void> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/groups/${encodeURIComponent(groupId)}`,
    { method: "DELETE" },
  );
  await ensureOk(res, "刪除投放組失敗。");
}

/** 七維座標——值一律是 `brand_coordinate.key`，不是 `label`。 */
export interface AdCoordinates {
  audience: string;
  pain: string;
  angle: string;
  hook: string;
  proof: string;
  offer: string;
  format: string;
}

export interface CreateAdInput {
  group_id: string;
  name: string;
  coordinates: AdCoordinates;
}

export async function createAd(
  brandId: string,
  campaignId: string,
  input: CreateAdInput,
): Promise<AdRow> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/ads`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) },
  );
  const data = await parseJsonOrThrow<{ ad: AdRow }>(res, "新增廣告失敗。");
  return data.ad;
}

export interface PatchAdInput {
  name?: string;
  coordinates?: Partial<AdCoordinates>;
}

export async function patchAd(
  brandId: string,
  adId: string,
  input: PatchAdInput,
): Promise<AdRow> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(adId)}`,
    { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) },
  );
  const data = await parseJsonOrThrow<{ ad: AdRow }>(res, "更新廣告失敗。");
  return data.ad;
}

export async function deleteAd(brandId: string, adId: string): Promise<void> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(adId)}`,
    { method: "DELETE" },
  );
  await ensureOk(res, "刪除廣告失敗。");
}

// -- F03-I08：素材就緒 -- 交棒工作檯任務包／讀就緒狀態／手動勾「素材已就位」 -------------------

/** `POST .../campaigns/{id}/pack` — 把這個 Campaign 底下所有廣告一次交棒成一個素材工作檯
 * 任務包，回傳新建的 pack id。已經交棒過會回 400（`pack_already_exists`）。 */
export async function dispatchPack(brandId: string, campaignId: string): Promise<string> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/pack`,
    { method: "POST" },
  );
  const data = await parseJsonOrThrow<{ pack_id: string }>(res, "交棒素材工作檯失敗。");
  return data.pack_id;
}

export interface AssetsResponse extends AssetReadinessSummary {
  assets: AssetReadinessRow[];
}

export async function getAssets(brandId: string, campaignId: string): Promise<AssetsResponse> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/assets`,
  );
  return parseJsonOrThrow<AssetsResponse>(res, "讀取素材就緒狀態失敗。");
}

export async function setAssetReady(
  brandId: string,
  adId: string,
  ready: boolean,
): Promise<AdRow> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(adId)}/asset-ready`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ready }) },
  );
  const data = await parseJsonOrThrow<{ ad: AdRow }>(res, "更新素材就位狀態失敗。");
  return data.ad;
}

// -- F03-I09：手動發布／配對 -------------------------------------------------------------------

export type AdapterKey = "manual" | "auto_meta" | "simulated";

export interface AdapterOption {
  key: AdapterKey;
  label: string;
}

/** 逐節點清單的一列——campaign 節點打頭，然後每個投放組，再來是它底下每支廣告。 */
export interface PublishChecklistField {
  label: string;
  value: string | number;
  reason: string;
}

export interface PublishChecklistNode {
  level: "campaign" | "group" | "ad";
  id: string;
  name: string;
  fields: PublishChecklistField[];
}

/** `describe`：`message` 非 `null` 時（例如 `auto_meta` 的「自動發布未接上」）沒有清單可看。 */
export interface PublishDescribe {
  adapter: AdapterKey;
  message: string | null;
  checklist: PublishChecklistNode[];
}

export interface PublishGetResponse {
  adapters: AdapterOption[];
  adapter: AdapterKey;
  describe: PublishDescribe;
}

export async function getPublish(
  brandId: string,
  campaignId: string,
  adapter: AdapterKey = "manual",
): Promise<PublishGetResponse> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}`
    + `/publish?adapter=${encodeURIComponent(adapter)}`,
  );
  return parseJsonOrThrow<PublishGetResponse>(res, "讀取發布方式失敗。");
}

export async function publishCampaign(
  brandId: string,
  campaignId: string,
  adapter: AdapterKey = "manual",
): Promise<PublishDescribe> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/publish`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ adapter }) },
  );
  return parseJsonOrThrow<PublishDescribe>(res, "發布失敗。");
}

/** `POST .../bind` — 手動路徑的「配對」：精準名稱比對，逐節點由上往下。`message` 是
 * `null`（整批都配對成功）或一句話（哪些節點沒配上，§0「一次講完整批」）。 */
export interface BindResponse {
  message: string | null;
  campaign: CampaignDetail;
}

export async function bindCampaign(brandId: string, campaignId: string): Promise<BindResponse> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/bind`,
    { method: "POST" },
  );
  return parseJsonOrThrow<BindResponse>(res, "配對失敗。");
}

// -- F03-I11：成效 -----------------------------------------------------------------------------

/** 一列聚合數字——campaign 層總計、每日序列、每投放組／每廣告都是同一個形狀。`purchases`／
 * `revenue`／`cpa`／`ctr`／`roas`／`roas_conservative` 全部可能是 `null`——代表未追蹤，不是
 * 0（§0「never a percentage / never 0」的同一條精神）。 */
export interface OutcomeBucket {
  spend: number;
  impressions: number;
  clicks: number;
  purchases: number | null;
  revenue: number | null;
  cpa: number | null;
  ctr: number | null;
  /** 樂觀值——分母只算有追蹤到營收的花費。 */
  roas: number | null;
  /** 保守值——分母是這一組全部花費。兩個都給，畫面自己決定怎麼放大小字。 */
  roas_conservative: number | null;
}

export interface OutcomeDailyPoint extends OutcomeBucket {
  day: string;
}

export interface OutcomeGroupRow extends OutcomeBucket {
  group_id: string;
  name: string;
  spend_share: number | null;
}

export interface OutcomeAdRow extends OutcomeBucket {
  ad_id: string;
  name: string;
  spend_share: number | null;
}

export interface OutcomeCoverage {
  expected: number;
  missing: number;
}

/** `GET/POST .../performance` 與 `.../ingest` 共用的回應形狀（一個 action，兩邊派工，
 * §0「One endpoint」）。 */
export interface CampaignPerformance {
  totals: OutcomeBucket;
  daily: OutcomeDailyPoint[];
  groups: OutcomeGroupRow[];
  ads: OutcomeAdRow[];
  coverage: OutcomeCoverage;
  last_data_at: string | null;
}

export async function getPerformance(
  brandId: string,
  campaignId: string,
): Promise<CampaignPerformance> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/performance`,
  );
  return parseJsonOrThrow<CampaignPerformance>(res, "讀取成效失敗。");
}

/** 依這個 Campaign 怎麼發布的派工：模擬通路補到今天缺的天數；其餘拉既有的 Meta 每日拉取
 * 結果，不多打一次 Meta。回傳跟 `getPerformance` 同一份 payload。 */
export async function ingestOutcome(
  brandId: string,
  campaignId: string,
): Promise<CampaignPerformance> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/ingest`,
    { method: "POST" },
  );
  return parseJsonOrThrow<CampaignPerformance>(res, "更新成效失敗。");
}

// -- F03-I12：結案 -----------------------------------------------------------------------------

/** 提前手動結案；自動路徑（end+7d）在後端背景工作，寫的是同一個 verdict/verdict_json 形狀。 */
export async function closeCampaign(
  brandId: string,
  campaignId: string,
  reason?: string,
): Promise<CampaignDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/close`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason ?? null }),
    },
  );
  const data = await parseJsonOrThrow<{ campaign: CampaignDetail }>(res, "結案失敗。");
  return data.campaign;
}

// -- F04-I08：首頁四塊 -------------------------------------------------------------------------

export interface AdsHomeCounts {
  running: number;
  upcoming: number;
  ended: number;
  needs_decision: number;
}

/** `GET /home` 的整包 payload——一句整體判斷、四個計數、進行中的 Campaign（最多 6 張）、
 * 最近做了什麼（最多 6 筆）。不含成效、不打模型。 */
export interface AdsHome {
  headline: { text: string; facts: string };
  counts: AdsHomeCounts;
  campaigns: CampaignCard[];
  actions: AdsActionLine[];
}

export async function getAdsHome(brandId: string): Promise<AdsHome> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/home`);
  const data = await parseJsonOrThrow<{ home: AdsHome }>(res, "讀取投放中心首頁失敗。");
  return data.home;
}
