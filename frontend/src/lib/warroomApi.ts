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
export type OfferType = "discount" | "bundle" | "gift";

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
// app/ads/offer.py:TYPES（票 V1-01）
export const OFFER_TYPE_LABELS: Record<OfferType, string> = {
  discount: "折扣",
  bundle: "組合",
  gift: "贈品",
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

/** 切角格現名（票 04-angle-rename 一.3）：`PlanOption.angles[]` 是選定當下的快照，改名後
 * 不會跟著變——提案書畫面顯示切角標題要以這份為準（對應 `app/ads/plan.py
 * list_cell_angles()`），順序跟 `angles[]` 依 index 對齊（同一批 `_persist()` 依序寫入）。 */
export interface PlanCellAngle {
  id: string;
  creative_angle: string;
}

export interface Dissent {
  id: string;
  target_type: "account_structure" | "budget_allocation" | "offer";
  suggestion: string;
  reason: string;
}

export interface RuleCardLearned {
  id: string;
  text: string;
}

// app/ads/offer.py（票 V1-01）：PUT `.../offer` 200 回應跟 Cycle.offer 是同一個形狀。
export interface Offer {
  id: string;
  name: string;
  offer_type: OfferType;
  offer_type_label: string;
  terms: string;
  valid_from: string;
  valid_to: string;
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
  plan_version: number;
  offer: Offer | null;
}

export interface CycleDetail {
  cycle: Cycle;
  stage: CampaignStage;
  readiness_notes: ReadinessNote[];
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
  kpis: { ctr: number | null; cpc: number | null; cpa: number | null; roas: number | null; cpm: number | null; cvr: number | null };
  discarded_rows: number;
}

export interface CsvImportResult {
  imported: number;
  quarantined: number;
  skipped: number;
  matched_assets: number;
  unmatched_columns: string[];
  warnings: string[];
  // 已判讀過的檔期補匯數字會自動重判（ADR 0022 第 2 點，
  // app/ads/routes_campaigns_performance_api.py _late_data_rerun）：
  // live_reading＝LIVE 檔期第一次判讀、late_data＝重算且有變、
  // unchanged＝重算但結論一樣、skipped＝沒有資料可判讀。
  rerun: "live_reading" | "late_data" | "unchanged" | "skipped";
  rerun_message: string | null;
}

// app/ads/reading_assets.py asset_totals()（_asset_totals()，reading.py:393-417）——
// 只有 CSV 匯入時廣告名稱對回已授權素材的資料列才會出現在這裡，對不上的不硬湊一列（鐵則 16）。
export interface AssetBreakdownRow {
  pkg_id: string;
  asset_name: string;
  impressions: number;
  clicks: number;
  spend: number;
  conversions: number;
  revenue: number;
  kpis: { ctr: number | null; cpc: number | null; cpa: number | null; roas: number | null; cpm: number | null; cvr: number | null };
  // B0-33 修復（票 R4-late-data-downstream）：`app/ads/reading_assets.py asset_totals()`
  // 已經比過損益兩平算好——只有真的低於打平線的最低那（幾）支才是 true，不是前端自己
  // 找 rows 裡最小值就標紅（原本的 bug：三支比例相近的廣告翻盤轉盈後，因為還是「並列最
  // 低」而繼續全部掛紅標）。
  dragging_down_cycle: boolean;
}

export interface ReadingResult {
  status: keyof typeof READING_STATUS_LABELS;
  status_label: string;
  statistical_level: "statistical" | "directional";
  statistical_level_label: string;
  llm_explanation: string;
  reasons: string[];
  // 契約 C：可能不存在（舊資料／後端尚未接線）或空陣列（沒有對得回素材的成效列）。
  asset_breakdown?: AssetBreakdownRow[];
}

/** 票 C2-01：錢卡在哪一關（`app/ads/bottleneck.py diagnose()`，逐欄照後端 envelope）。
 * `reliable: false` 時只有 `reason_unreliable` 有意義，其餘欄位不列入判讀。 */
export interface BottleneckFactor {
  key: "cpm" | "ctr" | "cvr";
  label: string;
  ratio: number | null;
  share: number | null;
  detail: string;
  sub: "audience_too_narrow" | null;
}

export interface BottleneckResult {
  reliable: boolean;
  reason_unreliable: string | null;
  underspend: boolean;
  cpa_ratio: number | null;
  primary: "cpm" | "ctr" | "cvr" | null;
  factors: BottleneckFactor[];
  reference: { ctr: number; label: string } | null;
}

export interface NextCycleAdvice {
  budget_advice: string;
  proposed_budget: number;
  rule_cards_created: number;
  echo_chamber: boolean;
  // 票 R4-late-data-downstream（B0-25）：金額補件後跟著變才會有值，說明哪裡變了；
  // 只有一版判讀、或營收沒變時為 null（不喊假理由）。
  delta_reason: string | null;
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

/** 票 S1-01：現在結算判定＋天花板價（`app/ads/performance_batches.py can_settle()`＋
 * `app/ads/reading.py estimated_run_cost()`，逐欄照後端 envelope）。 */
export interface SettleNowInfo {
  can_settle: boolean;
  reason: string | null;
  estimated_cost: number;
  already_closed: boolean;
}

/** 票 S1-01：最近匯入一批（`app/ads/performance_batches.py list_batches()`）。
 * `spend` 為該批花費合計，`quarantined` 為擱在一旁（不合理數字）的列數。 */
export interface PerformanceBatch {
  batch_id: string;
  imported_at: string;
  source: string;
  rows: number;
  quarantined: number;
  spend: number;
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
    hypotheses: {
      id: string;
      statement: string;
      verdict: "supported" | "rejected" | "inconclusive";
      /** 還在待結案（proposed／testing）才 true，人還沒按過。 */
      pending: boolean;
      /** 程式預選的裁決；已結案（`pending: false`）或這期沒真的做過對照（R2-learning-
       * honesty 契約第 1／3 點）時為 null——空值才誠實，不能補「看不出來」進去假裝有選過。 */
      preselected: "supported" | "rejected" | "inconclusive" | null;
      /** 這期真的對照過的切角（R2-learning-honesty 契約第 2 點）：少於 2 筆代表這條假設
       * 這期沒有 A／B 對照組可以驗證，簽核畫面不能只給結論不給數字。 */
      comparison_cells: {
        cell_id: string;
        creative_angle: string | null;
        spend: number;
        conversions: number;
        revenue: number;
        kpis: { cpa: number | null; roas: number | null };
      }[];
      // 票 R4-late-data-downstream（B0-34）：已簽核（`pending: false`）後這期又真的補件
      // 重判、數字真的變了才有值——純提示，不代表 verdict 被自動改動過。
      stale_note: string | null;
    }[];
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
  readiness_notes: ReadinessNote[];
  pain_suggestion: PainSuggestion;
}

/** 開檔前提醒（後端 ads_repo.check_readiness 的實際形狀；React 搬家時曾誤標成 string[]，
 * 2026-08-15 白畫面修正對齊）。 */
export interface ReadinessNote {
  code: string;
  message: string;
  action_label: string;
  action_url: string;
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
  if (!res.ok) {
    // 後端的 4xx 幾乎都附一句寫給使用者看的白話理由（例如覆盤：「這期還沒有結案…」）。
    // 原本只印狀態碼，等於把那句話丟掉，非工程使用者只看到「讀取失敗（狀態碼 400）」，
    // 會以為畫面壞了而不是「還沒到時候」。比照 postJson 先讀 `error`／`detail` 欄
    // （兩種錯誤 envelope 本檔案 API 都會遇到——`_error()` 用 error，FastAPI 內建
    // HTTPException 跟票 S1-01 新路由手動 JSONResponse 都用 detail，見 libraryApi.ts:244
    // 同一種雙欄兼容寫法）。
    let message = res.status === 404 ? "找不到這筆資料。" : `讀取失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: string; detail?: string };
      if (data.error) message = data.error;
      else if (data.detail) message = data.detail;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  const body: Envelope<T> = await res.json();
  return body.data;
}

async function postJson<T = void>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body ?? {}) });
  if (!res.ok) {
    let message = `處理失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: string; detail?: string };
      if (data.error) message = data.error;
      else if (data.detail) message = data.detail;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// 票 04-angle-rename：整檔第一個 PATCH 呼叫端，錯誤處理沿用 postJson 同一套雙欄兼容
// （error／detail）——後端這支改名路由用 FastAPI 的 detail 欄，不是本檔多數路由的 error。
async function patchJson<T = void>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(body ?? {}) });
  if (!res.ok) {
    let message = `處理失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: string; detail?: string };
      if (data.error) message = data.error;
      else if (data.detail) message = data.detail;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// 票 S1-01：整批撤銷用，本檔第一個 DELETE 呼叫端，錯誤處理沿用 postJson 同一套雙欄
// 兼容（error／detail）。
async function deleteJson<T = void>(path: string): Promise<T> {
  const res = await fetch(path, { method: "DELETE" });
  if (!res.ok) {
    let message = `撤銷失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: string; detail?: string };
      if (data.error) message = data.error;
      else if (data.detail) message = data.detail;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// 仿 frontend/src/lib/intakeApi.ts:205 的 postForm；這裡的錯誤訊息 envelope 是 {error}
// （這個模組全檔的慣例），不是 intakeApi 那邊的 extractError 寫法，兩邊各自維持自己檔案
// 的風格，不跨檔抽共用（container-contract 第八節：兩寫法擇一，取同檔案一致的那個）。
async function postForm<T = void>(path: string, form: FormData): Promise<T> {
  const res = await fetch(path, { method: "POST", body: form });
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
export interface CreateCycleBody {
  simulate?: boolean;
  product_ids: string[];
  budget: number;
  duration_days: number;
  background: string | null;
  objective: string;
  offer?: { name: string; offer_type: OfferType; terms: string }; // 票 V1-01：省略＝今天的行為不變
}
export const fetchNewContext = (brandId: string): Promise<NewContext> => getJson(`${base(brandId)}/new-context`);
export const fetchNewCycleDirection = (brandId: string): Promise<NewCycleDirection> =>
  getJson(`${base(brandId)}/new-context/direction`);
export const createCycle = (brandId: string, payload: CreateCycleBody): Promise<{ cycle_id: string; message: string }> =>
  postJson(base(brandId), payload);
export const saveGuidedTargetCpa = (
  brandId: string,
  payload: { events_per_sale: number; margin_per_sale: number },
): Promise<{ value: number }> => postJson(`${base(brandId)}/target-cpa-guided`, payload);

// ---- 檔期完整狀態 ----
export const fetchCycleDetail = (brandId: string, cycleId: string): Promise<CycleDetail> => getJson(cycleBase(brandId, cycleId));
export const archiveCycle = (brandId: string, cycleId: string): Promise<void> => postJson(`${cycleBase(brandId, cycleId)}/archive`);
// 票 V1-01：PUT／DELETE 優惠都回 `_envelope()` 形狀（data／generated_at），跟本檔其餘
// postJson／deleteJson 慣吃「204 或裸 JSON」不同，各自解一次 data——不改 postJson／
// deleteJson 既有行為（`deleteJson` 唯一既有呼叫端 performance/batches 那支吃的是裸
// JSON，共用同一顆解法會撞型別）。
async function envelopeJson<T>(path: string, method: "PUT" | "DELETE", body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let message = `處理失敗（狀態碼 ${res.status}）`;
    try {
      const data = (await res.json()) as { error?: string; detail?: string };
      if (data.error) message = data.error;
      else if (data.detail) message = data.detail;
    } catch {
      // 回應不是 JSON，用預設訊息。
    }
    throw new Error(message);
  }
  const envelope: Envelope<T> = await res.json();
  return envelope.data;
}
export const saveCycleOffer = (
  brandId: string,
  cycleId: string,
  fields: { name: string; offer_type: OfferType; terms: string },
): Promise<Offer> => envelopeJson(`${cycleBase(brandId, cycleId)}/offer`, "PUT", fields);
export const clearCycleOffer = (brandId: string, cycleId: string): Promise<{ cleared: boolean }> =>
  envelopeJson(`${cycleBase(brandId, cycleId)}/offer`, "DELETE");

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
): Promise<{
  options: PlanOption[];
  cells: PlanCellAngle[];
  angle_locked: boolean;
  account_structure: AccountStructure;
  dissents: Dissent[];
}> => getJson(`${cycleBase(brandId, cycleId)}/plan/options`);
/** 切角改名（票 04-angle-rename 決議）：跟矩陣頁（`workbenchApi.ts renameAngle()`）打同一支
 * 後端路由，各自檔案各留一份呼叫——本檔的 `不碰 workbenchApi.ts 的內部實作` 邊界見
 * proposalApi.ts 檔頭同款說明，不跨檔案抽共用。 */
