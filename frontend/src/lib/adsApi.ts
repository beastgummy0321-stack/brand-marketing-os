import type { ResultEvidence } from "./adsTriageApi";
export type { ResultEvidence } from "./adsTriageApi";
import type { AdapterKey, PublishDescribe, PublishGetResponse } from "./adsPublishTypes";
export type { AdapterKey, AdapterOption, PublishChecklistField, PublishChecklistNode, PublishDescribe, PublishGetResponse } from "./adsPublishTypes";
/** 投放中心 API 型別與呼叫（F03-I01），對應 `app/ads/routes.py`；後續票在這裡加，不重排既定形狀。
 * 錯誤：回應一律交給 `http.readJson`／`throwIfFailed`（F51 Contract H），失敗是 `ApiResponseError`（`code`／`details`）。 */
import { apiFetch, isRejected, readJson, throwIfFailed, type ApiResponseError } from "./http";
import type { ExternalCampaignFields, ExternalView } from "./adsExternalApi";
import type { ManualHandoff } from "./adsLaunchApi";
// F27-I06 800-line gate: `CampaignCapacity` moved to `adsTriageApi.ts` (its own owner lookup
// touches `triage_capacity.py`/`triage_scale.py`, already documented there) -- imported back
// here as a type only, so `CampaignData.capacity` keeps the one shared shape.
import type { CampaignCapacity, CampaignObjectiveFamily, CapView } from "./adsTriageApi";
import type { NextPeriodSource } from "./adsWizardApi";
import type { CampaignContextJson, CampaignCreateExtras } from "./adsCampaignTypes";
import type { BudgetAdvice, BudgetPreview, BudgetScenarioRow, PlanCapacity, PlanMenuRow, ResplitRow, StrategyBasis, StrategyPayload, StrategyRole } from "./adsStrategyTypes";

export type CampaignStatus = "draft" | "ready" | "live" | "ended" | "closed";
export type LocalState = "unbound" | "bound" | "detached" | "retired";

/** F49 Contract L (`app/ads/lifecycle.py`): the served campaign lifecycle — screens branch on `state` and print
 * `label`; 結案 shows only when `can_close`. */
export type LifecycleState = "draft" | "live" | "ended" | "closed";
export interface CampaignLifecycle { state: LifecycleState; label: string; can_close: boolean }
/** F49 Contract L: one platform object's served delivery (its adapter's status table); `unknown` is never dropped. */
export type DeliveryState = "running" | "not_running" | "off" | "unknown";
export interface DeliveryView { state: DeliveryState; label: string }
/** F49 Contract L: 「在投」 = `count` running ads; `unknown` ads apart; `read_at` = the newest clean structure read,
 * `stale` when it is older than the newest launch item the user reported done. */
export interface RunningAds {
  count: number; unknown: number; read_at: string | null; stale: boolean;
  /** F52 Contract L: additive actual adapter/structure facts; absent legacy fields remain unknown. */
  not_running?: number; off?: number; scheduled?: number;
  state?: DeliveryState; label?: string; reason?: string;
  freshness?: "read" | "unread" | "stale" | "partial" | "failed" | "syncing";
}
/** Navigation descriptors are passed to existing adsRoutes builders; never reconstruct delivery in a view. */
export interface CampaignNextAction {
  id: "review_checklist" | "prepare_campaign" | "review_period" | "view_delivery" | "read_platform" | "view_performance";
  label: string; reason: string;
  target: {kind: "campaign"; tab: "strategy" | "assets" | "perf" | "structure"} | {kind: "flow"; parts: string[]};
}

export interface CampaignOutcomeTotals {
  spend: number | null;
  purchases: number | null;
  revenue: number | null;
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
  currency?: string | null;
  budget_currency?: "TWD";
  reason?: string | null;
  scope?: PerformanceScope | null;
}

