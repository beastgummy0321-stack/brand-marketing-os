/** S8 檔期作戰室 API 型別與呼叫（票 B4-warroom，契約 `.scratch/grill/GRILL-B4-warroom.md`）。
 * 型別逐字對照契約「假資料形狀（TypeScript，草案）」節；封閉列舉值（目標／漏斗階層／排期
 * 策略／受眾三層／統計等級／判讀狀態）對照後端既有常數（查證日 2026-08-12，各檔案見
 * 對應函式註解），不是自創。`CycleDetail`／`NewContext`／`HandoffData` 這幾個外層包裝形狀
 * 契約本身沒有給（契約只列了各段落各自的資料形狀），是本票把它們組成單一 GET 回應的
 * 內部決定，不是外部規格。 */
import type { CampaignStatus } from "./campaignsApi";

export type CampaignStage = "intake" | "plan" | "creative" | "handoff" | "prelaunch" | "performance" | "review";
export type FunnelStage = "exposure" | "consideration" | "conversion";
export type PacingStrategy = "continuous" | "intermittent" | "pulse";

/** GRILL-B4R-performance.md R1-2：階段條從 7 格收成 5 個自適應單頁區塊（開檔／企劃／交接／
 * 成效／覆盤）。`STAGE_ORDER` 保留原本 7 段後端階段細節（`deriveStage()` 仍回這 7 種之一），
 * `BLOCK_OF_STAGE` 是新增的分組對照表（GRILL-B4R-performance.md 194-208 行「新區塊吸收舊哪幾
 * 格」），不重寫第二份階段判定邏輯。 */
export const STAGE_BAR_LABELS = ["開檔", "企劃", "交接", "成效", "覆盤"];
export const STAGE_ORDER: CampaignStage[] = ["intake", "plan", "creative", "handoff", "prelaunch", "performance", "review"];
export const BLOCK_OF_STAGE: Record<CampaignStage, number> = {
  intake: 1,
  plan: 2,
  creative: 2,
  handoff: 3,
  prelaunch: 3,
  performance: 4,
  review: 5,
};

// app/ads/plan.py:60-72（查證日 2026-08-12）
export const FUNNEL_STAGE_LABELS: Record<FunnelStage, string> = {
  exposure: "曝光層",
  consideration: "考慮層",
  conversion: "轉換層",
};
// app/ads/plan.py 80-87
export const AUDIENCE_TIER_LABELS: Record<string, string> = {
  cold: "冷受眾（陌生開發）",
  warm: "暖受眾（再行銷）",
  hot: "熱受眾（已成交／高互動）",
};
// app/ads/pacing_curve.py:27-31
export const PACING_STRATEGY_LABELS: Record<PacingStrategy, { title: string; tag: string; desc: string }> = {
  continuous: { title: "穩定投放", tag: "連續", desc: "每天花一樣多，先求穩定" },
  intermittent: { title: "喘息投放", tag: "間歇", desc: "投3天、緩1天，避免受眾看膩" },
  pulse: { title: "衝刺投放", tag: "脈動", desc: "先穩、後衝，越接近檔期尾聲花越多" },
};
// app/ads/reading.py:69-76
export const READING_STATUS_LABELS: Record<string, string> = {
  insufficient_data: "資料還不夠",
  learning: "還在學習期",
  maintain: "維持現狀",
  scale_candidate: "可以考慮加碼",
  pause_candidate: "該考慮停下來",
  unclear_economics: "還看不出賺不賺",
};

export interface TargetCpaView {
  kind: "conversion" | "non_conversion";
  target_cpa: { value: number; basis_label: string } | null;
  volume: { weekly_conversions: number; groups_sustainable: number; cycle_creative_cap: number } | null;
  tiers: Record<string, { label: string; weekly_budget: number; formula: string; capped?: boolean; default?: boolean }>;
  range: { low: number; high: number; basis_label: string } | null;
  learning_note: string;
}

export interface StructureGroup {
  role: string;
  label: string;
  ratio: number;
  daily_budget: number;
  below_floor: boolean;
}

export interface AccountStructure {
  tier: "small" | "medium" | "large";
  tier_label: string;
  structure_label: string;
  groups: StructureGroup[];
  note: string;
}

export interface PlanOption {
  id: string;
  is_recommended: boolean;
  summary: string;
  difference: string | null;
  audience: { tiers: Record<string, { available: boolean; description?: string; reason?: string }>; exclusions: string[] };
  angles: { title: string; message: string; why?: string }[];
  hypotheses: { statement: string; verify?: string }[] | null;
}