export const MAX_ANGLE_LENGTH = 30;
export const renameAngle = (brandId: string, cycleId: string, cellId: string, creativeAngle: string): Promise<string> =>
  patchJson<{ ok: boolean; creative_angle: string }>(
    `${cycleBase(brandId, cycleId)}/cells/${encodeURIComponent(cellId)}/angle`,
    { creative_angle: creativeAngle },
  ).then((body) => body.creative_angle);
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

// ---- Meta 官方 Ads MCP：一鍵建（暫停）＋發布（票 M1-01，ADR 0023，後端 app/ads/meta_mcp.py）----
export interface MetaMcpStatus {
  ok: boolean;
  account_id?: string;
  tools?: string[];
  reason?: string;
}

export interface MetaCreateAllResult {
  ok: boolean;
  created: number;
  failed: { package_id: string; package_name: string; reason: string }[];
}

export interface MetaPublishAllResult {
  ok: boolean;
  activated: number;
  failed: { package_id: string; reason: string }[];
}

export const fetchMetaStatus = (brandId: string, cycleId: string): Promise<MetaMcpStatus> =>
  getJson(`${cycleBase(brandId, cycleId)}/handoff/meta-status`);
export const createAllMetaPackages = (brandId: string, cycleId: string): Promise<MetaCreateAllResult> =>
  postJson(`${cycleBase(brandId, cycleId)}/handoff/create-all`);