/** F24-I01: campaign-level sync status, read-only from `context_json.external_sync` plus the
 * platform-bound-accounts check (`app/ads/repository.py::campaign_sync_state`). Priority order
 * `never` (no `external_sync` recorded at all) / `disconnected` (a (platform, source_account)
 * pair of the campaign's entities isn't among the reader's bound accounts) / `auth_expired`
 * (F27-I09: the failing section's own stored error code reads as an auth error) / `failed` (any
 * other section `status` was `"error"`/`"partial"`) / `syncing` / `ok`. `last_success_at` is the
 * newest section value across sections — a failed sync keeps the OLD value, so this can be
 * stale, never "recent", when `state` is `"failed"`/`"auth_expired"`. Shared by
 * `CampaignCard.data.sync` here and `CampaignTriage.data.sync` (`adsTriageApi.ts`). */
export type CampaignSyncStatus = "ok" | "syncing" | "failed" | "disconnected" | "never" | "auth_expired";
export interface CampaignSyncState {
  state: CampaignSyncStatus;
  error: string | null;
  last_success_at: string | null;
}
export interface CampaignData {
  sync: CampaignSyncState;
  /** F27-I06: optional for the same `do_not_touch`-vs-`touch` scope conflict noted on `data`
   * below -- existing hand-written `data: {sync: ...}` fixtures can't be reached to add it. Real
   * responses always carry it (`repository.py::list_campaigns`). */
  capacity?: CampaignCapacity;
}

/** F05-I12：`app/ads/judgment.py::conversion_labels()`——這個品牌的「購買」該叫什麼名字。
 * 每一個 Campaign payload（列表／詳情）都跟著出去，畫面不再自己寫死「購買」。 */
export interface CampaignLabels {
  conversion: string;
  count: string;
  cpa: string;
}

/** `GET /campaigns` 一列。`budget_total` 是後端推導出來的（`sum(投放組.daily_budget) x 天數`），
 * `budget_planned` 是使用者採用的情境金額——兩者可能因為天數捨入而略有出入，畫面上要分開標。 */