export interface Dissent {
  id: string;
  target_type: "account_structure" | "budget_allocation" | "offer";
  suggestion: string;
  reason: string;
}

export interface RuleCardLearned {
  text: string;
}

export interface Cycle {
  id: string;
  brand_id: string;
  start_date: string;
  end_date: string;
  status: CampaignStatus;
  phase: "normal" | "simulation" | "calibration";
  objective: string;
  funnel_stage: FunnelStage | null;
  budget: number;
  duration_days: number;
  daily_budget: number;
  background: string | null;
  pacing_strategy: PacingStrategy;
  pacing_reason: string;
  archived: boolean;
  daily_below_floor: boolean;
}

export interface CycleDetail {
  cycle: Cycle;
  stage: CampaignStage;
  readiness_notes: string[];
}

export interface ChecklistItem {
  key: string;
  label: string;
  help: string;
  checked: boolean;
  checked_by: string | null;
  hint?: string | null;
  flagged?: boolean;
  flagged_reason?: string;
}

export interface AutoCheckResult {
  key: string;
  label: string;
  available: boolean;
  passed: boolean | null;
  note: string;
  /** 使用者自行勾選「已確認」（跟 `available`／`passed` 的系統覆核是兩件事，
   * S8R.16：交接總分環的過關判定看這個欄位，系統覆核只是輔助提示）。 */
  checked: boolean;
}

export interface NamingCheckResult {
  duplicates: { field: "campaign_name" | "adset_name" | "ad_name"; value: string; package_ids: string[] }[];
  missing: { package_id: string; field: string }[];
  passed: boolean;
}

export interface UtmCheckResult {
  package_id: string;
  present: string[];
  not_applicable: { param: string; reason: string }[];
  passed: boolean;
}

export interface HandoffPackage {
  id: string;
  campaign_name: string;
  adset_name: string;
  ad_name: string;
  objective_label: string;
  daily_budget: number;
  schedule_text: string;
  hook_text: string | null;
  copy_text: string | null;
  full_url: string | null;
  image_prompts: string[];
  mapping: { meta_campaign_id: string; confirmed_by: string; confirmed_at: string } | null;
}

export interface CodeAssignment {
  kind: "ad" | "voiceover";
  kind_label: string;
  code: string;
  discount_pct: number | null;
  usage_cap: number;
  valid_until: string;
}

export interface CheckpointResult {
  kind: "day3" | "day7";
  data_sufficient: boolean;
  spend_ok: boolean | null;
  learning_normal: boolean | null;
  learning_note: string;
  reach: { reach: number | null; note: string } | null;
  fatigue: { frequency: number | null; status_label: string; status: "safe" | "warn"; note: string; audience_type_label: string } | null;
}

export interface PerformanceSummary {
  spend: number;
  impressions: number;
  reach: number;
  clicks: number;
  conversions: number;
  revenue: number;
  kpis: { ctr: number | null; cpc: number | null; cpa: number | null; roas: number | null };
  discarded_rows: number;
}

export interface ReadingResult {
  status: keyof typeof READING_STATUS_LABELS;
  status_label: string;
  statistical_level: "statistical" | "directional";
  statistical_level_label: string;
  llm_explanation: string;
  reasons: string[];
}

export interface NextCycleAdvice {
  budget_advice: string;
  proposed_budget: number;
  rule_cards_created: number;
  echo_chamber: boolean;
}

/** S8R.24：訂單歸因四分類（`app/ads/codes.py:217-246 attribution_summary()`，查證日
 * 2026-08-12，形狀原樣沿用）。 */
export interface AttributionCategory {
  count: number;
  net_revenue: number;
}

export interface AttributionSummary {
  gross: AttributionCategory;
  net: AttributionCategory;
  excluded: AttributionCategory;
  natural: AttributionCategory;
}

export interface ClosingReview {
  cycle_id: string;
  goal_comparison: {
    objective_label: string;
    target: string;
    /** S8R.23 雙條圖左條：目標 CPA 或建議花費區間中點。 */
    target_value: number;
    /** S8R.23 雙條圖右條：實際算出的對應數字，算不出來時為 `null`（不給假的 0）。 */
    actual_value: number | null;
    metric_label: string;
    lower_is_better: boolean;
    actual_kpis: PerformanceSummary["kpis"];
  };
  gap_attribution: { reasons: string[]; channel_note: string | null; ga4_leak_note: string | null; attribution: AttributionSummary };
  learning: {
    hypotheses: { statement: string; verdict: "supported" | "rejected" | "inconclusive" }[];
    ledger_entries: { text: string; created_at: string }[];
  };
  recommendation: NextCycleAdvice;
}