export const publishAllMetaPackages = (brandId: string, cycleId: string): Promise<MetaPublishAllResult> =>
  postJson(`${cycleBase(brandId, cycleId)}/handoff/publish-all`);

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
): Promise<{
  summary: PerformanceSummary | null; reading: ReadingResult | null; bottleneck: BottleneckResult | null;
  confidence_label: string; last_synced_at?: string | null;
}> =>
  getJson(`${cycleBase(brandId, cycleId)}/performance`);
export const simulatePerformance = (brandId: string, cycleId: string): Promise<void> =>
  postJson(`${cycleBase(brandId, cycleId)}/performance/simulate`);
// 票 11 D2：跟 CSV 匯入同一個回應形狀（imported/skipped/…），面板才能秀出跳過幾筆。
export const submitManualPerformance = (brandId: string, cycleId: string, fields: Record<string, string>): Promise<CsvImportResult> =>
  postJson(`${cycleBase(brandId, cycleId)}/performance/manual`, fields);
export function importPerformanceCsv(brandId: string, cycleId: string, file: File): Promise<CsvImportResult> {
  const form = new FormData();
  form.append("perf_file", file);
  return postForm(`${cycleBase(brandId, cycleId)}/performance/csv`, form);
}

// ---- 現在結算＋匯入整批撤銷（票 S1-01）----
export const fetchSettleNow = (brandId: string, cycleId: string): Promise<SettleNowInfo> =>
  getJson(`${cycleBase(brandId, cycleId)}/settle-now`);