export interface CampaignCard extends ExternalCampaignFields {
  id: string;
  name: string;
  status: CampaignStatus;
  lifecycle?: CampaignLifecycle;
  running?: RunningAds;
  next_action?: CampaignNextAction;
  start_date: string | null;
  end_date: string | null;
  objective: string; // F27-I09: `campaign_objective` optional, see `adsTriageApi.ts`.
  campaign_objective?: CampaignObjectiveFamily; created_at: string;
  created_by: string | null;
  budget_planned: number | null;
  budget_total: number | null;
  budget_progress: CampaignBudgetProgress;
  judgment: CampaignJudgment;
  outcome: CampaignOutcomeTotals;
  /** F05-I12：後端一律回傳；選填只為了既有手寫 fixture（`AdsHomePage`／`AllCampaignsPage` 測試）。 */
  labels?: CampaignLabels;
  /** F24-I01：後端一律回傳（`repository.py::list_campaigns`）；選填只是同 `labels` 的先例——
   * 這次 `do_not_touch`（`frontend/src/components/ads/**\/*.tsx`）在 harness 的 `scopeDenial`
   * 裡比 `touch` 的 `**\/*.test.tsx` 先判，蓋掉了原本該給的例外，既有的手寫測試 fixture 補不了
   * 這個新欄位（issue 已回報，不擴權限硬改）。 */
  data?: CampaignData;
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
  /** Current stored targeting and scene; optional only for older fixtures. */
  customer_group_id?: string | null;
  scene?: string | null;
  product_id: string | null;
  asset_ready_source: "workbench" | "manual" | null;
  asset_ready_by: string | null;
  asset_ready_at: string | null;
  /** F48 Contract K: 「沿用上一期」 on an ad carried from the previous period (`null` otherwise); `carry_note` says
   * what is still missing (the previous creative was not found). Optional only for hand-written fixtures. */
  carried_label?: string | null;
  carry_note?: string | null;
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
export interface CampaignDetail extends EntityBinding, ExternalCampaignFields {
  budget_advice?: BudgetAdvice | null;
  simulation_mode?: boolean;
  manual_handoff?: ManualHandoff;
  id: string;
  name: string;
  goal_text: string | null;
  objective: string;
  /** F28-I01: the one cost-per-result cap (`app/ads/targets.py::resolve`); F43-I04: `knowledge_product_id` is the
   * sell-way's first knowledge product (null without a product) — 「去填商品成本」 opens its 賣法與價格 step. */
  cap: CapView & { knowledge_product_id?: string | null };
  start_date: string | null;
  end_date: string | null;
  status: CampaignStatus;
  lifecycle?: CampaignLifecycle;
  running?: RunningAds;
  next_action?: CampaignNextAction;
  budget_planned: number | null;
  budget_scenario: string | null;
  /** 產生策略前是 `{}`；F03-I05 起是 `AdsBudgetBasisJson`——讀前先檢查 `.strategy` 存不存在。 */
  budget_basis_json: Partial<AdsBudgetBasisJson>;
  budget_total: number | null;
  context_json: CampaignContextJson & { next_period_source?: NextPeriodSource };
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
  /** F04-I08：同 `CampaignCard.judgment`（`campaign_judgment()`）；後端一律回傳，選填只為了既有手寫 fixture。 */
  judgment?: CampaignJudgment;
  /** F04-I08：`actions` 每列跑過 `judgment.action_line()` 的三句話；`actions` 保留給別的分頁。 */
  action_lines?: AdsActionLine[];
  /** F05-I12：同 `CampaignCard.labels`；選填只為了既有測試 fixture，後端不會漏。 */
  labels?: CampaignLabels;
  /** F42-I02 (`app/ads/materials_in_hand.py`): the brand's offers／proof／media the plan may use; `null` on an
   * imported campaign. Optional only for hand-written fixtures. */
  materials?: {
    offers: { key: string; label: string; sentence: string }[];
    proof: { key: string; label: string; text: string }[];
    media: "photo" | "photo_video" | null;
  } | null;
  /** F48 Contract M: the chosen total's whole daily and real period total (`null` before a total is chosen). */
  budget_preview?: BudgetPreview | null;
  /** F48-I06: this period's coordinate menu and capacity (`plan.served`); `null` on an imported campaign, capacity
   * also `null` while the cap or the budget is unknown. Optional only for hand-written fixtures. */
  menu?: PlanMenuRow[] | null;
  capacity?: PlanCapacity | null;
  /** F50 Contract J (`app/ads/busy.py`): the planner call still running for this campaign, else `null`. */
  busy?: CampaignBusy | null;
  /** F51 Contract F: the closeout sentence the learning ledger stored (`learning.closed_sentence`); `null` before closeout. */
  learning_sentence?: string | null;
}

/** F50 Contract J: `since` = the ISO instant the running call started. */
export interface CampaignBusy { kind: "strategy" | "plan" | "brief"; since: string }
/** F50 Contract J: a planner refusal's 502 `error.details` (`message` already ends with 「（reason）」);
 * `refusal` names the rule (`plan.REFUSALS`／`strategy.REFUSALS`). 409 `campaign_busy` = a call still runs. */
export interface PlannerRefusalDetails { refusal: string; reason: string }

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
  /** 交棒過的任務包 id，讀自 pack 本身（§6.2 決議 15）；後端一律回傳，選填只為了既有 fixture。 */
  pack_id?: string | null;
}

/** `POST /campaigns` 的回應：`CampaignDetail` 加一個 transient 的 `parsed` 旗標（F03-I03）——
 * AI 有沒有解析出這次投放的目標；`false` 時欄位仍然是一組可用的預設值，不落地，只存在這次
 * 回應裡，畫面用它決定要不要提示使用者檢查一下 AI 填的內容。 */