export interface AiCostMeter {
  brand_id: string;
  spent: number;
  limit: number;
  settings_url: string;
}

/** S8R.4／S8R.5：最大虧損卡 AI 建議（GRILL-B4R-performance.md 452-457 行既有型別，逐字沿用）。 */
export interface PainSuggestion {
  amount: number;
  is_ai_suggested: boolean;
  basis_label: string;
}

export interface SliderOption {
  amount: number;
  amount_label: string;
  duration_days: number;
  daily_budget: number;
  daily_budget_label: string;
  below_floor: boolean;
  note: string;
}

/** GRILL-B4R-performance.md 修復票 R2-4：虧損卡「自己調」展開的三檔預算卡（保守／建議／
 * 積極），形狀＝`SliderOption` 加上檔位識別，直接沿用滑桿檔位（`SLIDER_STEPS`）既有欄位，
 * 不另外發明第二套金額換算（同「budget_tiers」精神：目標 CPA 三層鏈用同一套保守/建議/積極
 * 分法，見 `TargetCpaView.tiers`）。`key === "recommended"` 那筆即為 AI 建議（金額同
 * `pain_suggestion.amount`）。 */
export interface BudgetTier extends SliderOption {
  key: "conservative" | "recommended" | "aggressive";
  label: string;
}

export interface NewContext {
  offer_simulation: boolean;
  products: { id: string; name: string }[];
  slider_options: SliderOption[];
  budget_tiers: BudgetTier[];
  duration_config: { min: number; max: number; min_daily_budget: number };
  /** S8R.2：檔期長度建議（真後端 `app/ads/routes_common.py:100 _duration_suggestion()`）。 */
  duration_suggestion: { value: number; basis_label: string };
  objectives: { value: string; label: string; hint: string }[];
  recommended_objective: string;
  readiness_notes: string[];
  pain_suggestion: PainSuggestion;
}

export type NewCycleDirection =
  | { status: "ready"; direction: string }
  | { status: "empty" | "unavailable" };

/** S8R.9-11：排期到期提醒（GRILL-B4R-performance.md 459-464 行既有型別，逐字沿用）。
 * `null` 表示今天不需要調整（`continuous` 策略恆為 `null`）。 */
export interface ScheduleReminder {
  date: string;
  new_daily_budget: number;
  copy_text: string;
}

/** S8R.13-17：交接總分環（GRILL-B4R-performance.md 466-479 行既有型別，逐字沿用）。 */
export interface ReadinessRingItem {
  key: string;
  label: string;
  passed: boolean;
  section: "one_time_checklist" | "cycle_checklist" | "naming_check" | "utm_check" | "qa_launch";
  fix_anchor: string;
}

export interface ReadinessRing {
  passed: number;
  total: number;
  items: ReadinessRingItem[];
}

/** S8R.20-21／S3P.12：檔期健康燈號（GRILL-B4R-performance.md 429-445 行既有型別，逐字沿用）。 */
export type HealthLightStatus = "green" | "yellow" | "red" | "insufficient";

export interface HealthLight {
  status: HealthLightStatus;
  value: number | null;
  label: string;
  note: string;
}

export interface HealthLights {
  spend_rate: HealthLight;
  cpa: HealthLight;
  roas: HealthLight;
  fatigue: HealthLight;
}

/** R5-1／R6-3：追蹤鏈儀表的四個固定節點。
 * 欄位逐欄照 SOL 同步契約：每節點只回傳燈號、白話訊息與修復動作文字。 */
export type TrackingChainStatus = "green" | "yellow" | "red";
export type TrackingChainNodeKey = "naming" | "mapping" | "codes" | "landing_utm";

export interface TrackingChainNode {
  status: TrackingChainStatus;
  message: string;
  action: string;
}

export interface TrackingChain {
  naming: TrackingChainNode;
  mapping: TrackingChainNode;
  codes: TrackingChainNode;
  landing_utm: TrackingChainNode;
}

interface Envelope<T> {
  data: T;
  generated_at: string;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(res.status === 404 ? "找不到這筆資料。" : `讀取失敗（狀態碼 ${res.status}）`);
  const body: Envelope<T> = await res.json();
  return body.data;
}