export const settleNow = (brandId: string, cycleId: string): Promise<{ ok: boolean; message: string }> =>
  postJson(`${cycleBase(brandId, cycleId)}/settle-now`);
export const fetchPerformanceBatches = (
  brandId: string,
  cycleId: string,
): Promise<{ items: PerformanceBatch[]; estimated_rerun_cost: number }> =>
  getJson(`${cycleBase(brandId, cycleId)}/performance/batches`);
export const deletePerformanceBatch = (
  brandId: string,
  cycleId: string,
  batchId: string,
): Promise<{ ok: boolean; deleted: number; rerun: "done" | "late_data" | "skipped"; message: string }> =>
  deleteJson(`${cycleBase(brandId, cycleId)}/performance/batches/${encodeURIComponent(batchId)}`);

// ---- 覆盤（S8.59-66）----
export const fetchClosingReview = (brandId: string, cycleId: string): Promise<ClosingReview> =>
  getJson(`${cycleBase(brandId, cycleId)}/closing-review`);
// 假設結案（票 L1-01，決策 0035 第三節第 6 點：入帳前必須經人確認，不自動結算）。
export const resolveHypotheses = (
  brandId: string,
  cycleId: string,
  verdicts: Record<string, "supported" | "rejected" | "inconclusive">,
): Promise<{ ok: boolean; updated: number; message: string }> =>
  postJson(`${cycleBase(brandId, cycleId)}/hypotheses/resolve`, { verdicts });

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