export interface CampaignDraft extends CampaignDetail {
  parsed: boolean;
  /** F50 Contract J: why the sentence was not read (`brief.REFUSALS`); `null` when it was. */
  parse_refusal?: { code: string; reason: string } | null;
}

// F40-I12: `FieldSource` / `CampaignFieldSources` / `CampaignCreateExtras` / `CampaignContextJson` live in
// `adsCampaignTypes.ts` (this file's 800-line cap); pages import them from there.

/** `POST /campaigns` 的請求體——一句話＋選填的投放期間（兩個都留空讓行銷駕駛艙從句子判斷）
 * ＋選填的額外限制。 */
export interface CreateCampaignInput extends CampaignCreateExtras {
  goal_text: string;
  start_date?: string;
  end_date?: string;
  constraints?: Record<string, unknown>;
}

/** `PATCH /campaigns/{id}` 的請求體——草稿欄位的一般編輯，不是 `ads_action`。所有欄位選填，
 * 沒帶到的欄位維持原樣。上限不在這裡改（F28-I01：`PUT .../target`）。 */
export interface PatchCampaignInput {
  goal_text?: string;
  name?: string;
  objective?: string;
  start_date?: string;
  end_date?: string;
  constraints_json?: Record<string, unknown>;
  product_ids?: string[];
  /** 受眾方向（舊活動的自由文字）；空字串清掉。 */
  audience_hint?: string | null;
  /** F43-I18：這期投的顧客群（這個賣法的群）；`[]`＝全部群。換賣法而沒帶這個鍵時，後端重設為新賣法的全部群。 */
  customer_group_ids?: string[];
  /** F40-I04 (2b)：活動層落地頁 `context_json.landing_url`；`null`／空字串清掉。 */
  landing_url?: string | null;
}

// -- F03-I05：策略（POST .../strategy 與 .../strategy/scenario）------------------------------

export type BudgetScenarioMode = "cold_start" | "history";
export type BudgetScenarioKey = "minimum" | "recommended" | "aggressive" | "conservative";

/** `app/ads/budget.py::scenarios()` 的整包回傳——程式算的，AI 只預填百分比。 */
export interface BudgetScenarios {
  advice?: BudgetAdvice | null;
  mode: BudgetScenarioMode;
  scenarios: BudgetScenarioRow[];
  recommended: string | null; // Served recommendation; null must not select the legacy "recommended" comparison key.
  basis: Record<string, unknown>;
  budget_cap: number | null; // F28-I03: `constraints_json.budget`; unset／0／negative -> null
}

// F41-I04: the strategy shapes live in `adsStrategyTypes.ts` (this file's 800-line cap); re-exported here.
export type { BudgetScenarioRow, StrategyRole, StrategyAllocationItem, StrategyPayload, StrategyDecision, StrategyAssignmentFacts, StrategyFact, BudgetPreview, ResplitRow, PlanMenuRow, PlanCapacity, StrategyBasisFact, StrategyBasisPrice, StrategyBasisLearning, StrategyCoordinateLearning, StrategyBasis } from "./adsStrategyTypes";

/** `ads_campaign.budget_basis_json` 的形狀（F03-I05 起）：策略＋預算情境＋依據，整包存在
 * Campaign 這一列，沒有另開表。 */
export interface AdsBudgetBasisJson {
  strategy: StrategyPayload;
  scenarios: BudgetScenarios;
  basis: StrategyBasis;
  over_cap_confirmation?: { by: string; at: string; total: number; cap: number; over: number }; // F28-I03
}

export interface SelectScenarioInput {
  scenario_key: string;
  custom_total?: number | null;
}

export const BASE = "/api/ads";

export async function listCampaigns(brandId: string): Promise<CampaignCard[]> {
  const res = await apiFetch(`${BASE}/brands/${encodeURIComponent(brandId)}/campaigns`);
  const data = await readJson<{ campaigns: CampaignCard[] }>(res, "讀取 Campaign 清單失敗。");
  return data.campaigns;
}