async function postJson<T = void>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body ?? {}) });
  if (!res.ok) {
    let message = `處理失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: string };
      if (data.error) message = data.error;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const base = (brandId: string) => `/api/campaigns/${encodeURIComponent(brandId)}`;
const cycleBase = (brandId: string, cycleId: string) => `${base(brandId)}/${encodeURIComponent(cycleId)}`;

// ---- 開檔（S8.1-11）----
export const fetchNewContext = (brandId: string): Promise<NewContext> => getJson(`${base(brandId)}/new-context`);
export const fetchNewCycleDirection = (brandId: string): Promise<NewCycleDirection> =>
  getJson(`${base(brandId)}/new-context/direction`);
export const createCycle = (brandId: string, payload: Record<string, unknown>): Promise<{ cycle_id: string; message: string }> =>
  postJson(base(brandId), payload);
export const saveGuidedTargetCpa = (
  brandId: string,
  payload: { events_per_sale: number; margin_per_sale: number },
): Promise<{ value: number }> => postJson(`${base(brandId)}/target-cpa-guided`, payload);

// ---- 檔期完整狀態 ----
export const fetchCycleDetail = (brandId: string, cycleId: string): Promise<CycleDetail> => getJson(cycleBase(brandId, cycleId));
export const archiveCycle = (brandId: string, cycleId: string): Promise<void> => postJson(`${cycleBase(brandId, cycleId)}/archive`);

// ---- 企劃（S8.12-22）----
export const startPlanGeneration = (brandId: string, cycleId: string): Promise<void> => postJson(`${cycleBase(brandId, cycleId)}/plan/generate`);
export const fetchPlanStatus = (
  brandId: string,
  cycleId: string,
): Promise<{ status: "running" | "done" | "failed"; message?: string }> =>
  getJson(`${cycleBase(brandId, cycleId)}/plan/status`);
export const fetchPlanOptions = (
  brandId: string,
  cycleId: string,
): Promise<{ options: PlanOption[]; account_structure: AccountStructure; dissents: Dissent[] }> =>
  getJson(`${cycleBase(brandId, cycleId)}/plan/options`);
export const selectPlanOption = (brandId: string, cycleId: string, optionId: string): Promise<void> =>
  postJson(`${cycleBase(brandId, cycleId)}/plan/select`, { option_id: optionId });
export const decideDissent = (brandId: string, cycleId: string, dissentId: string, accepted: boolean): Promise<void> =>
  postJson(`${cycleBase(brandId, cycleId)}/dissents/${encodeURIComponent(dissentId)}/decide`, { accepted });
export const approvePlan = (brandId: string, cycleId: string): Promise<void> => postJson(`${cycleBase(brandId, cycleId)}/plan/approve`);
export const updatePacing = (brandId: string, cycleId: string, strategy: PacingStrategy, reason: string): Promise<void> =>
  postJson(`${cycleBase(brandId, cycleId)}/pacing`, { pacing_strategy: strategy, pacing_reason: reason });
export const fetchRuleCardsLearned = (brandId: string, cycleId: string): Promise<RuleCardLearned[]> =>
  getJson(`${cycleBase(brandId, cycleId)}/rule-cards-learned`);

// ---- 交接（S8.25-46）----
export const fetchChecklist = (brandId: string, cycleId: string): Promise<ChecklistItem[]> => getJson(`${cycleBase(brandId, cycleId)}/checklist`);
export const toggleChecklistItem = (brandId: string, cycleId: string, scope: "one-time" | "cycle", itemKey: string): Promise<void> =>
  postJson(`${cycleBase(brandId, cycleId)}/checklist/${scope}/${encodeURIComponent(itemKey)}`);
export const toggleQaLaunchItem = (brandId: string, cycleId: string, itemKey: string): Promise<void> =>
  postJson(`${cycleBase(brandId, cycleId)}/handoff/qa-launch/${encodeURIComponent(itemKey)}`);
export const fetchAutoChecks = (brandId: string, cycleId: string): Promise<AutoCheckResult[]> =>
  getJson(`${cycleBase(brandId, cycleId)}/handoff/qa-auto-check`);
export const fetchNamingCheck = (brandId: string, cycleId: string): Promise<{ naming: NamingCheckResult; utm: UtmCheckResult[] }> =>
  getJson(`${cycleBase(brandId, cycleId)}/handoff/naming-check`);
export const fetchHandoff = (
  brandId: string,
  cycleId: string,
): Promise<{ packages: HandoffPackage[]; codes: CodeAssignment[]; codes_verify_mismatch: string[] | null; account_structure: AccountStructure }> =>
  getJson(`${cycleBase(brandId, cycleId)}/handoff`);
export const buildHandoffPackages = (brandId: string, cycleId: string): Promise<void> => postJson(`${cycleBase(brandId, cycleId)}/handoff/build`);
export const generateCodes = (brandId: string, cycleId: string, discountPct: number): Promise<void> =>
  postJson(`${cycleBase(brandId, cycleId)}/handoff/codes`, { discount_pct: discountPct });
export const verifyCodes = (brandId: string, cycleId: string): Promise<{ mismatches: string[] }> =>
  postJson(`${cycleBase(brandId, cycleId)}/handoff/codes/verify`);
export const activatePackage = (brandId: string, cycleId: string, packageId: string, metaCampaignId: string): Promise<void> =>
  postJson(`${cycleBase(brandId, cycleId)}/handoff/${encodeURIComponent(packageId)}/activate`, { meta_campaign_id: metaCampaignId });

// ---- 企劃排期到期提醒（S8R.9-11）----
export const fetchScheduleReminder = (brandId: string, cycleId: string): Promise<ScheduleReminder | null> =>
  getJson(`${cycleBase(brandId, cycleId)}/schedule-reminder`);

// ---- 交接總分環（S8R.13-17）----
export const fetchReadiness = (brandId: string, cycleId: string): Promise<ReadinessRing> => getJson(`${cycleBase(brandId, cycleId)}/readiness`);

// ---- 追蹤鏈儀表（R5-1／R5-2／R6-3）----
export const fetchTrackingChain = (brandId: string, cycleId: string): Promise<TrackingChain> =>
  getJson(`${cycleBase(brandId, cycleId)}/tracking-chain`);

/** mapping 黃燈的唯一確認入口；後端沿用 handoff.authorize_and_map 寫入。 */
export const confirmTrackingMapping = (brandId: string, cycleId: string): Promise<void> =>
  postJson(`${cycleBase(brandId, cycleId)}/tracking-chain/mapping/confirm`);

// ---- 檔期健康燈號（S8R.20-21）----
export const fetchHealthLights = (brandId: string, cycleId: string): Promise<HealthLights> => getJson(`${cycleBase(brandId, cycleId)}/health-lights`);

// ---- 期中檢查點（S8.47-50）----
export const fetchCheckpoint = (brandId: string, cycleId: string, kind: "day3" | "day7"): Promise<CheckpointResult> =>
  getJson(`${cycleBase(brandId, cycleId)}/checkpoint/${kind}`);

// ---- 成效（S8.51-58）----
export const fetchPerformance = (
  brandId: string,
  cycleId: string,
): Promise<{ summary: PerformanceSummary | null; reading: ReadingResult | null; confidence_label: string; last_synced_at?: string | null }> =>
  getJson(`${cycleBase(brandId, cycleId)}/performance`);
export const simulatePerformance = (brandId: string, cycleId: string): Promise<void> =>
  postJson(`${cycleBase(brandId, cycleId)}/performance/simulate`);

// ---- 覆盤（S8.59-66）----
export const fetchClosingReview = (brandId: string, cycleId: string): Promise<ClosingReview> =>
  getJson(`${cycleBase(brandId, cycleId)}/closing-review`);

// ---- 右欄 AI 花費儀表（跟 B3 同一份品牌層數字，見契約「任務流版型」節）----
export const fetchAiCostMeter = (brandId: string): Promise<AiCostMeter> => getJson(`${base(brandId)}/ai-cost-meter`);

/** 預算換算（app/ads/budget.py:48-73 plan_from_pain，查證日 2026-08-12，純函數原樣搬）：
 * 14 天為預設檔期長度，金額太小時縮短天數把日預算撐到下限之上。 */
export function planFromPain(painValue: number): { durationDays: number; dailyBudget: number; belowFloor: boolean } {
  const MIN_DAILY_BUDGET = 300;
  const DEFAULT_DURATION_DAYS = 14;
  const MIN_DURATION_DAYS = 7;
  const MAX_DURATION_DAYS = 30;
  let days = DEFAULT_DURATION_DAYS;
  if (painValue / days < MIN_DAILY_BUDGET) {
    days = Math.max(MIN_DURATION_DAYS, Math.floor(painValue / MIN_DAILY_BUDGET));
  }
  days = Math.min(days, MAX_DURATION_DAYS);
  const daily = Math.round((painValue / days) * 100) / 100;
  return { durationDays: days, dailyBudget: daily, belowFloor: daily < MIN_DAILY_BUDGET };
}