export async function getCampaign(brandId: string, campaignId: string): Promise<CampaignDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}`,
  );
  const data = await readJson<{ campaign: CampaignDetail }>(res, "讀取 Campaign 失敗。");
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
  const data = await readJson<{ campaign: CampaignDraft }>(res, "建立 Campaign 失敗。");
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
  const data = await readJson<{ campaign: CampaignDetail }>(res, "更新 Campaign 失敗。");
  return data.campaign;
}

export async function generateStrategy(brandId: string, campaignId: string): Promise<CampaignDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/strategy`,
    { method: "POST" },
  );
  const data = await readJson<{ campaign: CampaignDetail }>(res, "產生策略失敗。");
  return data.campaign;
}

/** F28-I03: a total above the budget cap needs `{ confirmOverCap: true }`, else 409 `over_cap_unconfirmed`.
 * F48 decision 8: `resplit` lists the ad sets a new total re-split after adoption (`null` on a draft); a campaign
 * with an ad set on the platform → 409 `campaign_bound` (the server's sentence is the error). */
export interface SelectScenarioResult { campaign: CampaignDetail; resplit: ResplitRow[] | null }
export async function selectScenario(
  brandId: string,
  campaignId: string,
  input: SelectScenarioInput,
  options: { confirmOverCap?: boolean } = {},
): Promise<SelectScenarioResult> {
  const body = options.confirmOverCap ? { ...input, confirm_over_cap: true } : input;
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/strategy/scenario`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
  );
  const data = await readJson<{ campaign: CampaignDetail; resplit?: ResplitRow[] | null }>(res, "選擇預算情境失敗。");
  return { campaign: data.campaign, resplit: data.resplit ?? null };
}

/** F28-I03: editable in any status; a positive integer sets, `null` clears. Internal only. */
export async function setBudgetCap(brandId: string, campaignId: string, budgetCap: number | null): Promise<CampaignDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/strategy/budget-cap`,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ budget_cap: budgetCap }) },
  );
  return (await readJson<{ campaign: CampaignDetail }>(res, "更新預算上限失敗。")).campaign;
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
  const data = await readJson<{ campaign: CampaignDetail }>(res, "調整預算分配失敗。");
  return data.campaign;
}

// -- F03-I06：採用策略 -> 投放組／廣告，以及後續編輯 ------------------------------------------

/** `POST .../campaigns/{id}/plan` — 把已採用的策略角色分配展開成投放組／廣告，草稿 -> `ready`。
 * Approves the revision currently displayed; retries retain the operation identity. */
export async function adoptStrategy(brandId: string, campaignId: string,
  approval: { expected_revision: string; operation_id: string }): Promise<CampaignDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/plan`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(approval) },
  );
  const data = await readJson<{ campaign: CampaignDetail }>(res, "展開投放結構失敗。");
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
  const data = await readJson<{ group: DeliveryGroupRow }>(res, "新增投放組失敗。");
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
  const data = await readJson<{ group: DeliveryGroupRow }>(res, "更新投放組失敗。");
  return data.group;
}

export async function deleteGroup(brandId: string, groupId: string): Promise<void> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/groups/${encodeURIComponent(groupId)}`,
    { method: "DELETE" },
  );
  await throwIfFailed(res, "刪除投放組失敗。");
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
  const data = await readJson<{ ad: AdRow }>(res, "新增廣告失敗。");
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
  const data = await readJson<{ ad: AdRow }>(res, "更新廣告失敗。");
  return data.ad;
}

export async function deleteAd(brandId: string, adId: string): Promise<void> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/ads/${encodeURIComponent(adId)}`,
    { method: "DELETE" },
  );
  await throwIfFailed(res, "刪除廣告失敗。");
}

// -- F03-I08：素材就緒 -- 交棒工作檯任務包／讀就緒狀態／手動勾「素材已就位」 -------------------

/** `POST .../campaigns/{id}/pack` — 把這個 Campaign 底下所有廣告一次交棒成一個素材工作檯
 * 任務包，回傳新建的 pack id。已經交棒過會回 400（`pack_already_exists`）。F48 Contract K：每則都是素材已備妥的
 * 沿用廣告時沒有東西要做，回 `null`（`nothing_to_prepare`）。 */
export async function dispatchPack(brandId: string, campaignId: string): Promise<string | null> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/pack`,
    { method: "POST" },
  );
  const data = await readJson<{ pack_id: string | null }>(res, "交棒素材工作檯失敗。");
  return data.pack_id;
}

export interface AssetsResponse extends AssetReadinessSummary {
  assets: AssetReadinessRow[];
}

export async function getAssets(brandId: string, campaignId: string): Promise<AssetsResponse> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/assets`,
  );
  return readJson<AssetsResponse>(res, "讀取素材就緒狀態失敗。");
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
  const data = await readJson<{ ad: AdRow }>(res, "更新素材就位狀態失敗。");
  return data.ad;
}

// -- F03-I09：手動發布 -------------------------------------------------------------------------

export async function getPublish(
  brandId: string,
  campaignId: string,
  adapter: AdapterKey = "manual",
): Promise<PublishGetResponse> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}`
    + `/publish?adapter=${encodeURIComponent(adapter)}`,
  );
  return readJson<PublishGetResponse>(res, "讀取發布方式失敗。");
}

export async function publishCampaign(
  brandId: string,
  campaignId: string,
  adapter: AdapterKey = "manual",
  approval?: { operation_id: string; content_hash: string },
): Promise<PublishDescribe> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/publish`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ adapter, ...approval }) },
  );
  return readJson<PublishDescribe>(res, "發布失敗。");
}

// -- F03-I11：成效 -----------------------------------------------------------------------------

/** 一列聚合數字——campaign 層總計、每日序列、每投放組／每廣告都是同一個形狀。`purchases`／
 * `revenue`／`cpa`／`ctr`／`roas_tracked_spend`／`roas_all_spend` 全部可能是 `null`——代表未追蹤，不是
 * 0（§0「never a percentage / never 0」的同一條精神）。F51 Contract F：ROAS 的 key 就是它的口徑代碼。 */
export interface OutcomeBucket {
  spend: number | null;
  impressions: number | null;
  clicks: number | null;
  currency?: string | null;
  attribution_key?: string | null;
  reason?: string | null;
  purchases: number | null;
  revenue: number | null;
  cpa: number | null;
  ctr: number | null;
  /** 樂觀值——分母只算有追蹤到營收的花費。 */
  roas_tracked_spend: number | null;
  /** 保守值——分母是這一組全部花費。兩個都給，畫面自己決定怎麼放大小字。 */
  roas_all_spend: number | null;
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

/** F37 Contract P: coverage of the platform read over the campaign window (`start_date` …
 * min(end_date, org yesterday)). `never_synced` = the platform was never read, not "nothing missing". */
export interface OutcomeCoverage {
  start: string | null;
  end: string | null;
  expected: number;
  missing: number;
  missing_days: string[];
  never_synced: boolean;
}

/** F40-I01: the period's one-ruler grade (`app/ads/outcome.py::_period_grade` through
 * `triage.grade_window`) the 成效分頁's 「這期狀態列」 prints beside 整期合計 -- the backend's answer,
 * never a frontend copy of the ruler. `label` is the word to show as is. */
export interface PeriodGrade {
  grade: "on_target" | "watch" | "over" | "wasted" | "insufficient" | "no_target";
  label: string;
}

/** `GET .../performance` 的回應形狀——數字只來自平台同步表（F37 Contract P）。 */
export interface CampaignPerformance {
  /** `grade` is optional only for hand-written test fixtures; real responses always carry it (F40-I01). */
  totals: OutcomeBucket & { grade?: PeriodGrade };
  daily: OutcomeDailyPoint[];
  groups: OutcomeGroupRow[];
  ads: OutcomeAdRow[];
  coverage: OutcomeCoverage;
  last_data_at: string | null;
  /** Observed goal results; purchase/revenue totals retain their original unit. */
  result_view?: ResultEvidence;
  /** Optional for historical client fixtures; current responses name their actual period. */
  scope?: PerformanceScope;
  cap_comparison?: { basis: string | null; currency: string | null; reason: string | null;
    message: string | null; source?: string | null; unit_basis?: string | null };
}


export interface PerformanceScope {
  start: string | null;
  end: string | null;
  days: number;
  basis: "campaign_window" | "requested_range";
  state: "ready" | "missing_dates" | "future";
  last_complete_day: string;
  incomplete_day_policy: "excluded";
  day_basis: "account_timezone" | "conservative_org_fallback";
  account_timezone: string | null;
  account_currency?: string | null;
  currency?: string | null;
  attribution_key?: string | null;
  reason?: string | null;
  caption: string;
  reason_text?: string | null;
}

export interface ImportedCampaignPerformance {
  origin: "imported";
  external_view: ExternalView & { scope?: PerformanceScope };
}
export function getPerformance(brandId: string, campaignId: string): Promise<CampaignPerformance>;
export function getPerformance(brandId: string, campaignId: string, imported: true): Promise<ImportedCampaignPerformance>;
export function getPerformance(brandId: string, campaignId: string, imported?: boolean): Promise<CampaignPerformance | ImportedCampaignPerformance>;
export async function getPerformance(
  brandId: string,
  campaignId: string,
  _imported?: boolean,
): Promise<CampaignPerformance | ImportedCampaignPerformance> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/performance`,
  );
  return readJson<CampaignPerformance | ImportedCampaignPerformance>(res, "讀取成效失敗。");
}

// -- F03-I12：結案 -----------------------------------------------------------------------------

/** F37 Contract Q/S: the close route refuses a window the platform read does not cover with 409
 * `coverage_missing`; `error.details` names the days and whether the skip is open (`can_skip`, only
 * after the last platform read failed). F51 Contract H: the refusal is an `ApiResponseError` with that
 * code; `coverageGapOf` reads its details (`null` for any other failure). */
export interface CoverageGap {
  missing_days: string[];
  never_synced: boolean;
  can_skip: boolean;
}

export function coverageGapOf(err: unknown): CoverageGap | null {
  if (!isRejected(err, "coverage_missing")) return null;
  const d = (err as ApiResponseError).details as { missing_days?: unknown; never_synced?: unknown; can_skip?: unknown } | null;
  if (!d || typeof d !== "object") return null;
  return {
    missing_days: Array.isArray(d.missing_days) ? d.missing_days.filter((x): x is string => typeof x === "string") : [],
    never_synced: d.never_synced === true,
    can_skip: d.can_skip === true,
  };
}

/** 手動結案——結案永遠是使用者動作，沒有活動過了結束日就自動結案這回事（F16-I05）。
 * `skip_missing` 只在 `coverageGapOf(err).can_skip` 之後由使用者明確選擇（F37 ruling 3）。 */
export async function closeCampaign(
  brandId: string,
  campaignId: string,
  body: { reason?: string; skip_missing?: boolean } = {},
): Promise<CampaignDetail> {
  const res = await apiFetch(
    `${BASE}/brands/${encodeURIComponent(brandId)}/campaigns/${encodeURIComponent(campaignId)}/close`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: body.reason ?? null, skip_missing: body.skip_missing ?? false }),
    },
  );
  const data = await readJson<{ campaign: CampaignDetail }>(res, "結案失敗。");
  return data.campaign;
}

